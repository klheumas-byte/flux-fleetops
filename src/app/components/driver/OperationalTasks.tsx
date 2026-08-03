import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowLeft, ClipboardList, ExternalLink, Loader2, RefreshCw } from 'lucide-react';
import { ApiRequestError } from '../../lib/api';
import { fetchDriverOperationalTasks, type DriverOperationalTask } from '../../lib/driver-api';

const SupplierPickup = lazy(() => import('../shared/SupplierPickup'));
const StockTransfers = lazy(() => import('../shared/StockTransfers'));
const OperationalRequests = lazy(() => import('../shared/OperationalRequests'));

function message(error: unknown) {
  return error instanceof ApiRequestError || error instanceof Error
    ? error.message
    : 'Unable to load operational tasks.';
}

function formatDate(value?: string | null) {
  if (!value) return 'Not scheduled';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function statusTone(status: string) {
  if (['in_transit', 'movement_in_progress'].includes(status)) return 'bg-amber-100 text-amber-800';
  if (['awaiting_receipt', 'awaiting_verification'].includes(status)) return 'bg-violet-100 text-violet-800';
  return 'bg-blue-100 text-blue-800';
}

type TaskFilter = 'all' | 'today' | 'upcoming' | 'pending';

function readDashboardIntent(): { filter?: TaskFilter; taskKey?: string } {
  try {
    const raw = sessionStorage.getItem('flux_operational_task_intent');
    if (!raw) return {};
    sessionStorage.removeItem('flux_operational_task_intent');
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

export default function OperationalTasks({ onNavigate }: { onNavigate?: (page: string) => void }) {
  const dashboardIntent = useRef(readDashboardIntent());
  const [tasks, setTasks] = useState<DriverOperationalTask[]>([]);
  const [selected, setSelected] = useState<DriverOperationalTask | null>(null);
  const [filter, setFilter] = useState<TaskFilter>(dashboardIntent.current.filter || 'all');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const result = await fetchDriverOperationalTasks();
      setTasks(result.tasks || []);
      if (dashboardIntent.current.taskKey) {
        const requested = result.tasks.find((task) => task.task_key === dashboardIntent.current.taskKey);
        if (requested) setSelected(requested);
        dashboardIntent.current.taskKey = undefined;
      }
      if (selected && !result.tasks.some((task) => task.task_key === selected.task_key)) {
        setSelected(null);
      }
    } catch (value) {
      setError(message(value));
    } finally {
      setLoading(false);
    }
  }, [selected]);

  useEffect(() => { void load(); }, []);
  useEffect(() => {
    const refresh = () => { if (document.visibilityState === 'visible') void load(); };
    const interval = window.setInterval(refresh, 15_000);
    window.addEventListener('flux-notifications-changed', refresh);
    return () => {
      window.clearInterval(interval);
      window.removeEventListener('flux-notifications-changed', refresh);
    };
  }, [load]);

  const openWaybill = (task: DriverOperationalTask) => {
    if (!task.linked_waybill_id || !onNavigate) return;
    sessionStorage.setItem('flux_notification_target', JSON.stringify({
      referenceType: 'waybill',
      referenceId: task.linked_waybill_id,
    }));
    onNavigate('digital-waybills');
  };

  const filteredTasks = useMemo(() => {
    const today = new Date();
    const todayKey = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
    return tasks.filter((task) => {
      const schedule = task.schedule ? new Date(task.schedule) : null;
      const scheduleKey = schedule && !Number.isNaN(schedule.getTime())
        ? `${schedule.getFullYear()}-${String(schedule.getMonth() + 1).padStart(2, '0')}-${String(schedule.getDate()).padStart(2, '0')}`
        : '';
      if (filter === 'today') return scheduleKey === todayKey;
      if (filter === 'upcoming') return scheduleKey > todayKey;
      if (filter === 'pending') return ['accept', 'acknowledge'].includes(task.current_action.key);
      return true;
    });
  }, [filter, tasks]);

  if (selected) {
    return <div className="min-h-full bg-slate-50">
      <div className="px-4 pt-4 md:px-6 md:pt-6">
        <button
          type="button"
          onClick={() => { setSelected(null); void load(); }}
          className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700"
        >
          <ArrowLeft className="h-4 w-4" />Back to Operational Tasks
        </button>
      </div>
      <Suspense fallback={<div className="flex h-64 items-center justify-center"><Loader2 className="h-7 w-7 animate-spin text-blue-600" /></div>}>
        {selected.operation_type === 'supplier_pickup' && <SupplierPickup driverMode taskId={selected.id} />}
        {selected.operation_type === 'stock_transfer' && <StockTransfers driverMode taskId={selected.id} onNavigate={onNavigate} />}
        {selected.operation_type === 'operational_request' && <OperationalRequests driverMode taskId={selected.id} />}
      </Suspense>
    </div>;
  }

  return <div className="min-h-full bg-slate-50 p-4 md:p-6">
    <div className="mx-auto max-w-7xl space-y-5">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">My Operational Tasks</h1>
          <p className="text-sm text-slate-500">Supplier pickups, stock transfers, and approved internal operations assigned to you.</p>
        </div>
        <button type="button" disabled={loading} onClick={() => void load()} className="inline-flex items-center gap-2 rounded-lg border bg-white px-3 py-2 text-sm disabled:opacity-60">
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />Refresh
        </button>
      </header>

      {filter !== 'all' && <div className="flex items-center justify-between rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-800">
        <span>Showing {filter === 'pending' ? 'tasks pending acceptance' : `${filter} tasks`}.</span>
        <button type="button" onClick={() => setFilter('all')} className="font-medium">Show all</button>
      </div>}

      {error && <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}

      {loading ? <div className="flex h-64 items-center justify-center"><Loader2 className="h-7 w-7 animate-spin text-blue-600" /></div>
        : filteredTasks.length === 0 ? <section className="rounded-xl border border-dashed bg-white p-12 text-center">
          <ClipboardList className="mx-auto h-10 w-10 text-slate-300" />
          <h2 className="mt-3 font-semibold text-slate-900">No active operational tasks</h2>
          <p className="mt-1 text-sm text-slate-500">Approved operations appear here when they are assigned to you.</p>
        </section>
          : <div className="grid gap-4 lg:grid-cols-2">
            {filteredTasks.map((task) => <article key={task.task_key} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-blue-600">{task.operation_label}</p>
                  <h2 className="mt-1 font-semibold text-slate-900">{task.reference}</h2>
                  <p className="mt-1 text-sm text-slate-600">{task.title}</p>
                </div>
                <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${statusTone(task.status)}`}>{task.status_label}</span>
              </div>
              <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
                <Info label="Schedule" value={formatDate(task.schedule)} />
                <Info label="Vehicle" value={task.vehicle?.registration_number || 'Not assigned'} />
                <Info label="Origin" value={task.origin || 'Not set'} />
                <Info label="Destination" value={task.destination || 'Not set'} />
              </dl>
              <div className="mt-5 flex flex-wrap gap-2">
                <button type="button" onClick={() => { if (task.operation_type === 'smart_living_delivery' && onNavigate) { sessionStorage.setItem('flux_smart_living_batch', task.id); onNavigate('smart-living-deliveries'); } else setSelected(task); }} className="rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white">
                  {task.current_action.label}
                </button>
                {task.linked_waybill_id && <button type="button" onClick={() => openWaybill(task)} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700">
                  Digital Waybill <ExternalLink className="h-4 w-4" />
                </button>}
              </div>
            </article>)}
          </div>}
    </div>
  </div>;
}

function Info({ label, value }: { label: string; value: string }) {
  return <div><dt className="text-xs uppercase tracking-wide text-slate-400">{label}</dt><dd className="mt-1 text-slate-700">{value}</dd></div>;
}
