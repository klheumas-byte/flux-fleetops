import { useEffect, useMemo, useState } from 'react';
import { Bell, CheckCheck, Clock3, Search, Trash2, Volume2, VolumeX } from 'lucide-react';
import { apiRequest } from '../../lib/api';
import { getNotificationSoundState, playNotificationSound, setNotificationSoundsEnabled, unlockNotificationSound } from '../../lib/notification-sound';

type NotificationRecord = {
  id: string;
  title: string;
  message: string;
  category: string;
  module?: string;
  priority: 'critical' | 'high' | 'medium' | 'low';
  notification_type?: 'info' | 'reminder' | 'action_required' | 'success' | 'critical';
  state?: string;
  is_read: boolean;
  action_url?: string | null;
  action_label?: string | null;
  reference_type?: string | null;
  reference_id?: string | null;
  created_at: string;
};

type NotificationCounts = { critical: number; action_required: number; reminders: number; total_actionable: number; completed_today: number };
type PageResponse = { data?: { notifications?: NotificationRecord[]; pagination?: { has_more: boolean; total: number }; counts?: Partial<NotificationCounts> & { unread?: number; pending_action?: number } } };
type Props = { audience: 'admin' | 'driver'; onNavigate?: (section: string) => void };

const notifyBadgeChanged = () => window.dispatchEvent(new CustomEvent('flux-notifications-changed'));

const adminTargets: Record<string, string> = {
  maintenance: 'maintenance', preventive_maintenance: 'preventive-maintenance', incident: 'incidents',
  accident: 'incidents', dispatch_job: 'dispatch-planner', dispatch: 'dispatch-planner',
  fault: 'fault-approvals', collection: 'collections', vehicle: 'vehicles', fuel: 'fuel',
};
const driverTargets: Record<string, string> = {
  maintenance: 'my-vehicle', preventive_maintenance: 'my-vehicle', incident: 'incidents',
  accident: 'incidents', dispatch_job: 'my-dispatches', dispatch: 'my-dispatches',
  fault: 'fault-history', collection: 'my-wallet', vehicle: 'my-vehicle', fuel: 'fuel-logs',
};

function dateGroup(value: string) {
  const date = new Date(value);
  const today = new Date();
  const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1);
  const key = date.toDateString();
  if (key === today.toDateString()) return 'Today';
  if (key === yesterday.toDateString()) return 'Yesterday';
  return 'Earlier';
}

function initialNotificationFilter() {
  try {
    const target = JSON.parse(sessionStorage.getItem('flux_work_queue_filter') || 'null');
    if (target?.module === 'notifications' && target?.filter === 'needs_action') {
      sessionStorage.removeItem('flux_work_queue_filter');
      return 'needs_action';
    }
  } catch { sessionStorage.removeItem('flux_work_queue_filter'); }
  return '';
}

export default function NotificationCenter({ audience, onNavigate }: Props) {
  const [items, setItems] = useState<NotificationRecord[]>([]);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [total, setTotal] = useState(0);
  const [query, setQuery] = useState('');
  const [stateFilter, setStateFilter] = useState(initialNotificationFilter);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [counts, setCounts] = useState<NotificationCounts>({ critical: 0, action_required: 0, reminders: 0, total_actionable: 0, completed_today: 0 });
  const [soundState, setSoundState] = useState(getNotificationSoundState);

  useEffect(() => {
    const update = (event: Event) => setSoundState((event as CustomEvent<ReturnType<typeof getNotificationSoundState>>).detail);
    window.addEventListener('flux-notification-sound-state', update);
    return () => window.removeEventListener('flux-notification-sound-state', update);
  }, []);

  const load = async (nextPage = 1, append = false) => {
    setLoading(true); setError('');
    const params = new URLSearchParams({ page: String(nextPage), page_size: '25' });
    if (query.trim()) params.set('q', query.trim());
    if (stateFilter) params.set('state', stateFilter);
    try {
      const response = await apiRequest<PageResponse>(`/notifications?${params}`, { componentName: 'NotificationCenter', requestLabel: 'notifications-page' });
      const data = response.data;
      const incoming = Array.isArray(data?.notifications) ? data.notifications : [];
      setItems((current) => append ? [...current, ...incoming] : incoming);
      setHasMore(Boolean(data?.pagination?.has_more)); setTotal(data?.pagination?.total ?? incoming.length);
      setCounts({
        critical: Number(data?.counts?.critical) || 0,
        action_required: Number(data?.counts?.action_required) || 0,
        reminders: Number(data?.counts?.reminders) || 0,
        total_actionable: Number(data?.counts?.total_actionable) || 0,
        completed_today: Number(data?.counts?.completed_today) || 0,
      });
      setPage(nextPage);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Unable to load notifications.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { const timer = window.setTimeout(() => void load(1), 250); return () => window.clearTimeout(timer); }, [query, stateFilter]);

  const groups = useMemo(() => ['Today', 'Yesterday', 'Earlier'].map((label) => ({ label, items: items.filter((item) => dateGroup(item.created_at) === label) })).filter((group) => group.items.length), [items]);

  const patchState = async (item: NotificationRecord, state: string, snoozedUntil?: string) => {
    if (busyId) return;
    setBusyId(item.id); setError('');
    try {
      await apiRequest(`/notifications/${item.id}/state`, { method: 'PATCH', body: JSON.stringify({ state, snoozed_until: snoozedUntil }), headers: { 'Content-Type': 'application/json' } });
      setItems((current) => state === 'dismissed' ? current.filter(({ id }) => id !== item.id) : current.map((entry) => entry.id === item.id ? { ...entry, state, is_read: true } : entry));
      notifyBadgeChanged();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Unable to update this notification.');
    } finally {
      setBusyId(null);
    }
  };

  const openAction = async (item: NotificationRecord) => {
    if (!item.is_read) {
      await apiRequest(`/notifications/${item.id}/read`, { method: 'PATCH' });
      setItems((current) => current.map((entry) => entry.id === item.id ? { ...entry, is_read: true, state: entry.state === 'unread' ? 'viewed' : entry.state } : entry));
      notifyBadgeChanged();
    }
    const targetMap = audience === 'driver' ? driverTargets : adminTargets;
    const explicit = item.action_url?.replace(/^\//, '');
    const target = explicit || targetMap[item.reference_type || ''] || targetMap[item.module || item.category];
    if (target && onNavigate) {
      sessionStorage.setItem('flux_notification_target', JSON.stringify({ referenceType: item.reference_type, referenceId: item.reference_id }));
      onNavigate(target);
    }
  };

  const markAllRead = async () => {
    if (busyId) return; setBusyId('all');
    try {
      await apiRequest('/notifications/read-all', { method: 'PATCH' });
      setItems((current) => current.map((item) => ({ ...item, is_read: true, state: item.state === 'unread' ? 'viewed' : item.state })));
      notifyBadgeChanged();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Unable to mark notifications as read.');
    } finally {
      setBusyId(null);
    }
  };

  return <div className="min-h-full bg-slate-50 p-4 sm:p-6 lg:p-8">
    <div className="mx-auto max-w-5xl">
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div><h1 className="text-2xl font-semibold text-slate-900">{audience === 'driver' ? 'Driver Notifications' : 'Notifications'}</h1><p className="text-sm text-slate-500">{total} notification{total === 1 ? '' : 's'}</p></div>
        <div className="flex flex-wrap gap-2">
          <button onClick={() => { setNotificationSoundsEnabled(!soundState.enabled); setSoundState(getNotificationSoundState()); }} className="inline-flex items-center gap-2 rounded-lg border bg-white px-3 py-2 text-sm">{soundState.enabled ? <Volume2 size={16}/> : <VolumeX size={16}/>}Sound {soundState.enabled ? 'on' : 'off'}</button>
          <button disabled={!soundState.enabled || !soundState.supported} onClick={() => void unlockNotificationSound().then(() => playNotificationSound('action_required'))} className="rounded-lg border bg-white px-3 py-2 text-sm disabled:opacity-50">Test Sound</button>
          <button disabled={Boolean(busyId)} onClick={() => void markAllRead()} className="inline-flex items-center gap-2 rounded-lg border bg-white px-3 py-2 text-sm disabled:opacity-50"><CheckCheck size={16}/>Mark all read</button>
        </div>
      </div>
      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4" aria-label="Notification summary">
        <div className="rounded-xl border border-red-200 bg-white p-4"><div className="text-sm font-medium text-red-700">Critical</div><div className="mt-1 text-2xl font-semibold text-slate-900">{counts.critical}</div></div>
        <div className="rounded-xl border border-orange-200 bg-white p-4"><div className="text-sm font-medium text-orange-700">Action Required</div><div className="mt-1 text-2xl font-semibold text-slate-900">{counts.action_required}</div></div>
        <div className="rounded-xl border border-yellow-200 bg-white p-4"><div className="text-sm font-medium text-yellow-700">Reminders</div><div className="mt-1 text-2xl font-semibold text-slate-900">{counts.reminders}</div></div>
        <div className="rounded-xl border border-green-200 bg-white p-4"><div className="text-sm font-medium text-green-700">Completed Today</div><div className="mt-1 text-2xl font-semibold text-slate-900">{counts.completed_today}</div></div>
      </div>
      <div className="mb-5 grid gap-3 rounded-xl border bg-white p-4 sm:grid-cols-[1fr_190px]">
        <label className="relative"><Search className="absolute left-3 top-2.5 text-slate-400" size={18}/><span className="sr-only">Search notifications</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search notifications" className="w-full rounded-lg border py-2 pl-10 pr-3 outline-none focus:ring-2 focus:ring-blue-500"/></label>
        <select aria-label="Filter notification state" value={stateFilter} onChange={(event) => setStateFilter(event.target.value)} className="rounded-lg border px-3 py-2"><option value="">All states</option><option value="unread">Unread</option><option value="needs_action">Needs action</option><option value="action_pending">Pending action</option><option value="snoozed">Snoozed</option><option value="completed">Completed</option></select>
      </div>
      {error && <div role="alert" className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}
      {loading && !items.length ? <div className="rounded-xl border bg-white p-10 text-center text-slate-500">Loading notifications…</div> : groups.length ? groups.map((group) => <section key={group.label} className="mb-6"><h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">{group.label}</h2><div className="space-y-3">{group.items.map((item) => {
        const urgent = item.notification_type === 'critical' || item.priority === 'critical';
        return <article key={item.id} className={`rounded-xl border bg-white p-4 shadow-sm ${!item.is_read ? 'border-l-4 border-l-blue-500' : ''}`}><div className="flex gap-3"><div className={`mt-1 rounded-full p-2 ${item.state === 'completed' ? 'bg-green-100 text-green-700' : urgent ? 'bg-red-100 text-red-700' : item.notification_type === 'success' ? 'bg-green-100 text-green-700' : item.notification_type === 'action_required' ? 'bg-orange-100 text-orange-700' : item.notification_type === 'reminder' ? 'bg-yellow-100 text-yellow-700' : 'bg-blue-100 text-blue-700'}`}><Bell size={17}/></div><div className="min-w-0 flex-1"><div className="flex flex-wrap justify-between gap-2"><h3 className="font-semibold text-slate-900">{item.title}</h3><time className="text-xs text-slate-500">{new Date(item.created_at).toLocaleString()}</time></div><div className="mt-1 flex flex-wrap gap-2 text-xs font-medium"><span className="rounded-full bg-slate-100 px-2 py-0.5 capitalize">{item.state === 'completed' ? 'Completed' : (item.notification_type || 'info').replace('_', ' ')}</span><span className="rounded-full bg-slate-100 px-2 py-0.5 capitalize">Priority: {item.priority}</span></div><p className="mt-1 text-sm text-slate-600">{item.message}</p><div className="mt-3 flex flex-wrap gap-2">
          {(item.action_url || item.reference_type) && <button disabled={busyId === item.id} onClick={() => void openAction(item)} className="rounded-lg bg-blue-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50">{item.action_label || 'View details'}</button>}
          <button aria-label={`Snooze ${item.title}`} disabled={busyId === item.id} onClick={() => { const until = new Date(Date.now() + 86400000).toISOString(); void patchState(item, 'snoozed', until); }} className="rounded-lg border p-2 disabled:opacity-50"><Clock3 size={15}/></button>
          {!['action_pending', 'pending_action', 'snoozed'].includes(item.state || '') && <button aria-label={`Archive ${item.title}`} disabled={busyId === item.id} onClick={() => void patchState(item, 'dismissed')} className="rounded-lg border p-2 text-slate-500 disabled:opacity-50"><Trash2 size={15}/></button>}
        </div></div></div></article>})}</div></section>) : <div className="rounded-xl border bg-white p-10 text-center text-slate-500">No notifications match these filters.</div>}
      {hasMore && <div className="text-center"><button disabled={loading} onClick={() => void load(page + 1, true)} className="rounded-lg border bg-white px-4 py-2 text-sm disabled:opacity-50">{loading ? 'Loading…' : 'Load more'}</button></div>}
    </div>
  </div>;
}
