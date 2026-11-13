import { useEffect, useState } from 'react';
import {
  Briefcase,
  LayoutDashboard,
  ClipboardList,
  Search,
  Mail,
  ChevronDown,
  Plus,
  Settings,
  Menu,
  X,
  CalendarCheck,
  CalendarDays,
  Shield,
  PenLine,
  Users,
  BarChart3,
} from 'lucide-react';
import { request } from './jobs-api';
import TodayView from './hub/TodayView';
import SearchPlanView from './hub/SearchPlanView';
import DashboardView from './hub/DashboardView';
import ApplicationsView from './hub/ApplicationsView';
import JobBoardView from './hub/JobBoardView';
import AlertsView from './hub/AlertsView';
import EvidenceView from './hub/EvidenceView';
import ContentView from './hub/ContentView';
import ContactsView from './hub/ContactsView';
import MetricsView from './hub/MetricsView';
import DiscoveryView from './hub/DiscoveryView';
import SettingsView from './hub/SettingsView';

type Page =
  | 'today'
  | 'plan'
  | 'dashboard'
  | 'applications'
  | 'jobs'
  | 'contacts'
  | 'evidence'
  | 'content'
  | 'metrics'
  | 'messages'
  | 'discovery'
  | 'settings';

interface InboxCount {
  unread: number;
}

const NAV_ITEMS: { label: string; icon: typeof LayoutDashboard; page: Page }[] = [
  { label: 'Today', icon: CalendarCheck, page: 'today' },
  { label: 'Search Plan', icon: CalendarDays, page: 'plan' },
  { label: 'Dashboard', icon: LayoutDashboard, page: 'dashboard' },
  { label: 'Applications', icon: ClipboardList, page: 'applications' },
  { label: 'Job Board', icon: Search, page: 'jobs' },
  { label: 'Discovery', icon: Settings, page: 'discovery' },
  { label: 'Contacts', icon: Users, page: 'contacts' },
  { label: 'Evidence', icon: Shield, page: 'evidence' },
  { label: 'Content', icon: PenLine, page: 'content' },
  { label: 'Metrics', icon: BarChart3, page: 'metrics' },
  { label: 'Alerts', icon: Mail, page: 'messages' },
  { label: 'Settings', icon: Settings, page: 'settings' },
];

export default function NextupHub() {
  const [page, setPage] = useState<Page>('today');
  const [unread, setUnread] = useState(0);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const result = await request<InboxCount>('alerts?unread_only=true&limit=1');
        if (active) setUnread(result.unread);
      } catch {
        /* ignore */
      }
      if (active) timer = setTimeout(poll, 10000);
    }
    void poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, []);

  function navigate(p: string) {
    setPage(p as Page);
    setSidebarOpen(false);
    window.scrollTo(0, 0);
  }

  const sidebar = (
    <>
      <div className="flex items-center gap-3 px-6 py-6">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-white/10">
          <Briefcase className="h-5 w-5 text-white" />
        </div>
        <span className="text-lg font-semibold text-white">Nextup</span>
        <button
          type="button"
          onClick={() => setSidebarOpen(false)}
          className="ml-auto rounded p-1 text-slate-400 hover:text-white lg:hidden"
        >
          <X className="h-5 w-5" />
        </button>
      </div>

      <nav className="flex-1 space-y-1 px-3">
        {NAV_ITEMS.map(({ label, icon: Icon, page: p }) => (
          <button
            key={p}
            type="button"
            onClick={() => navigate(p)}
            className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${
              page === p ? 'bg-slate-800 text-white' : 'hover:bg-slate-800/60 hover:text-white'
            }`}
          >
            <Icon className="h-[18px] w-[18px] shrink-0" />
            <span className="flex-1 text-left">{label}</span>
            {p === 'messages' && unread > 0 && (
              <span className="flex h-5 min-w-[20px] items-center justify-center rounded-full bg-orange-500 px-1.5 text-xs font-semibold text-white">
                {unread}
              </span>
            )}
          </button>
        ))}
      </nav>

      <div className="mx-3 mb-4 border-t border-slate-800 px-3 py-4">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-gradient-to-br from-sky-400 to-indigo-500 text-sm font-semibold text-white">
            N
          </div>
          <div className="flex-1">
            <p className="text-sm font-medium text-white">Local Workspace</p>
            <p className="text-xs text-slate-400">All data stays here</p>
          </div>
          <ChevronDown className="h-4 w-4 text-slate-400" />
        </div>
      </div>
    </>
  );

  return (
    <div className="min-h-screen bg-slate-50 font-sans text-slate-900 antialiased">
      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 z-20 hidden w-64 flex-col bg-slate-900 text-slate-300 lg:flex">
        {sidebar}
      </aside>

      {/* Mobile sidebar overlay */}
      {sidebarOpen && (
        <div className="fixed inset-0 z-30 lg:hidden" onClick={() => setSidebarOpen(false)}>
          <div className="absolute inset-0 bg-black/50" />
          <aside
            className="absolute inset-y-0 left-0 flex w-64 flex-col bg-slate-900 text-slate-300"
            onClick={(e) => e.stopPropagation()}
          >
            {sidebar}
          </aside>
        </div>
      )}

      {/* Main */}
      <main className="min-h-screen overflow-y-auto lg:ml-64">
        <div className="mx-auto max-w-[1400px] px-4 py-6 sm:px-8 sm:py-8">
          {/* Header */}
          <header className="flex flex-wrap items-start justify-between gap-4">
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={() => setSidebarOpen(true)}
                className="rounded-lg border border-slate-300 p-2 text-slate-700 hover:bg-slate-100 lg:hidden"
              >
                <Menu className="h-5 w-5" />
              </button>
              <div>
                <h1 className="text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">
                  {page === 'today' && 'Today'}
                  {page === 'plan' && 'Search Plan'}
                  {page === 'dashboard' && 'Dashboard'}
                  {page === 'applications' && 'Applications'}
                  {page === 'jobs' && 'Job Board'}
                  {page === 'contacts' && 'Contacts'}
                  {page === 'evidence' && 'Evidence Bank'}
                  {page === 'content' && 'Content'}
                  {page === 'metrics' && 'Metrics'}
                  {page === 'messages' && 'Alerts'}
                  {page === 'discovery' && 'Discovery'}
                  {page === 'settings' && 'Settings'}
                </h1>
                <p className="mt-1 hidden text-sm text-slate-500 sm:block">
                  {page === 'today' && 'Your highest-priority actions right now.'}
                  {page === 'plan' && 'Campaign tasks, weekly schedule, and seed import.'}
                  {page === 'dashboard' && 'Your job search at a glance.'}
                  {page === 'applications' && 'Track your pipeline from discovery to offer.'}
                  {page === 'jobs' && 'Browse and filter job listings.'}
                  {page === 'contacts' && 'People, relationships, and communication history.'}
                  {page === 'evidence' &&
                    'Approved career facts, achievements, and resume variants.'}
                  {page === 'content' && 'Content calendar for LinkedIn posts and articles.'}
                  {page === 'metrics' && 'Cohort metrics, conversion rates, and weekly review.'}
                  {page === 'messages' && 'Local job match notifications.'}
                  {page === 'discovery' && 'Configure automatic employer board fetching.'}
                  {page === 'settings' && 'Campaign, profile, integrations, and system health.'}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              {(page === 'dashboard' || page === 'jobs') && (
                <button
                  type="button"
                  onClick={() => navigate('applications')}
                  className="flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-slate-800"
                >
                  <Plus className="h-4 w-4" />
                  <span className="hidden sm:inline">View Pipeline</span>
                </button>
              )}
            </div>
          </header>

          {/* Page content */}
          <section className="mt-6 sm:mt-8">
            {page === 'today' && <TodayView onNavigate={navigate} />}
            {page === 'plan' && <SearchPlanView />}
            {page === 'dashboard' && <DashboardView onNavigate={navigate} />}
            {page === 'applications' && <ApplicationsView />}
            {page === 'jobs' && <JobBoardView />}
            {page === 'contacts' && <ContactsView />}
            {page === 'evidence' && <EvidenceView />}
            {page === 'content' && <ContentView />}
            {page === 'metrics' && <MetricsView />}
            {page === 'messages' && <AlertsView />}
            {page === 'discovery' && <DiscoveryView onViewJobs={() => navigate('jobs')} />}
            {page === 'settings' && <SettingsView />}
          </section>
        </div>
      </main>
    </div>
  );
}
