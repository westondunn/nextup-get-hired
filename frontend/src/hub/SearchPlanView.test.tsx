import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Campaign, CampaignTask } from './campaign-api';
import SearchPlanView from './SearchPlanView';

// The view derives calendar dates from local midnight; the suite pins the zone so that the
// expected dates do not depend on the machine that runs it.
process.env.TZ = 'UTC';

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

// Wednesday. The synthetic campaign starts on the Monday of the same week.
const TODAY = '2026-11-04';

const campaign: Campaign = {
  id: 'c1',
  campaign_key: 'synthetic',
  title: 'Synthetic campaign',
  start_date: '2026-11-02',
  end_date: '2026-11-29',
  timezone: 'UTC',
  daily_capacity_minutes: 240,
  preferences: {},
  is_active: true,
  task_counts: {},
  created_at: '2026-11-01T00:00:00Z',
  updated_at: '2026-11-01T00:00:00Z',
};

function task(id: string, title: string, changes: Partial<CampaignTask> = {}): CampaignTask {
  return {
    id,
    campaign_id: 'c1',
    seed_key: null,
    title,
    category: 'other',
    status: 'planned',
    priority: 'P1',
    due_date: null,
    estimated_minutes: null,
    depends_on: [],
    suggested_after: [],
    completion_criteria: '',
    notes: '',
    pursuit_id: null,
    completed_at: null,
    created_at: '2026-11-01T00:00:00Z',
    updated_at: '2026-11-01T00:00:00Z',
    ...changes,
  };
}

const dueToday = task('t1', 'Draft outreach list', { due_date: TODAY, estimated_minutes: 60 });
const overloaded = task('t2', 'Update summary section', {
  due_date: '2026-11-05',
  status: 'in_progress',
  priority: 'P0',
  estimated_minutes: 300,
});
const unscheduled = task('t3', 'Unscheduled idea');
const finished = task('t4', 'Week two review', {
  due_date: '2026-11-10',
  status: 'completed',
  estimated_minutes: 30,
});
const allTasks = [dueToday, overloaded, unscheduled, finished];

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date(`${TODAY}T12:00:00Z`));
  api.readCampaigns.mockResolvedValue([campaign]);
  api.readTasks.mockResolvedValue(allTasks);
});

afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

async function renderLoaded() {
  render(<SearchPlanView />);
  await screen.findByText('Draft outreach list');
}

describe('SearchPlanView', () => {
  it('loads the active campaign and groups its tasks by week and day', async () => {
    await renderLoaded();
    expect(api.readCampaigns).toHaveBeenCalledTimes(1);
    expect(api.readTasks).toHaveBeenCalledWith('c1', undefined);
    expect(screen.getByText('4 tasks')).toBeTruthy();
    // Four weeks: 2-8, 9-15, 16-22 and 23-29 November.
    expect(screen.getByRole('button', { name: 'Week 1 (2)' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Week 2 (1)' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Week 3 (0)' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Week 4 (0)' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /^Week 5/ })).toBeNull();
    expect(screen.getByText('Update summary section')).toBeTruthy();
    expect(screen.getByText('DUE TODAY')).toBeTruthy();
    expect(screen.queryByText('OVERDUE')).toBeNull();
    // The second week is not shown until its tab is chosen; undated tasks have their own list.
    expect(screen.queryByText('Week two review')).toBeNull();
    expect(screen.getByText('Unscheduled (1)')).toBeTruthy();
    expect(screen.getByText('Unscheduled idea')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Week 2 (1)' }));
    expect(screen.getByText('Week two review')).toBeTruthy();
    expect(screen.queryByText('Draft outreach list')).toBeNull();
  });

  it('keeps the first and last day of a week in that week', async () => {
    api.readTasks.mockResolvedValue([
      task('mon', 'Monday task', { due_date: '2026-11-02' }),
      task('sun', 'Sunday task', { due_date: '2026-11-08' }),
      task('next', 'Next Monday task', { due_date: '2026-11-09' }),
      task('last', 'Last day task', { due_date: '2026-11-29' }),
    ]);
    render(<SearchPlanView />);
    await screen.findByText('Monday task');
    expect(screen.getByText('Sunday task')).toBeTruthy();
    expect(screen.queryByText('Next Monday task')).toBeNull();
    expect(screen.getByRole('button', { name: 'Week 1 (2)' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Week 2 (1)' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Week 4 (1)' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Week 4 (1)' }));
    expect(screen.getByText('Last day task')).toBeTruthy();
  });

  it('marks a task that is past its due date as overdue', async () => {
    api.readTasks.mockResolvedValue([task('late', 'Late task', { due_date: '2026-11-03' })]);
    render(<SearchPlanView />);
    await screen.findByText('Late task');
    expect(screen.getByText('OVERDUE')).toBeTruthy();
    expect(screen.queryByText('DUE TODAY')).toBeNull();
  });

  it('asks the server again when a filter changes and reports an empty week', async () => {
    await renderLoaded();
    api.readTasks.mockResolvedValue([finished]);
    fireEvent.change(screen.getByDisplayValue('All statuses'), { target: { value: 'completed' } });
    await waitFor(() =>
      expect(api.readTasks).toHaveBeenLastCalledWith('c1', { status: 'completed' }),
    );
    await screen.findByText('1 tasks');
    expect(screen.getByText('No tasks scheduled for this week with current filters.')).toBeTruthy();
    expect(screen.queryByText('Draft outreach list')).toBeNull();

    fireEvent.change(screen.getByDisplayValue('All categories'), { target: { value: 'review' } });
    fireEvent.change(screen.getByDisplayValue('All priorities'), { target: { value: 'P1' } });
    await waitFor(() =>
      expect(api.readTasks).toHaveBeenLastCalledWith('c1', {
        status: 'completed',
        category: 'review',
        priority: 'P1',
      }),
    );
  });

  it('creates a task from the form and reloads the list', async () => {
    await renderLoaded();
    const created = task('t5', 'Call a recruiter', { due_date: '2026-11-06' });
    api.createTask.mockResolvedValue(created);
    fireEvent.click(screen.getByRole('button', { name: 'Add Task' }));
    expect(screen.getByText('New Task')).toBeTruthy();
    const create = screen.getByRole('button', { name: 'Create' }) as HTMLButtonElement;
    expect(create.disabled).toBe(true);

    fireEvent.change(screen.getByLabelText('Title'), { target: { value: '  Call a recruiter  ' } });
    fireEvent.change(screen.getByLabelText('Category'), { target: { value: 'networking' } });
    fireEvent.change(screen.getByLabelText('Priority'), { target: { value: 'P2' } });
    fireEvent.change(screen.getByLabelText('Due date'), { target: { value: '2026-11-06' } });
    fireEvent.change(screen.getByLabelText('Estimated minutes'), { target: { value: '45' } });
    expect(create.disabled).toBe(false);
    api.readTasks.mockResolvedValue([...allTasks, created]);
    fireEvent.click(create);

    await screen.findByText('Task created.');
    expect(api.createTask).toHaveBeenCalledWith('c1', {
      title: 'Call a recruiter',
      category: 'networking',
      priority: 'P2',
      due_date: '2026-11-06',
      estimated_minutes: 45,
    });
    expect(await screen.findByText('Call a recruiter')).toBeTruthy();
    expect(screen.getByText('5 tasks')).toBeTruthy();
    expect(screen.queryByText('New Task')).toBeNull();
  });

  it('shows the reason when a task cannot be created', async () => {
    await renderLoaded();
    api.createTask.mockRejectedValue(new Error('Title is too long.'));
    fireEvent.click(screen.getByRole('button', { name: 'Add Task' }));
    fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Anything' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create' }));
    expect(await screen.findByText('Title is too long.')).toBeTruthy();
    expect(screen.queryByText('Task created.')).toBeNull();
  });

  it('advances a planned task with the quick status control', async () => {
    await renderLoaded();
    api.updateTask.mockResolvedValue({ ...dueToday, status: 'in_progress' });
    const card = screen.getByText('Draft outreach list').closest('div.rounded-xl') as HTMLElement;
    fireEvent.click(within(card).getAllByRole('button')[0]);
    await waitFor(() =>
      expect(api.updateTask).toHaveBeenCalledWith('c1', 't1', { status: 'in_progress' }),
    );
  });

  it('renders the calendar month, places tasks on their dates and opens a day', async () => {
    await renderLoaded();
    fireEvent.click(screen.getByRole('button', { name: 'Calendar' }));
    const heading = screen.getByRole('heading', { name: 'November 2026' });
    const grid = heading.parentElement!.nextElementSibling as HTMLElement;
    for (const day of ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'])
      expect(within(grid).getByText(day)).toBeTruthy();
    // 1 November 2026 is a Sunday: thirty day cells and no leading blanks.
    expect(within(grid).getAllByRole('button')).toHaveLength(30);
    expect(grid.children).toHaveLength(7 + 30);

    const fourth = within(grid).getByText('Draft outreach list').closest('button')!;
    expect(fourth.textContent?.startsWith('4')).toBe(true);
    expect(within(grid).getByText('Week two review').closest('button')!.textContent).toMatch(/^10/);
    expect(within(grid).queryByText('Unscheduled idea')).toBeNull();

    // The filter row belongs to the task list; the calendar has none.
    expect(screen.queryByDisplayValue('All statuses')).toBeNull();
    fireEvent.click(fourth);
    expect(screen.getByRole('heading', { name: 'Wednesday, November 4' })).toBeTruthy();
    expect(screen.getAllByText('Draft outreach list')).toHaveLength(2);
    fireEvent.click(fourth);
    expect(screen.queryByRole('heading', { name: 'Wednesday, November 4' })).toBeNull();
  });

  it('moves between months and pads the first week of a month that starts midweek', async () => {
    await renderLoaded();
    fireEvent.click(screen.getByRole('button', { name: 'Calendar' }));
    fireEvent.click(screen.getByRole('button', { name: 'Next →' }));
    const december = screen.getByRole('heading', { name: 'December 2026' });
    const grid = december.parentElement!.nextElementSibling as HTMLElement;
    // 1 December 2026 is a Tuesday: two leading blanks, thirty-one days.
    expect(within(grid).getAllByRole('button')).toHaveLength(31);
    expect(grid.children).toHaveLength(7 + 2 + 31);
    fireEvent.click(screen.getByRole('button', { name: '← Prev' }));
    fireEvent.click(screen.getByRole('button', { name: '← Prev' }));
    expect(screen.getByRole('heading', { name: 'October 2026' })).toBeTruthy();
  });

  it('summarises the next three weeks of open work against daily capacity', async () => {
    await renderLoaded();
    expect(screen.getByText('Workload Projection (next 3 weeks)')).toBeTruthy();
    // Open tasks: 60 + 300 + an unestimated one. The completed task is not counted.
    expect(screen.getByText('3 tasks · 6h total')).toBeTruthy();
    expect(screen.getByText('240m/day capacity')).toBeTruthy();
    expect(screen.getByText('1 overloaded days')).toBeTruthy();
    expect(screen.getByText(/: 1 tasks, 300m ⚠ over capacity$/)).toBeTruthy();
    expect(screen.getByText(/: 1 tasks, 60m$/)).toBeTruthy();
    // Twenty-one days are projected; the completed task's day counts nothing.
    expect(screen.getAllByText(/: \d+ tasks, \d+m/)).toHaveLength(21);
    expect(screen.getAllByText(/: 0 tasks, 0m$/)).toHaveLength(19);
    // The projection stays visible on the calendar tab.
    fireEvent.click(screen.getByRole('button', { name: 'Calendar' }));
    expect(screen.getByText('Workload Projection (next 3 weeks)')).toBeTruthy();
  });

  it('reports no overload when every day is within capacity', async () => {
    api.readTasks.mockResolvedValue([dueToday]);
    await renderLoaded();
    expect(screen.getByText('1 tasks · 1h total')).toBeTruthy();
    expect(screen.queryByText(/overloaded days/)).toBeNull();
  });

  it('explains how to start when there is no campaign', async () => {
    api.readCampaigns.mockResolvedValue([]);
    render(<SearchPlanView />);
    expect(
      await screen.findByText('No campaign yet. Import a seed JSON to get started.'),
    ).toBeTruthy();
    expect(api.readTasks).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: 'Tasks' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Calendar' })).toBeNull();
    expect(screen.queryByText('Workload Projection (next 3 weeks)')).toBeNull();
    // Adding a task and importing a seed stay available.
    expect(screen.getByRole('button', { name: 'Add Task' })).toBeTruthy();
    expect(screen.getByText('Import Seed JSON')).toBeTruthy();
  });

  it('shows an error instead of content when loading fails', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    api.readCampaigns.mockRejectedValue(new Error('network down'));
    render(<SearchPlanView />);
    expect(await screen.findByText('Could not load campaign data.')).toBeTruthy();
    expect(screen.queryByText('Loading…')).toBeNull();
    expect(screen.queryByText('Draft outreach list')).toBeNull();
  });

  it('shows a campaign with no tasks as an empty week', async () => {
    api.readTasks.mockResolvedValue([]);
    render(<SearchPlanView />);
    expect(await screen.findByText('No tasks scheduled for this week.')).toBeTruthy();
    expect(screen.getByText('0 tasks')).toBeTruthy();
    expect(screen.queryByText(/^Unscheduled/)).toBeNull();
  });

  it('offers only the task list and the calendar, with no benefits or separation content', async () => {
    const storage = vi.spyOn(Storage.prototype, 'getItem');
    const writes = vi.spyOn(Storage.prototype, 'setItem');
    const { container } = render(<SearchPlanView />);
    await screen.findByText('Draft outreach list');
    const tabs = screen.getByRole('button', { name: 'Tasks' }).parentElement!;
    expect(
      within(tabs)
        .getAllByRole('button')
        .map((b) => b.textContent?.trim()),
    ).toEqual(['Tasks', 'Calendar']);
    const removed =
      /benefit|unemploy|severance|separation|terminat|insurance|claim|deadline|agency|weekly rate/i;
    expect(container.textContent).not.toMatch(removed);
    fireEvent.click(screen.getByRole('button', { name: 'Calendar' }));
    expect(container.textContent).not.toMatch(removed);
    expect(container.querySelector('a[href]')).toBeNull();
    expect(container.querySelector('table')).toBeNull();
    expect(storage).not.toHaveBeenCalled();
    expect(writes).not.toHaveBeenCalled();
  });
});
