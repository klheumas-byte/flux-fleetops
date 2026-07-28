import { Fragment, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import { AlertCircle, CheckCircle2, Download, Loader2, PenLine, Printer, RefreshCw, Search } from 'lucide-react';
import { ApiRequestError } from '../../lib/api';
import { mutateStockTransfer } from '../../lib/stock-transfer-api';
import {
  confirmWaybill, fetchWaybill, fetchWaybills, reviewWaybillVariance, saveWaybillSignature,
  searchWaybillProducts, transitionWaybill, updateWaybillItems,
  type Waybill, type WaybillItem, type WaybillProduct, type WaybillStatus,
} from '../../lib/waybill-api';

const STEPS: WaybillStatus[] = ['draft', 'approved', 'driver_confirmed', 'loaded', 'in_transit', 'delivered', 'verified', 'completed'];
const label = (value: string) => value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
const errorMessage = (error: unknown) => error instanceof ApiRequestError || error instanceof Error ? error.message : 'Unable to update the Digital Waybill.';
const blankItem = (): WaybillItem => ({ item_id: '', sku: '', name: '', unit: 'unit', expected_quantity: 1, loaded_quantity: null, received_quantity: null, variance: null, notes: '', serial_numbers: [], photos: [] });

export default function DigitalWaybills({ driverMode = false }: { driverMode?: boolean }) {
  const [records, setRecords] = useState<Waybill[]>([]);
  const [selected, setSelected] = useState<Waybill | null>(null);
  const [items, setItems] = useState<WaybillItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [paste, setPaste] = useState('');
  const [search, setSearch] = useState('');
  const [products, setProducts] = useState<WaybillProduct[]>([]);
  const [receiver, setReceiver] = useState('');
  const [varianceResolution, setVarianceResolution] = useState('');

  const load = async () => {
    setLoading(true); setError('');
    try {
      const nextRecords = await fetchWaybills();
      setRecords(nextRecords);
      const rawTarget = sessionStorage.getItem('flux_notification_target');
      if (rawTarget) {
        const target = JSON.parse(rawTarget) as { referenceType?: string; referenceId?: string };
        const match = ['waybill', 'digital_waybill'].includes(target.referenceType || '')
          ? nextRecords.find((record) => record.id === target.referenceId)
          : undefined;
        if (match) {
          sessionStorage.removeItem('flux_notification_target');
          const detail = await fetchWaybill(match.id);
          setSelected(detail);
          setItems(detail.items.map((item) => ({ ...item })));
        }
      }
    } catch (value) { setError(errorMessage(value)); } finally { setLoading(false); }
  };
  useEffect(() => { void load(); }, []);

  const open = async (record: Waybill) => {
    setBusy(record.id); setError('');
    try { const detail = await fetchWaybill(record.id); setSelected(detail); setItems(detail.items.map((item) => ({ ...item }))); }
    catch (value) { setError(errorMessage(value)); } finally { setBusy(''); }
  };
  const accept = (updated: Waybill) => {
    setSelected(updated); setItems(updated.items.map((item) => ({ ...item })));
    setRecords((current) => current.map((item) => item.id === updated.id ? updated : item));
  };
  const run = async (name: string, action: () => Promise<Waybill>) => {
    setBusy(name); setError(''); setNotice('');
    try { accept(await action()); setNotice('Digital Waybill updated.'); }
    catch (value) { setError(errorMessage(value)); } finally { setBusy(''); }
  };
  const saveItems = () => selected && run('items', () => updateWaybillItems(selected.id, items, selected.notes || undefined));
  const transition = (status: WaybillStatus, payload: Record<string, unknown> = {}) => selected && run(status, () => transitionWaybill(selected.id, status, payload));
  const runStockTransferAction = (action: 'acknowledge' | 'release' | 'start' | 'arrive' | 'verify-delivery' | 'report-exception', payload: Record<string, unknown> = {}) => selected && run(action, async () => {
    await mutateStockTransfer(selected.source_id, action, payload);
    return fetchWaybill(selected.id);
  });
  const quantities = (field: 'loaded_quantity' | 'received_quantity') => items.map((item) => ({
    item_id: item.item_id,
    quantity: Number(field === 'loaded_quantity'
      ? item.loaded_quantity ?? item.expected_quantity
      : item.received_quantity ?? item.loaded_quantity ?? item.expected_quantity),
  }));
  const addProduct = (product: WaybillProduct) => {
    if (items.some((item) => item.item_id.toLowerCase() === product.item_id.toLowerCase())) return;
    setItems((current) => [...current, { ...blankItem(), ...product, expected_quantity: 1 }]);
  };
  const runSearch = async () => { if (search.trim().length < 2) return; try { setProducts(await searchWaybillProducts(search)); } catch (value) { setError(errorMessage(value)); } };
  const importPaste = () => {
    const rows = paste.split(/\r?\n/).map((row) => row.trim()).filter(Boolean).map((row) => {
      const [itemId, name, quantity, unit = 'unit', notes = ''] = row.split(row.includes('\t') ? '\t' : ',').map((cell) => cell.trim());
      return { ...blankItem(), item_id: itemId, sku: itemId, name: name || itemId, expected_quantity: Number(quantity || 1), unit, notes };
    });
    const deduped = [...items, ...rows].filter((item, index, all) => item.item_id && all.findIndex((candidate) => candidate.item_id.toLowerCase() === item.item_id.toLowerCase()) === index);
    setItems(deduped); setPaste('');
  };
  const exportCsv = () => {
    if (!selected) return;
    const rows = [['Item ID', 'Name', 'Expected', 'Loaded', 'Received', 'Variance', 'Unit'], ...selected.items.map((item) => [item.item_id, item.name, item.expected_quantity, item.loaded_quantity ?? '', item.received_quantity ?? '', item.variance ?? '', item.unit])];
    const blob = new Blob([rows.map((row) => row.map((cell) => `"${String(cell).replaceAll('"', '""')}"`).join(',')).join('\n')], { type: 'text/csv' });
    const url = URL.createObjectURL(blob); const anchor = document.createElement('a'); anchor.href = url; anchor.download = `${selected.waybill_number}.csv`; anchor.click(); URL.revokeObjectURL(url);
  };
  const taskOwnedWaybill = selected?.source_type === 'supplier_pickup';

  if (loading) return <div className="flex min-h-80 items-center justify-center"><Loader2 className="h-7 w-7 animate-spin text-blue-600" /></div>;
  return <div className="min-h-full bg-slate-50 p-4 md:p-6"><div className="mx-auto max-w-7xl space-y-5">
    <header className="flex flex-wrap items-center justify-between gap-3"><div><h1 className="text-2xl font-semibold text-slate-900">Digital Waybill</h1><p className="text-sm text-slate-500">Items, custody, confirmation and variance—separate from the vehicle journey.</p></div><button type="button" onClick={() => void load()} className="rounded-lg border bg-white p-2.5"><RefreshCw className="h-4 w-4" /></button></header>
    {error && <div className="flex gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"><AlertCircle className="h-4 w-4 shrink-0" />{error}</div>}
    {notice && <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-700">{notice}</div>}
    {!selected ? <div className="grid gap-4 lg:grid-cols-2">{records.length ? records.map((record) => <button type="button" key={record.id} onClick={() => void open(record)} className="rounded-xl border bg-white p-5 text-left shadow-sm transition hover:border-blue-300"><div className="flex justify-between gap-3"><div><p className="text-xs font-semibold text-blue-600">{record.waybill_number}</p><h2 className="mt-1 font-semibold text-slate-900">{record.origin || 'Origin'} → {record.destination || 'Destination'}</h2><p className="mt-1 text-sm text-slate-500">{label(record.source_type)} · {record.source_reference || record.source_id} · {record.item_count} items</p></div><span className="h-fit rounded-full bg-blue-100 px-2.5 py-1 text-xs text-blue-800">{label(record.status)}</span></div>{busy === record.id && <Loader2 className="mt-3 h-4 w-4 animate-spin" />}</button>) : <div className="col-span-full rounded-xl border border-dashed bg-white p-12 text-center text-sm text-slate-500">Waybills appear automatically after Dispatch or Stock Transfer creates its Vehicle Movement.</div>}</div> : <section className="rounded-xl border bg-white shadow-sm print:border-0 print:shadow-none">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b p-5"><div><button type="button" onClick={() => setSelected(null)} className="text-sm text-blue-600 print:hidden">← All Waybills</button><h2 className="mt-2 text-xl font-semibold">{selected.waybill_number}</h2><p className="text-sm text-slate-500">{selected.origin || 'Origin'} → {selected.destination || 'Destination'} · Movement {selected.movement_id}</p><p className="mt-1 text-xs text-slate-500">Vehicle {selected.vehicle_id || '—'} · Driver {selected.driver_id || '—'}{selected.scheduled_at ? ` · Scheduled ${new Date(selected.scheduled_at).toLocaleString()}` : ''}</p>{selected.notes && <p className="mt-2 max-w-2xl text-sm text-slate-700">Notes: {selected.notes}</p>}</div><div className="flex gap-2 print:hidden"><button type="button" onClick={exportCsv} className="inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm"><Download className="h-4 w-4" />Export</button><button type="button" onClick={() => window.print()} className="inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm"><Printer className="h-4 w-4" />Print</button></div></div>
      <div className="overflow-x-auto border-b p-4"><div className="flex min-w-max gap-2">{STEPS.map((step, index) => <div key={step} className={`rounded-full px-3 py-1.5 text-xs font-medium ${index <= STEPS.indexOf(selected.status) ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-500'}`}>{label(step)}</div>)}</div></div>
      <div className="space-y-6 p-5">
        {taskOwnedWaybill && <p className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm text-blue-800 print:hidden">This Supplier Pickup Waybill is read-only. Driver actions are completed from Operational Tasks.</p>}
        {selected.source_type === 'stock_transfer' && <WaybillRecipient recipient={selected.recipient} />}
        {selected.source_type === 'stock_transfer' && selected.actual_receiver && <ActualReceiverDetails receiver={selected.actual_receiver} status={selected.status} />}
        {selected.status === 'draft' && !driverMode && <div className="space-y-4"><div className="flex flex-wrap items-end gap-2"><label className="min-w-64 flex-1 text-sm">Product search<input value={search} onChange={(event) => setSearch(event.target.value)} onKeyDown={(event) => event.key === 'Enter' && void runSearch()} className="mt-1 w-full rounded-lg border px-3 py-2" placeholder="SKU or product name" /></label><Action onClick={runSearch} busy={false}><Search className="h-4 w-4" />Search</Action></div>{products.length > 0 && <div className="flex flex-wrap gap-2">{products.map((product) => <button type="button" key={product.item_id} onClick={() => addProduct(product)} className="rounded-full border bg-slate-50 px-3 py-1.5 text-xs">+ {product.item_id} · {product.name}</button>)}</div>}
          <div className="overflow-x-auto"><table className="w-full min-w-[1050px] text-sm"><thead><tr className="border-b text-left text-slate-500">{['Item / SKU', 'Name', 'Expected', 'Unit', 'Serial numbers', 'Photo URLs', 'Notes', ''].map((heading) => <th key={heading} className="p-2">{heading}</th>)}</tr></thead><tbody>{items.map((item, index) => <tr key={`${item.item_id}-${index}`} className="border-b"><td className="p-2"><Cell value={item.item_id} onChange={(value) => setItems(items.map((row, rowIndex) => rowIndex === index ? { ...row, item_id: value, sku: value } : row))} /></td><td className="p-2"><Cell value={item.name} onChange={(value) => setItems(items.map((row, rowIndex) => rowIndex === index ? { ...row, name: value } : row))} /></td><td className="p-2"><Cell type="number" value={String(item.expected_quantity)} onChange={(value) => setItems(items.map((row, rowIndex) => rowIndex === index ? { ...row, expected_quantity: Number(value) } : row))} /></td><td className="p-2"><Cell value={item.unit} onChange={(value) => setItems(items.map((row, rowIndex) => rowIndex === index ? { ...row, unit: value } : row))} /></td><td className="p-2"><Cell value={(item.serial_numbers || []).join(', ')} onChange={(value) => setItems(items.map((row, rowIndex) => rowIndex === index ? { ...row, serial_numbers: value.split(',').map((part) => part.trim()).filter(Boolean) } : row))} /></td><td className="p-2"><Cell value={(item.photos || []).join(', ')} onChange={(value) => setItems(items.map((row, rowIndex) => rowIndex === index ? { ...row, photos: value.split(',').map((part) => part.trim()).filter(Boolean) } : row))} /></td><td className="p-2"><Cell value={item.notes || ''} onChange={(value) => setItems(items.map((row, rowIndex) => rowIndex === index ? { ...row, notes: value } : row))} /></td><td><button type="button" onClick={() => setItems(items.filter((_, rowIndex) => rowIndex !== index))} className="text-red-600">Remove</button></td></tr>)}</tbody></table></div>
          <div className="flex flex-wrap gap-2"><button type="button" onClick={() => setItems([...items, blankItem()])} className="rounded-lg border px-3 py-2 text-sm">Add row</button><Action onClick={saveItems} busy={busy === 'items'}>Save items</Action><Action onClick={() => transition('approved')} busy={busy === 'approved'}>Approve Waybill</Action></div>
          <div className="rounded-lg bg-slate-50 p-4"><label className="text-sm font-medium">Spreadsheet paste</label><p className="text-xs text-slate-500">Paste tab- or comma-separated: item ID, name, expected quantity, unit, notes.</p><textarea value={paste} onChange={(event) => setPaste(event.target.value)} rows={4} className="mt-2 w-full rounded-lg border p-3 font-mono text-xs" /><button type="button" onClick={importPaste} className="mt-2 rounded-lg border bg-white px-3 py-2 text-sm">Import rows</button></div>
        </div>}
        {selected.source_type === 'stock_transfer' && driverMode && selected.status === 'approved' && <div className="rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm text-blue-900 print:hidden"><p>Review the items and accept custody before loading begins.</p><div className="mt-3"><Action onClick={() => runStockTransferAction('acknowledge')} busy={busy === 'acknowledge'}><CheckCircle2 className="h-4 w-4" />Accept Waybill</Action></div></div>}
        {selected.source_type === 'stock_transfer' && !driverMode && selected.status === 'approved' && <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800 print:hidden">Waiting for the assigned driver to accept the Waybill before loading begins.</p>}
        <ItemQuantities items={items} setItems={setItems} editableField={taskOwnedWaybill ? null : selected.source_type === 'stock_transfer' ? selected.status === 'driver_confirmed' && !driverMode ? 'loaded_quantity' : null : selected.status === 'driver_confirmed' && !driverMode ? 'loaded_quantity' : selected.status === 'in_transit' ? 'received_quantity' : null} />
        {selected.source_type !== 'stock_transfer' && !taskOwnedWaybill && selected.status === 'approved' && driverMode && <Action onClick={() => run('confirm', async () => confirmWaybill(selected.id, { device: { user_agent: navigator.userAgent }, statement: 'I confirm the items and custody shown on this Digital Waybill.' }))} busy={busy === 'confirm'}><CheckCircle2 className="h-4 w-4" />Confirm Waybill</Action>}
        {selected.source_type !== 'stock_transfer' && !taskOwnedWaybill && selected.status === 'driver_confirmed' && !driverMode && <Action onClick={() => transition('loaded', { quantities: quantities('loaded_quantity') })} busy={busy === 'loaded'}>Confirm Loading</Action>}
        {selected.source_type === 'stock_transfer' && selected.status === 'driver_confirmed' && !driverMode && <Action onClick={() => runStockTransferAction('release', { loaded_quantities: quantities('loaded_quantity') })} busy={busy === 'release'}>Confirm Loading</Action>}
        {selected.source_type === 'stock_transfer' && selected.status === 'loaded' && driverMode && <Action onClick={() => runStockTransferAction('start')} busy={busy === 'start'}>Start Journey</Action>}
        {selected.source_type === 'stock_transfer' && selected.status === 'in_transit' && driverMode && <Action onClick={() => runStockTransferAction('arrive')} busy={busy === 'arrive'}>Arrived / Delivered</Action>}
        {selected.source_type === 'stock_transfer' && selected.status === 'delivered' && driverMode && !selected.linked_delivery_exception_id && <ReceiverVerificationForm
          waybill={selected}
          busy={busy}
          onSubmit={(action, payload) => runStockTransferAction(action, payload)}
        />}
        {selected.source_type === 'stock_transfer' && selected.linked_delivery_exception_id && <WaybillExceptionSummary waybill={selected} />}
        {selected.source_type !== 'stock_transfer' && !taskOwnedWaybill && selected.status === 'loaded' && <Action onClick={() => transition('in_transit')} busy={busy === 'in_transit'}>Mark In Transit</Action>}
        {selected.source_type !== 'stock_transfer' && !taskOwnedWaybill && selected.status === 'in_transit' && <div className="flex flex-wrap items-end gap-3"><label className="text-sm">Receiver name<input value={receiver} onChange={(event) => setReceiver(event.target.value)} className="mt-1 block rounded-lg border px-3 py-2" /></label><Action onClick={() => transition('delivered', { receiver, quantities: quantities('received_quantity') })} busy={busy === 'delivered'}>Confirm Delivery</Action></div>}
        {selected.source_type !== 'stock_transfer' && !taskOwnedWaybill && (selected.status === 'delivered' || selected.status === 'verified') && selected.has_variance && !selected.variance_review && !driverMode && <div className="rounded-lg border border-amber-200 bg-amber-50 p-4"><label className="text-sm font-medium text-amber-900">Variance resolution<input value={varianceResolution} onChange={(event) => setVarianceResolution(event.target.value)} className="mt-2 block w-full rounded-lg border px-3 py-2 text-slate-900" /></label><Action onClick={() => run('variance', () => reviewWaybillVariance(selected.id, varianceResolution))} busy={busy === 'variance'}>Record Variance Review</Action></div>}
        {selected.source_type !== 'stock_transfer' && !taskOwnedWaybill && selected.status === 'delivered' && !driverMode && <Action onClick={() => transition('verified')} busy={busy === 'verified'}>Verify Receipt</Action>}
        {selected.source_type !== 'stock_transfer' && !taskOwnedWaybill && selected.status === 'verified' && !driverMode && <Action onClick={() => transition('completed')} busy={busy === 'completed'}>Complete Waybill</Action>}
        {selected.source_type !== 'stock_transfer' && !taskOwnedWaybill && <SignatureSection waybill={selected} driverMode={driverMode} onSaved={accept} onError={setError} />}
        <div><h3 className="font-semibold">Custody history</h3><div className="mt-2 space-y-2">{selected.custody_events.length ? selected.custody_events.map((event, index) => <div key={String(event.handover_id || index)} className="rounded-lg bg-slate-50 p-3 text-sm"><b>{String(event.from_name || event.from || 'Unknown')}</b> → <b>{String(event.to_name || event.to || 'Unknown')}</b><span className="ml-2 text-slate-500">{String(event.location || '')} · {event.time ? new Date(String(event.time)).toLocaleString() : ''}</span></div>) : <p className="text-sm text-slate-500">No custody handovers recorded yet.</p>}</div></div>
      </div>
    </section>}
  </div></div>;
}

function WaybillRecipient({ recipient }: { recipient: Waybill['recipient'] }) {
  if (!recipient) return <div className="rounded-lg border border-dashed p-4 text-sm text-slate-500">Recipient details were not captured for this legacy transfer.</div>;
  return <div className="rounded-lg border p-4 text-sm text-slate-700">
    <h3 className="font-semibold text-slate-900">Planned recipient</h3>
    <p className="mt-2 font-medium">{recipient.full_name}{recipient.role ? ` · ${recipient.role}` : ''}</p>
    <p>{recipient.primary_phone}{recipient.secondary_phone ? ` · ${recipient.secondary_phone}` : ''}</p>
    {recipient.email && <p>{recipient.email}</p>}
    {recipient.delivery_instructions && <p className="mt-2"><span className="font-medium">Delivery instructions:</span> {recipient.delivery_instructions}</p>}
  </div>;
}

function ActualReceiverDetails({ receiver, status }: { receiver: NonNullable<Waybill['actual_receiver']>; status: WaybillStatus }) {
  return <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-950">
    <h3 className="font-semibold">Actual receiver</h3>
    <p className="mt-2 font-medium">{receiver.full_name}{receiver.role ? ` · ${receiver.role}` : ''}</p>
    <p>{receiver.primary_contact}</p>
    {receiver.initials && <p>Initials: {receiver.initials}</p>}
    {receiver.notes && <p className="mt-2">Notes: {receiver.notes}</p>}
    {status === 'completed' && <p className="mt-2 font-medium">Verified and completed</p>}
  </div>;
}

function WaybillExceptionSummary({ waybill }: { waybill: Waybill }) {
  const affected = waybill.items.filter((item) => item.item_condition && item.item_condition !== 'correct');
  return <div className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">
    <div className="flex flex-wrap items-center justify-between gap-2"><p className="font-semibold">Delivery Exception {waybill.delivery_exception_status === 'resolved' ? 'Resolved' : 'Open'}</p><span className="rounded-full bg-amber-200 px-2 py-1 text-xs">{waybill.delivery_exception_summary?.exception_number || 'Exception case'}</span></div>
    <p className="mt-1">{affected.length} affected item(s). Verification and completion are blocked.</p>
    {waybill.delivery_exception_summary?.operational_status && <p className="mt-1 font-medium">Operational status: {label(waybill.delivery_exception_summary.operational_status)}</p>}
    <div className="mt-3 space-y-2">{affected.map((item) => <div key={item.item_id} className="rounded border border-amber-200 bg-white/70 p-3">
      <p className="font-medium">{item.name} · {label(item.item_condition || '')}</p>
      <p>Expected {item.expected_quantity}, received {item.received_quantity}, exception {item.exception_quantity} {item.unit}</p>
      {item.exception_notes && <p className="mt-1">{item.exception_notes}</p>}
      {item.exception_photos?.length ? <p className="mt-1 text-xs">{item.exception_photos.length} photo(s) attached</p> : null}
    </div>)}</div>
    <p className="mt-3 text-xs">Investigation, return, replacement, liability, and closure are deferred.</p>
  </div>;
}

type DeliveryCondition = 'correct' | 'missing' | 'damaged' | 'wrong_item' | 'excess';
const DELIVERY_CONDITIONS: Array<{ value: DeliveryCondition; label: string }> = [
  { value: 'correct', label: 'Correct' },
  { value: 'damaged', label: 'Damaged' },
  { value: 'wrong_item', label: 'Wrong Item' },
  { value: 'excess', label: 'Excess' },
];

function ReceiverVerificationForm({ waybill, busy, onSubmit }: {
  waybill: Waybill;
  busy: string;
  onSubmit: (action: 'verify-delivery' | 'report-exception', payload: Record<string, unknown>) => void | Promise<void>;
}) {
  const [reviews, setReviews] = useState(() => waybill.items.map((item) => ({
    item_id: item.item_id, expected_quantity: item.expected_quantity, received_quantity: item.expected_quantity,
    condition: 'correct' as DeliveryCondition, notes: '', photos: [] as string[],
  })));
  const [receiver, setReceiver] = useState({ full_name: '', primary_contact: '', role: '', initials: '', notes: '', acknowledged: false });
  const [validation, setValidation] = useState('');
  const canvas = useRef<HTMLCanvasElement>(null);
  const drawing = useRef(false);
  const [hasSignature, setHasSignature] = useState(false);
  const point = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    return { x: (event.clientX - box.left) * (event.currentTarget.width / box.width), y: (event.clientY - box.top) * (event.currentTarget.height / box.height) };
  };
  const start = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    drawing.current = true;
    const context = canvas.current?.getContext('2d'); const next = point(event);
    context?.beginPath(); context?.moveTo(next.x, next.y); event.currentTarget.setPointerCapture(event.pointerId);
  };
  const move = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    if (!drawing.current) return;
    const context = canvas.current?.getContext('2d'); const next = point(event);
    if (context) { context.lineWidth = 2; context.lineCap = 'round'; context.strokeStyle = '#0f172a'; context.lineTo(next.x, next.y); context.stroke(); setHasSignature(true); }
  };
  const clearSignature = () => { canvas.current?.getContext('2d')?.clearRect(0, 0, canvas.current.width, canvas.current.height); setHasSignature(false); };
  const calculatedCondition = (index: number): DeliveryCondition => {
    const review = reviews[index]; const expected = waybill.items[index].expected_quantity;
    if (review.received_quantity < expected) return 'missing';
    if (review.received_quantity > expected) return 'excess';
    return review.condition;
  };
  const hasIssue = reviews.some((review, index) => review.received_quantity !== waybill.items[index].expected_quantity || calculatedCondition(index) !== 'correct');
  const reviewsValid = reviews.every((review) => Number.isFinite(review.received_quantity) && review.received_quantity >= 0);
  const receiverReady = Boolean(receiver.full_name.trim() && receiver.primary_contact.trim() && (receiver.initials.trim() || hasSignature));
  const changeReceived = (index: number, value: number) => setReviews((current) => current.map((entry, itemIndex) => {
    if (itemIndex !== index) return entry;
    const expected = waybill.items[index].expected_quantity;
    return { ...entry, received_quantity: value, condition: value === expected ? entry.condition : 'correct' as DeliveryCondition };
  }));
  const changeCondition = (index: number, condition: DeliveryCondition) => setReviews((current) => current.map((entry, itemIndex) => {
    if (itemIndex !== index) return entry;
    return { ...entry, condition };
  }));
  const addPhotos = async (index: number, files: FileList | null) => {
    if (!files?.length) return;
    const additions = await Promise.all(Array.from(files).slice(0, 10).map((file) => new Promise<string>((resolve, reject) => {
      const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.onerror = () => reject(reader.error); reader.readAsDataURL(file);
    })));
    setReviews((current) => current.map((entry, itemIndex) => itemIndex === index ? { ...entry, photos: [...entry.photos, ...additions].slice(0, 10) } : entry));
  };
  const submit = (action: 'verify-delivery' | 'report-exception') => {
    if (!receiver.full_name.trim() || !receiver.primary_contact.trim()) {
      setValidation('Actual receiver name and primary contact are required.'); return;
    }
    if (!receiver.initials.trim() && !hasSignature) {
      setValidation('Receiver initials or a drawn signature are required.'); return;
    }
    if (action === 'report-exception' && !receiver.acknowledged) {
      setValidation('The actual receiver must acknowledge the exception report.'); return;
    }
    if (action === 'verify-delivery' && hasIssue) {
      setValidation('Verify & Sign requires matching quantities and Correct condition for every item.'); return;
    }
    if (action === 'report-exception' && !hasIssue) {
      setValidation('Select Missing, Damaged, Wrong Item, or Excess for at least one item.'); return;
    }
    if (action === 'report-exception' && reviews.some((review, index) => ['damaged', 'wrong_item'].includes(calculatedCondition(index)) && !review.notes.trim())) {
      setValidation('Notes are required for Damaged or Wrong Item conditions.'); return;
    }
    setValidation('');
    void onSubmit(action, {
      items: reviews.map((review, index) => ({ ...review, exception_type: calculatedCondition(index) })),
      actual_receiver: {
        full_name: receiver.full_name.trim(), primary_contact: receiver.primary_contact.trim(),
        role: receiver.role.trim() || undefined, initials: receiver.initials.trim() || undefined,
        signature: hasSignature ? canvas.current?.toDataURL('image/png') : undefined,
        notes: receiver.notes.trim() || undefined,
        acknowledged: action === 'report-exception' ? receiver.acknowledged : undefined,
      },
    });
  };
  return <div className="rounded-xl border border-blue-200 bg-blue-50/40 p-4 print:hidden">
    <h3 className="font-semibold text-slate-900">Receiver verification</h3>
    <p className="mt-1 text-sm text-slate-600">The actual receiver must review every item and sign or initial the result.</p>
    <div className="mt-4 overflow-x-auto rounded-lg border bg-white"><table className="w-full min-w-[1180px] text-sm"><thead className="bg-slate-50 text-left text-slate-600"><tr><th className="p-3">Product</th><th className="p-3">Expected Qty</th><th className="p-3">Loaded Qty</th><th className="p-3">Received Qty</th><th className="p-3">Condition</th><th className="p-3">Missing Qty</th><th className="p-3">Excess Qty</th><th className="p-3">Variance</th><th className="p-3">Exception status</th></tr></thead><tbody>{waybill.items.map((item, index) => {
      const review = reviews[index]; const variance = Number(review.received_quantity || 0) - item.expected_quantity; const condition = calculatedCondition(index); const automatic = variance !== 0;
      return <Fragment key={item.item_id}><tr className="border-t"><td className="p-3 font-medium">{item.name}</td><td className="p-3">{item.expected_quantity} {item.unit}</td><td className="p-3">{item.loaded_quantity ?? item.expected_quantity} {item.unit}</td><td className="p-3"><input type="number" min="0" step="any" value={review.received_quantity} onChange={(event) => changeReceived(index, Number(event.target.value))} className="w-28 rounded border px-2 py-1.5" /></td><td className="p-3"><select value={condition} disabled={automatic} onChange={(event) => changeCondition(index, event.target.value as DeliveryCondition)} className="rounded border px-2 py-1.5 disabled:bg-slate-100"><option value="missing" disabled>Missing (automatic)</option>{DELIVERY_CONDITIONS.map((option) => <option key={option.value} value={option.value} disabled={option.value === 'excess' && !automatic}>{option.label}{option.value === 'excess' ? ' (automatic)' : ''}</option>)}</select></td><td className="p-3 font-medium text-amber-700">{variance < 0 ? Math.abs(variance) : 0}</td><td className="p-3 font-medium text-amber-700">{variance > 0 ? variance : 0}</td><td className={`p-3 font-medium ${variance === 0 ? 'text-emerald-700' : 'text-amber-700'}`}>{variance}</td><td className="p-3"><span className={`rounded-full px-2 py-1 text-xs ${condition === 'correct' ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-900'}`}>{condition === 'correct' ? 'Clear' : label(condition)}</span></td></tr><tr className={condition === 'correct' ? '' : 'bg-amber-50/60'}><td colSpan={9} className="p-3"><div className="grid gap-3 md:grid-cols-2"><label>Notes{['damaged', 'wrong_item'].includes(condition) ? ' *' : ' (optional)'}<textarea rows={2} value={review.notes} onChange={(event) => setReviews((current) => current.map((entry, itemIndex) => itemIndex === index ? { ...entry, notes: event.target.value } : entry))} className="mt-1 block w-full rounded border p-2" /></label>{condition !== 'correct' && <label>Optional photos<input type="file" accept="image/*" multiple onChange={(event) => void addPhotos(index, event.target.files)} className="mt-1 block w-full text-sm" /><span className="mt-1 block text-xs text-slate-500">{review.photos.length} photo(s) attached · maximum 10</span></label>}</div></td></tr></Fragment>;
    })}</tbody></table></div>
    <div className="mt-4 grid gap-3 sm:grid-cols-2">
      <label className="text-sm">Actual receiver name *<input value={receiver.full_name} onChange={(event) => setReceiver({ ...receiver, full_name: event.target.value })} className="mt-1 block w-full rounded-lg border px-3 py-2" /></label>
      <label className="text-sm">Primary contact *<input value={receiver.primary_contact} onChange={(event) => setReceiver({ ...receiver, primary_contact: event.target.value })} className="mt-1 block w-full rounded-lg border px-3 py-2" /></label>
      <label className="text-sm">Role<input value={receiver.role} onChange={(event) => setReceiver({ ...receiver, role: event.target.value })} className="mt-1 block w-full rounded-lg border px-3 py-2" /></label>
      <label className="text-sm">Initials<input value={receiver.initials} onChange={(event) => setReceiver({ ...receiver, initials: event.target.value })} maxLength={30} className="mt-1 block w-full rounded-lg border px-3 py-2" /></label>
      <label className="text-sm sm:col-span-2">Receiver notes<textarea rows={3} value={receiver.notes} onChange={(event) => setReceiver({ ...receiver, notes: event.target.value })} className="mt-1 block w-full rounded-lg border px-3 py-2" /></label>
      {hasIssue && <label className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm sm:col-span-2"><input type="checkbox" checked={receiver.acknowledged} onChange={(event) => setReceiver({ ...receiver, acknowledged: event.target.checked })} className="mt-0.5" /><span>I acknowledge that the exception details above accurately describe the delivery received.</span></label>}
      <div className="sm:col-span-2"><div className="flex items-center justify-between"><p className="text-sm">Draw signature</p><button type="button" onClick={clearSignature} className="text-xs text-blue-700">Clear</button></div><canvas ref={canvas} width={720} height={160} onPointerDown={start} onPointerMove={move} onPointerUp={() => { drawing.current = false; }} onPointerCancel={() => { drawing.current = false; }} className="mt-1 h-36 w-full touch-none rounded-lg border bg-white" /></div>
    </div>
    {validation && <p className="mt-3 text-sm text-red-700">{validation}</p>}
    <div className="mt-4 flex flex-wrap gap-2"><button type="button" disabled={Boolean(busy) || hasIssue || !reviewsValid || !receiverReady} onClick={() => submit('verify-delivery')} className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-50">{busy === 'verify-delivery' && <Loader2 className="h-4 w-4 animate-spin" />}<CheckCircle2 className="h-4 w-4" />Verify & Sign</button><button type="button" disabled={Boolean(busy) || !hasIssue || !reviewsValid} onClick={() => submit('report-exception')} className="rounded-lg border border-red-300 bg-white px-3 py-2 text-sm font-medium text-red-700 disabled:opacity-60">{busy === 'report-exception' && <Loader2 className="mr-2 inline h-4 w-4 animate-spin" />}Report Exception</button></div>
  </div>;
}

function ItemQuantities({ items, setItems, editableField }: { items: WaybillItem[]; setItems: (items: WaybillItem[]) => void; editableField: 'loaded_quantity' | 'received_quantity' | null }) {
  return <div className="overflow-x-auto"><table className="w-full min-w-[780px] text-sm"><thead><tr className="border-b text-left text-slate-500"><th className="p-2">Item</th><th className="p-2">Expected</th><th className="p-2">Loaded</th><th className="p-2">Received</th><th className="p-2">Variance</th><th className="p-2">Condition</th></tr></thead><tbody>{items.map((item, index) => <tr key={item.item_id} className="border-b"><td className="p-2"><b>{item.item_id}</b><div className="text-xs text-slate-500">{item.name}</div></td><td className="p-2">{item.expected_quantity} {item.unit}</td><td className="p-2">{editableField === 'loaded_quantity' ? <Cell type="number" value={String(item.loaded_quantity ?? item.expected_quantity)} onChange={(value) => setItems(items.map((row, rowIndex) => rowIndex === index ? { ...row, loaded_quantity: Number(value) } : row))} /> : item.loaded_quantity ?? '—'}</td><td className="p-2">{editableField === 'received_quantity' ? <Cell type="number" value={String(item.received_quantity ?? item.loaded_quantity ?? item.expected_quantity)} onChange={(value) => setItems(items.map((row, rowIndex) => rowIndex === index ? { ...row, received_quantity: Number(value) } : row))} /> : item.received_quantity ?? '—'}</td><td className={`p-2 font-medium ${(item.variance || 0) !== 0 ? 'text-amber-700' : 'text-emerald-700'}`}>{item.variance ?? '—'}</td><td className="p-2">{item.item_condition ? label(item.item_condition) : '—'}</td></tr>)}</tbody></table></div>;
}

function SignatureSection({ waybill, driverMode, onSaved, onError }: { waybill: Waybill; driverMode: boolean; onSaved: (waybill: Waybill) => void; onError: (message: string) => void }) {
  const [party, setParty] = useState<'sender' | 'receiver' | null>(null);
  if (driverMode || waybill.status === 'draft') return null;
  return <div className="print:hidden"><h3 className="font-semibold">Optional handwritten signatures</h3><div className="mt-2 flex gap-2">{(['sender', 'receiver'] as const).map((item) => <button type="button" key={item} disabled={Boolean(waybill.signatures[item])} onClick={() => setParty(item)} className="inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm disabled:bg-slate-100"><PenLine className="h-4 w-4" />{waybill.signatures[item] ? `${label(item)} signed` : `Add ${item} signature`}</button>)}</div>{party && <SignaturePad party={party} onCancel={() => setParty(null)} onSave={async (signature, name) => { try { onSaved(await saveWaybillSignature(waybill.id, party, signature, name)); setParty(null); } catch (value) { onError(errorMessage(value)); } }} />}</div>;
}

function SignaturePad({ party, onCancel, onSave }: { party: 'sender' | 'receiver'; onCancel: () => void; onSave: (signature: string, name: string) => Promise<void> }) {
  const canvas = useRef<HTMLCanvasElement>(null); const drawing = useRef(false); const [name, setName] = useState('');
  const point = (event: ReactPointerEvent<HTMLCanvasElement>) => { const box = event.currentTarget.getBoundingClientRect(); return { x: event.clientX - box.left, y: event.clientY - box.top }; };
  const start = (event: ReactPointerEvent<HTMLCanvasElement>) => { drawing.current = true; const context = canvas.current?.getContext('2d'); const next = point(event); context?.beginPath(); context?.moveTo(next.x, next.y); event.currentTarget.setPointerCapture(event.pointerId); };
  const move = (event: ReactPointerEvent<HTMLCanvasElement>) => { if (!drawing.current) return; const context = canvas.current?.getContext('2d'); const next = point(event); if (context) { context.lineWidth = 2; context.lineCap = 'round'; context.strokeStyle = '#0f172a'; context.lineTo(next.x, next.y); context.stroke(); } };
  return <div className="mt-3 max-w-xl rounded-lg border bg-slate-50 p-4"><p className="text-sm font-medium">{label(party)} signature</p><canvas ref={canvas} width={520} height={150} onPointerDown={start} onPointerMove={move} onPointerUp={() => { drawing.current = false; }} className="mt-2 h-36 w-full touch-none rounded border bg-white" /><input value={name} onChange={(event) => setName(event.target.value)} placeholder="Signer name" className="mt-2 w-full rounded-lg border px-3 py-2 text-sm" /><div className="mt-2 flex gap-2"><button type="button" onClick={onCancel} className="rounded-lg border px-3 py-2 text-sm">Cancel</button><button type="button" onClick={() => { const signature = canvas.current?.toDataURL('image/png'); if (signature && name.trim()) void onSave(signature, name.trim()); }} className="rounded-lg bg-blue-600 px-3 py-2 text-sm text-white">Save signature</button></div></div>;
}

function Action({ children, onClick, busy }: { children: React.ReactNode; onClick: () => void | Promise<void>; busy: boolean }) { return <button type="button" onClick={() => void onClick()} disabled={busy} className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-60">{busy && <Loader2 className="h-4 w-4 animate-spin" />}{children}</button>; }
function Cell({ value, onChange, type = 'text' }: { value: string; onChange: (value: string) => void; type?: string }) { return <input type={type} min={type === 'number' ? 0 : undefined} step={type === 'number' ? 'any' : undefined} value={value} onChange={(event) => onChange(event.target.value)} className="w-full min-w-24 rounded border px-2 py-1.5" />; }
