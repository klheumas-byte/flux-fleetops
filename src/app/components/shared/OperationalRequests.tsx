import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react';
import { AlertCircle, CheckCircle2, ClipboardCheck, Loader2, Plus, RefreshCw, X } from 'lucide-react';
import { ApiRequestError } from '../../lib/api';
import {
  createOperationRequest,
  fetchOperationRequest,
  fetchOperationOptions,
  fetchOperationRequests,
  fetchPersonalUseAnalytics,
  mutateOperationRequest,
  type OperationOptions,
  type OperationRequest,
  type OperationType,
  type PersonalUseAnalytics,
} from '../../lib/operational-request-api';
import { MovementFuelDialog, type MovementFuelDraft } from './MovementFuelDialog';

const LABELS: Record<OperationType, string> = {
  internal_company_delivery: 'Internal Company Delivery',
  fuel_station_visit: 'Fuel-station Visit',
  compliance_inspection_visit: 'Compliance / Inspection Visit',
  administrative_errand: 'Administrative Errand',
  vehicle_repositioning: 'Vehicle Repositioning',
  personal_use: 'Personal Vehicle Use',
};

const EMPTY_FORM = {
  operation_type: 'internal_company_delivery' as OperationType,
  title: '', purpose: '', origin: '', destination: '', journey_mode: 'round_trip',
  planned_departure_at: '', expected_return_at: '', priority: 'normal', notes: '',
  sender_name: '', intended_receiver_name: '', delivery_item: '', related_source_id: '',
};

function errorMessage(error: unknown) {
  return error instanceof ApiRequestError || error instanceof Error ? error.message : 'Unable to complete this action.';
}

function formatDate(value?: string | null) {
  if (!value) return 'Not scheduled';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function statusTone(status: string) {
  if (status === 'completed') return 'bg-emerald-100 text-emerald-800';
  if (['rejected', 'cancelled', 'aborted'].includes(status)) return 'bg-red-100 text-red-800';
  if (['movement_in_progress', 'awaiting_verification'].includes(status)) return 'bg-amber-100 text-amber-800';
  return 'bg-blue-100 text-blue-800';
}

export default function OperationalRequests({ driverMode = false, taskId }: { driverMode?: boolean; taskId?: string }) {
  const [records, setRecords] = useState<OperationRequest[]>([]);
  const [options, setOptions] = useState<OperationOptions | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busyId, setBusyId] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [schedule, setSchedule] = useState({ requestId: '', vehicle_id: '', driver_id: '', planned_departure_at: '', expected_return_at: '' });
  const [confirming, setConfirming] = useState<OperationRequest | null>(null);
  const [confirmation, setConfirmation] = useState({ receiver_name: '', accepted_by_name: '', outcome: '', fuel_log_id: '', no_purchase_reason: '', notes: '' });
  const [movementAction, setMovementAction] = useState<{ record: OperationRequest; mode: 'start' | 'return'; draft: MovementFuelDraft } | null>(null);
  const [personalAnalytics, setPersonalAnalytics] = useState<PersonalUseAnalytics | null>(null);
  const [analyticsFilters, setAnalyticsFilters] = useState({ driver_id: '', vehicle_id: '', date_from: '', date_to: '', branch_id: '', status: '' });

  const load = async () => {
    setLoading(true); setError('');
    try {
      if (taskId) {
        setRecords([await fetchOperationRequest(taskId)]);
      } else {
        const [listResult, optionsResult] = await Promise.allSettled([
          fetchOperationRequests(),
          fetchOperationOptions(),
        ]);
        if (listResult.status === 'fulfilled') {
          setRecords(listResult.value.requests);
        } else {
          throw listResult.reason;
        }
        if (optionsResult.status === 'fulfilled') {
          setOptions(optionsResult.value);
        } else {
          setOptions(null);
          setError(`Requests loaded, but scheduling options are unavailable: ${errorMessage(optionsResult.reason)}`);
        }
        if (!driverMode) {
          setPersonalAnalytics(await fetchPersonalUseAnalytics(analyticsFilters));
        }
      }
    } catch (loadError) { setError(errorMessage(loadError)); }
    finally { setLoading(false); }
  };

  useEffect(() => { void load(); }, [taskId]);

  const activeCount = useMemo(() => records.filter((item) => !['completed', 'cancelled', 'rejected', 'aborted'].includes(item.status)).length, [records]);

  const run = async (record: OperationRequest, action: string, payload: Record<string, unknown> = {}, message?: string) => {
    setBusyId(record.id); setError(''); setNotice('');
    try {
      const updated = await mutateOperationRequest(record.id, action, payload);
      setRecords((current) => current.map((item) => item.id === updated.id ? updated : item));
      setNotice(message || 'Operational request updated.');
      window.dispatchEvent(new CustomEvent('flux-notifications-changed', { detail: { path: `/operational-requests/${record.id}/${action}` } }));
      return true;
    } catch (actionError) { setError(errorMessage(actionError)); return false; }
    finally { setBusyId(''); }
  };

  const submitCreate = async (event: FormEvent) => {
    event.preventDefault(); setBusyId('create'); setError('');
    try {
      const created = await createOperationRequest({
        ...form,
        delivery_items: form.delivery_item ? [{ description: form.delivery_item }] : [],
        related_source_type: form.operation_type === 'compliance_inspection_visit' && form.related_source_id ? 'compliance_record' : null,
        related_source_id: form.related_source_id || null,
        submit_for_approval: true,
      });
      setRecords((current) => [created, ...current]); setForm(EMPTY_FORM); setShowCreate(false); setNotice('Operational request submitted for approval.');
    } catch (createError) { setError(errorMessage(createError)); }
    finally { setBusyId(''); }
  };

  const submitSchedule = async (record: OperationRequest) => {
    const ok = await run(record, 'schedule', { vehicle_id: schedule.vehicle_id, driver_id: schedule.driver_id, planned_departure_at: schedule.planned_departure_at, expected_return_at: schedule.expected_return_at || null }, 'Vehicle and driver scheduled.');
    if (ok) setSchedule({ requestId: '', vehicle_id: '', driver_id: '', planned_departure_at: '', expected_return_at: '' });
  };

  const submitPersonalApproval = async (record: OperationRequest) => {
    const ok = await run(record, 'approve', { vehicle_id: schedule.vehicle_id || record.vehicle_id, planned_departure_at: schedule.planned_departure_at, expected_return_at: schedule.expected_return_at }, 'Personal Vehicle Use approved and reserved.');
    if (ok) setSchedule({ requestId: '', vehicle_id: '', driver_id: '', planned_departure_at: '', expected_return_at: '' });
  };

  const submitConfirmation = async () => {
    if (!confirming) return;
    const payload: Record<string, unknown> = { notes: confirmation.notes };
    if (confirming.operation_type === 'internal_company_delivery') payload.receiver_name = confirmation.receiver_name;
    if (confirming.operation_type === 'vehicle_repositioning') payload.accepted_by_name = confirmation.accepted_by_name;
    if (confirming.operation_type === 'compliance_inspection_visit') payload.outcome = confirmation.outcome;
    if (confirming.operation_type === 'fuel_station_visit') { payload.fuel_log_id = confirmation.fuel_log_id || null; payload.no_purchase_reason = confirmation.no_purchase_reason || null; }
    const ok = await run(confirming, 'confirm-task', payload, 'Task confirmation recorded.');
    if (ok) { setConfirming(null); setConfirmation({ receiver_name: '', accepted_by_name: '', outcome: '', fuel_log_id: '', no_purchase_reason: '', notes: '' }); }
  };

  const submitMovement = async () => {
    if (!movementAction || movementAction.draft.fuel == null) return;
    const { record, mode, draft } = movementAction;
    const odometer = draft.odometer.trim();
    const payload: Record<string, unknown> = {
      [mode === 'start' ? 'opening_fuel_level' : 'closing_fuel_level']: draft.fuel,
      notes: draft.notes.trim() || undefined,
    };
    if (odometer) payload[mode === 'start' ? 'opening_odometer' : 'closing_odometer'] = Number(odometer);
    const ok = await run(record, mode, payload, mode === 'start' ? 'Movement started.' : 'Physical return submitted for verification.');
    if (ok) setMovementAction(null);
  };

  const openMovement = (record: OperationRequest, mode: 'start' | 'return') => {
    setError('');
    setMovementAction({ record, mode, draft: { fuel: null, odometer: '', notes: '' } });
  };

  const driverActions = (record: OperationRequest) => {
    if (record.status === 'scheduled' && !record.acknowledged_at) return <ActionButton onClick={() => run(record, 'acknowledge', {}, 'Task acknowledged.')} busy={busyId === record.id}>Acknowledge</ActionButton>;
    if (record.status === 'scheduled') return <ActionButton onClick={() => openMovement(record, 'start')} busy={busyId === record.id}>Start Movement</ActionButton>;
    if (record.status === 'movement_in_progress') {
      const hasEvidence = record.operation_type === 'internal_company_delivery'
        ? Boolean(record.receiver_confirmation)
        : record.operation_type === 'vehicle_repositioning'
          ? Boolean(record.destination_acceptance)
          : Boolean(record.task_confirmation);
      return hasEvidence
        ? <ActionButton onClick={() => openMovement(record, 'return')} busy={busyId === record.id}>Return Vehicle</ActionButton>
        : <ActionButton onClick={() => setConfirming(record)} busy={false}>Confirm Task</ActionButton>;
    }
    return null;
  };

  return <div className="min-h-full bg-slate-50 p-4 md:p-6">
    <div className="mx-auto max-w-7xl space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div><h1 className="text-2xl font-semibold text-slate-900">{driverMode ? 'My Operational Tasks' : 'Operational Requests'}</h1><p className="text-sm text-slate-500">{activeCount} active · source status and physical movement remain independently auditable.</p></div>
        <div className="flex gap-2"><button type="button" onClick={() => void load()} disabled={loading} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"><RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />Refresh</button>{!driverMode && <button type="button" onClick={() => setShowCreate(true)} className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white"><Plus className="h-4 w-4" />New Request</button>}</div>
      </div>
      {error && <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"><AlertCircle className="h-4 w-4" />{error}</div>}
      {notice && <div className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-700"><CheckCircle2 className="h-4 w-4" />{notice}</div>}
      {!driverMode && personalAnalytics && <section className="space-y-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div><h2 className="font-semibold text-slate-900">Personal Vehicle Use analytics</h2><p className="text-sm text-slate-500">Lifetime reporting from operational requests and their linked vehicle movements.</p></div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6"><Select label="Driver" value={analyticsFilters.driver_id} onChange={(value) => setAnalyticsFilters((current) => ({ ...current, driver_id: value }))} options={(options?.drivers || []).map((item) => ({ value: item.id, label: item.full_name }))} /><Select label="Vehicle" value={analyticsFilters.vehicle_id} onChange={(value) => setAnalyticsFilters((current) => ({ ...current, vehicle_id: value }))} options={(options?.vehicles || []).map((item) => ({ value: item.id, label: item.registration_number }))} /><Field label="From" type="date" value={analyticsFilters.date_from} onChange={(value) => setAnalyticsFilters((current) => ({ ...current, date_from: value }))} /><Field label="To" type="date" value={analyticsFilters.date_to} onChange={(value) => setAnalyticsFilters((current) => ({ ...current, date_to: value }))} /><Field label="Branch ID" value={analyticsFilters.branch_id} onChange={(value) => setAnalyticsFilters((current) => ({ ...current, branch_id: value }))} /><Select label="Status" value={analyticsFilters.status} onChange={(value) => setAnalyticsFilters((current) => ({ ...current, status: value }))} options={(options?.statuses || []).map((item) => ({ value: item, label: item.replaceAll('_', ' ') }))} /></div>
        <div className="flex justify-end"><ActionButton onClick={async () => { try { setPersonalAnalytics(await fetchPersonalUseAnalytics(analyticsFilters)); } catch (caught) { setError(errorMessage(caught)); } }} busy={false}>Apply filters</ActionButton></div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4"><Metric label="Requests" value={String(personalAnalytics.totals.requests)} /><Metric label="Trips" value={String(personalAnalytics.totals.trips)} /><Metric label="Hours" value={personalAnalytics.totals.hours.toFixed(1)} /><Metric label="Distance" value={personalAnalytics.totals.distance == null ? 'Not recorded' : `${personalAnalytics.totals.distance} km`} /></div>
        <div className="overflow-x-auto"><table className="min-w-[1000px] w-full text-left text-sm"><thead className="bg-slate-50 text-xs uppercase text-slate-500"><tr><th className="p-3">Driver</th><th className="p-3">Requests</th><th className="p-3">Approved</th><th className="p-3">Rejected</th><th className="p-3">Cancelled</th><th className="p-3">Completed</th><th className="p-3">Pending</th><th className="p-3">Trips / hours</th><th className="p-3">Vehicles</th><th className="p-3">Target / other</th><th className="p-3">Approval rate</th><th className="p-3">Exceptions</th></tr></thead><tbody>{personalAnalytics.drivers.map((item) => <tr key={item.driver_id || item.driver_name} className="border-t"><td className="p-3 font-medium">{item.driver_name}</td><td className="p-3">{item.total_requests}</td><td className="p-3">{item.approved}</td><td className="p-3">{item.rejected}</td><td className="p-3">{item.cancelled}</td><td className="p-3">{item.completed}</td><td className="p-3">{item.pending}</td><td className="p-3">{item.total_personal_use_trips} / {item.total_personal_use_hours.toFixed(1)}</td><td className="p-3">{item.vehicles_used}</td><td className="p-3">{item.target_assigned_vehicle_usage_count} / {item.other_vehicle_usage_count}{item.unknown_target_usage_count ? ` / ${item.unknown_target_usage_count} unknown` : ''}</td><td className="p-3">{item.approval_rate}%</td><td className="p-3">{item.late_return_exception_count}</td></tr>)}</tbody></table></div>
        <div className="overflow-x-auto"><table className="min-w-[1100px] w-full text-left text-sm"><thead className="bg-slate-50 text-xs uppercase text-slate-500"><tr><th className="p-3">Date</th><th className="p-3">Driver</th><th className="p-3">Vehicle</th><th className="p-3">Target?</th><th className="p-3">Purpose</th><th className="p-3">Departure / return</th><th className="p-3">Duration</th><th className="p-3">Distance</th><th className="p-3">Status</th><th className="p-3">Approved by</th><th className="p-3">Fuel / cost</th><th className="p-3">Exception</th></tr></thead><tbody>{personalAnalytics.history.map((item) => <tr key={item.request_id} className="border-t"><td className="p-3">{formatDate(item.date)}</td><td className="p-3">{item.driver_name}</td><td className="p-3">{item.vehicle_registration}</td><td className="p-3">{item.target_vehicle == null ? '—' : item.target_vehicle ? 'Yes' : 'No'}</td><td className="p-3">{item.purpose || '—'}</td><td className="p-3">{formatDate(item.departure)}<br />{item.return ? formatDate(item.return) : 'Not recorded'}</td><td className="p-3">{item.duration_minutes == null ? '—' : `${item.duration_minutes} min`}</td><td className="p-3">{item.distance == null ? '—' : `${item.distance} km`}</td><td className="p-3 capitalize">{item.status.replaceAll('_', ' ')}</td><td className="p-3">{item.approved_by || '—'}</td><td className="p-3">{item.fuel_impact == null ? 'Not recorded' : item.fuel_impact}{item.cost_impact == null ? ' / —' : ` / ${item.cost_impact}`}</td><td className="p-3">{item.exception ? (item.late_return ? 'Late return' : 'Exception') : 'No'}</td></tr>)}</tbody></table></div>
      </section>}
      {loading ? <div className="flex min-h-56 items-center justify-center"><Loader2 className="h-7 w-7 animate-spin text-blue-600" /></div> : records.length === 0 ? <div className="rounded-xl border border-dashed border-slate-300 bg-white p-12 text-center text-slate-500">{error ? 'Operational requests could not be loaded.' : 'No operational requests found.'}</div> : <div className="grid gap-4 lg:grid-cols-2">{records.map((record) => <article key={record.id} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-start justify-between gap-3"><div><p className="text-xs font-medium uppercase tracking-wide text-blue-600">{record.request_id}</p><h2 className="mt-1 font-semibold text-slate-900">{record.title}</h2><p className="mt-1 text-sm text-slate-500">{LABELS[record.operation_type]}</p></div><span className={`rounded-full px-2.5 py-1 text-xs font-medium ${statusTone(record.status)}`}>{record.status.replaceAll('_', ' ')}</span></div>
        <p className="mt-4 text-sm text-slate-700">{record.purpose}</p>
        <div className="mt-4 grid grid-cols-2 gap-3 text-sm"><Info label="Route" value={[record.origin, record.destination].filter(Boolean).join(' → ') || 'Not set'} /><Info label="Departure" value={formatDate(record.planned_departure_at)} /><Info label="Vehicle" value={record.vehicle?.registration_number || 'Not assigned'} /><Info label="Driver" value={record.driver?.full_name || 'Not assigned'} /></div>
        <div className="mt-5 flex flex-wrap gap-2">{driverMode ? driverActions(record) : <>
          {record.status === 'draft' && <ActionButton onClick={() => run(record, 'submit')} busy={busyId === record.id}>Submit</ActionButton>}
          {record.status === 'pending_approval' && record.operation_type !== 'personal_use' && <ActionButton onClick={() => run(record, 'approve')} busy={busyId === record.id}>Approve</ActionButton>}
          {record.status === 'pending_approval' && record.operation_type === 'personal_use' && <><ActionButton onClick={() => setSchedule({ requestId: record.id, vehicle_id: record.vehicle_id || '', driver_id: record.driver_id || '', planned_departure_at: record.planned_departure_at?.slice(0, 16) || '', expected_return_at: record.expected_return_at?.slice(0, 16) || '' })} busy={false}>Review & Approve</ActionButton><ActionButton tone="secondary" onClick={() => { const reason = window.prompt('Rejection reason'); if (reason) void run(record, 'reject', { reason }, 'Personal Vehicle Use rejected.'); }} busy={busyId === record.id}>Reject</ActionButton></>}
          {record.status === 'approved' && <ActionButton onClick={() => setSchedule({ requestId: record.id, vehicle_id: '', driver_id: '', planned_departure_at: record.planned_departure_at?.slice(0, 16) || '', expected_return_at: record.expected_return_at?.slice(0, 16) || '' })} busy={false}>Assign & Schedule</ActionButton>}
          {record.status === 'awaiting_verification' && <ActionButton onClick={() => run(record, 'verify', {}, 'Operational request completed.')} busy={busyId === record.id}>Verify Completion</ActionButton>}
        </>}</div>
        {!driverMode && schedule.requestId === record.id && <div className="mt-4 grid gap-3 rounded-lg bg-slate-50 p-4 sm:grid-cols-2"><Select label="Vehicle" value={schedule.vehicle_id} onChange={(value) => setSchedule((current) => ({ ...current, vehicle_id: value }))} options={(options?.vehicles || []).map((item) => ({ value: item.id, label: `${item.registration_number}${item.is_available === false && item.primary_reason ? ` — ${item.primary_reason}` : ''}` }))} />{record.operation_type !== 'personal_use' && <Select label="Driver" value={schedule.driver_id} onChange={(value) => setSchedule((current) => ({ ...current, driver_id: value }))} options={(options?.drivers || []).map((item) => ({ value: item.id, label: item.full_name }))} />}<Field label="Departure" type="datetime-local" value={schedule.planned_departure_at} onChange={(value) => setSchedule((current) => ({ ...current, planned_departure_at: value }))} /><Field label="Expected return" type="datetime-local" value={schedule.expected_return_at} onChange={(value) => setSchedule((current) => ({ ...current, expected_return_at: value }))} /><div className="flex gap-2 sm:col-span-2"><ActionButton onClick={() => record.operation_type === 'personal_use' ? submitPersonalApproval(record) : submitSchedule(record)} busy={busyId === record.id}>{record.operation_type === 'personal_use' ? 'Approve & Reserve' : 'Schedule'}</ActionButton><ActionButton onClick={() => setSchedule((current) => ({ ...current, requestId: '' }))} busy={false} tone="secondary">Cancel</ActionButton></div></div>}
      </article>)}</div>}
    </div>

    {showCreate && <Modal title="New Operational Request" onClose={() => setShowCreate(false)}><form onSubmit={submitCreate} className="grid gap-4 sm:grid-cols-2"><Select label="Operation type" value={form.operation_type} onChange={(value) => setForm((current) => ({ ...current, operation_type: value as OperationType }))} options={Object.entries(LABELS).map(([value, label]) => ({ value, label }))} /><Select label="Journey" value={form.journey_mode} onChange={(value) => setForm((current) => ({ ...current, journey_mode: value }))} options={[{ value: 'one_way', label: 'One way' }, { value: 'round_trip', label: 'Round trip' }, { value: 'multi_stop', label: 'Multi-stop' }]} /><Field label="Title" value={form.title} onChange={(value) => setForm((current) => ({ ...current, title: value }))} required /><Field label="Purpose" value={form.purpose} onChange={(value) => setForm((current) => ({ ...current, purpose: value }))} required /><Field label="Origin" value={form.origin} onChange={(value) => setForm((current) => ({ ...current, origin: value }))} /><Field label="Destination" value={form.destination} onChange={(value) => setForm((current) => ({ ...current, destination: value }))} required />{form.operation_type === 'internal_company_delivery' && <><Field label="Sender" value={form.sender_name} onChange={(value) => setForm((current) => ({ ...current, sender_name: value }))} /><Field label="Intended receiver" value={form.intended_receiver_name} onChange={(value) => setForm((current) => ({ ...current, intended_receiver_name: value }))} /><div className="sm:col-span-2"><Field label="Items / documents" value={form.delivery_item} onChange={(value) => setForm((current) => ({ ...current, delivery_item: value }))} /></div></>}{form.operation_type === 'compliance_inspection_visit' && <div className="sm:col-span-2"><Field label="Compliance record ID (for blocker exception)" value={form.related_source_id} onChange={(value) => setForm((current) => ({ ...current, related_source_id: value }))} /></div>}<Field label="Planned departure" type="datetime-local" value={form.planned_departure_at} onChange={(value) => setForm((current) => ({ ...current, planned_departure_at: value }))} /><Field label="Expected return" type="datetime-local" value={form.expected_return_at} onChange={(value) => setForm((current) => ({ ...current, expected_return_at: value }))} /><div className="sm:col-span-2"><Field label="Notes" value={form.notes} onChange={(value) => setForm((current) => ({ ...current, notes: value }))} /></div><div className="flex justify-end gap-2 sm:col-span-2"><ActionButton onClick={() => setShowCreate(false)} busy={false} tone="secondary" type="button">Cancel</ActionButton><ActionButton onClick={() => undefined} busy={busyId === 'create'} type="submit">Submit for Approval</ActionButton></div></form></Modal>}

    {confirming && <Modal title="Confirm Operational Task" onClose={() => setConfirming(null)}><div className="space-y-4">{confirming.operation_type === 'internal_company_delivery' && <Field label="Receiver name" value={confirmation.receiver_name} onChange={(value) => setConfirmation((current) => ({ ...current, receiver_name: value }))} required />}{confirming.operation_type === 'vehicle_repositioning' && <Field label="Accepted by" value={confirmation.accepted_by_name} onChange={(value) => setConfirmation((current) => ({ ...current, accepted_by_name: value }))} required />}{confirming.operation_type === 'compliance_inspection_visit' && <Field label="Inspection outcome" value={confirmation.outcome} onChange={(value) => setConfirmation((current) => ({ ...current, outcome: value }))} required />}{confirming.operation_type === 'fuel_station_visit' && <><Field label="Fuel log ID (if purchased)" value={confirmation.fuel_log_id} onChange={(value) => setConfirmation((current) => ({ ...current, fuel_log_id: value }))} /><Field label="No-purchase reason (if none)" value={confirmation.no_purchase_reason} onChange={(value) => setConfirmation((current) => ({ ...current, no_purchase_reason: value }))} /></>}<Field label="Notes" value={confirmation.notes} onChange={(value) => setConfirmation((current) => ({ ...current, notes: value }))} /><div className="flex justify-end gap-2"><ActionButton onClick={() => setConfirming(null)} busy={false} tone="secondary">Cancel</ActionButton><ActionButton onClick={submitConfirmation} busy={busyId === confirming.id}>Save Confirmation</ActionButton></div></div></Modal>}
    {movementAction && <MovementFuelDialog mode={movementAction.mode} vehicleLabel={movementAction.record.vehicle?.registration_number} draft={movementAction.draft} busy={busyId === movementAction.record.id} error={error} onChange={(draft) => setMovementAction((current) => current ? { ...current, draft } : null)} onClose={() => setMovementAction(null)} onConfirm={() => void submitMovement()} />}
  </div>;
}

function ActionButton({ children, onClick, busy, tone = 'primary', type = 'button' }: { children: ReactNode; onClick: () => void; busy: boolean; tone?: 'primary' | 'secondary'; type?: 'button' | 'submit' }) {
  return <button type={type} onClick={onClick} disabled={busy} className={`inline-flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-medium disabled:opacity-60 ${tone === 'primary' ? 'bg-blue-600 text-white hover:bg-blue-700' : 'border border-slate-300 bg-white text-slate-700 hover:bg-slate-50'}`}>{busy && <Loader2 className="h-4 w-4 animate-spin" />}{children}</button>;
}
function Info({ label, value }: { label: string; value: string }) { return <div><p className="text-xs uppercase tracking-wide text-slate-400">{label}</p><p className="mt-1 text-slate-700">{value}</p></div>; }
function Metric({ label, value }: { label: string; value: string }) { return <div className="rounded-lg bg-slate-50 p-3"><p className="text-xs text-slate-500">{label}</p><p className="mt-1 text-lg font-semibold text-slate-900">{value}</p></div>; }
function Field({ label, value, onChange, type = 'text', required = false }: { label: string; value: string; onChange: (value: string) => void; type?: string; required?: boolean }) { return <label className="block text-sm font-medium text-slate-700">{label}<input type={type} value={value} required={required} onChange={(event) => onChange(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" /></label>; }
function Select({ label, value, onChange, options }: { label: string; value: string; onChange: (value: string) => void; options: Array<{ value: string; label: string }> }) { return <label className="block text-sm font-medium text-slate-700">{label}<select value={value} onChange={(event) => onChange(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5"><option value="">Select</option>{options.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>; }
function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) { return <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4"><div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-xl bg-white shadow-xl"><div className="flex items-center justify-between border-b border-slate-200 p-5"><div className="flex items-center gap-2"><ClipboardCheck className="h-5 w-5 text-blue-600" /><h2 className="text-lg font-semibold text-slate-900">{title}</h2></div><button type="button" onClick={onClose} className="rounded-lg p-2 hover:bg-slate-100" aria-label="Close"><X className="h-5 w-5" /></button></div><div className="p-5">{children}</div></div></div>; }
