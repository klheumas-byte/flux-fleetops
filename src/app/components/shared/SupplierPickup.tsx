import { useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, ClipboardList, Loader2, PackagePlus, Plus, RefreshCw, Search, Trash2, X } from 'lucide-react';
import { ApiRequestError } from '../../lib/api';
import { fetchOperationOptions, type OperationOptions } from '../../lib/operational-request-api';
import { createStockTransfer, fetchStockTransfer, fetchStockTransfers, fetchSupplierPickupTasks, mutateStockTransfer, type StockTransfer, type StockTransferItem } from '../../lib/stock-transfer-api';
import { searchWaybillProducts, type WaybillProduct } from '../../lib/waybill-api';

const PICKUP_STATUSES = ['Draft', 'Approved', 'Assigned', 'Driver Accepted', 'Arrived at Supplier', 'Pickup Confirmed', 'Loaded', 'In Transit', 'Delivered', 'Completed'];
const emptyForm = () => ({
  supplier_name: '', contact_person: '', primary_phone: '', pickup_address: '',
  receiving_location: '', requested_date: '', pickup_instructions: '', supplier_reference: '',
});
const message = (error: unknown) => error instanceof ApiRequestError || error instanceof Error ? error.message : 'Unable to save supplier pickup.';
const displayStage = (record: StockTransfer) => {
  if (record.status === 'scheduled' && record.pickup_confirmation) return 'Pickup Confirmed';
  if (record.status === 'scheduled' && record.supplier_arrived_at) return 'Arrived at Supplier';
  if (record.status === 'scheduled') return record.acknowledged_at ? 'Driver Accepted' : 'Assigned';
  if (record.status === 'released') return 'Loaded';
  if (record.status === 'in_transit') return 'In Transit';
  if (record.status === 'awaiting_receipt') return 'Delivered';
  if (record.status === 'completed') return 'Completed';
  return record.status.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
};
const currentAction = (record: StockTransfer) => {
  if (record.status === 'scheduled' && !record.acknowledged_at) return 'Accept Pickup';
  if (record.status === 'scheduled' && !record.supplier_arrived_at) return 'Arrive at Supplier';
  if (record.status === 'scheduled' && !record.pickup_confirmation) return 'Confirm Pickup';
  if (record.status === 'scheduled') return 'Mark Loaded';
  if (record.status === 'released') return 'Start Journey';
  if (record.status === 'in_transit') return 'Mark Delivered';
  if (record.status === 'awaiting_receipt') return 'Confirm Delivery with Receiver';
  return 'No action required';
};
const loadingLabel = (active: boolean, label: string, pendingLabel: string) => <>{active && <Loader2 className="h-4 w-4 animate-spin" />}{active ? pendingLabel : label}</>;

export default function SupplierPickup({ driverMode = false, taskId }: { driverMode?: boolean; taskId?: string }) {
  const loadedOnce = useRef(false);
  const [records, setRecords] = useState<StockTransfer[]>([]);
  const [options, setOptions] = useState<OperationOptions | null>(null);
  const [creating, setCreating] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [busyAction, setBusyAction] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [scheduling, setScheduling] = useState({ id: '', vehicle_id: '', driver_id: '' });
  const [pickupEntry, setPickupEntry] = useState<{ id: string; items: Record<string, { collected: string; reason: string }> }>({ id: '', items: {} });
  const [deliveryEntry, setDeliveryEntry] = useState<{ id: string; receiver_name: string; receiver_contact: string; receiver_initials: string; items: Record<string, string> }>({ id: '', receiver_name: '', receiver_contact: '', receiver_initials: '', items: {} });

  const load = async () => {
    if (!loadedOnce.current) setLoading(true);
    setError('');
    try {
      const items = taskId
        ? [await fetchStockTransfer(taskId)]
        : await (driverMode ? fetchSupplierPickupTasks() : fetchStockTransfers({ operation_type: 'supplier_pickup' }));
      setRecords(items);
      // Vehicle availability/options are only needed when assigning a pickup.
      // Load them after the task list so they cannot delay the admin page.
      if (!driverMode && !options) void fetchOperationOptions().then(setOptions).catch(() => undefined);
    } catch (value) { setError(message(value)); } finally { loadedOnce.current = true; setLoading(false); }
  };
  useEffect(() => { void load(); }, [driverMode, taskId]);
  useEffect(() => {
    if (!driverMode || taskId) return;
    const refresh = () => { if (document.visibilityState === 'visible') void load(); };
    const interval = window.setInterval(refresh, 15_000);
    window.addEventListener('flux-notifications-changed', refresh);
    return () => { window.clearInterval(interval); window.removeEventListener('flux-notifications-changed', refresh); };
  }, [driverMode, taskId]);

  const run = async (record: StockTransfer, action: string, payload: Record<string, unknown> = {}) => {
    setBusy(true); setBusyAction(`${record.id}:${action}`); setError(''); setNotice('');
    try {
      const updated = await mutateStockTransfer(record.id, action, payload);
      setRecords((current) => current.map((item) => item.id === updated.id ? updated : item));
      window.dispatchEvent(new CustomEvent('flux-notifications-changed', { detail: { operationType: 'supplier_pickup', taskId: record.id } }));
      return updated;
    } catch (value) { setError(message(value)); return undefined; } finally { setBusy(false); setBusyAction(''); }
  };
  const isBusy = (record: StockTransfer, action?: string) => busyAction === `${record.id}:${action}` || (!action && busyAction.startsWith(`${record.id}:`));
  const approve = async (record: StockTransfer) => {
    const submitted = record.status === 'draft' ? await run(record, 'submit') : record;
    if (!submitted) return;
    const approved = await run(submitted, 'approve');
    if (approved) setNotice('Supplier pickup approved and locked.');
  };
  const assign = async (record: StockTransfer) => {
    const scheduledAt = record.requested_date ? `${record.requested_date}T09:00:00` : new Date().toISOString();
    const updated = await run(record, 'schedule', { vehicle_id: scheduling.vehicle_id, driver_id: scheduling.driver_id, scheduled_at: scheduledAt });
    if (updated) { setScheduling({ id: '', vehicle_id: '', driver_id: '' }); setNotice(record.status === 'scheduled' ? 'Supplier pickup reassigned.' : 'Supplier pickup assigned.'); await load(); }
  };
  const acceptAssignment = async (record: StockTransfer) => {
    const updated = await run(record, 'acknowledge');
    if (updated) { setNotice('Supplier Pickup assignment accepted.'); await load(); }
  };
  const openPickupEntry = (record: StockTransfer) => setPickupEntry({ id: record.id, items: Object.fromEntries((record.transfer_items || []).map((item) => [item.item_id, { collected: String(item.quantity), reason: '' }])) });
  useEffect(() => {
    if (!driverMode || pickupEntry.id) return;
    const arrived = records.find((record) => record.status === 'scheduled' && Boolean(record.supplier_arrived_at) && !record.pickup_confirmation);
    if (arrived) openPickupEntry(arrived);
  }, [driverMode, records, pickupEntry.id]);
  const savePickupConfirmation = async (record: StockTransfer) => {
    const invalid = (record.transfer_items || []).find((item) => { const entry = pickupEntry.items[item.item_id]; const collected = Number(entry?.collected); const variance = Number(item.quantity) - collected; return !entry || entry.collected === '' || !Number.isFinite(collected) || collected < 0 || collected > Number(item.quantity) || (variance !== 0 && !entry.reason.trim()); });
    if (invalid) { setError(`Enter a valid collected quantity for ${invalid.name}. A reason is required for every variance.`); return; }
    const items = (record.transfer_items || []).map((item) => ({ item_id: item.item_id, collected_quantity: Number(pickupEntry.items[item.item_id]?.collected), shortfall_reason: pickupEntry.items[item.item_id]?.reason || undefined }));
    const updated = await run(record, 'pickup-confirmation', { items });
    if (updated) { setPickupEntry({ id: '', items: {} }); setNotice('Collected quantities confirmed.'); }
  };
  const openDeliveryConfirmation = (record: StockTransfer) => {
    const quantities = record.pickup_confirmation?.items || [];
    setDeliveryEntry({ id: record.id, receiver_name: record.recipient?.full_name || '', receiver_contact: record.recipient?.primary_phone || '', receiver_initials: '', items: Object.fromEntries(quantities.map((item) => [item.item_id, String(item.collected_quantity)])) });
  };
  const saveDeliveryConfirmation = async (record: StockTransfer) => {
    if (!deliveryEntry.receiver_name.trim() || !deliveryEntry.receiver_contact.trim() || !deliveryEntry.receiver_initials.trim()) {
      setError('Receiver name, contact, and initials are required.'); return;
    }
    const confirmedItems = record.pickup_confirmation?.items || [];
    const invalid = confirmedItems.find((item) => { const quantity = Number(deliveryEntry.items[item.item_id]); return !Number.isFinite(quantity) || quantity < 0 || quantity !== Number(item.collected_quantity); });
    if (invalid) { setError(`Received quantity for ${invalid.name} must match the collected quantity. Delivery exceptions are handled separately.`); return; }
    const updated = await run(record, 'verify-delivery', {
      actual_receiver: { full_name: deliveryEntry.receiver_name.trim(), primary_contact: deliveryEntry.receiver_contact.trim(), initials: deliveryEntry.receiver_initials.trim(), acknowledged: true },
      items: confirmedItems.map((item) => ({ item_id: item.item_id, expected_quantity: item.collected_quantity, received_quantity: Number(deliveryEntry.items[item.item_id]), condition: 'correct' })),
    });
    if (updated) { setDeliveryEntry({ id: '', receiver_name: '', receiver_contact: '', receiver_initials: '', items: {} }); setNotice('Supplier Pickup delivered and completed.'); await load(); }
  };

  return <div className="min-h-full bg-slate-50 p-4 md:p-6">
    <div className="mx-auto max-w-7xl space-y-5">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">{driverMode ? 'My Supplier Pickup Tasks' : 'Supplier Pickup'}</h1>
          <p className="text-sm text-slate-500">{driverMode ? 'Review and confirm pickups assigned to you.' : 'Create supplier pickup requests using the shared operations workflow.'}</p>
        </div>
        <div className="flex gap-2"><button type="button" disabled={loading} onClick={() => void load()} className="rounded-lg border bg-white p-2.5 disabled:opacity-60" aria-label="Refresh supplier pickups"><RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} /></button>{!driverMode && <button type="button" onClick={() => setCreating(true)} className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white"><Plus className="h-4 w-4" />Create Pickup Request</button>}</div>
      </header>

      <div className="overflow-x-auto rounded-xl border bg-white p-3"><div className="flex min-w-max items-center gap-2">
        {PICKUP_STATUSES.map((status, index) => <div key={status} className="flex items-center gap-2"><span className="rounded-full bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-600">{status}</span>{index < PICKUP_STATUSES.length - 1 && <span className="text-slate-300">→</span>}</div>)}
      </div></div>

      {error && <div className="flex gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"><AlertCircle className="h-4 w-4 shrink-0" />{error}</div>}
      {notice && <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-700">{notice}</div>}

      {creating && !driverMode && <CreatePickupRequestPanel busy={busy} setBusy={setBusy} onError={setError} onCancel={() => setCreating(false)} onCreated={(record) => { setRecords((current) => [record, ...current]); setCreating(false); setNotice('Supplier pickup draft saved.'); }} />}

      {loading ? <div className="flex h-56 items-center justify-center"><Loader2 className="h-7 w-7 animate-spin text-blue-600" /></div> : records.length ? <div className="grid gap-4 lg:grid-cols-2">
        {records.map((record) => <article key={record.id} className="rounded-xl border bg-white p-5 shadow-sm">
          <div className="flex justify-between gap-3"><div><p className="text-xs font-medium text-blue-600">{record.transfer_id}</p><h2 className="mt-1 font-semibold text-slate-900">{record.supplier?.supplier_name || 'Supplier'} → {record.receiving_location}</h2><p className="mt-1 text-sm text-slate-500">{record.item_count} item(s){record.requested_date ? ` · Requested ${new Date(`${record.requested_date}T00:00:00`).toLocaleDateString()}` : ''}</p>{record.supplier_reference && <p className="mt-2 text-sm text-slate-700">Reference: {record.supplier_reference}</p>}</div><span className="h-fit rounded-full bg-blue-100 px-2.5 py-1 text-xs text-blue-800">{displayStage(record)}</span></div>
          <div className="mt-4 rounded-lg bg-slate-50 p-3 text-sm text-slate-700"><p className="font-medium text-slate-900">{record.supplier?.contact_person}</p><p className="mt-1">{record.supplier?.primary_phone}{record.supplier?.email ? ` · ${record.supplier.email}` : ''}</p><p className="mt-2 text-slate-600">{record.supplier?.pickup_address}</p></div>
          {record.approved_at && <p className="mt-3 text-xs text-slate-500">Approved {new Date(record.approved_at).toLocaleString()}</p>}
          {driverMode && <p className="mt-3 text-sm text-slate-700"><span className="font-medium">Current action:</span> {currentAction(record)}</p>}
          {record.vehicle_id && record.driver_id && <div className="mt-3 grid gap-2 rounded-lg border bg-white p-3 text-sm sm:grid-cols-2"><p><span className="text-slate-500">Vehicle:</span> {record.vehicle?.registration_number || options?.vehicles.find((item) => item.id === record.vehicle_id)?.registration_number || record.vehicle_id}</p><p><span className="text-slate-500">Driver:</span> {options?.drivers.find((item) => item.id === record.driver_id)?.full_name || (driverMode ? 'Assigned to you' : record.driver_id)}</p></div>}
          {driverMode && (record.transfer_items || []).length > 0 && <div className="mt-3 overflow-hidden rounded-lg border"><table className="w-full text-sm"><thead className="bg-slate-50 text-left text-slate-600"><tr><th className="px-3 py-2">Requested item</th><th className="px-3 py-2">Requested quantity</th></tr></thead><tbody>{record.transfer_items!.map((item) => <tr key={item.item_id} className="border-t"><td className="px-3 py-2">{item.name}</td><td className="px-3 py-2">{item.quantity} {item.unit}</td></tr>)}</tbody></table></div>}
          <div className="mt-4 flex flex-wrap gap-2">
            {!driverMode && ['draft', 'pending_approval'].includes(record.status) && <button type="button" disabled={busy} onClick={() => void approve(record)} className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-60">{loadingLabel(isBusy(record), 'Approve', 'Approving…')}</button>}
            {!driverMode && record.status === 'approved' && <button type="button" onClick={() => setScheduling({ id: record.id, vehicle_id: '', driver_id: '' })} className="rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white">Assign Driver + Vehicle</button>}
            {!driverMode && record.status === 'scheduled' && !record.acknowledged_at && <button type="button" onClick={() => setScheduling({ id: record.id, vehicle_id: record.vehicle_id || '', driver_id: record.driver_id || '' })} className="rounded-lg border px-3 py-2 text-sm font-medium text-slate-700">Reassign</button>}
            {driverMode && record.status === 'scheduled' && !record.acknowledged_at && <button type="button" disabled={busy} onClick={() => void acceptAssignment(record)} className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-60">{loadingLabel(isBusy(record, 'acknowledge'), 'Accept Pickup', 'Accepting…')}</button>}
            {driverMode && record.status === 'scheduled' && record.acknowledged_at && !record.supplier_arrived_at && <button type="button" disabled={busy} onClick={() => void run(record, 'arrive')} className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-60">{loadingLabel(isBusy(record, 'arrive'), 'Arrived at Supplier', 'Updating…')}</button>}
            {driverMode && record.status === 'scheduled' && Boolean(record.pickup_confirmation) && <button type="button" disabled={busy} onClick={() => void run(record, 'release')} className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-60">{loadingLabel(isBusy(record, 'release'), 'Mark Loaded', 'Loading…')}</button>}
            {driverMode && record.status === 'released' && <button type="button" disabled={busy} onClick={() => void run(record, 'start')} className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-60">{loadingLabel(isBusy(record, 'start'), 'Start Journey', 'Starting…')}</button>}
            {driverMode && record.status === 'in_transit' && <button type="button" disabled={busy} onClick={() => void run(record, 'arrive')} className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-60">{loadingLabel(isBusy(record, 'arrive'), 'Mark Delivered', 'Delivering…')}</button>}
            {driverMode && record.status === 'awaiting_receipt' && !record.actual_receiver && <button type="button" disabled={busy} onClick={() => openDeliveryConfirmation(record)} className="rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-60">Confirm Delivery</button>}
          </div>
          {scheduling.id === record.id && <div className="mt-4 grid gap-3 rounded-lg bg-slate-50 p-4 sm:grid-cols-2">{!options && <div className="inline-flex items-center gap-2 text-sm text-slate-600 sm:col-span-2"><Loader2 className="h-4 w-4 animate-spin" />Loading vehicles and drivers…</div>}<Select label="Vehicle" value={scheduling.vehicle_id} onChange={(vehicle_id) => setScheduling({ ...scheduling, vehicle_id })} options={(options?.vehicles || []).map((item) => ({ value: item.id, label: item.registration_number }))} /><Select label="Driver" value={scheduling.driver_id} onChange={(driver_id) => setScheduling({ ...scheduling, driver_id })} options={(options?.drivers || []).map((item) => ({ value: item.id, label: item.full_name }))} /><div className="flex gap-2 sm:col-span-2"><button type="button" disabled={busy || !scheduling.vehicle_id || !scheduling.driver_id} onClick={() => void assign(record)} className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-60">{loadingLabel(isBusy(record, 'schedule'), 'Save Assignment', 'Saving…')}</button><button type="button" onClick={() => setScheduling({ id: '', vehicle_id: '', driver_id: '' })} className="rounded-lg border px-3 py-2 text-sm">Cancel</button></div></div>}
          {pickupEntry.id === record.id && <div className="mt-4 overflow-x-auto rounded-lg border bg-white p-4"><table className="w-full min-w-[680px] text-sm"><thead className="bg-slate-50 text-left text-slate-600"><tr><th className="px-3 py-2">Item</th><th className="px-3 py-2">Requested Qty</th><th className="px-3 py-2">Collected Qty</th><th className="px-3 py-2">Variance</th><th className="px-3 py-2">Reason</th></tr></thead><tbody>{(record.transfer_items || []).map((item) => { const entry = pickupEntry.items[item.item_id] || { collected: '', reason: '' }; const variance = Number(item.quantity) - Number(entry.collected || 0); const setEntry = (next: Partial<typeof entry>) => setPickupEntry((current) => ({ ...current, items: { ...current.items, [item.item_id]: { ...entry, ...next } } })); return <tr key={item.item_id} className="border-t"><td className="px-3 py-2">{item.name}</td><td className="px-3 py-2">{item.quantity}</td><td className="px-3 py-2"><input type="number" min="0" max={item.quantity} value={entry.collected} onChange={(event) => setEntry({ collected: event.target.value })} className="w-24 rounded border px-2 py-1.5" /></td><td className="px-3 py-2 font-medium">{variance.toLocaleString()}</td><td className="px-3 py-2"><input value={entry.reason} disabled={variance === 0} onChange={(event) => setEntry({ reason: event.target.value })} placeholder={variance ? 'Required' : 'No variance'} className="w-48 rounded border px-2 py-1.5 disabled:bg-slate-100" /></td></tr>; })}</tbody></table><div className="mt-4 flex gap-2"><button type="button" disabled={busy} onClick={() => void savePickupConfirmation(record)} className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-60">{loadingLabel(isBusy(record, 'pickup-confirmation'), 'Confirm Pickup', 'Confirming…')}</button><button type="button" onClick={() => setPickupEntry({ id: '', items: {} })} className="rounded-lg border px-3 py-2 text-sm">Cancel</button></div></div>}
          {record.pickup_confirmation && <div className="mt-4 overflow-x-auto rounded-lg border"><table className="w-full min-w-[620px] text-sm"><thead className="bg-slate-50 text-left text-slate-600"><tr><th className="px-3 py-2">Item</th><th className="px-3 py-2">Requested Qty</th><th className="px-3 py-2">Collected Qty</th><th className="px-3 py-2">Variance</th><th className="px-3 py-2">Reason</th></tr></thead><tbody>{record.pickup_confirmation.items.map((item) => <tr key={item.item_id} className="border-t"><td className="px-3 py-2">{item.name}</td><td className="px-3 py-2">{item.requested_quantity}</td><td className="px-3 py-2">{item.collected_quantity}</td><td className="px-3 py-2">{item.shortfall_quantity}</td><td className="px-3 py-2">{item.shortfall_reason || '—'}</td></tr>)}</tbody></table></div>}
          {deliveryEntry.id === record.id && <div className="mt-4 rounded-lg border bg-slate-50 p-4"><h3 className="font-medium text-slate-900">Destination receiver confirmation</h3><div className="mt-3 grid gap-3 sm:grid-cols-3"><Input label="Receiver name" value={deliveryEntry.receiver_name} onChange={(receiver_name) => setDeliveryEntry({ ...deliveryEntry, receiver_name })} /><Input label="Receiver contact" value={deliveryEntry.receiver_contact} onChange={(receiver_contact) => setDeliveryEntry({ ...deliveryEntry, receiver_contact })} /><Input label="Receiver initials" value={deliveryEntry.receiver_initials} onChange={(receiver_initials) => setDeliveryEntry({ ...deliveryEntry, receiver_initials })} /></div><div className="mt-4 grid gap-3 sm:grid-cols-2">{(record.pickup_confirmation?.items || []).map((item) => <Input key={item.item_id} label={`${item.name} received quantity`} type="number" value={deliveryEntry.items[item.item_id] || ''} onChange={(value) => setDeliveryEntry({ ...deliveryEntry, items: { ...deliveryEntry.items, [item.item_id]: value } })} />)}</div><div className="mt-4 flex gap-2"><button type="button" disabled={busy} onClick={() => void saveDeliveryConfirmation(record)} className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-60">{loadingLabel(isBusy(record, 'verify-delivery'), 'Complete Pickup', 'Completing…')}</button><button type="button" onClick={() => setDeliveryEntry({ id: '', receiver_name: '', receiver_contact: '', receiver_initials: '', items: {} })} className="rounded-lg border px-3 py-2 text-sm">Cancel</button></div></div>}
        </article>)}
      </div> : <EmptyState onCreate={() => !driverMode && setCreating(true)} driverMode={driverMode} />}
    </div>
  </div>;
}

function EmptyState({ onCreate, driverMode }: { onCreate: () => void; driverMode: boolean }) {
  return <section className="rounded-xl border bg-white p-8 text-center shadow-sm"><div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-blue-50 text-blue-600"><ClipboardList className="h-6 w-6" /></div><h2 className="mt-4 text-lg font-semibold text-slate-900">No supplier pickups yet</h2><p className="mx-auto mt-2 max-w-md text-sm text-slate-500">{driverMode ? 'Assigned supplier pickups will appear here.' : 'Pickup requests will appear here after they are created.'}</p>{!driverMode && <button type="button" onClick={onCreate} className="mt-5 inline-flex items-center gap-2 rounded-lg border border-blue-600 px-4 py-2 text-sm font-medium text-blue-700"><PackagePlus className="h-4 w-4" />Create Pickup Request</button>}</section>;
}

function CreatePickupRequestPanel({ busy, setBusy, onCancel, onCreated, onError }: { busy: boolean; setBusy: (value: boolean) => void; onCancel: () => void; onCreated: (record: StockTransfer) => void; onError: (message: string) => void }) {
  const idempotencyKey = useRef(globalThis.crypto?.randomUUID?.() || `supplier-pickup-${Date.now()}`);
  const [form, setForm] = useState(emptyForm);
  const [items, setItems] = useState<StockTransferItem[]>([]);
  const [selectedProduct, setSelectedProduct] = useState<WaybillProduct | null>(null);
  const [chosenProduct, setChosenProduct] = useState('');
  const [expectedQuantity, setExpectedQuantity] = useState(1);
  const [search, setSearch] = useState('');
  const [searching, setSearching] = useState(false);
  const [products, setProducts] = useState<WaybillProduct[]>([]);
  const [validation, setValidation] = useState('');
  const totals = useMemo(() => items.reduce((sum, item) => sum + Number(item.quantity || 0), 0), [items]);

  useEffect(() => {
    const query = search.trim();
    if (selectedProduct || query.length < 2) {
      setProducts([]);
      return;
    }
    const timer = window.setTimeout(() => { void runSearch(); }, 350);
    return () => window.clearTimeout(timer);
  }, [search, selectedProduct]);

  const runSearch = async () => {
    if (search.trim().length < 2) {
      setProducts([]);
      setValidation('Enter at least two characters to search products.');
      return;
    }
    setSearching(true);
    setValidation('');
    try {
      setProducts(await searchWaybillProducts(search.trim()));
    } catch (value) {
      onError(message(value));
    } finally {
      setSearching(false);
    }
  };
  const chooseProduct = (product: WaybillProduct) => {
    setSelectedProduct({ item_id: product.item_id, name: product.name, sku: product.sku, unit: product.unit || 'unit' });
    setChosenProduct(product.name);
    setSearch(product.name);
    setProducts([]);
    setValidation('');
  };
  const enterChosenProduct = (value: string) => {
    setChosenProduct(value);
    const name = value.trim();
    setSelectedProduct(name ? { item_id: name, name, sku: '', unit: 'unit' } : null);
    setValidation('');
  };
  const addItem = () => {
    const quantity = Number(expectedQuantity);
    if (!selectedProduct) { setValidation('Select a product from Product Search or enter one in Chosen product before adding it.'); return; }
    if (!Number.isFinite(quantity) || quantity <= 0) { setValidation('Expected quantity must be greater than zero.'); return; }
    const duplicate = items.some((item) => item.item_id.toLowerCase() === selectedProduct.item_id.toLowerCase());
    if (duplicate) { setValidation(`${selectedProduct.name} is already in this pickup. Remove it first or adjust quantity before saving.`); return; }
    setItems((current) => [...current, { item_id: selectedProduct.item_id, name: selectedProduct.name, quantity, unit: selectedProduct.unit || 'unit' }]);
    setSelectedProduct(null); setChosenProduct(''); setExpectedQuantity(1); setSearch(''); setProducts([]); setValidation('');
  };
  const save = async () => {
    if (!form.supplier_name.trim() || !form.contact_person.trim() || !form.primary_phone.trim() || !form.pickup_address.trim() || !form.receiving_location.trim() || !form.requested_date) { setValidation('Supplier name, contact person, primary phone, pickup address, receiving location, and requested date are required.'); return; }
    if (!items.length) { setValidation('Add at least one pickup item.'); return; }
    setBusy(true); setValidation(''); onError('');
    try {
      const record = await createStockTransfer({
        operation_type: 'supplier_pickup',
        idempotency_key: idempotencyKey.current,
        supplier: { supplier_name: form.supplier_name, contact_person: form.contact_person, primary_phone: form.primary_phone, pickup_address: form.pickup_address, pickup_instructions: form.pickup_instructions || undefined },
        receiving_location: form.receiving_location,
        supplier_reference: form.supplier_reference || undefined,
        requested_date: form.requested_date,
        transfer_items: items,
      });
      onCreated(record);
    } catch (value) { onError(message(value)); } finally { setBusy(false); }
  };

  return <section className="rounded-xl border bg-white shadow-sm"><div className="flex items-center justify-between border-b p-5"><div><h2 className="text-lg font-semibold text-slate-900">Create Pickup Request</h2><p className="text-sm text-slate-500">Creates a Draft supplier pickup operation.</p></div><button type="button" onClick={onCancel} className="rounded-lg p-2 text-slate-500 hover:bg-slate-100" aria-label="Close pickup request form"><X className="h-5 w-5" /></button></div><div className="space-y-5 p-5">
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{Object.entries({ supplier_name: 'Supplier name', contact_person: 'Contact person', primary_phone: 'Primary phone', pickup_address: 'Pickup address', receiving_location: 'Receiving location', requested_date: 'Requested date', pickup_instructions: 'Pickup instructions (optional)', supplier_reference: 'PO/reference (optional)' }).map(([key, label]) => <Input key={key} label={label} type={key === 'requested_date' ? 'date' : key.includes('phone') ? 'tel' : 'text'} value={form[key as keyof typeof form]} onChange={(value) => setForm({ ...form, [key]: value })} />)}</div>
    <div className="rounded-xl border bg-slate-50 p-4"><h3 className="font-medium text-slate-900">Pickup items</h3><p className="mt-1 text-sm text-slate-500">Search and select a product, or enter an item directly in Chosen product.</p><div className="mt-3 grid gap-3 lg:grid-cols-[1.4fr_1.4fr_0.65fr_auto] lg:items-end"><div className="relative"><label className="block text-sm text-slate-700">Type item / product search</label><div className="mt-1 flex"><input value={search} onChange={(event) => { setSearch(event.target.value); setSelectedProduct(null); setChosenProduct(''); }} onKeyDown={(event) => event.key === 'Enter' && void runSearch()} placeholder="Type item name, e.g. brake pad" className="w-full rounded-l-lg border border-r-0 border-slate-300 px-3 py-2.5" /><button type="button" onClick={() => void runSearch()} className="rounded-r-lg border border-slate-300 bg-white px-3" aria-label="Search products">{searching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}</button></div>{products.length > 0 && <div className="absolute z-20 mt-1 max-h-52 w-full overflow-y-auto rounded-lg border bg-white p-1 shadow-lg">{products.map((product) => <button type="button" key={product.item_id} onClick={() => chooseProduct(product)} className="block w-full rounded px-3 py-2 text-left text-sm hover:bg-blue-50">{product.name}{product.sku ? <span className="ml-2 text-xs text-slate-500">{product.sku}</span> : null}</button>)}</div>}{search.trim().length >= 2 && !searching && !selectedProduct && products.length === 0 && <p className="mt-1 text-xs text-slate-500">No matching products yet. Keep typing or press search.</p>}</div><Input label="Chosen product" value={chosenProduct} onChange={enterChosenProduct} placeholder="Enter or select a product" /><Input label="Expected quantity" type="number" value={String(expectedQuantity)} onChange={(quantity) => setExpectedQuantity(Number(quantity))} min="0.001" /><button type="button" onClick={addItem} disabled={!selectedProduct} className="rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-50">Add Item</button></div></div>
    {items.length > 0 && <div className="overflow-x-auto rounded-xl border"><table className="w-full min-w-[560px] text-sm"><thead className="bg-slate-50 text-left text-slate-600"><tr><th className="px-4 py-3">Item</th><th className="px-4 py-3">Expected quantity</th><th className="w-16 px-4 py-3" /></tr></thead><tbody>{items.map((item) => <tr key={item.item_id} className="border-t"><td className="px-4 py-3">{item.name}</td><td className="px-4 py-3">{item.quantity} {item.unit}</td><td className="px-4 py-3"><button type="button" onClick={() => setItems((current) => current.filter((value) => value.item_id !== item.item_id))} className="rounded-lg p-2 text-red-600 hover:bg-red-50"><Trash2 className="h-4 w-4" /></button></td></tr>)}</tbody><tfoot className="border-t bg-slate-50"><tr><td className="px-4 py-3 font-medium">{items.length} item(s)</td><td className="px-4 py-3">Total quantity: {totals.toLocaleString()}</td><td /></tr></tfoot></table></div>}
    {validation && <div className="flex gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800"><AlertCircle className="h-4 w-4 shrink-0" />{validation}</div>}
    <div className="flex justify-end gap-2 border-t pt-5"><button type="button" onClick={onCancel} className="rounded-lg border px-4 py-2 text-sm font-medium text-slate-700">Cancel</button><button type="button" disabled={busy} onClick={() => void save()} className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-60">{busy && <Loader2 className="h-4 w-4 animate-spin" />}{busy ? 'Saving…' : 'Save Draft'}</button></div>
  </div></section>;
}

function Input({ label, value, onChange, type = 'text', disabled = false, min, placeholder }: { label: string; value: string; onChange: (value: string) => void; type?: string; disabled?: boolean; min?: string; placeholder?: string }) {
  return <label className="block text-sm text-slate-700">{label}<input type={type} min={min} value={value} disabled={disabled} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2.5 disabled:bg-slate-100 disabled:text-slate-500" /></label>;
}

function Select({ label, value, onChange, options }: { label: string; value: string; onChange: (value: string) => void; options: Array<{ value: string; label: string }> }) {
  return <label className="block text-sm text-slate-700">{label}<select value={value} onChange={(event) => onChange(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5"><option value="">Select {label.toLowerCase()}</option>{options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>;
}
