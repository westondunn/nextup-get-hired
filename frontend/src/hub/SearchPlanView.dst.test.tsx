import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Campaign, CampaignTask, TaskMessage } from './campaign-api';
import MessageCard, { groupThreads, messageTime, messageWhen } from './MessageCard';
import SearchPlanView from './SearchPlanView';

// Dates and times in the Search Plan view across daylight-saving changes, in UTC and in
// America/Chicago. Chicago changes clocks at 08:00 UTC on 2027-03-14 (02:00 becomes 03:00) and
// at 07:00 UTC on 2026-11-01 (02:00 becomes 01:00). All data is synthetic.

const api = vi.hoisted(() => ({
  readCampaigns: vi.fn(),
  readTasks: vi.fn(),
  createTask: vi.fn(),
  updateTask: vi.fn(),
  updateCampaign: vi.fn(),
  previewSeed: vi.fn(),
  applySeed: vi.fn(),
}));
vi.mock('./campaign-api', () => api);

type Zone = 'UTC' | 'America/Chicago';

function campaign(start_date: string, end_date: string): Campaign {
  return {
    id: 'c1',
    campaign_key: 'synthetic',
    title: 'Synthetic campaign',
    start_date,
    end_date,
    timezone: 'UTC',
    daily_capacity_minutes: 240,
    preferences: {},
    is_active: true,
    task_counts: {},
    created_at: '2026-10-01T00:00:00Z',
    updated_at: '2026-10-01T00:00:00Z',
  };
}

function task(due_date: string, changes: Partial<CampaignTask> = {}): CampaignTask {
  return {
    id: due_date,
    campaign_id: 'c1',
    seed_key: null,
    title: `Task due ${due_date}`,
    category: 'other',
    status: 'planned',
    priority: 'P1',
    due_date,
    estimated_minutes: null,
    depends_on: [],
    suggested_after: [],
    completion_criteria: '',
    notes: '',
    pursuit_id: null,
    completed_at: null,
    created_at: '2026-10-01T00:00:00Z',
    updated_at: '2026-10-01T00:00:00Z',
    ...changes,
  };
}

function calendarEvent(received_at: string, body = 'When: synthetic'): TaskMessage {
  return {
    id: `event-${received_at}`,
    source: 'calendar',
    channel: 'other',
    direction: 'note',
    sender: 'Riley <riley@acme.example>',
    subject: 'Synthetic interview',
    body,
    received_at,
    contact_id: null,
    pursuit_id: null,
  };
}

const SPRING = campaign('2027-03-08', '2027-04-04'); // Monday to Sunday, four weeks
const AUTUMN = campaign('2026-10-26', '2026-11-22'); // Monday to Sunday, four weeks

/** Days one after another as the view labels them, built in UTC so no local clock is involved. */
function dayLabels(first: string, count: number, options: Intl.DateTimeFormatOptions): string[] {
  const start = new Date(`${first}T00:00:00Z`).getTime();
  const format = new Intl.DateTimeFormat('en-US', { ...options, timeZone: 'UTC' });
  return Array.from({ length: count }, (_, i) => format.format(new Date(start + i * 86_400_000)));
}

/** The title of the task card that carries a "DUE TODAY" or "OVERDUE" badge. */
function badged(label: string): string[] {
  return screen
    .queryAllByText(label)
    .map((badge) => badge.parentElement!.parentElement!.querySelector('p')!.textContent ?? '');
}

/** How the page writes a wall-clock time in the zone the test is running in. */
function wallClock(year: number, month: number, day: number, hour: number, minute: number) {
  return new Date(year, month - 1, day, hour, minute, 0).toLocaleString();
}

async function renderPlan(active: Campaign, tasks: CampaignTask[], now: string) {
  vi.setSystemTime(new Date(now));
  api.readCampaigns.mockResolvedValue([active]);
  api.readTasks.mockResolvedValue(tasks);
  render(<SearchPlanView />);
  await screen.findByRole('button', { name: /^Week 1/ });
}

let zoneBefore: string | undefined;

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
});

afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

describe.each<Zone>(['UTC', 'America/Chicago'])('Search Plan dates in %s', (zone) => {
  const chicago = zone === 'America/Chicago';

  beforeAll(() => {
    zoneBefore = process.env.TZ;
    process.env.TZ = zone;
  });

  afterAll(() => {
    if (zoneBefore === undefined) delete process.env.TZ;
    else process.env.TZ = zoneBefore;
  });

  it('really runs in the zone it names', () => {
    const offset = (instant: string) => new Date(instant).getTimezoneOffset();
    const hour = (instant: string) => new Date(instant).getHours();
    if (!chicago) {
      expect([offset('2027-01-15T12:00:00Z'), offset('2027-07-15T12:00:00Z')]).toEqual([0, 0]);
      return;
    }
    expect([offset('2027-01-15T12:00:00Z'), offset('2027-07-15T12:00:00Z')]).toEqual([360, 300]);
    // Spring: 01:59:59 is followed by 03:00:00. Autumn: 01:xx happens twice.
    expect([hour('2027-03-14T07:59:59Z'), hour('2027-03-14T08:00:00Z')]).toEqual([1, 3]);
    expect([hour('2026-11-01T06:30:00Z'), hour('2026-11-01T07:30:00Z')]).toEqual([1, 1]);
  });

  it('keeps the spring transition day as the last day of its week', async () => {
    await renderPlan(
      SPRING,
      [task('2027-03-13'), task('2027-03-14'), task('2027-03-15'), task('2027-04-04')],
      '2027-03-14T12:00:00Z',
    );
    expect(screen.getByRole('button', { name: 'Week 1 (2)' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Week 2 (1)' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Week 3 (0)' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Week 4 (1)' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /^Week 5/ })).toBeNull();
    expect(screen.getByRole('heading', { name: 'Saturday, Mar 13' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Sunday, Mar 14' })).toBeTruthy();
    expect(screen.queryByText('Task due 2027-03-15')).toBeNull();
    expect(badged('DUE TODAY')).toEqual(['Task due 2027-03-14']);
    expect(badged('OVERDUE')).toEqual(['Task due 2027-03-13']);
    fireEvent.click(screen.getByRole('button', { name: 'Week 2 (1)' }));
    expect(screen.getByRole('heading', { name: 'Monday, Mar 15' })).toBeTruthy();
    expect(screen.queryByText('Task due 2027-03-14')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Week 4 (1)' }));
    expect(screen.getByRole('heading', { name: 'Sunday, Apr 4' })).toBeTruthy();
  });

  it('keeps the autumn transition day, which lasts 25 hours, as one day of its week', async () => {
    await renderPlan(
      AUTUMN,
      [task('2026-10-31'), task('2026-11-01'), task('2026-11-02'), task('2026-11-22')],
      '2026-11-01T12:00:00Z',
    );
    expect(screen.getByRole('button', { name: 'Week 1 (2)' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Week 2 (1)' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Week 3 (0)' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Week 4 (1)' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /^Week 5/ })).toBeNull();
    expect(screen.getByRole('heading', { name: 'Saturday, Oct 31' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Sunday, Nov 1' })).toBeTruthy();
    expect(badged('DUE TODAY')).toEqual(['Task due 2026-11-01']);
    expect(badged('OVERDUE')).toEqual(['Task due 2026-10-31']);
    fireEvent.click(screen.getByRole('button', { name: 'Week 2 (1)' }));
    expect(screen.getByRole('heading', { name: 'Monday, Nov 2' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Week 4 (1)' }));
    expect(screen.getByRole('heading', { name: 'Sunday, Nov 22' })).toBeTruthy();
  });

  // "Today" is the viewer's own calendar date. Each row is one instant and the date it falls
  // on in UTC and in Chicago.
  it.each([
    // 23:30 CST on the 13th, half an hour before the transition day starts in Chicago.
    ['2027-03-14T05:30:00Z', SPRING, '2027-03-14', '2027-03-13'],
    // One second before the clocks change, and the instant they change.
    ['2027-03-14T07:59:59Z', SPRING, '2027-03-14', '2027-03-14'],
    ['2027-03-14T08:00:00Z', SPRING, '2027-03-14', '2027-03-14'],
    // 22:00 CDT on the transition day; already the 15th in UTC.
    ['2027-03-15T03:00:00Z', SPRING, '2027-03-15', '2027-03-14'],
    // 00:30 CDT, in the first hour of the autumn transition day.
    ['2026-11-01T05:30:00Z', AUTUMN, '2026-11-01', '2026-11-01'],
    // 23:30 CST: twenty-four and a half hours after local midnight, and still 1 November.
    ['2026-11-02T05:30:00Z', AUTUMN, '2026-11-02', '2026-11-01'],
    // 00:30 CST on the 2nd.
    ['2026-11-02T06:30:00Z', AUTUMN, '2026-11-02', '2026-11-02'],
  ])('marks the right task as due at %s', async (now, active, utcDate, chicagoDate) => {
    const today = chicago ? chicagoDate : utcDate;
    const [year, month, day] = today.split('-').map(Number);
    const near = (shift: number) =>
      new Date(Date.UTC(year, month - 1, day + shift)).toISOString().slice(0, 10);
    // Every task sits in the campaign's first two weeks; show whichever week holds today.
    const tasks = [task(near(-1)), task(today), task(near(1))];
    await renderPlan(active, tasks, now);
    if (!screen.queryByText(`Task due ${today}`))
      fireEvent.click(screen.getByRole('button', { name: /^Week 2/ }));
    expect(badged('DUE TODAY')).toEqual([`Task due ${today}`]);
    expect(badged('OVERDUE')).not.toContain(`Task due ${today}`);
    expect(badged('OVERDUE')).not.toContain(`Task due ${near(1)}`);
    if (screen.queryByText(`Task due ${near(-1)}`))
      expect(badged('OVERDUE')).toEqual([`Task due ${near(-1)}`]);
  });

  it('lays out the month of the spring transition and opens the transition day', async () => {
    await renderPlan(SPRING, [task('2027-03-14'), task('2027-03-15')], '2027-03-14T12:00:00Z');
    fireEvent.click(screen.getByRole('button', { name: 'Calendar' }));
    const heading = screen.getByRole('heading', { name: 'March 2027' });
    const grid = heading.parentElement!.nextElementSibling as HTMLElement;
    // 1 March 2027 is a Monday: one leading blank, thirty-one days.
    expect(within(grid).getAllByRole('button')).toHaveLength(31);
    expect(grid.children).toHaveLength(7 + 1 + 31);
    const cell = within(grid).getByText('Task due 2027-03-14').closest('button')!;
    expect(cell.textContent).toMatch(/^14\D/);
    expect(within(grid).getByText('Task due 2027-03-15').closest('button')!.textContent).toMatch(
      /^15\D/,
    );
    // The 14th is a Sunday, so it is the first cell of its row.
    expect(Array.from(grid.children).indexOf(cell) % 7).toBe(0);
    fireEvent.click(cell);
    expect(screen.getByRole('heading', { name: 'Sunday, March 14' })).toBeTruthy();
  });

  it('lays out the month of the autumn transition and opens the transition day', async () => {
    await renderPlan(AUTUMN, [task('2026-11-01'), task('2026-11-02')], '2026-11-01T12:00:00Z');
    fireEvent.click(screen.getByRole('button', { name: 'Calendar' }));
    expect(screen.getByRole('heading', { name: 'October 2026' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Next →' }));
    const heading = screen.getByRole('heading', { name: 'November 2026' });
    const grid = heading.parentElement!.nextElementSibling as HTMLElement;
    // 1 November 2026 is a Sunday: no leading blanks, thirty days.
    expect(within(grid).getAllByRole('button')).toHaveLength(30);
    expect(grid.children).toHaveLength(7 + 30);
    const cell = within(grid).getByText('Task due 2026-11-01').closest('button')!;
    expect(cell.textContent).toMatch(/^1\D/);
    expect(Array.from(grid.children).indexOf(cell)).toBe(7);
    expect(within(grid).getByText('Task due 2026-11-02').closest('button')!.textContent).toMatch(
      /^2\D/,
    );
    fireEvent.click(cell);
    expect(screen.getByRole('heading', { name: 'Sunday, November 1' })).toBeTruthy();
  });

  it.each([
    ['spring', SPRING, '2027-03-08', '2027-03-14', 'Sun, 3/14'],
    ['autumn', AUTUMN, '2026-10-26', '2026-11-01', 'Sun, 11/1'],
  ])(
    'projects twenty-one consecutive days through the %s transition',
    async (_, active, first, transitionDay, transitionLabel) => {
      await renderPlan(
        active,
        [task(transitionDay, { estimated_minutes: 45 })],
        `${first}T12:00:00Z`,
      );
      const projected = screen
        .getAllByText(/: \d+ tasks, \d+m/)
        .map((entry) => entry.textContent ?? '');
      // No day is skipped or shown twice, and the transition day carries its own task.
      expect(projected.map((entry) => entry.split(':')[0])).toEqual(
        dayLabels(first, 21, { weekday: 'short', month: 'numeric', day: 'numeric' }),
      );
      expect(projected.filter((entry) => !entry.endsWith(': 0 tasks, 0m'))).toEqual([
        `${transitionLabel}: 1 tasks, 45m`,
      ]);
    },
  );

  // A calendar event's start is stored as an instant. Each row is an instant and the wall-clock
  // time it must be shown at: [month, day, hour, minute] in UTC, then in Chicago.
  const eventTimes: [string, string, number[], number[]][] = [
    ['the hour before the spring change', '2027-03-14T07:30:00Z', [3, 14, 7, 30], [3, 14, 1, 30]],
    ['the hour after the spring change', '2027-03-14T08:30:00Z', [3, 14, 8, 30], [3, 14, 3, 30]],
    ['the evening of the spring change', '2027-03-15T02:00:00Z', [3, 15, 2, 0], [3, 14, 21, 0]],
    ['the hour before the autumn change', '2026-11-01T05:30:00Z', [11, 1, 5, 30], [11, 1, 0, 30]],
    ['the first pass of the repeated hour', '2026-11-01T06:30:00Z', [11, 1, 6, 30], [11, 1, 1, 30]],
    [
      'the second pass of the repeated hour',
      '2026-11-01T07:30:00Z',
      [11, 1, 7, 30],
      [11, 1, 1, 30],
    ],
    ['the hour after the autumn change', '2026-11-01T08:30:00Z', [11, 1, 8, 30], [11, 1, 2, 30]],
  ];

  it.each(eventTimes)(
    'shows a calendar event in %s at the local time',
    (_, instant, utc, local) => {
      const [month, day, hour, minute] = chicago ? local : utc;
      const year = Number(instant.slice(0, 4));
      render(<MessageCard message={calendarEvent(instant)} />);
      expect(screen.getByText('calendar')).toBeTruthy();
      expect(screen.getByText(wallClock(year, month, day, hour, minute))).toBeTruthy();
    },
  );

  it('shows the event time on the task that carries the event', async () => {
    const withEvent = task('2027-03-14', { communication: calendarEvent('2027-03-14T08:30:00Z') });
    await renderPlan(SPRING, [withEvent], '2027-03-14T12:00:00Z');
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    expect(screen.getByText('Message to answer')).toBeTruthy();
    const shown = chicago ? wallClock(2027, 3, 14, 3, 30) : wallClock(2027, 3, 14, 8, 30);
    expect(screen.getByText(shown)).toBeTruthy();
  });

  // An all-day event is stored at midnight UTC of its date, with a flag. West of UTC that
  // instant falls on the evening before, so the date is read from the flag and never
  // converted to the viewer's zone.
  const allDayEvents: [string, string, number, number, number][] = [
    ['the spring transition day', '2027-03-14T00:00:00Z', 2027, 3, 14],
    ['the autumn transition day', '2026-11-01T00:00:00Z', 2026, 11, 1],
    ['an ordinary winter day', '2027-01-15T00:00:00Z', 2027, 1, 15],
    ['the last day of a year', '2026-12-31T00:00:00Z', 2026, 12, 31],
  ];

  it.each(allDayEvents)(
    'shows an all-day event on %s on its own date, with no time',
    (_, stored, year, month, day) => {
      render(
        <MessageCard message={{ ...calendarEvent(stored, 'When: all day'), all_day: true }} />,
      );
      const date = new Date(year, month - 1, day).toLocaleDateString();
      expect(screen.getByText(`${date}, all day`)).toBeTruthy();
      expect(screen.queryByText(/\d:\d\d/)).toBeNull();
    },
  );

  it('still shows an event that really starts at midnight UTC as a time', () => {
    // The same stored instant without the flag is an ordinary timed event.
    render(<MessageCard message={calendarEvent('2027-03-14T00:00:00Z')} />);
    const shown = chicago ? wallClock(2027, 3, 13, 18, 0) : wallClock(2027, 3, 14, 0, 0);
    expect(screen.getByText(shown)).toBeTruthy();
    expect(screen.queryByText(/all day/)).toBeNull();
  });

  it('shows the all-day date on the task that carries the event', async () => {
    const event = { ...calendarEvent('2027-03-14T00:00:00Z', 'When: all day'), all_day: true };
    await renderPlan(
      SPRING,
      [task('2027-03-14', { communication: event })],
      '2027-03-14T12:00:00Z',
    );
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    const date = new Date(2027, 2, 14).toLocaleDateString();
    expect(screen.getByText(`${date}, all day`)).toBeTruthy();
  });

  it('writes the date of an all-day event the same way wherever a message time appears', () => {
    const event = { ...calendarEvent('2026-11-01T00:00:00Z'), all_day: true };
    const date = new Date(2026, 10, 1).toLocaleDateString();
    expect(messageWhen(event)).toBe(`${date}, all day`);
    expect(messageWhen(event, true)).toBe(`${date}, all day`);
    // Without a stored time the flag means nothing, and the creation time is used.
    const undated = { received_at: null, all_day: true, created_at: '2026-11-01T12:00:00Z' };
    expect(messageWhen(undated)).toBe(new Date('2026-11-01T12:00:00Z').toLocaleString());
    expect(messageWhen({ received_at: null })).toBe('');
    // A timed message keeps its local time, or its local date when only the date is wanted.
    const timed = calendarEvent('2026-11-01T06:30:00Z');
    expect(messageWhen(timed)).toBe(new Date('2026-11-01T06:30:00Z').toLocaleString());
    expect(messageWhen(timed, true)).toBe(new Date('2026-11-01T06:30:00Z').toLocaleDateString());
  });

  it('sorts an all-day event at the start of its own day in the viewer\u2019s zone', () => {
    const at = (id: string, received_at: string, all_day = false) => ({
      ...calendarEvent(received_at),
      id,
      thread_id: null,
      all_day,
    });
    // 19:00 local on the 13th, the all-day event of the 14th, and 09:00 local on the 14th.
    const eveningBefore = chicago ? '2027-03-14T01:00:00Z' : '2027-03-13T19:00:00Z';
    const morningOf = chicago ? '2027-03-14T14:00:00Z' : '2027-03-14T09:00:00Z';
    const rows = [
      at('morning', morningOf),
      at('day', '2027-03-14T00:00:00Z', true),
      at('evening-before', eveningBefore),
    ];
    // Threads are listed newest first; each of these is a thread of one.
    expect(groupThreads(rows).map((thread) => thread[0].id)).toEqual([
      'morning',
      'day',
      'evening-before',
    ]);
    expect(messageTime(rows[1])).toBe(new Date(2027, 2, 14).getTime());
  });
});
