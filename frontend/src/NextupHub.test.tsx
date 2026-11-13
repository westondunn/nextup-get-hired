import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import NextupHub from './NextupHub';

const api = vi.hoisted(() => ({
  request: vi.fn(),
  readCampaigns: vi.fn(),
  readTasks: vi.fn(),
}));

// The shell polls the alert count; every other page is replaced by a marker so that this
// test exercises navigation and the real Search Plan view only.
vi.mock('./jobs-api', () => ({ request: api.request }));
vi.mock('./hub/campaign-api', () => ({
  readCampaigns: api.readCampaigns,
  readTasks: api.readTasks,
  createTask: vi.fn(),
  updateTask: vi.fn(),
  updateCampaign: vi.fn(),
  previewSeed: vi.fn(),
  applySeed: vi.fn(),
}));
vi.mock('./hub/TodayView', () => ({ default: () => <div>today page marker</div> }));
vi.mock('./hub/DashboardView', () => ({ default: () => <div>dashboard page marker</div> }));
vi.mock('./hub/ApplicationsView', () => ({ default: () => <div>applications page marker</div> }));
vi.mock('./hub/JobBoardView', () => ({ default: () => <div>job board page marker</div> }));
vi.mock('./hub/AlertsView', () => ({ default: () => <div>alerts page marker</div> }));
vi.mock('./hub/EvidenceView', () => ({ default: () => <div>evidence page marker</div> }));
vi.mock('./hub/ContentView', () => ({ default: () => <div>content page marker</div> }));
vi.mock('./hub/ContactsView', () => ({ default: () => <div>contacts page marker</div> }));
vi.mock('./hub/MetricsView', () => ({ default: () => <div>metrics page marker</div> }));
vi.mock('./hub/DiscoveryView', () => ({ default: () => <div>discovery page marker</div> }));
vi.mock('./hub/SettingsView', () => ({ default: () => <div>settings page marker</div> }));

beforeEach(() => {
  window.scrollTo = vi.fn();
  api.request.mockResolvedValue({ unread: 0 });
  api.readCampaigns.mockResolvedValue([]);
  api.readTasks.mockResolvedValue([]);
});

afterEach(() => {
  vi.clearAllMocks();
});

it('opens on Today and navigates to the Search Plan view', async () => {
  render(<NextupHub />);
  expect(screen.getByRole('heading', { level: 1, name: 'Today' })).toBeTruthy();
  expect(screen.getByText('today page marker')).toBeTruthy();
  expect(api.readCampaigns).not.toHaveBeenCalled();

  fireEvent.click(screen.getAllByRole('button', { name: 'Search Plan' })[0]);
  expect(screen.getByRole('heading', { level: 1, name: 'Search Plan' })).toBeTruthy();
  expect(screen.getByText('Campaign tasks, weekly schedule, and seed import.')).toBeTruthy();
  expect(screen.queryByText('today page marker')).toBeNull();
  // The real view mounted and asked for its data.
  expect(
    await screen.findByText('No campaign yet. Import a seed JSON to get started.'),
  ).toBeTruthy();
  expect(api.readCampaigns).toHaveBeenCalledTimes(1);
  expect(window.scrollTo).toHaveBeenCalledWith(0, 0);

  fireEvent.click(screen.getAllByRole('button', { name: 'Dashboard' })[0]);
  expect(screen.getByText('dashboard page marker')).toBeTruthy();
  expect(screen.queryByText('No campaign yet. Import a seed JSON to get started.')).toBeNull();
});

it('lists the Search Plan entry once per sidebar, directly after Today', () => {
  render(<NextupHub />);
  const labels = screen
    .getAllByRole('button')
    .map((b) => b.textContent?.trim())
    .filter((t) => t === 'Today' || t === 'Search Plan' || t === 'Dashboard');
  expect(labels.slice(0, 3)).toEqual(['Today', 'Search Plan', 'Dashboard']);
});
