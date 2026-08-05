import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { AlertCircle, Car, CheckCircle2, Clock3, Loader2, Plus, RefreshCw, X } from 'lucide-react';
import { ApiRequestError } from '../../lib/api';
import { MovementFuelDialog } from '../shared/MovementFuelDialog';
import {
  createOperationRequest,
  fetchOperationOptions,
  fetchOperationRequest,
  fetchOperationRequests,
  fetchPersonalUseAnalytics,
  mutateOperationRequest,
  PERSONAL_USE_OPERATION_TYPE,
  type OperationOptions,
  type OperationRequest,
  type PersonalUseAnalytics,
} from '../../lib/operational-request-api';
import { fetchVehicleMovementById, type VehicleMovementRecord } from '../../lib/vehicle-movement-api';

const EMPTY = { vehicle_id: '', purpose: '', origin: '', destination: '', planned_departure_at: '', expected_return_at: '', notes: '' };

function message(error: unknown) {
  return error instanceof ApiRequestError || error instanceof Error ? error.message : 'Unable to complete this action.';
}

function date(value?: string | null) {
  if (!value) return 'Not recorded';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function isPast(value?: string | null) {
  if (!value) return false;
  const parsed = new Date(value);
  return !Number.isNaN(parsed.getTime()) && parsed.getTime() < Date.now();
}

function tone(status: string) {
  if (['completed', 'returned', 'closed'].includes(status)) return 'bg-emerald-100 text-emerald-800';
  if (['rejected', 'cancelled', 'aborted'].includes(status)) return 'bg-red-100 text-red-800';
  if (['movement_in_progress', 'in_progress', 'awaiting_verification', 'ready_to_start'].includes(status)) return 'bg-amber-100 text-amber-800';
  return 'bg-blue-100 text-blue-800';
}

export default function PersonalVehicleUse() {
  const [records, setRecords] = useState<OperationRequest[]>([]);
  const [options, setOptions] = useState<OperationOptions | null>(null);
  const [analytics, setAnalytics] = useState<PersonalUseAnalytics | null>(null);
  const [loading, setLoading] = useState(true);
  const [vehiclesLoading, setVehiclesLoading] = useState(false);
  const [vehicleOptionsError, setVehicleOptionsError] = useState('');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(EMPTY);
  const [inspection, setInspection] = useState<{ id: string; mode: 'opening' | 'return'; odometer: string; fuel: number | null; notes: string; damage: string } | null>(null);
  const [movements, setMovements] = useState<Record<string, VehicleMovementRecord>>({});
  const vehicleOptionsRequest = useRef(0);

  const load = async () => {
    setLoading(true); setError('');
    try {
      const [list, available, usage] = await Promise.all([fetchOperationRequests({ operation_type: PERSONAL_USE_OPERATION_TYPE }), fetchOperationOptions(), fetchPersonalUseAnalytics()]);
      setRecords(list.requests); setOptions(available); setAnalytics(usage);
      const linked = list.requests.filter((record) => record.linked_vehicle_movement_id);
      const movementResults = await Promise.allSettled(linked.map((record) => fetchVehicleMovementById(record.linked_vehicle_movement_id!)));
      setMovements(Object.fromEntries(movementResults.flatMap((result) => result.status === 'fulfilled' ? [[result.value.id, result.value] as const] : [])));
    } catch (caught) { setError(message(caught)); }
    finally { setLoading(false); }
  };
  useEffect(() => { void load(); }, []);

  useEffect(() => {
    if (!form.planned_departure_at || !form.expected_return_at) return;
    const requestId = ++vehicleOptionsRequest.current;
    const timeout = window.setTimeout(async () => {
      setVehiclesLoading(true); setVehicleOptionsError('');
      try {
        const available = await fetchOperationOptions({
          planned_departure_at: form.planned_departure_at,
          expected_return_at: form.expected_return_at,
        });
        if (requestId !== vehicleOptionsRequest.current) return;
        setOptions(available);
        setForm((current) => {
          const selected = available.vehicles.find((vehicle) => vehicle.id === current.vehicle_id);
          return selected && selected.is_available === false ? { ...current, vehicle_id: '' } : current;
        });
      } catch (caught) {
        if (requestId === vehicleOptionsRequest.current) setVehicleOptionsError(message(caught));
      } finally {
        if (requestId === vehicleOptionsRequest.current) setVehiclesLoading(false);
      }
    }, 250);
    return () => window.clearTimeout(timeout);
  }, [form.planned_departure_at, form.expected_return_at]);

  const active = useMemo(() => records.filter((record) => !['completed', 'rejected', 'cancelled', 'aborted'].includes(record.status)).length, [records]);

  const run = async (record: OperationRequest, action: string, payload: Record<string, unknown> = {}, success = 'Request updated.') => {
    setBusy(`${record.id}:${action}`); setError(''); setNotice('');
    try {
      const updated = await mutateOperationRequest(record.id, action, payload);
      setRecords((current) => current.map((item) => item.id === updated.id ? updated : item));
      try {
        const fresh = await fetchOperationRequest(updated.id);
        setRecords((current) => current.map((item) => item.id === fresh.id ? fresh : item));
        if (fresh.linked_vehicle_movement_id) {
          const movement = await fetchVehicleMovementById(fresh.linked_vehicle_movement_id, { fresh: true });
          setMovements((current) => ({ ...current, [movement.id]: movement }));
        }
      } catch (refreshError) {
        setError(`Action saved, but the latest movement state could not be refreshed: ${message(refreshError)}`);
      }
      setNotice(success); return true;
    } catch (caught) { setError(message(caught)); return false; }
    finally { setBusy(''); }
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault(); setBusy('create'); setError('');
    try {
      const created = await createOperationRequest({
        ...form, operation_type: PERSONAL_USE_OPERATION_TYPE, title: `Personal Vehicle Use — ${form.destination}`,
        journey_mode: 'round_trip', submit_for_approval: true,
      });
      setRecords((current) => [created, ...current]); setForm(EMPTY); setShowForm(false);
      setNotice('Personal Vehicle Use request submitted for approval.');
    } catch (caught) { setError(message(caught)); }
    finally { setBusy(''); }
  };

  const saveInspection = async () => {
    if (!inspection) return;
    const record = records.find((item) => item.id === inspection.id);
    if (!record) return;
    const odometer = inspection.odometer === '' ? undefined : Number(inspection.odometer);
    if (inspection.fuel == null || (odometer !== undefined && (!Number.isFinite(odometer) || odometer < 0))) {
      setError('Select a fuel level and enter a valid non-negative odometer when available.'); return;
    }
    const returning = inspection.mode === 'return';
    const payload = returning
      ? { closing_odometer: odometer, closing_fuel_level: inspection.fuel, notes: inspection.notes, damage_reported: Boolean(inspection.damage.trim()), damage_notes: inspection.damage }
      : { opening_odometer: odometer, opening_fuel_level: inspection.fuel, notes: inspection.notes };
    const ok = await run(record, returning ? 'return' : 'opening-check', payload, returning ? 'Vehicle return completed.' : 'Opening check saved. You can now start the movement.');
    if (ok) setInspection(null);
  };

  return <div className="min-h-full bg-slate-50 p-4 md:p-6"><div className="mx-auto max-w-6xl space-y-5">
    <header className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"><div><h1 className="text-2xl font-semibold text-slate-900">Personal Vehicle Use</h1><p className="text-sm text-slate-500">Request a FleetOps vehicle using your existing Driver account. {active} active request{active === 1 ? '' : 's'}.</p></div><div className="flex gap-2"><button onClick={() => void load()} disabled={loading} className="inline-flex min-h-11 items-center gap-2 rounded-lg border bg-white px-4 py-2"><RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />Refresh</button><button onClick={() => setShowForm(true)} className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-white"><Plus className="h-4 w-4" />New request</button></div></header>
    {error && <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"><AlertCircle className="h-4 w-4 shrink-0" />{error}</div>}
    {notice && <div className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-700"><CheckCircle2 className="h-4 w-4 shrink-0" />{notice}</div>}
    {analytics && <section className="grid grid-cols-2 gap-3 sm:grid-cols-4"><Metric label="Lifetime requests" value={String(analytics.totals.requests)} /><Metric label="Personal trips" value={String(analytics.totals.trips)} /><Metric label="Hours" value={analytics.totals.hours.toFixed(1)} /><Metric label="Distance" value={analytics.totals.distance == null ? 'Not recorded' : `${analytics.totals.distance} km`} /></section>}
    {loading ? <div className="flex min-h-52 items-center justify-center"><Loader2 className="h-7 w-7 animate-spin text-blue-600" /></div> : records.length === 0 ? <div className="rounded-xl border border-dashed bg-white p-12 text-center text-slate-500"><Car className="mx-auto mb-3 h-9 w-9" />No Personal Vehicle Use requests yet.</div> : <div className="grid gap-4 lg:grid-cols-2">{records.map((record) => {
      const movement = record.linked_vehicle_movement_id ? movements[record.linked_vehicle_movement_id] : undefined;
      const movementStatus = movement?.status || record.linked_vehicle_movement_status || undefined;
      const hasLinkedMovement = Boolean(record.linked_vehicle_movement_id);
      const movementStateKnown = !hasLinkedMovement || Boolean(movementStatus);
      const needsOpeningCheck = movementStatus === 'approved';
      const readyToStart = movementStatus === 'checked_out';
      const canReturn = movementStatus === 'in_progress';
      const movementFinished = movementStatus === 'returned' || movementStatus === 'closed';
      const cardStatus = movementStatus === 'closed' ? 'completed'
        : movementStatus === 'returned' ? 'returned'
          : canReturn ? 'in_progress'
            : readyToStart ? 'ready_to_start'
              : movementStatus === 'approved' ? 'scheduled'
                : record.status;
      const departureOverdue = (needsOpeningCheck || readyToStart) && isPast(record.planned_departure_at);
      const returnOverdue = canReturn && isPast(record.expected_return_at);
      return <article key={record.id} className="rounded-xl border bg-white p-5 shadow-sm">
      <div className="flex items-start justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-wide text-blue-600">{record.request_id}</p><h2 className="mt-1 font-semibold">{record.purpose}</h2></div><span className={`rounded-full px-2.5 py-1 text-xs font-medium capitalize ${tone(cardStatus)}`}>{cardStatus.replaceAll('_', ' ')}</span></div>
      <div className="mt-4 grid grid-cols-2 gap-3 text-sm"><Info label="Vehicle" value={record.vehicle?.registration_number || 'Awaiting vehicle'} /><Info label="Route" value={`${record.origin || '—'} → ${record.destination || '—'}`} /><Info label="Departure" value={date(record.planned_departure_at)} /><Info label="Expected return" value={date(record.expected_return_at)} /></div>
      {departureOverdue && <div className="mt-3 flex items-center gap-2 rounded-lg bg-amber-50 p-2 text-sm font-medium text-amber-800"><Clock3 className="h-4 w-4" />Departure overdue</div>}
      {returnOverdue && <div className="mt-3 flex items-center gap-2 rounded-lg bg-red-50 p-2 text-sm font-medium text-red-700"><Clock3 className="h-4 w-4" />Return overdue</div>}
      {hasLinkedMovement && !movementStateKnown && <div className="mt-3 flex items-center gap-2 rounded-lg bg-amber-50 p-2 text-sm text-amber-800"><AlertCircle className="h-4 w-4" />Linked movement state is unavailable. Refresh before continuing.</div>}
      {record.status === 'rejected' && <p className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-700">Decision: rejected{record.rejection_reason ? ` — ${record.rejection_reason}` : ''}</p>}
      {(record.status === 'completed' || movementFinished) && <div className="mt-3 grid grid-cols-3 gap-2 rounded-lg bg-slate-50 p-3 text-xs"><Info label="Distance" value={record.distance_travelled == null ? '—' : `${record.distance_travelled} km`} /><Info label="Duration" value={record.duration_minutes == null ? '—' : `${record.duration_minutes} min`} /><Info label="Returned" value={date(record.returned_at)} /></div>}
      <div className="mt-5 flex flex-wrap gap-2">
        {record.status === 'draft' && <Button busy={busy === `${record.id}:submit`} onClick={() => void run(record, 'submit', {}, 'Request submitted for approval.')}>Submit</Button>}
        {record.status === 'scheduled' && !record.acknowledged_at && movementStatus === 'approved' && <Button busy={busy === `${record.id}:acknowledge`} onClick={() => void run(record, 'acknowledge', {}, 'Vehicle custody acknowledged.')}>Acknowledge custody</Button>}
        {record.status === 'scheduled' && record.acknowledged_at && needsOpeningCheck && <Button busy={false} onClick={() => setInspection({ id: record.id, mode: 'opening', odometer: '', fuel: null, notes: '', damage: '' })}>Opening Check</Button>}
        {record.status === 'scheduled' && record.acknowledged_at && readyToStart && <Button busy={busy === `${record.id}:start`} onClick={() => void run(record, 'start', {}, 'Personal trip started.')}>Start Movement</Button>}
        {canReturn && <Button busy={false} onClick={() => setInspection({ id: record.id, mode: 'return', odometer: '', fuel: null, notes: '', damage: '' })}>Complete / return</Button>}
        {['draft', 'pending_approval', 'approved', 'scheduled'].includes(record.status) && !canReturn && !readyToStart && !needsOpeningCheck && !(record.status === 'scheduled' && record.acknowledged_at) && <Button secondary busy={busy === `${record.id}:cancel`} onClick={() => void run(record, 'cancel', { reason: 'Cancelled by requesting driver.' }, 'Request cancelled.')}>Cancel</Button>}
      </div>
    </article>; })}</div>}
  </div>

  {showForm && <Modal title="Request Personal Vehicle Use" onClose={() => setShowForm(false)}><form onSubmit={submit} className="grid gap-4 sm:grid-cols-2"><div><Select label="Fleet vehicle" value={form.vehicle_id} onChange={(value) => setForm({ ...form, vehicle_id: value })} disabled={vehiclesLoading} placeholder={vehiclesLoading ? 'Checking availability…' : 'Select vehicle'} options={(options?.vehicles || []).map((vehicle) => ({ value: vehicle.id, label: `${vehicle.registration_number} — ${vehicle.availability_label || vehicle.primary_reason || (vehicle.is_available === false ? 'Unavailable' : 'Available')}`, disabled: vehicle.is_available === false }))} />{vehicleOptionsError && <p className="mt-1 text-sm text-red-600">{vehicleOptionsError}</p>}{!vehiclesLoading && !vehicleOptionsError && form.planned_departure_at && form.expected_return_at && !(options?.vehicles || []).some((vehicle) => vehicle.is_available !== false) && <p className="mt-1 text-sm text-amber-700">No vehicles available for the selected period.</p>}</div><Field label="Purpose" value={form.purpose} onChange={(value) => setForm({ ...form, purpose: value })} required /><Field label="Starting location" value={form.origin} onChange={(value) => setForm({ ...form, origin: value })} required /><Field label="Destination" value={form.destination} onChange={(value) => setForm({ ...form, destination: value })} required /><Field type="datetime-local" label="Planned departure" value={form.planned_departure_at} onChange={(value) => setForm({ ...form, planned_departure_at: value })} required /><Field type="datetime-local" label="Expected return" value={form.expected_return_at} onChange={(value) => setForm({ ...form, expected_return_at: value })} required /><div className="sm:col-span-2"><Field label="Notes" value={form.notes} onChange={(value) => setForm({ ...form, notes: value })} /></div><footer className="flex flex-col-reverse gap-2 sm:col-span-2 sm:flex-row sm:justify-end"><Button secondary busy={false} type="button" onClick={() => setShowForm(false)}>Cancel</Button><Button busy={busy === 'create'} type="submit" onClick={() => undefined}>Submit for approval</Button></footer></form></Modal>}
  {inspection && <MovementFuelDialog mode={inspection.mode === 'return' ? 'return' : 'start'} title={inspection.mode === 'opening' ? 'Opening Check' : undefined} confirmLabel={inspection.mode === 'opening' ? 'Save Opening Check' : undefined} vehicleLabel={records.find((item) => item.id === inspection.id)?.vehicle?.registration_number} draft={inspection} busy={Boolean(busy)} error={error} onChange={(draft) => setInspection({ ...inspection, ...draft })} onClose={() => setInspection(null)} onConfirm={() => void saveInspection()}>{inspection.mode === 'return' ? <Field label="Damage / fault found (optional)" value={inspection.damage} onChange={(damage) => setInspection({ ...inspection, damage })} /> : null}</MovementFuelDialog>}
  </div>;
}

function Info({ label, value }: { label: string; value: string }) { return <div className="min-w-0"><p className="text-[11px] uppercase tracking-wide text-slate-400">{label}</p><p className="mt-1 break-words text-slate-700">{value}</p></div>; }
function Metric({ label, value }: { label: string; value: string }) { return <div className="rounded-xl border bg-white p-4"><p className="text-xs text-slate-500">{label}</p><p className="mt-1 text-xl font-semibold text-slate-900">{value}</p></div>; }
function Field({ label, value, onChange, required = false, type = 'text' }: { label: string; value: string; onChange: (value: string) => void; required?: boolean; type?: string }) { return <label className="block text-sm font-medium text-slate-700">{label}<input type={type} min={type === 'number' ? 0 : undefined} required={required} value={value} onChange={(event) => onChange(event.target.value)} className="mt-1 min-h-11 w-full rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" /></label>; }
function Select({ label, value, onChange, options, disabled = false, placeholder = 'Select vehicle' }: { label: string; value: string; onChange: (value: string) => void; options: Array<{ value: string; label: string; disabled?: boolean }>; disabled?: boolean; placeholder?: string }) { return <label className="block text-sm font-medium text-slate-700">{label}<select required disabled={disabled} value={value} onChange={(event) => onChange(event.target.value)} className="mt-1 min-h-11 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-base disabled:bg-slate-100"><option value="">{placeholder}</option>{options.map((option) => <option key={option.value} value={option.value} disabled={option.disabled}>{option.label}</option>)}</select></label>; }
function Button({ children, onClick, busy, secondary = false, type = 'button' }: { children: React.ReactNode; onClick: () => void; busy: boolean; secondary?: boolean; type?: 'button' | 'submit' }) { return <button type={type} onClick={onClick} disabled={busy} className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium disabled:opacity-60 ${secondary ? 'border bg-white text-slate-700' : 'bg-blue-600 text-white'}`}>{busy && <Loader2 className="h-4 w-4 animate-spin" />}{children}</button>; }
function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) { return <div className="fixed inset-0 z-50 flex items-end justify-center bg-slate-950/50 sm:items-center sm:p-4"><section className="flex max-h-[100dvh] w-full max-w-2xl flex-col overflow-hidden rounded-t-2xl bg-white shadow-xl sm:max-h-[85vh] sm:rounded-2xl"><header className="sticky top-0 flex items-center justify-between border-b bg-white p-4"><h2 className="text-lg font-semibold">{title}</h2><button onClick={onClose} className="rounded-lg p-2" aria-label="Close"><X className="h-5 w-5" /></button></header><div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-5">{children}</div></section></div>; }
