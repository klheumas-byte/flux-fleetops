import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, Clock3, ExternalLink, History, Plus, RefreshCw, ShieldCheck, X } from 'lucide-react';
import { ApiRequestError } from '../../lib/api';
import {
  fetchOperationsControl,
  fetchOperationsTimeline,
  runOperationsControlAction,
  type OperationsAction,
  type OperationsControl,
  type OperationsIssue,
  type OperationsTimeline,
} from '../../lib/operations-control-api';

const errorMessage = (error: unknown) => error instanceof ApiRequestError || error instanceof Error
  ? error.message
  : 'Unable to load Operations Control Center.';

const recoveryErrorMessage = (error: unknown) => {
  const message = errorMessage(error);
  return message === 'We could not complete that request right now. Please try again.'
    ? 'The database could not confirm this recovery. Recheck the blocker before retrying so an already-applied action is not repeated.'
    : message;
};

const actionLabels: Record<OperationsAction, string> = {
  open_record: 'Open Record',
  resolve: 'Resolve',
  recheck: 'Recheck',
  release_reservation: 'Release Stale Reservation',
  force_close_movement: 'Force Close',
  release_assignment: 'Release Stale Assignment',
  restart_movement: 'Continue / Restart',
  reassign: 'Reassign',
  resolve_maintenance: 'Resolve Maintenance',
};

const mutatingActions = new Set<OperationsAction>([
  'resolve', 'release_reservation', 'force_close_movement', 'release_assignment', 'restart_movement',
]);
const forceActions = new Set<OperationsAction>([
  'release_reservation', 'force_close_movement', 'release_assignment',
]);

type RecoverySelection = { issue: OperationsIssue; action: OperationsAction };
type RecoveryState = 'blocked' | 'recovery_required' | 'available_with_attention' | 'available';

const stateLabels: Record<RecoveryState, string> = {
  blocked: 'BLOCKED', recovery_required: 'RECOVERY REQUIRED',
  available_with_attention: 'AVAILABLE WITH ATTENTION', available: 'AVAILABLE',
};
const stateTones: Record<RecoveryState, string> = {
  blocked: 'border-red-200 bg-red-100 text-red-800',
  recovery_required: 'border-orange-200 bg-orange-100 text-orange-800',
  available_with_attention: 'border-amber-200 bg-amber-100 text-amber-800',
  available: 'border-emerald-200 bg-emerald-100 text-emerald-800',
};

const allResolutionOptions = [
  ['continue_operation', 'Continue operation'],
  ['physically_completed', 'Physically completed'],
  ['cancelled', 'Cancelled / no longer required'],
  ['reassignment_required', 'Reassignment required'],
  ['stale_incorrect_record', 'Stale / incorrect record'],
] as const;

function resolutionOptionsFor(issue: OperationsIssue) {
  if (issue.blocker_type === 'active_source_terminal_movement') return allResolutionOptions;
  if (issue.kind === 'reservation' || issue.kind === 'assignment') {
    return allResolutionOptions.filter(([value]) => value === 'reassignment_required' || value === 'stale_incorrect_record');
  }
  if (issue.kind === 'movement') {
    return allResolutionOptions.filter(([value]) => value !== 'continue_operation' && value !== 'cancelled');
  }
  return allResolutionOptions.filter(([value]) => value === 'reassignment_required');
}

function formatDate(value?: string | null) {
  if (!value) return '—';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function formatAge(seconds?: number | null) {
  if (seconds == null) return '—';
  if (seconds < 3600) return `${Math.max(1, Math.floor(seconds / 60))}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
  return `${Math.floor(seconds / 86400)}d ${Math.floor((seconds % 86400) / 3600)}h`;
}

export default function OperationsControlCenter({ onNavigate }: { onNavigate?: (page: string) => void }) {
  const [data, setData] = useState<OperationsControl | null>(null);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [busy, setBusy] = useState(false);
  const [selection, setSelection] = useState<RecoverySelection | null>(null);
  const [reason, setReason] = useState('');
  const [physicalConfirmed, setPhysicalConfirmed] = useState(false);
  const [confirmation, setConfirmation] = useState('');
  const [resolution, setResolution] = useState('');
  const [stateFilter, setStateFilter] = useState<'all' | RecoveryState>('all');
  const [assetFilter, setAssetFilter] = useState<'all' | 'vehicle' | 'driver'>('all');
  const [sortBy, setSortBy] = useState<'overdue' | 'unresolved' | 'name'>('overdue');
  const [timelineIssue, setTimelineIssue] = useState<OperationsIssue | null>(null);
  const [timeline, setTimeline] = useState<OperationsTimeline | null>(null);
  const [timelineLoading, setTimelineLoading] = useState(false);
  const submitInFlight = useRef(false);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      setData(await fetchOperationsControl());
      setError('');
    } catch (value) {
      setError(errorMessage(value));
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const closeRecovery = () => {
    setSelection(null);
    setReason('');
    setPhysicalConfirmed(false);
    setConfirmation('');
    setResolution('');
  };

  const handleAction = (issue: OperationsIssue, action: OperationsAction) => {
    setSuccess('');
    setError('');
    if (action === 'recheck') {
      void load();
      return;
    }
    if (action === 'open_record' || action === 'reassign' || action === 'resolve_maintenance') {
      if (issue.open_target?.page && onNavigate) onNavigate(issue.open_target.page);
      return;
    }
    if (mutatingActions.has(action)) setSelection({ issue, action });
  };

  const openTimeline = async (issue: OperationsIssue) => {
    setTimelineIssue(issue); setTimeline(null); setTimelineLoading(true); setError('');
    try { setTimeline(await fetchOperationsTimeline(issue)); }
    catch (value) { setError(errorMessage(value)); }
    finally { setTimelineLoading(false); }
  };

  const submitRecovery = async () => {
    if (!selection || submitInFlight.current) return;
    submitInFlight.current = true;
    setBusy(true);
    setError('');
    try {
      const navigateAfter = selection.action === 'resolve' && resolution === 'reassignment_required'
        ? selection.issue.open_target?.page
        : null;
      await runOperationsControlAction({
        action: selection.action,
        issue: selection.issue,
        reason,
        resolution: selection.action === 'resolve' ? resolution : undefined,
        physical_state_confirmed: physicalConfirmed,
        confirmation,
      });
      setError('');
      setSuccess(`${actionLabels[selection.action]} completed. Rechecking availability…`);
      closeRecovery();
      if (navigateAfter && onNavigate) onNavigate(navigateAfter);
      try {
        setData(await fetchOperationsControl());
        setSuccess(`${actionLabels[selection.action]} completed. Availability and blockers were recalculated.`);
      } catch (refreshError) {
        setError(`Recovery was applied, but the Control Center could not refresh: ${errorMessage(refreshError)}`);
        setSuccess(`${actionLabels[selection.action]} completed. Use Recheck before taking another recovery action.`);
      }
    } catch (value) {
      setError(recoveryErrorMessage(value));
    } finally {
      submitInFlight.current = false;
      setBusy(false);
    }
  };

  const vehicles = data?.overview.vehicles || {};
  const drivers = data?.overview.drivers || {};
  const selectedIsForce = selection ? forceActions.has(selection.action) : false;
  const resolveNeedsForce = selection?.action === 'resolve' && ['physically_completed', 'cancelled', 'stale_incorrect_record'].includes(resolution);
  const resolutionOptions = selection?.action === 'resolve' ? resolutionOptionsFor(selection.issue) : [];
  const canSubmit = Boolean(
    selection && reason.trim()
    && (selection.action !== 'resolve' || resolution)
    && (!(selectedIsForce || resolveNeedsForce) || (physicalConfirmed && confirmation.trim().toUpperCase() === 'FORCE RELEASE')),
  );

  const groups = useMemo(() => {
    const filtered = (data?.groups || []).filter((group) =>
      (stateFilter === 'all' || group.recovery_state === stateFilter)
      && (assetFilter === 'all' || group.asset_type === assetFilter));
    return [...filtered].sort((a, b) => {
      if (sortBy === 'name') return a.label.localeCompare(b.label);
      const field = sortBy === 'overdue' ? 'overdue_seconds' : 'unresolved_seconds';
      const age = (group: typeof a) => Math.max(0, ...group.blockers.map((item) => item[field] || 0));
      return age(b) - age(a);
    });
  }, [assetFilter, data, sortBy, stateFilter]);

  return (
    <div className="min-h-full bg-slate-50 p-4 md:p-6">
      <div className="mx-auto max-w-7xl space-y-5">
        <header className="flex items-start justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold text-slate-900">Operations Control Center</h1>
            <p className="mt-1 text-sm text-slate-500">Authoritative readiness, grouped blockers, and audited recovery.</p>
            {data?.generated_at && <p className="mt-1 text-xs text-slate-400">Checked {new Date(data.generated_at).toLocaleString()}</p>}
          </div>
          <div className="flex gap-2">
            {onNavigate && <button type="button" onClick={() => onNavigate('report-fault')} className="inline-flex items-center gap-2 rounded-lg bg-red-600 px-3 py-2 text-sm font-medium text-white"><Plus className="h-4 w-4" />Report Fault</button>}
            <button type="button" onClick={() => void load()} disabled={busy} className="rounded-lg border bg-white p-2.5 disabled:opacity-60" aria-label="Refresh Operations Control Center"><RefreshCw className={`h-4 w-4 ${busy ? 'animate-spin' : ''}`} /></button>
          </div>
        </header>

        {error && <p className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p>}
        {success && <p className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-700">{success}</p>}

        <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Metric label="Vehicles available" value={vehicles.available || 0} />
          <Metric label="Vehicles active" value={vehicles.active || 0} />
          <Metric label="Vehicles blocked" value={(vehicles.blocked || 0) + (vehicles.maintenance || 0)} />
          <Metric label="Drivers available" value={drivers.available || 0} />
        </section>

        <section className="flex flex-wrap gap-3 rounded-xl border bg-white p-3 text-sm">
          <label>State<select value={stateFilter} onChange={(event) => setStateFilter(event.target.value as typeof stateFilter)} className="ml-2 rounded-lg border px-2 py-1.5"><option value="all">All</option>{Object.entries(stateLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label>Asset<select value={assetFilter} onChange={(event) => setAssetFilter(event.target.value as typeof assetFilter)} className="ml-2 rounded-lg border px-2 py-1.5"><option value="all">All</option><option value="vehicle">Vehicles</option><option value="driver">Drivers</option></select></label>
          <label>Sort<select value={sortBy} onChange={(event) => setSortBy(event.target.value as typeof sortBy)} className="ml-2 rounded-lg border px-2 py-1.5"><option value="overdue">Overdue age</option><option value="unresolved">Unresolved age</option><option value="name">Name</option></select></label>
        </section>

        <section className="space-y-4">
          {groups.length ? groups.map((group) => (
            <article key={`${group.asset_type}:${group.asset_id}`} className="overflow-hidden rounded-xl border bg-white">
              <header className="flex flex-wrap items-center justify-between gap-2 border-b bg-slate-50 px-4 py-3">
                <div>
                  <h2 className="font-semibold text-slate-900">{group.label}</h2>
                  <p className="text-xs capitalize text-slate-500">{group.asset_type} · {String(group.operational_state || 'blocked').replaceAll('_', ' ')}</p>
                </div>
                <div className="flex items-center gap-2"><span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${stateTones[group.recovery_state]}`}>{stateLabels[group.recovery_state]}</span><span className="text-xs text-slate-500">{group.blockers?.length || 0} issue{group.blockers?.length === 1 ? '' : 's'}</span></div>
              </header>
              <div className="divide-y">
                {(group.blockers || []).map((issue) => (
                  <div key={issue.id} className="p-4">
                    <div className="flex gap-3">
                      <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" />
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="font-medium text-slate-900">{issue.blocker}</h3>
                          <span className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-600">{issue.blocker_type.replaceAll('_', ' ')}</span>
                        </div>
                        <dl className="mt-2 grid gap-x-6 gap-y-2 text-sm text-slate-600 sm:grid-cols-3 lg:grid-cols-4">
                          <div><dt className="text-xs text-slate-400">Source</dt><dd>{issue.source_type || '—'}</dd></div>
                          <div><dt className="text-xs text-slate-400">Reference</dt><dd className="truncate">{issue.source_reference || '—'}</dd></div>
                          <div><dt className="text-xs text-slate-400">Status</dt><dd className="capitalize">{issue.current_status?.replaceAll('_', ' ') || '—'}</dd></div>
                          <div><dt className="text-xs text-slate-400">Asset itself blocked?</dt><dd>{issue.asset_blocked ? 'Yes — safety/asset condition' : 'No — workflow occupancy/state'}</dd></div>
                          <div><dt className="text-xs text-slate-400">Driver / Vehicle</dt><dd>{[issue.driver_label, issue.vehicle_label].filter(Boolean).join(' / ') || '—'}</dd></div>
                          <div><dt className="text-xs text-slate-400">Task / Route</dt><dd>{issue.task || [issue.origin, issue.destination].filter(Boolean).join(' → ') || '—'}</dd></div>
                          <div><dt className="text-xs text-slate-400">Assigned / Scheduled</dt><dd>{formatDate(issue.assigned_at)} / {formatDate(issue.scheduled_at)}</dd></div>
                          <div><dt className="text-xs text-slate-400">Movement Start / End</dt><dd>{formatDate(issue.movement_started_at)} / {formatDate(issue.movement_ended_at)}</dd></div>
                          <div><dt className="text-xs text-slate-400">Last activity</dt><dd>{formatDate(issue.last_activity_at)}</dd></div>
                          <div><dt className="text-xs text-slate-400">Overdue / Unresolved</dt><dd>{formatAge(issue.overdue_seconds)} / {formatAge(issue.unresolved_seconds)}</dd></div>
                        </dl>
                        <p className="mt-2 text-sm text-slate-600"><b>Recommended:</b> {issue.recommended_action}</p>
                        <div className="mt-3 flex flex-wrap gap-2">
                          {(issue.allowed_actions || ['recheck']).map((action) => (
                            <button
                              key={action}
                              type="button"
                              disabled={busy || ((action === 'open_record' || action === 'reassign' || action === 'resolve_maintenance') && !onNavigate)}
                              onClick={() => handleAction(issue, action)}
                              className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium disabled:opacity-50 ${action === issue.primary_action ? 'border-blue-600 bg-blue-600 text-white' : forceActions.has(action) ? 'border-orange-300 bg-orange-50 text-orange-800' : 'border-slate-200 text-slate-700 hover:bg-slate-50'}`}
                            >
                              {(action === 'open_record' || action === 'reassign' || action === 'resolve_maintenance') && <ExternalLink className="h-3.5 w-3.5" />}
                              {actionLabels[action]}
                            </button>
                          ))}
                          {issue.timeline_available && <button type="button" onClick={() => void openTimeline(issue)} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-700"><History className="h-3.5 w-3.5" />View Timeline</button>}
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
                {group.blockers.length === 0 && <div className="flex items-center gap-2 p-4 text-sm text-emerald-700"><ShieldCheck className="h-4 w-4" />No blockers. Asset is available.</div>}
              </div>
            </article>
          )) : (
            <div className="flex items-center gap-2 rounded-xl border bg-white p-6 text-sm text-emerald-700">
              <ShieldCheck className="h-5 w-5" />No operational blockers detected.
            </div>
          )}
        </section>
      </div>

      {selection && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4" role="dialog" aria-modal="true" aria-labelledby="recovery-title">
          <div className="w-full max-w-lg rounded-xl bg-white shadow-xl">
            <header className="flex items-start justify-between border-b p-4">
              <div>
                <h2 id="recovery-title" className="font-semibold text-slate-900">{actionLabels[selection.action]}</h2>
                <p className="mt-1 text-sm text-slate-500">{selection.issue.source_reference || selection.issue.blocker}</p>
              </div>
              <button type="button" onClick={closeRecovery} disabled={busy} className="rounded p-1 text-slate-500"><X className="h-5 w-5" /></button>
            </header>
            <div className="space-y-4 p-4">
              {error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p>}
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
                Historical records will be preserved. Valid maintenance and active source workflows are not silently cleared.
              </div>
              {selection.action === 'resolve' && <label className="block text-sm font-medium text-slate-700">Resolution outcome<select value={resolution} onChange={(event) => setResolution(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-normal"><option value="">Select outcome</option>{resolutionOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>}
              <label className="block text-sm font-medium text-slate-700">
                Recovery reason
                <textarea value={reason} onChange={(event) => setReason(event.target.value)} rows={3} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-normal" placeholder="Explain why this state is stale or broken." />
              </label>
              {(selectedIsForce || resolveNeedsForce) && (
                <>
                  <label className="flex items-start gap-3 rounded-lg border p-3 text-sm text-slate-700">
                    <input type="checkbox" checked={physicalConfirmed} onChange={(event) => setPhysicalConfirmed(event.target.checked)} className="mt-0.5" />
                    I have physically confirmed the vehicle/driver is available and no active work is being interrupted.
                  </label>
                  <label className="block text-sm font-medium text-slate-700">
                    Type FORCE RELEASE to confirm
                    <input value={confirmation} onChange={(event) => setConfirmation(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-normal" autoComplete="off" />
                  </label>
                </>
              )}
            </div>
            <footer className="flex justify-end gap-2 border-t p-4">
              <button type="button" onClick={closeRecovery} disabled={busy} className="rounded-lg border px-4 py-2 text-sm">Cancel</button>
              <button type="button" onClick={() => void submitRecovery()} disabled={busy || !canSubmit} className="rounded-lg bg-orange-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
                {busy ? 'Applying…' : actionLabels[selection.action]}
              </button>
            </footer>
          </div>
        </div>
      )}
      {timelineIssue && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4" role="dialog" aria-modal="true">
          <div className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-xl bg-white shadow-xl">
            <header className="flex items-start justify-between border-b p-4"><div><h2 className="font-semibold text-slate-900">Blocker Timeline</h2><p className="mt-1 text-sm text-slate-500">{timelineIssue.source_reference || timelineIssue.blocker}</p></div><button type="button" onClick={() => setTimelineIssue(null)} className="rounded p-1 text-slate-500"><X className="h-5 w-5" /></button></header>
            <div className="space-y-3 p-4">
              {timelineLoading ? <div className="p-8 text-center text-sm text-slate-500">Loading timeline…</div> : timeline?.events.length ? timeline.events.map((event, index) => <div key={`${event.record_id}:${event.timestamp}:${index}`} className="flex gap-3 rounded-lg border p-3"><Clock3 className="mt-0.5 h-4 w-4 shrink-0 text-blue-600" /><div><p className="text-sm font-medium capitalize text-slate-900">{event.event.replaceAll('_', ' ')}</p><p className="text-xs text-slate-500">{formatDate(event.timestamp)} · {event.record_type}{event.status ? ` · ${event.status.replaceAll('_', ' ')}` : ''}</p>{event.note && <p className="mt-1 text-sm text-slate-700">{event.note}</p>}</div></div>) : <p className="rounded-lg border border-dashed p-6 text-center text-sm text-slate-500">No recorded history is available for this blocker.</p>}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return <article className="rounded-xl border bg-white p-4"><p className="text-sm text-slate-500">{label}</p><p className="mt-1 text-2xl font-semibold text-slate-900">{value}</p></article>;
}
