import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { AlertCircle, CheckCircle2, Circle, Loader2, PackageCheck, Plus, RefreshCw, Search, Trash2, X } from 'lucide-react';
import { ApiRequestError } from '../../lib/api';
import { getStoredSessionUser } from '../../lib/auth-session';
import { fetchOperationOptions, type OperationOptions } from '../../lib/operational-request-api';
import {
  createStockTransfer,
  fetchStockTransferRecipientOptions,
  fetchStockTransfer,
  fetchStockTransfers,
  type CaseClosureSummary,
  type InvestigationCostImpact,
  mutateStockTransfer,
  type StockTransfer,
  type StockTransferItem,
  type TransferRecipient,
  type StockTransferRecipientBranch,
  type StockTransferRecipientOption,
} from '../../lib/stock-transfer-api';
import { searchWaybillProducts, type WaybillProduct } from '../../lib/waybill-api';
import { SearchableSelect } from '../ui/searchable-select';

const WORKFLOW = ['Draft', 'Submitted', 'Approved', 'Assigned', 'Driver Confirmed', 'Loaded', 'In Transit', 'Delivered', 'Received', 'Variance Review', 'Completed'];

const emptyItem = (): StockTransferItem => ({ item_id: '', name: '', quantity: 1, unit: 'unit' });
const emptyRecipient = (): TransferRecipient => ({ full_name: '', role: '', primary_phone: '', secondary_phone: '', email: '', delivery_instructions: '' });
const emptyForm = () => ({ sending_location: '', receiving_location: '', receiving_location_id: '', requested_date: '', purpose: '', notes: '', recipient: emptyRecipient() });
const message = (error: unknown) => error instanceof ApiRequestError || error instanceof Error
  ? error.message
  : 'Unable to update stock transfer.';
const RECIPIENT_LOCKED_STATUSES = new Set(['released', 'in_transit', 'awaiting_receipt', 'completed', 'cancelled']);
const canEditRecipient = (record: StockTransfer) => !record.acknowledged_at && !RECIPIENT_LOCKED_STATUSES.has(record.status);
type ReceiptDraft = Record<string, { received: string; good: string; damaged: string; wrong: string; notes: string }>;

function displayStage(record: StockTransfer) {
  if (record.operation_type === 'supplier_pickup') {
    if (record.status === 'scheduled' && record.supplier_handover) return 'Supplier Handover';
    if (record.status === 'scheduled' && record.supplier_arrived_at) return 'Arrived at Supplier';
    if (record.status === 'scheduled') return record.acknowledged_at ? 'Driver Confirmed' : 'Assigned';
  }
  if (record.status === 'pending_approval') return 'Submitted';
  if (record.status === 'approved') return 'Approved';
  if (record.status === 'scheduled') return record.acknowledged_at ? 'Driver Confirmed' : 'Assigned';
  if (record.status === 'released') return 'Loaded';
  if (record.status === 'in_transit') return 'In Transit';
  if (record.status === 'awaiting_receipt' && record.linked_delivery_exception_id) return record.delivery_exception_status === 'resolved' ? 'Exception Resolved' : 'Delivery Exception';
  if (record.status === 'awaiting_receipt' && record.receiving_status !== 'received') return 'Delivered';
  if (record.status === 'awaiting_receipt' && record.quantity_variance?.length) return record.variance_review ? 'Variance Reviewed' : 'Variance Review';
  if (record.status === 'awaiting_receipt') return 'Received';
  return record.status.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export default function StockTransfers({ driverMode = false, onNavigate, taskId }: { driverMode?: boolean; onNavigate?: (page: string) => void; taskId?: string }) {
  const sessionUser = getStoredSessionUser();
  const activeWorkspace = String(sessionUser?.selected_workspace || sessionUser?.role || '').toLowerCase();
  const branchReceiverMode = ['branch_manager', 'branch_warehouse_coordinator'].includes(activeWorkspace);
  const [records, setRecords] = useState<StockTransfer[]>([]);
  const [options, setOptions] = useState<OperationOptions | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [creating, setCreating] = useState(false);
  const [scheduling, setScheduling] = useState({ id: '', vehicle_id: '', driver_id: '', scheduled_at: '' });
  const [receiving, setReceiving] = useState<StockTransfer | null>(null);
  const [receiptDraft, setReceiptDraft] = useState<ReceiptDraft>({});
  const [receiptConfirmed, setReceiptConfirmed] = useState(false);
  const [receiverInitials, setReceiverInitials] = useState('');
  const [receiptNotes, setReceiptNotes] = useState('');
  const [externalReceiver, setExternalReceiver] = useState({ full_name: '', role: '', primary_contact: '' });
  const [loadingTransfer, setLoadingTransfer] = useState<StockTransfer | null>(null);
  const [loadedQuantities, setLoadedQuantities] = useState<Record<string, string>>({});
  const [handover, setHandover] = useState({ id: '', supplier_representative: '', phone: '', notes: '' });
  const [varianceResolution, setVarianceResolution] = useState<Record<string, string>>({});
  const [editingRecipient, setEditingRecipient] = useState<StockTransfer | null>(null);
  const [exceptionDetail, setExceptionDetail] = useState<StockTransfer | null>(null);

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      if (taskId) {
        setRecords([await fetchStockTransfer(taskId)]);
      } else {
        const [items, opts] = await Promise.all([fetchStockTransfers({ operation_type: 'stock_transfer' }), branchReceiverMode ? Promise.resolve(null) : fetchOperationOptions()]);
        setRecords(items);
        setOptions(opts);
      }
    } catch (value) {
      setError(message(value));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, [taskId]);

  const run = async (record: StockTransfer, action: string, payload: Record<string, unknown> = {}) => {
    setBusy(record.id);
    setError('');
    setNotice('');
    try {
      const updated = await mutateStockTransfer(record.id, action, payload);
      setRecords((current) => current.map((item) => item.id === updated.id ? updated : item));
      setNotice('Stock transfer updated.');
      if (exceptionDetail?.id === updated.id) setExceptionDetail(updated);
      window.dispatchEvent(new CustomEvent('flux-notifications-changed', { detail: { operationType: updated.operation_type, taskId: record.id } }));
      return updated;
    } catch (value) {
      setError(message(value));
      return undefined;
    } finally {
      setBusy('');
    }
  };

  const openLoading = async (record: StockTransfer) => {
    setBusy(record.id);
    setError('');
    try {
      const detail = await fetchStockTransfer(record.id);
      setLoadingTransfer(detail);
      setLoadedQuantities(Object.fromEntries((detail.transfer_items || []).map((item) => [item.item_id, String(item.quantity)])));
    } catch (value) {
      setError(message(value));
    } finally {
      setBusy('');
    }
  };

  const saveLoading = async () => {
    if (!loadingTransfer) return;
    const quantities = (loadingTransfer.transfer_items || []).map((item) => ({
      item_id: item.item_id,
      quantity: Number(loadedQuantities[item.item_id] || 0),
    }));
    if (await run(loadingTransfer, 'release', { loaded_quantities: quantities })) {
      setLoadingTransfer(null);
      await load();
    }
  };

  const openReceipt = async (record: StockTransfer) => {
    setBusy(record.id);
    try {
      const detail = await fetchStockTransfer(record.id);
      setReceiving(detail);
      setReceiptDraft(Object.fromEntries((detail.transfer_items || []).map((item) => [item.item_id, { received: String(item.quantity), good: String(item.quantity), damaged: '0', wrong: '0', notes: '' }])));
      setReceiptConfirmed(false); setReceiverInitials(''); setReceiptNotes('');
      setExternalReceiver({
        full_name: detail.recipient?.recipient_type === 'external' ? detail.recipient.full_name : '',
        role: detail.recipient?.recipient_type === 'external' ? detail.recipient.role || '' : '',
        primary_contact: detail.recipient?.recipient_type === 'external' ? detail.recipient.primary_phone : '',
      });
    } catch (value) {
      setError(message(value));
    } finally {
      setBusy('');
    }
  };

  const saveReceipt = async () => {
    if (!receiving) return;
    const items = (receiving.transfer_items || []).map((item) => ({ ...item,
      received_quantity: Number(receiptDraft[item.item_id]?.received || 0), good_quantity: Number(receiptDraft[item.item_id]?.good || 0),
      damaged_quantity: Number(receiptDraft[item.item_id]?.damaged || 0), wrong_item_quantity: Number(receiptDraft[item.item_id]?.wrong || 0),
      notes: receiptDraft[item.item_id]?.notes || undefined,
    }));
    const externalActualReceiver = receiving.recipient?.recipient_type === 'external' && !branchReceiverMode
      ? { receiver_type: 'external', ...externalReceiver, notes: receiptNotes || undefined }
      : undefined;
    if (await run(receiving, 'receive', { received_items: items, confirmed: receiptConfirmed, receiver_initials: receiverInitials || undefined, notes: receiptNotes || undefined, actual_receiver: externalActualReceiver })) setReceiving(null);
  };

  const openAssignedWaybill = (record: StockTransfer) => {
    if (!record.linked_waybill_id || !onNavigate) return;
    sessionStorage.setItem('flux_notification_target', JSON.stringify({ referenceType: 'waybill', referenceId: record.linked_waybill_id }));
    onNavigate('digital-waybills');
  };
  const openException = async (record: StockTransfer) => {
    setBusy(record.id); setError('');
    try { setExceptionDetail(await fetchStockTransfer(record.id)); } catch (value) { setError(message(value)); } finally { setBusy(''); }
  };

  return <div className="min-h-full bg-slate-50 p-4 md:p-6">
    <div className="mx-auto max-w-7xl space-y-5">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">{driverMode ? 'Assigned Stock Transfers' : branchReceiverMode ? 'Incoming Stock' : 'Stock Transfers'}</h1>
          <p className="text-sm text-slate-500">{branchReceiverMode ? 'Receive and verify transfers addressed to your authorized branches.' : 'Create and track items being transferred between locations.'}</p>
        </div>
        <div className="flex gap-2">
          <button type="button" onClick={() => void load()} className="rounded-lg border bg-white p-2.5" aria-label="Refresh transfers"><RefreshCw className="h-4 w-4" /></button>
          {!driverMode && !branchReceiverMode && <button type="button" onClick={() => setCreating(true)} className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white"><Plus className="h-4 w-4" />New Transfer</button>}
        </div>
      </header>

      <div className="overflow-x-auto rounded-xl border bg-white p-3">
        <div className="flex min-w-max items-center gap-2">
          {WORKFLOW.map((step, index) => <div key={step} className="flex items-center gap-2">
            <span className="rounded-full bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-600">{step}</span>
            {index < WORKFLOW.length - 1 && <span className="text-slate-300">→</span>}
          </div>)}
        </div>
      </div>

      {error && <div className="flex gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"><AlertCircle className="h-4 w-4 shrink-0" />{error}</div>}
      {notice && <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-700">{notice}</div>}

      {creating && !driverMode && !branchReceiverMode && <CreateTransferPanel
        busy={busy === 'create'}
        onCancel={() => setCreating(false)}
        onError={setError}
        onCreated={(record) => {
          setRecords((current) => [record, ...current]);
          setCreating(false);
          setNotice(record.status === 'draft' ? 'Stock transfer draft saved.' : 'Stock transfer submitted for approval.');
        }}
        setBusy={setBusy}
      />}

      {driverMode && records.some((record) => record.status === 'scheduled' && !record.acknowledged_at) && <div className="rounded-xl border border-blue-200 bg-blue-50 p-4">
        <p className="text-sm font-medium text-blue-900">Review the items and accept custody before loading begins.</p>
        <div className="mt-3 flex flex-wrap gap-2">{records.filter((record) => record.status === 'scheduled' && !record.acknowledged_at && record.linked_waybill_id).map((record) => <Button key={record.id} busy={false} onClick={() => openAssignedWaybill(record)}>Open Waybill {record.transfer_id}</Button>)}</div>
      </div>}

      {loading ? <div className="flex h-56 items-center justify-center"><Loader2 className="h-7 w-7 animate-spin text-blue-600" /></div> : <div className="grid gap-4 lg:grid-cols-2">
        {records.map((record) => <article key={record.id} className="rounded-xl border bg-white p-5 shadow-sm">
          <div className="flex justify-between gap-3">
            <div>
              <p className="text-xs font-medium text-blue-600">{record.transfer_id}</p>
              <h2 className="mt-1 font-semibold text-slate-900">{record.operation_type === 'supplier_pickup' ? `${record.supplier?.supplier_name || 'Supplier'} → ${record.receiving_location}` : `${record.sending_location} → ${record.receiving_location}`}</h2>
              <p className="mt-1 text-sm text-slate-500">{record.item_count} item(s){record.requested_date ? ` · Requested ${new Date(`${record.requested_date}T00:00:00`).toLocaleDateString()}` : ''}</p>
              {record.purpose && <p className="mt-2 text-sm text-slate-700">{record.purpose}</p>}
              {branchReceiverMode && <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-xs text-slate-600 sm:grid-cols-3">
                <p><b>Driver:</b> {record.driver?.full_name || 'Unassigned'}</p><p><b>Vehicle:</b> {record.vehicle?.registration_number || 'Unassigned'}</p>
                <p><b>Dispatch:</b> {record.dispatch_date ? new Date(record.dispatch_date).toLocaleString() : 'Not dispatched'}</p><p><b>Expected:</b> {record.expected_arrival ? new Date(record.expected_arrival).toLocaleString() : 'Not scheduled'}</p>
                <p><b>Items:</b> {record.item_count}</p><p><b>Quantity:</b> {record.total_quantity ?? 0}</p>
              </div>}
              {branchReceiverMode && Boolean(record.transfer_items?.length) && <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700"><p className="font-medium text-slate-900">Product lines</p>{record.transfer_items?.map((item) => <p key={item.item_id} className="mt-1 flex justify-between gap-3"><span>{item.name}</span><span className="shrink-0 font-medium">{item.quantity} {item.unit}</span></p>)}</div>}
            </div>
            <span className="h-fit rounded-full bg-blue-100 px-2.5 py-1 text-xs text-blue-800">{displayStage(record)}</span>
          </div>
          <RecipientDetails recipient={record.recipient} />
          {record.receiver_name && <div className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900"><p className="font-medium">Received by: {record.receiver_name} — {record.receiver_role}</p><p>{record.receiving_location}{record.received_at ? ` · ${new Date(record.received_at).toLocaleString()}` : ''}</p></div>}
          {record.actual_receiver && <div className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900"><p className="font-medium">Actual receiver: {record.actual_receiver.full_name}</p><p>{record.actual_receiver.primary_contact}{record.actual_receiver.role ? ` · ${record.actual_receiver.role}` : ''}</p></div>}
          {record.linked_delivery_exception_id && <div className={`mt-3 rounded-lg border p-3 text-sm ${record.delivery_exception_status === 'resolved' ? 'border-emerald-200 bg-emerald-50 text-emerald-900' : 'border-amber-200 bg-amber-50 text-amber-900'}`}><div className="flex flex-wrap justify-between gap-2"><p className="font-medium">Delivery Exception {record.delivery_exception_status === 'resolved' ? 'Resolved' : 'Open'}</p><span className="text-xs">{record.delivery_exception_summary?.exception_number}</span></div><p className="mt-1">{record.delivery_exception_summary?.affected_item_count ?? record.quantity_variance?.length ?? 0} affected item(s) · {(record.delivery_exception_summary?.exception_types || []).map((value) => value.replaceAll('_', ' ')).join(', ')}</p><p className="mt-1">{record.delivery_exception_status === 'resolved' ? 'Linked replacement completed successfully.' : 'Verification and completion are blocked.'}</p>{record.delivery_exception_summary?.investigation_status && <p className="mt-1 font-medium">Investigation: {titleCase(record.delivery_exception_summary.investigation_status)}</p>}<button type="button" onClick={() => void openException(record)} className="mt-3 rounded-lg border bg-white px-3 py-2 font-medium">{record.delivery_exception_status === 'resolved' ? 'View Investigation' : 'Next Action'}</button></div>}
          <div className="mt-4 flex flex-wrap items-end gap-2">
            {driverMode ? <>
              {record.status === 'scheduled' && !record.acknowledged_at && <Button busy={busy === record.id} onClick={() => run(record, 'acknowledge')}>Accept Transfer</Button>}
              {record.linked_waybill_id && <Button busy={false} onClick={() => openAssignedWaybill(record)}>Open Waybill</Button>}
              {record.operation_type === 'supplier_pickup' && record.status === 'scheduled' && record.acknowledged_at && !record.supplier_arrived_at && <Button busy={busy === record.id} onClick={() => run(record, 'arrive')}>Arrived at Supplier</Button>}
              {record.operation_type === 'supplier_pickup' && record.status === 'scheduled' && record.supplier_arrived_at && !record.supplier_handover && <Button busy={false} onClick={() => setHandover({ id: record.id, supplier_representative: '', phone: '', notes: '' })}>Record Handover</Button>}
              {record.operation_type === 'supplier_pickup' && record.status === 'scheduled' && record.supplier_handover && <Button busy={busy === record.id} onClick={() => void openLoading(record)}>Confirm Loaded</Button>}
              {record.status === 'released' && <Button busy={busy === record.id} onClick={() => run(record, 'start')}>Start Journey</Button>}
              {record.status === 'in_transit' && record.operation_type !== 'supplier_pickup' && <Button busy={busy === record.id} onClick={() => run(record, 'arrive')}>Arrived / Delivered</Button>}
            </> : branchReceiverMode ? <>
              {record.status === 'awaiting_receipt' && record.receiving_status !== 'received' && <Button busy={busy === record.id} onClick={() => void openReceipt(record)}>Receive Stock</Button>}
              {record.workflow_stage === 'variance' && !record.variance_review && <>
                <Input label="Variance report" value={varianceResolution[record.id] || ''} onChange={(value) => setVarianceResolution({ ...varianceResolution, [record.id]: value })} />
                <Button busy={busy === record.id} onClick={() => run(record, 'variance', { resolution: varianceResolution[record.id] })}>Report Variance</Button>
              </>}
            </> : <>
              {canEditRecipient(record) && <button type="button" onClick={() => setEditingRecipient(record)} className="rounded-lg border px-3 py-2 text-sm font-medium text-slate-700">Edit Recipient</button>}
              {record.status === 'draft' && <Button busy={busy === record.id} onClick={() => run(record, 'submit')}>Submit for Approval</Button>}
              {record.status === 'pending_approval' && <Button busy={busy === record.id} onClick={() => run(record, 'approve')}>Approve</Button>}
              {record.status === 'approved' && <Button busy={false} onClick={() => setScheduling({ id: record.id, vehicle_id: '', driver_id: '', scheduled_at: '' })}>Assign Driver</Button>}
              {record.status === 'scheduled' && record.acknowledged_at && <Button busy={busy === record.id} onClick={() => void openLoading(record)}>Confirm Loading</Button>}
              {record.status === 'scheduled' && !record.acknowledged_at && <span className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">Awaiting Driver Acceptance</span>}
              {record.status === 'awaiting_receipt' && record.receiving_status !== 'received' && <Button busy={busy === record.id} onClick={() => void openReceipt(record)}>Confirm Receipt</Button>}
              {record.workflow_stage === 'variance' && !record.variance_review && <>
                <Input label="Variance resolution" value={varianceResolution[record.id] || ''} onChange={(value) => setVarianceResolution({ ...varianceResolution, [record.id]: value })} />
                <Button busy={busy === record.id} onClick={() => run(record, 'variance', { resolution: varianceResolution[record.id] })}>Review Variance</Button>
              </>}
              {record.status === 'awaiting_receipt' && record.receiving_status === 'received' && (record.workflow_stage !== 'variance' || Boolean(record.variance_review)) && <Button busy={busy === record.id} onClick={() => run(record, 'complete')}>Complete</Button>}
            </>}
          </div>
          {scheduling.id === record.id && <div className="mt-4 grid gap-3 rounded-lg bg-slate-50 p-4 sm:grid-cols-2">
            <Select label="Vehicle" value={scheduling.vehicle_id} onChange={(value) => setScheduling({ ...scheduling, vehicle_id: value })} options={(options?.vehicles || []).map((item) => ({ value: item.id, label: item.registration_number }))} />
            <Select label="Driver" value={scheduling.driver_id} onChange={(value) => setScheduling({ ...scheduling, driver_id: value })} options={(options?.drivers || []).map((item) => ({ value: item.id, label: item.full_name }))} />
            <Input label="Scheduled time" type="datetime-local" value={scheduling.scheduled_at} onChange={(value) => setScheduling({ ...scheduling, scheduled_at: value })} />
            <div className="flex items-end"><Button busy={busy === record.id} onClick={async () => {
              if (await run(record, 'schedule', scheduling)) setScheduling({ id: '', vehicle_id: '', driver_id: '', scheduled_at: '' });
            }}>Save Assignment</Button></div>
          </div>}
          {handover.id === record.id && <div className="mt-4 grid gap-3 rounded-lg bg-slate-50 p-4 sm:grid-cols-2">
            <Input label="Supplier representative" value={handover.supplier_representative} onChange={(value) => setHandover({ ...handover, supplier_representative: value })} required />
            <Input label="Phone" value={handover.phone} onChange={(value) => setHandover({ ...handover, phone: value })} />
            <Textarea label="Notes" value={handover.notes} onChange={(value) => setHandover({ ...handover, notes: value })} />
            <div className="flex items-end"><Button busy={busy === record.id} onClick={async () => {
              if (await run(record, 'supplier-handover', { supplier_representative: handover.supplier_representative, phone: handover.phone || undefined, notes: handover.notes || undefined })) setHandover({ id: '', supplier_representative: '', phone: '', notes: '' });
            }}>Save Handover</Button></div>
          </div>}
        </article>)}
      </div>}
    </div>

    {loadingTransfer && <QuantityModal
      title="Confirm loaded quantities"
      action="Confirm Loading"
      transfer={loadingTransfer}
      quantities={loadedQuantities}
      setQuantities={setLoadedQuantities}
      busy={busy === loadingTransfer.id}
      backendError={error}
      onCancel={() => setLoadingTransfer(null)}
      onSave={saveLoading}
    />}
    {receiving && <ReceivingModal transfer={receiving} draft={receiptDraft} setDraft={setReceiptDraft} confirmed={receiptConfirmed} setConfirmed={setReceiptConfirmed} initials={receiverInitials} setInitials={setReceiverInitials} notes={receiptNotes} setNotes={setReceiptNotes} externalReceiver={externalReceiver} setExternalReceiver={setExternalReceiver} externalMode={receiving.recipient?.recipient_type === 'external' && !branchReceiverMode} busy={busy === receiving.id} onCancel={() => setReceiving(null)} onSave={saveReceipt} />}
    {editingRecipient && <RecipientEditor
      transfer={editingRecipient}
      busy={busy === editingRecipient.id}
      onCancel={() => setEditingRecipient(null)}
      onSave={async (recipient, reason) => {
        if (await run(editingRecipient, 'recipient', { recipient, reason: reason || undefined })) setEditingRecipient(null);
      }}
    />}
    {exceptionDetail?.delivery_exception && <ExceptionActionPanel transfer={exceptionDetail} driverMode={driverMode} options={options} busy={busy === exceptionDetail.id} onClose={() => setExceptionDetail(null)} onAction={async (action, payload = {}) => { const updated = await run(exceptionDetail, action, payload); if (updated) setExceptionDetail(updated); }} />}
  </div>;
}

function ExceptionActionPanel({ transfer, driverMode, options, busy, onClose, onAction }: { transfer: StockTransfer; driverMode: boolean; options: OperationOptions | null; busy: boolean; onClose: () => void; onAction: (action: string, payload?: Record<string, unknown>) => Promise<void> }) {
  const exception = transfer.delivery_exception!; const current = exception.current_action || {}; const returnRequest = exception.return_request;
  const types = new Set(exception.items.map((item) => item.exception_type));
  const actions = new Set<string>();
  if (types.has('missing')) ['dispatch_replacement', 'hold_for_investigation', 'correct_documentation'].forEach((item) => actions.add(item));
  if (types.has('damaged')) ['return_item', 'hold_for_investigation'].forEach((item) => actions.add(item));
  if (types.has('wrong_item')) ['return_item', 'dispatch_replacement'].forEach((item) => actions.add(item));
  if (types.has('excess')) ['return_item', 'accept_excess'].forEach((item) => actions.add(item));
  const active = current.status === 'active'; const resolved = exception.status === 'resolved'; const completedReturn = exception.action_history?.some((entry) => entry.action === 'return_item' && entry.status === 'completed');
  const [assignment, setAssignment] = useState({ driver_id: returnRequest?.driver_id || '', vehicle_id: returnRequest?.vehicle_id || '' });
  const title = (value: string) => value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"><div className="max-h-[92vh] w-full max-w-3xl overflow-y-auto rounded-xl bg-white p-5">
    <div className="flex items-start justify-between"><div><h2 className="text-lg font-semibold">Delivery Exception · Next Action</h2><p className="text-sm text-slate-500">{exception.exception_number} · {exception.items.length} affected item(s)</p></div><button type="button" onClick={onClose}><X className="h-5 w-5" /></button></div>
    {exception.replacement_request && exception.operations_timeline?.length ? <div className="mt-4 rounded-xl border p-4"><h3 className="font-medium">Operations Timeline</h3><div className="mt-3 space-y-3">{exception.operations_timeline.map((stage, index) => <div key={stage.key} className="flex gap-3"><div className="flex flex-col items-center">{stage.completed ? <CheckCircle2 className="h-5 w-5 text-emerald-600" /> : <Circle className="h-5 w-5 text-slate-300" />}{index < exception.operations_timeline!.length - 1 && <span className={`mt-1 h-5 w-px ${stage.completed ? 'bg-emerald-300' : 'bg-slate-200'}`} />}</div><div><p className={`text-sm font-medium ${stage.completed ? 'text-slate-900' : 'text-slate-400'}`}>{stage.label}</p>{stage.timestamp && <p className="text-xs text-slate-500">{new Date(stage.timestamp).toLocaleString()}</p>}</div></div>)}</div></div> : <div className="mt-4 rounded-lg bg-amber-50 p-3 text-sm"><b>Operational status:</b> {current.action ? `${title(String(current.action))} · ${title(String(current.status || 'active'))}` : 'Awaiting action'}</div>}
    {!driverMode && !active && !resolved && <div className="mt-4"><h3 className="font-medium">Valid actions</h3><div className="mt-2 flex flex-wrap gap-2">{Array.from(actions).filter((action) => !(action === 'dispatch_replacement' && types.has('wrong_item') && !completedReturn)).map((action) => <button key={action} type="button" disabled={busy} onClick={() => void onAction('exception-action', { action })} className="rounded-lg bg-blue-600 px-3 py-2 text-sm text-white disabled:opacity-50">{title(action)}</button>)}</div></div>}
    {active && !returnRequest && <p className="mt-4 rounded-lg border p-3 text-sm">One action is active. Additional actions are blocked until it completes.</p>}
    {returnRequest && <div className="mt-4 rounded-xl border p-4"><h3 className="font-medium">Return Request {returnRequest.return_number}</h3><p className="mt-1 text-sm">Status: {title(returnRequest.status)}</p><p className="mt-1 text-xs text-slate-500">Waybill {returnRequest.linked_waybill_id} · Movement {returnRequest.linked_vehicle_movement_id}</p>
      {!driverMode && ['assigned', 'pending'].includes(returnRequest.status) && <div className="mt-3 grid gap-2 sm:grid-cols-2"><Select label="Returning driver" value={assignment.driver_id} onChange={(driver_id) => setAssignment({ ...assignment, driver_id })} options={(options?.drivers || []).map((item) => ({ value: item.id, label: item.full_name }))} /><Select label="Return vehicle" value={assignment.vehicle_id} onChange={(vehicle_id) => setAssignment({ ...assignment, vehicle_id })} options={(options?.vehicles || []).map((item) => ({ value: item.id, label: item.registration_number }))} /><Button busy={busy} onClick={() => onAction('exception-return/assigned', assignment)}>Save Assignment</Button></div>}
      {returnRequest.status === 'assigned' && <div className="mt-3"><Button busy={busy} onClick={() => onAction('exception-return/in_transit')}>Start Return Journey</Button></div>}
      {returnRequest.status === 'in_transit' && <div className="mt-3"><Button busy={busy} onClick={() => onAction('exception-return/returned')}>Mark Returned</Button></div>}
      {!driverMode && returnRequest.status === 'returned' && <div className="mt-3"><Button busy={busy} onClick={() => onAction('exception-return/received_at_origin')}>Received at Origin</Button></div>}
    </div>}
    {exception.replacement_request && <div className="mt-4 rounded-xl border p-4"><h3 className="font-medium">Replacement {exception.replacement_request.replacement_number}</h3><p className="mt-1 text-sm">Status: {title(exception.replacement_request.status)}</p><p className="mt-1 text-xs text-slate-500">Transfer {exception.replacement_request.linked_stock_transfer_id} · Waybill {exception.replacement_request.linked_waybill_id} · Movement {exception.replacement_request.linked_vehicle_movement_id}</p></div>}
    {resolved && !driverMode && <InvestigationPanel transfer={transfer} busy={busy} onAction={onAction} />}
  </div></div>;
}

const INVESTIGATION_STAGES = ['open', 'under_investigation', 'awaiting_approval', 'approved', 'actions_in_progress', 'closed'];
const ROOT_CAUSES = ['warehouse_picking_error', 'warehouse_loading_error', 'driver_negligence', 'transport_accident', 'supplier_error', 'documentation_error', 'customer_receiver_error', 'suspected_theft', 'other'];
const RESPONSIBILITIES = ['warehouse', 'driver', 'supplier', 'customer', 'third_party', 'shared'];
const DECISIONS = ['no_action', 'retraining', 'warning', 'supplier_claim', 'recovery', 'hr_case', 'finance_case', 'write_off', 'escalate'];
const titleCase = (value: string) => value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
const formatCurrency = (value?: number | null) => new Intl.NumberFormat(undefined, { style: 'currency', currency: 'GHS' }).format(Number(value || 0));

function InvestigationPanel({ transfer, busy, onAction }: { transfer: StockTransfer; busy: boolean; onAction: (action: string, payload?: Record<string, unknown>) => Promise<void> }) {
  const investigation = transfer.delivery_exception?.investigation;
  const sessionUser = getStoredSessionUser();
  const [form, setForm] = useState({ investigator_id: investigation?.investigator_id || '', priority: investigation?.priority || 'medium', root_cause: investigation?.root_cause || '', responsibility: investigation?.responsibility || '', decision: investigation?.decision || '', note: '', estimated_loss: String(investigation?.cost_impact?.estimated_loss || ''), replacement_cost: String(investigation?.cost_impact?.replacement_cost || ''), recovered_amount: String(investigation?.cost_impact?.recovered_amount || ''), recovery_status: investigation?.cost_impact?.recovery_status || 'not_started' });
  const [evidence, setEvidence] = useState<Array<{ name: string; file_name: string; file_kind: string; content_type: string; data_url: string }>>([]);
  const [confirmTheft, setConfirmTheft] = useState(false);
  const [approvalComments, setApprovalComments] = useState('');
  const [validation, setValidation] = useState('');
  const choices = (values: string[]) => values.map((value) => ({ value, label: titleCase(value) }));
  const loadEvidence = async (files: FileList | null) => {
    if (!files) return;
    if (files.length > 10) { setValidation('A maximum of 10 evidence files can be added at once.'); return; }
    try {
      const selected = await Promise.all(Array.from(files).map((file) => new Promise<{ name: string; file_name: string; file_kind: string; content_type: string; data_url: string }>((resolve, reject) => {
        const reader = new FileReader(); reader.onerror = () => reject(new Error('Unable to read evidence.')); reader.onload = () => resolve({ name: file.name, file_name: file.name, file_kind: file.type.startsWith('image/') ? 'photo' : 'document', content_type: file.type, data_url: String(reader.result) }); reader.readAsDataURL(file);
      })));
      setEvidence(selected); setValidation('');
    } catch { setValidation('One or more evidence files could not be read.'); }
  };
  const start = async () => {
    if (!form.investigator_id) { setValidation('Assign an investigator before opening the case.'); return; }
    setValidation(''); await onAction('investigation/start', { investigator_id: form.investigator_id, priority: form.priority, note: form.note || undefined, evidence });
  };
  const save = async () => {
    setValidation(''); await onAction('investigation/update', { investigator_id: form.investigator_id, priority: form.priority, root_cause: form.root_cause || undefined, responsibility: form.responsibility || undefined, decision: form.decision || undefined, note: form.note || undefined, evidence, cost_impact: { affected_items: transfer.delivery_exception?.items || [], estimated_loss: Number(form.estimated_loss || 0), replacement_cost: Number(form.replacement_cost || 0), recovered_amount: Number(form.recovered_amount || 0), recovery_status: form.recovery_status } });
    setEvidence([]); setForm((current) => ({ ...current, note: '' }));
  };
  const history = new Map((investigation?.status_history || []).map((item) => [item.status, item]));
  const currentStage = investigation ? INVESTIGATION_STAGES.indexOf(investigation.status) : -1;
  const editable = Boolean(investigation && ['open', 'under_investigation'].includes(investigation.status));
  const allActionsComplete = Boolean(investigation?.linked_actions.every((action) => action.status === 'completed'));
  return <div className="mt-4 rounded-xl border border-indigo-200 bg-indigo-50/40 p-4">
    <h3 className="font-semibold text-indigo-950">Investigation &amp; Accountability</h3>
    <p className="mt-1 text-sm text-indigo-800">Investigation is separate from the resolved delivery operation and preserves the original records.</p>
    {!investigation ? <div className="mt-4 grid gap-3 sm:grid-cols-2">
      <Select label="Assign investigator" value={form.investigator_id} onChange={(investigator_id) => setForm({ ...form, investigator_id })} options={(transfer.investigation_users || []).map((item) => ({ value: item.id, label: `${item.full_name} · ${titleCase(item.role)}` }))} />
      <Select label="Priority" value={form.priority} onChange={(priority) => setForm({ ...form, priority })} options={choices(['low', 'medium', 'high', 'critical'])} />
      <div className="sm:col-span-2"><Textarea label="Opening notes" value={form.note} onChange={(note) => setForm({ ...form, note })} /></div>
      <EvidenceInput label="Photos/documents" onChange={loadEvidence} />
      <div className="sm:col-span-2"><Button busy={busy} onClick={start}>Open Investigation</Button></div>
    </div> : <div className="mt-4 space-y-4">
      <section className="rounded-lg border bg-white p-3"><h4 className="font-medium">Investigation Summary</h4><div className="mt-2 grid gap-2 text-sm sm:grid-cols-3"><p><b>Case:</b> {investigation.investigation_number}</p><p><b>Status:</b> {titleCase(investigation.status)}</p><p><b>Priority:</b> {titleCase(investigation.priority)}</p><p className="sm:col-span-3"><b>Investigator:</b> {investigation.investigator_name}</p></div></section>
      <section className="rounded-lg border bg-white p-3"><h4 className="font-medium">Timeline</h4><div className="mt-3 grid gap-2 sm:grid-cols-2">{INVESTIGATION_STAGES.map((stage, index) => { const entry = history.get(stage); const complete = index <= currentStage; return <div key={stage} className="flex items-start gap-2 text-sm">{complete ? <CheckCircle2 className="mt-0.5 h-4 w-4 text-emerald-600" /> : <Circle className="mt-0.5 h-4 w-4 text-slate-300" />}<div><p className={complete ? 'font-medium' : 'text-slate-400'}>{titleCase(stage)}</p>{entry && <p className="text-xs text-slate-500">{new Date(entry.timestamp).toLocaleString()}</p>}</div></div>; })}</div></section>
      {editable && <section className="grid gap-3 rounded-lg border bg-white p-3 sm:grid-cols-2"><h4 className="sm:col-span-2 font-medium">Evidence &amp; Findings</h4><Select label="Investigator" value={form.investigator_id} onChange={(investigator_id) => setForm({ ...form, investigator_id })} options={(transfer.investigation_users || []).map((item) => ({ value: item.id, label: item.full_name }))} /><Select label="Priority" value={form.priority} onChange={(priority) => setForm({ ...form, priority })} options={choices(['low', 'medium', 'high', 'critical'])} /><Select label="Root Cause" value={form.root_cause} onChange={(root_cause) => setForm({ ...form, root_cause })} options={choices(ROOT_CAUSES)} /><Select label="Responsibility" value={form.responsibility} onChange={(responsibility) => setForm({ ...form, responsibility })} options={choices(RESPONSIBILITIES)} /><Select label="Decision" value={form.decision} onChange={(decision) => setForm({ ...form, decision })} options={choices(DECISIONS)} /><Textarea label="Add note" value={form.note} onChange={(note) => setForm({ ...form, note })} /><Input label="Estimated Loss" type="number" value={form.estimated_loss} onChange={(estimated_loss) => setForm({ ...form, estimated_loss })} min="0" /><Input label="Replacement Cost" type="number" value={form.replacement_cost} onChange={(replacement_cost) => setForm({ ...form, replacement_cost })} min="0" /><Input label="Recovered Amount" type="number" value={form.recovered_amount} onChange={(recovered_amount) => setForm({ ...form, recovered_amount })} min="0" /><Select label="Recovery Status" value={form.recovery_status} onChange={(recovery_status) => setForm({ ...form, recovery_status })} options={choices(['not_started', 'in_progress', 'recovered', 'written_off', 'not_recoverable'])} /><EvidenceInput label="Add evidence" onChange={loadEvidence} /><div className="sm:col-span-2"><Button busy={busy} onClick={save}>Save Findings</Button></div></section>}
      <section className="grid gap-3 rounded-lg border bg-white p-3 text-sm sm:grid-cols-3"><Finding label="Root Cause" value={investigation.root_cause} /><Finding label="Responsibility" value={investigation.responsibility} /><Finding label="Decision" value={investigation.decision} /></section>
      <CostImpactSummary cost={investigation.cost_impact} />
      <section className="rounded-lg border bg-white p-3"><h4 className="font-medium">Evidence</h4>{investigation.evidence.length ? <ul className="mt-2 space-y-1 text-sm">{investigation.evidence.map((item, index) => <li key={item.evidence_id || index}><a className="text-blue-700 underline" href={item.data_url} target="_blank" rel="noreferrer">{item.name || item.file_name || `Evidence ${index + 1}`}</a> · {titleCase(item.file_kind || 'document')}</li>)}</ul> : <p className="mt-1 text-sm text-slate-500">No evidence attached.</p>}<h4 className="mt-3 font-medium">Notes</h4>{investigation.notes.length ? <ul className="mt-2 space-y-2 text-sm">{investigation.notes.map((item) => <li key={item.note_id} className="rounded bg-slate-50 p-2">{item.text}<span className="ml-2 text-xs text-slate-400">{new Date(item.created_at).toLocaleString()}</span></li>)}</ul> : <p className="mt-1 text-sm text-slate-500">No notes recorded.</p>}</section>
      <section className="rounded-lg border bg-white p-3"><h4 className="font-medium">Linked Actions</h4>{investigation.linked_actions.length ? <div className="mt-2 space-y-2">{investigation.linked_actions.map((action) => <div key={action.id} className="flex flex-wrap items-center justify-between gap-2 rounded border p-2 text-sm"><span>{titleCase(action.action_type)} · {titleCase(action.status)}</span>{investigation.status === 'actions_in_progress' && action.status === 'pending' && <Button busy={busy} onClick={() => onAction(`investigation-action/${action.id}/complete`)}>Complete Action</Button>}</div>)}</div> : <p className="mt-1 text-sm text-slate-500">{investigation.decision === 'no_action' ? 'No linked action is required.' : 'Linked actions are generated after approval.'}</p>}</section>
      <section className="rounded-lg border bg-white p-3"><h4 className="font-medium">Approvals</h4>{investigation.approval ? <div className="mt-1 text-sm"><p>Approved by {investigation.approval.approved_by} on {new Date(investigation.approval.approved_on || investigation.approval.approved_at).toLocaleString()}{investigation.suspected_theft_confirmed ? ' · Suspected Theft explicitly confirmed' : ''}</p>{investigation.approval.approval_comments && <p className="mt-1 text-slate-600">{investigation.approval.approval_comments}</p>}</div> : <p className="mt-1 text-sm text-slate-500">Awaiting management approval.</p>}{investigation.status === 'awaiting_approval' && sessionUser?.role === 'owner' && <div className="mt-3 space-y-3">{investigation.root_cause === 'suspected_theft' && <label className="flex gap-2 text-sm"><input type="checkbox" checked={confirmTheft} onChange={(event) => setConfirmTheft(event.target.checked)} />Explicitly confirm Suspected Theft</label>}<Textarea label="Approval comments" value={approvalComments} onChange={setApprovalComments} /><Button busy={busy} onClick={() => onAction('investigation/approved', { confirm_suspected_theft: confirmTheft, approval_comments: approvalComments || undefined })}>Approve Decision</Button></div>}</section>
      <section className="rounded-lg border bg-white p-3"><h4 className="font-medium">Close Case</h4><div className="mt-3 flex flex-wrap gap-2">{investigation.status === 'open' && <Button busy={busy} onClick={() => onAction('investigation/under_investigation')}>Begin Investigation</Button>}{investigation.status === 'under_investigation' && <Button busy={busy} onClick={() => onAction('investigation/awaiting_approval')}>Submit for Approval</Button>}{investigation.status === 'approved' && <Button busy={busy} onClick={() => onAction('investigation/actions_in_progress')}>Start Approved Actions</Button>}{investigation.status === 'actions_in_progress' && <button type="button" disabled={busy || !allActionsComplete} onClick={() => void onAction('investigation/closed')} className="rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-50">Close Case</button>}{investigation.status === 'closed' && <span className="rounded-full bg-emerald-100 px-3 py-1 text-sm font-medium text-emerald-800">Case Closed</span>}</div>{investigation.status === 'actions_in_progress' && !allActionsComplete && <p className="mt-2 text-sm text-amber-700">Complete all linked actions before closing the case.</p>}</section>
      {investigation.closure_summary && <ClosureSummary summary={investigation.closure_summary} />}
    </div>}
    {validation && <p className="mt-3 text-sm text-red-600">{validation}</p>}
  </div>;
}

function EvidenceInput({ label, onChange }: { label: string; onChange: (files: FileList | null) => void | Promise<void> }) { return <label className="text-sm text-slate-700 sm:col-span-2">{label}<input type="file" accept="image/jpeg,image/png,image/webp,application/pdf" multiple onChange={(event) => void onChange(event.target.files)} className="mt-1 block w-full rounded-lg border bg-white px-3 py-2" /></label>; }
function Finding({ label, value }: { label: string; value?: string | null }) { return <div><h4 className="font-medium">{label}</h4><p className="mt-1">{value ? titleCase(value) : 'Pending'}</p></div>; }
function CostImpactSummary({ cost }: { cost?: InvestigationCostImpact | null }) {
  return <section className="rounded-lg border bg-white p-3"><h4 className="font-medium">Cost Impact</h4><div className="mt-2 grid gap-2 text-sm sm:grid-cols-3"><p><b>Affected Items:</b> {cost?.affected_items?.length || 0}</p><p><b>Estimated Loss:</b> {formatCurrency(cost?.estimated_loss)}</p><p><b>Replacement Cost:</b> {formatCurrency(cost?.replacement_cost)}</p><p><b>Recovered Amount:</b> {formatCurrency(cost?.recovered_amount)}</p><p><b>Outstanding Amount:</b> {formatCurrency(cost?.outstanding_amount)}</p><p><b>Recovery Status:</b> {cost?.recovery_status ? titleCase(cost.recovery_status) : 'Not Started'}</p></div></section>;
}
function ClosureSummary({ summary }: { summary?: CaseClosureSummary | null }) {
  if (!summary) return null;
  return <section className="rounded-lg border border-emerald-200 bg-white p-3"><h4 className="font-medium">Case Closure Summary</h4><div className="mt-2 grid gap-2 text-sm sm:grid-cols-3"><p><b>Status:</b> {titleCase(summary.status || 'unknown')}</p><p><b>Exception Status:</b> {titleCase(summary.exception_status || 'unknown')}</p><p><b>Replacement Status:</b> {summary.replacement_status ? titleCase(summary.replacement_status) : 'None'}</p><p><b>Investigation Status:</b> {titleCase(summary.investigation_status || 'closed')}</p><p><b>Root Cause:</b> {summary.root_cause ? titleCase(summary.root_cause) : 'Pending'}</p><p><b>Responsibility:</b> {summary.responsibility ? titleCase(summary.responsibility) : 'Pending'}</p><p><b>Decision:</b> {summary.decision ? titleCase(summary.decision) : 'Pending'}</p><p><b>Linked Actions:</b> {summary.linked_actions?.length || 0}</p><p><b>Approved By:</b> {summary.approved_by || 'Pending'}</p><p><b>Closed By:</b> {summary.closed_by || 'Pending'}</p><p><b>Closed On:</b> {summary.closed_on ? new Date(summary.closed_on).toLocaleString() : 'Pending'}</p></div><CostImpactSummary cost={summary.cost_impact} /></section>;
}

function CreateTransferPanel({ busy, onCancel, onCreated, onError, setBusy }: {
  busy: boolean;
  onCancel: () => void;
  onCreated: (record: StockTransfer) => void;
  onError: (message: string) => void;
  setBusy: (value: string) => void;
}) {
  const idempotencyKey = useRef(globalThis.crypto?.randomUUID?.() || `stock-transfer-${Date.now()}-${Math.random().toString(36).slice(2)}`);
  const [form, setForm] = useState(emptyForm);
  const [items, setItems] = useState<StockTransferItem[]>([]);
  const [entry, setEntry] = useState<StockTransferItem>(emptyItem);
  const [search, setSearch] = useState('');
  const [searching, setSearching] = useState(false);
  const [products, setProducts] = useState<WaybillProduct[]>([]);
  const [validation, setValidation] = useState('');
  const [receiverType, setReceiverType] = useState<'fleetops_user' | 'external'>('fleetops_user');
  const [selectedRecipientId, setSelectedRecipientId] = useState('');
  const [branches, setBranches] = useState<StockTransferRecipientBranch[]>([]);
  const [receivers, setReceivers] = useState<StockTransferRecipientOption[]>([]);
  const [recipientOptionsBusy, setRecipientOptionsBusy] = useState(true);
  const totals = useMemo(() => ({
    items: items.length,
    quantity: items.reduce((sum, item) => sum + (Number(item.quantity) || 0), 0),
  }), [items]);

  useEffect(() => {
    let active = true;
    onError('');
    fetchStockTransferRecipientOptions().then((result) => {
      if (active) {
        setBranches(result.branches);
        onError('');
      }
    }).catch((value) => onError(message(value))).finally(() => {
      if (active) setRecipientOptionsBusy(false);
    });
    return () => { active = false; };
  }, []);

  const selectReceivingBranch = async (branchId: string) => {
    const branch = branches.find((item) => item.id === branchId);
    setForm((current) => ({ ...current, receiving_location_id: branchId, receiving_location: branch?.name || '', recipient: { ...emptyRecipient(), delivery_instructions: current.recipient.delivery_instructions } }));
    setSelectedRecipientId('');
    setReceivers([]);
    setValidation('');
    if (!branchId) return;
    setRecipientOptionsBusy(true);
    try {
      const result = await fetchStockTransferRecipientOptions(branchId);
      setReceivers(result.receivers);
      onError('');
    } catch (value) {
      onError(message(value));
    } finally {
      setRecipientOptionsBusy(false);
    }
  };

  const selectRecipient = (recipientId: string) => {
    const recipient = receivers.find((item) => item.id === recipientId);
    setSelectedRecipientId(recipientId);
    if (!recipient) return;
    setForm((current) => ({ ...current, recipient: {
      recipient_user_id: recipient.id, recipient_type: 'fleetops_user', full_name: recipient.full_name,
      role: recipient.role_name, primary_phone: recipient.primary_phone, secondary_phone: recipient.secondary_phone,
      email: recipient.email, branch_id: recipient.branch_id, branch_name: recipient.branch_name,
      delivery_instructions: current.recipient.delivery_instructions,
    } }));
    setValidation('');
  };

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
    setEntry({ item_id: product.item_id, name: product.name, quantity: entry.quantity || 1, unit: product.unit || 'unit' });
    setSearch(product.name);
    setProducts([]);
    setValidation('');
  };

  const addItem = () => {
    const name = entry.name.trim();
    const quantity = Number(entry.quantity);
    if (!name || !Number.isFinite(quantity) || quantity <= 0) {
      setValidation('Item name and an expected quantity greater than zero are required.');
      return;
    }
    if (items.some((item) => item.name.trim().toLowerCase() === name.toLowerCase())) {
      setValidation(`${name} is already in this transfer.`);
      return;
    }
    setItems((current) => [...current, { ...entry, item_id: entry.item_id.trim() || name, name, quantity, unit: entry.unit || 'unit' }]);
    setEntry(emptyItem());
    setSearch('');
    setValidation('');
  };

  const editItem = (index: number, field: 'name' | 'quantity', value: string) => {
    if (field === 'name') {
      const duplicate = items.some((item, itemIndex) => itemIndex !== index && item.name.trim().toLowerCase() === value.trim().toLowerCase());
      if (duplicate) {
        setValidation(`${value.trim()} is already in this transfer.`);
        return;
      }
    }
    setValidation('');
    setItems((current) => current.map((item, itemIndex) => itemIndex === index
      ? { ...item, [field]: field === 'quantity' ? Number(value) : value }
      : item));
  };

  const save = async (submitForApproval: boolean) => {
    const sending = form.sending_location.trim();
    const receiving = form.receiving_location.trim();
    if (!sending || !receiving || !form.receiving_location_id || !form.requested_date) {
      setValidation('Sending location, receiving location, and requested date are required.');
      return;
    }
    if (receiverType === 'fleetops_user' && !selectedRecipientId) {
      setValidation('Select an eligible FleetOps receiver for the receiving branch.');
      return;
    }
    if (receiverType === 'external' && (!form.recipient.full_name.trim() || !form.recipient.primary_phone.trim())) {
      setValidation('Recipient full name and primary phone are required.');
      return;
    }
    if (sending.toLowerCase() === receiving.toLowerCase()) {
      setValidation('Sending and receiving locations must be different.');
      return;
    }
    if (!items.length) {
      setValidation('Add at least one item before saving the transfer.');
      return;
    }
    if (items.some((item) => !item.name.trim() || !Number.isFinite(Number(item.quantity)) || Number(item.quantity) <= 0)) {
      setValidation('Every item requires an item name and expected quantity greater than zero.');
      return;
    }
    setBusy('create');
    onError('');
    setValidation('');
    try {
      const record = await createStockTransfer({
        idempotency_key: idempotencyKey.current,
        sending_location: sending,
        receiving_location: receiving,
        receiving_location_id: form.receiving_location_id,
        requested_date: form.requested_date,
        purpose: form.purpose.trim() || undefined,
        notes: form.notes.trim() || undefined,
        recipient: {
          recipient_user_id: receiverType === 'fleetops_user' ? selectedRecipientId : null,
          recipient_type: receiverType,
          full_name: form.recipient.full_name.trim(),
          role: form.recipient.role?.trim() || undefined,
          primary_phone: form.recipient.primary_phone.trim(),
          secondary_phone: form.recipient.secondary_phone?.trim() || undefined,
          email: form.recipient.email?.trim() || undefined,
          delivery_instructions: form.recipient.delivery_instructions?.trim() || undefined,
        },
        transfer_items: items.map((item) => ({
          item_id: item.item_id.trim() || item.name.trim(),
          name: item.name.trim(),
          quantity: Number(item.quantity),
          unit: item.unit || 'unit',
        })),
        submit_for_approval: submitForApproval,
      });
      onCreated(record);
    } catch (value) {
      onError(message(value));
    } finally {
      setBusy('');
    }
  };

  return <section className="rounded-xl border bg-white shadow-sm">
    <div className="flex items-center justify-between border-b p-5">
      <div><h2 className="text-lg font-semibold text-slate-900">Create Stock Transfer</h2><p className="text-sm text-slate-500">Transfer number is generated automatically when saved.</p></div>
      <button type="button" onClick={onCancel} className="rounded-lg p-2 text-slate-500 hover:bg-slate-100" aria-label="Close creation form"><X className="h-5 w-5" /></button>
    </div>
    <div className="space-y-6 p-5">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Input label="Transfer number" value="Auto-generated on save" onChange={() => undefined} disabled />
        <Input label="Sending location" value={form.sending_location} onChange={(value) => setForm({ ...form, sending_location: value })} required />
        <div><label className="block text-sm text-slate-700">Receiving location <span className="text-red-500">*</span></label><SearchableSelect value={form.receiving_location_id} options={branches.map((branch) => ({ value: branch.id, label: branch.name, description: branch.code }))} onChange={(value) => void selectReceivingBranch(value)} placeholder={recipientOptionsBusy ? 'Loading branches...' : 'Select receiving branch'} searchPlaceholder="Search branches..." disabled={recipientOptionsBusy && !branches.length} triggerClassName="mt-1" /></div>
        <Input label="Requested date" type="date" value={form.requested_date} onChange={(value) => setForm({ ...form, requested_date: value })} required />
        <Input label="Purpose" value={form.purpose} onChange={(value) => setForm({ ...form, purpose: value })} />
        <Textarea label="Notes" value={form.notes} onChange={(value) => setForm({ ...form, notes: value })} />
      </div>

      <div className="rounded-xl border p-4">
        <h3 className="font-medium text-slate-900">Planned recipient</h3>
        <p className="mt-1 text-sm text-slate-500">This delivery contact remains separate from the final logged-in branch receiver.</p>
        <div className="mt-4 flex flex-wrap gap-2" role="group" aria-label="Receiver type">
          {([['fleetops_user', 'FleetOps User'], ['external', 'External Recipient']] as const).map(([value, label]) => <button key={value} type="button" onClick={() => { setReceiverType(value); setSelectedRecipientId(''); setForm((current) => ({ ...current, recipient: emptyRecipient() })); setValidation(''); }} className={`min-h-11 rounded-lg border px-4 py-2 text-sm font-medium ${receiverType === value ? 'border-blue-600 bg-blue-50 text-blue-700' : 'text-slate-700'}`}>{label}</button>)}
        </div>
        {receiverType === 'fleetops_user' ? <div className="mt-4 space-y-4">
          <div><label className="block text-sm text-slate-700">Receiver <span className="text-red-500">*</span></label><SearchableSelect value={selectedRecipientId} options={receivers.map((recipient) => ({ value: recipient.id, label: recipient.full_name, description: `${recipient.role_name} · ${recipient.primary_phone}`, keywords: [recipient.email || '', recipient.primary_phone] }))} onChange={selectRecipient} placeholder={!form.receiving_location_id ? 'Select receiving branch first' : recipientOptionsBusy ? 'Loading eligible receivers...' : 'Search eligible receiver'} searchPlaceholder="Search name, role, phone, or email..." emptyLabel="No eligible branch receivers found." disabled={!form.receiving_location_id || recipientOptionsBusy} triggerClassName="mt-1" /></div>
          {selectedRecipientId && <div className="grid gap-2 rounded-lg bg-slate-50 p-3 text-sm text-slate-700 sm:grid-cols-2 lg:grid-cols-3"><p><b>Name:</b> {form.recipient.full_name}</p><p><b>Role:</b> {form.recipient.role}</p><p><b>Branch:</b> {form.recipient.branch_name}</p><p><b>Phone:</b> {form.recipient.primary_phone}</p><p><b>Email:</b> {form.recipient.email || 'Not provided'}</p></div>}
        </div> : <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Input label="Recipient full name" value={form.recipient.full_name} onChange={(value) => setForm({ ...form, recipient: { ...form.recipient, full_name: value } })} required />
          <Input label="Role" value={form.recipient.role || ''} onChange={(value) => setForm({ ...form, recipient: { ...form.recipient, role: value } })} />
          <Input label="Primary phone" type="tel" value={form.recipient.primary_phone} onChange={(value) => setForm({ ...form, recipient: { ...form.recipient, primary_phone: value } })} required />
          <Input label="Secondary phone" type="tel" value={form.recipient.secondary_phone || ''} onChange={(value) => setForm({ ...form, recipient: { ...form.recipient, secondary_phone: value } })} />
          <Input label="Email" type="email" value={form.recipient.email || ''} onChange={(value) => setForm({ ...form, recipient: { ...form.recipient, email: value } })} />
        </div>}
        <div className="mt-4"><Textarea label="Delivery instructions" value={form.recipient.delivery_instructions || ''} onChange={(value) => setForm({ ...form, recipient: { ...form.recipient, delivery_instructions: value } })} /></div>
      </div>

      <div className="rounded-xl border bg-slate-50 p-4">
        <h3 className="font-medium text-slate-900">Add transfer items</h3>
        <div className="mt-3 grid gap-3 lg:grid-cols-[1.4fr_1.4fr_0.65fr_auto] lg:items-end">
          <div className="relative">
            <label className="block text-sm text-slate-700">Search product</label>
            <div className="mt-1 flex">
              <input value={search} onChange={(event) => setSearch(event.target.value)} onKeyDown={(event) => event.key === 'Enter' && void runSearch()} placeholder="Search by product name" className="w-full rounded-l-lg border border-r-0 border-slate-300 px-3 py-2.5" />
              <button type="button" onClick={() => void runSearch()} className="rounded-r-lg border border-slate-300 bg-white px-3" aria-label="Search products">{searching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}</button>
            </div>
            {products.length > 0 && <div className="absolute z-20 mt-1 max-h-52 w-full overflow-y-auto rounded-lg border bg-white p-1 shadow-lg">{products.map((product) => <button type="button" key={product.item_id} onClick={() => chooseProduct(product)} className="block w-full rounded px-3 py-2 text-left text-sm hover:bg-blue-50">{product.name}</button>)}</div>}
          </div>
          <Input label="Item name" value={entry.name} onChange={(value) => setEntry({ ...entry, name: value })} />
          <Input label="Expected quantity" type="number" value={String(entry.quantity)} onChange={(value) => setEntry({ ...entry, quantity: Number(value) })} min="0.001" />
          <Button busy={false} onClick={addItem}><Plus className="h-4 w-4" />Add Item</Button>
        </div>
      </div>

      {validation && <div className="flex gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800"><AlertCircle className="h-4 w-4 shrink-0" />{validation}</div>}

      <div className="overflow-x-auto rounded-xl border">
        <table className="w-full min-w-[720px] text-sm">
          <thead className="bg-slate-50 text-left text-slate-600"><tr><th className="px-4 py-3">Item name</th><th className="px-4 py-3">Expected quantity</th><th className="w-20 px-4 py-3">Action</th></tr></thead>
          <tbody>{items.length ? items.map((item, index) => <tr key={`${item.item_id}-${index}`} className="border-t">
            <td className="p-3"><TableInput value={item.name} onChange={(value) => editItem(index, 'name', value)} /></td>
            <td className="p-3"><TableInput type="number" value={String(item.quantity)} onChange={(value) => editItem(index, 'quantity', value)} /></td>
            <td className="p-3"><button type="button" onClick={() => setItems((current) => current.filter((_, itemIndex) => itemIndex !== index))} className="rounded-lg p-2 text-red-600 hover:bg-red-50" aria-label={`Remove ${item.item_id}`}><Trash2 className="h-4 w-4" /></button></td>
          </tr>) : <tr><td colSpan={3} className="px-4 py-10 text-center text-slate-500">No items added yet. Search for a product or enter one manually.</td></tr>}</tbody>
          <tfoot className="border-t bg-slate-50 font-medium text-slate-700"><tr><td className="px-4 py-3">{totals.items} item{totals.items === 1 ? '' : 's'}</td><td className="px-4 py-3">Total quantity: {totals.quantity.toLocaleString()}</td><td /></tr></tfoot>
        </table>
      </div>

      <div className="flex flex-wrap justify-end gap-2 border-t pt-5">
        <button type="button" onClick={onCancel} className="rounded-lg border px-4 py-2 text-sm font-medium text-slate-700">Cancel</button>
        <button type="button" disabled={busy} onClick={() => void save(false)} className="rounded-lg border border-blue-600 px-4 py-2 text-sm font-medium text-blue-700 disabled:opacity-60">Save Draft</button>
        <Button busy={busy} onClick={() => save(true)}>Submit for Approval</Button>
      </div>
    </div>
  </section>;
}

function RecipientDetails({ recipient }: { recipient?: TransferRecipient | null }) {
  if (!recipient) return <div className="mt-4 rounded-lg border border-dashed p-3 text-sm text-slate-500">Recipient details were not captured for this legacy transfer.</div>;
  return <div className="mt-4 rounded-lg bg-slate-50 p-3 text-sm text-slate-700">
    <p className="font-medium text-slate-900">Planned receiver: {recipient.full_name}{recipient.role ? ` · ${recipient.role}` : ''}</p>
    <p className="mt-1">{recipient.primary_phone}{recipient.secondary_phone ? ` · ${recipient.secondary_phone}` : ''}{recipient.email ? ` · ${recipient.email}` : ''}</p>
    {recipient.delivery_instructions && <p className="mt-2 text-slate-600">Delivery instructions: {recipient.delivery_instructions}</p>}
  </div>;
}

function RecipientEditor({ transfer, busy, onCancel, onSave }: {
  transfer: StockTransfer;
  busy: boolean;
  onCancel: () => void;
  onSave: (recipient: TransferRecipient, reason: string) => void | Promise<void>;
}) {
  const [recipient, setRecipient] = useState<TransferRecipient>(transfer.recipient || emptyRecipient());
  const [reason, setReason] = useState('');
  const [validation, setValidation] = useState('');
  const reasonRequired = transfer.status === 'in_transit' || transfer.status === 'awaiting_receipt';
  const save = () => {
    if (!recipient.full_name.trim() || !recipient.primary_phone.trim()) {
      setValidation('Recipient full name and primary phone are required.');
      return;
    }
    if (reasonRequired && !reason.trim()) {
      setValidation('A reason is required after the journey has started.');
      return;
    }
    setValidation('');
    void onSave(recipient, reason.trim());
  };
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"><div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-xl bg-white p-5">
    <h2 className="font-semibold text-slate-900">Edit planned recipient</h2>
    <p className="mt-1 text-sm text-slate-500">Drivers can view these details but cannot edit them.</p>
    <div className="mt-4 grid gap-4 sm:grid-cols-2">
      <Input label="Recipient full name" value={recipient.full_name} onChange={(value) => setRecipient({ ...recipient, full_name: value })} required />
      <Input label="Role" value={recipient.role || ''} onChange={(value) => setRecipient({ ...recipient, role: value })} />
      <Input label="Primary phone" type="tel" value={recipient.primary_phone} onChange={(value) => setRecipient({ ...recipient, primary_phone: value })} required />
      <Input label="Secondary phone" type="tel" value={recipient.secondary_phone || ''} onChange={(value) => setRecipient({ ...recipient, secondary_phone: value })} />
      <Input label="Email" type="email" value={recipient.email || ''} onChange={(value) => setRecipient({ ...recipient, email: value })} />
      <Textarea label="Delivery instructions" value={recipient.delivery_instructions || ''} onChange={(value) => setRecipient({ ...recipient, delivery_instructions: value })} />
      {reasonRequired && <div className="sm:col-span-2"><Textarea label="Reason for change *" value={reason} onChange={setReason} /></div>}
    </div>
    {validation && <p className="mt-3 text-sm text-red-600">{validation}</p>}
    <div className="mt-5 flex justify-end gap-2"><button type="button" onClick={onCancel} className="rounded-lg border px-3 py-2 text-sm">Cancel</button><Button busy={busy} onClick={save}>Save Recipient</Button></div>
  </div></div>;
}

function ReceivingModal({ transfer, draft, setDraft, confirmed, setConfirmed, initials, setInitials, notes, setNotes, externalReceiver, setExternalReceiver, externalMode, busy, onCancel, onSave }: {
  transfer: StockTransfer; draft: ReceiptDraft; setDraft: (value: ReceiptDraft) => void; confirmed: boolean;
  setConfirmed: (value: boolean) => void; initials: string; setInitials: (value: string) => void;
  notes: string; setNotes: (value: string) => void;
  externalReceiver: { full_name: string; role: string; primary_contact: string };
  setExternalReceiver: (value: { full_name: string; role: string; primary_contact: string }) => void;
  externalMode: boolean;
  busy: boolean; onCancel: () => void; onSave: () => void | Promise<void>;
}) {
  const sessionUser = getStoredSessionUser();
  const receiverRole = sessionUser?.role_name || String(sessionUser?.selected_workspace || sessionUser?.role || '').replaceAll('_', ' ').replace(/\b\w/g, letter => letter.toUpperCase());
  const update = (id: string, field: keyof ReceiptDraft[string], value: string) => setDraft({ ...draft, [id]: { ...draft[id], [field]: value } });
  const receiveAll = () => setDraft(Object.fromEntries((transfer.transfer_items || []).map(item => [item.item_id, { received: String(item.quantity), good: String(item.quantity), damaged: '0', wrong: '0', notes: '' }])));
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-3"><div className="max-h-[94vh] w-full max-w-5xl overflow-y-auto rounded-xl bg-white p-4 sm:p-5">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><div className="flex items-center gap-2"><PackageCheck className="h-5 w-5 text-blue-600" /><h2 className="font-semibold">Confirm branch receipt</h2></div><p className="mt-1 text-sm text-slate-500">{transfer.transfer_id} · {transfer.sending_location} → {transfer.receiving_location}</p></div><button type="button" onClick={receiveAll} className="rounded-lg border border-blue-300 px-3 py-2 text-sm font-medium text-blue-700">Receive All as Sent</button></div>
    <div className="mt-4 overflow-x-auto"><table className="w-full min-w-[820px] text-sm"><thead className="bg-slate-50 text-left text-xs uppercase text-slate-500"><tr>{['Item','Sent','Expected','Received','Good','Damaged','Wrong item','Missing','Notes'].map(label => <th key={label} className="px-2 py-2">{label}</th>)}</tr></thead><tbody>{(transfer.transfer_items || []).map(item => { const row = draft[item.item_id] || { received: '', good: '', damaged: '0', wrong: '0', notes: '' }; const missing = Math.max(Number(item.quantity) - Number(row.received || 0), 0); return <tr key={item.item_id} className="border-t"><td className="px-2 py-2 font-medium">{item.name}<span className="block text-xs font-normal text-slate-500">{item.unit}</span></td><td className="px-2 py-2">{item.quantity}</td><td className="px-2 py-2">{item.quantity}</td>{(['received','good','damaged','wrong'] as const).map(field => <td key={field} className="px-2 py-2"><input type="number" min="0" step="any" value={row[field]} onChange={event => update(item.item_id, field, event.target.value)} className="w-20 rounded border px-2 py-1.5" /></td>)}<td className={`px-2 py-2 font-medium ${missing ? 'text-amber-700' : 'text-slate-600'}`}>{missing}</td><td className="px-2 py-2"><input value={row.notes} onChange={event => update(item.item_id, 'notes', event.target.value)} className="w-36 rounded border px-2 py-1.5" /></td></tr>; })}</tbody></table></div>
    <div className="mt-4 rounded-lg bg-slate-50 p-3">
      <p className="text-sm font-medium text-slate-900">Actual receiver</p>
      {externalMode ? <div className="mt-3 grid gap-3 sm:grid-cols-3"><Input label="Receiver name" value={externalReceiver.full_name} onChange={value => setExternalReceiver({ ...externalReceiver, full_name: value })} required /><Input label="Role" value={externalReceiver.role} onChange={value => setExternalReceiver({ ...externalReceiver, role: value })} /><Input label="Contact" value={externalReceiver.primary_contact} onChange={value => setExternalReceiver({ ...externalReceiver, primary_contact: value })} required /></div> : <div className="mt-2 grid gap-2 text-sm text-slate-700 sm:grid-cols-2 lg:grid-cols-4"><p><b>Name:</b> {sessionUser?.full_name || 'Current user'}</p><p><b>Role:</b> {receiverRole}</p><p><b>Contact:</b> {sessionUser?.phone || sessionUser?.email || 'Not provided'}</p><p><b>Branch:</b> {sessionUser?.branch || transfer.receiving_location}</p></div>}
      <div className="mt-3 grid gap-3 sm:grid-cols-2"><Input label="Receiver initials (optional)" value={initials} onChange={setInitials} /><Textarea label="Receipt notes" value={notes} onChange={setNotes} /></div>
      <label className="mt-3 flex items-center gap-2 rounded-lg border bg-white px-3 py-2.5 text-sm"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />I confirm these quantities and conditions are final.</label>
    </div>
    <p className="mt-3 text-xs text-slate-500">Quantity or condition differences will remain open as a delivery exception.</p>
    <div className="mt-5 flex justify-end gap-2"><button type="button" onClick={onCancel} className="rounded-lg border px-3 py-2 text-sm">Cancel</button><button type="button" disabled={busy || !confirmed || (externalMode && (!externalReceiver.full_name.trim() || !externalReceiver.primary_contact.trim()))} onClick={() => void onSave()} className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-50">{busy && <Loader2 className="h-4 w-4 animate-spin" />}Confirm Receipt</button></div>
  </div></div>;
}

function QuantityModal({ title, action, transfer, quantities, setQuantities, busy, backendError, onCancel, onSave, icon }: {
  title: string;
  action: string;
  transfer: StockTransfer;
  quantities: Record<string, string>;
  setQuantities: (value: Record<string, string>) => void;
  busy: boolean;
  backendError?: string;
  onCancel: () => void;
  onSave: () => void | Promise<void>;
  icon?: ReactNode;
}) {
  const [attempted, setAttempted] = useState(false);
  const submitLock = useRef(false);
  const validation = Object.fromEntries((transfer.transfer_items || []).map(item => {
    const raw = quantities[item.item_id]; const numeric = Number(raw);
    const error = raw === undefined || raw.trim() === '' ? 'Enter the actual loaded quantity.' : !Number.isFinite(numeric) ? 'Enter a valid number.' : numeric < 0 ? 'Quantity cannot be negative.' : '';
    return [item.item_id, error];
  }));
  const hasErrors = Object.values(validation).some(Boolean);
  const confirmAll = () => { setQuantities(Object.fromEntries((transfer.transfer_items || []).map(item => [item.item_id, String(item.quantity)]))); setAttempted(false); };
  const submit = async () => { setAttempted(true); if (hasErrors || busy || submitLock.current) return; submitLock.current = true; try { await onSave(); } finally { submitLock.current = false; } };
  return <div className="fixed inset-0 z-50 flex items-stretch justify-center bg-black/50 p-0 sm:items-center sm:p-4">
    <div role="dialog" aria-modal="true" aria-labelledby="confirm-loading-title" className="flex h-[100dvh] max-h-[100dvh] w-full flex-col overflow-hidden bg-white shadow-xl sm:h-auto sm:max-h-[85vh] sm:max-w-lg sm:rounded-xl">
      <header className="sticky top-0 z-10 flex shrink-0 items-start justify-between gap-3 border-b bg-white px-4 py-4 sm:px-5">
        <div><div className="flex items-center gap-2">{icon}<h2 id="confirm-loading-title" className="font-semibold">{title}</h2></div><p className="mt-1 text-xs text-slate-500">{transfer.transfer_id} · {transfer.transfer_items?.length || 0} item(s)</p></div>
        <button type="button" disabled={busy} onClick={confirmAll} className="min-h-11 rounded-lg border border-blue-300 px-3 py-2 text-sm font-medium text-blue-700 disabled:opacity-50">Confirm All as Expected</button>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-3 sm:px-5">
        <div className="space-y-2">{(transfer.transfer_items || []).map(item => { const itemError = validation[item.item_id]; return <label key={item.item_id} className="block rounded-lg border border-slate-200 p-3"><span className="block text-sm font-medium text-slate-900">{item.name}</span><span className="mt-0.5 block text-xs text-slate-500">Expected: {item.quantity} {item.unit}</span><span className="mt-2 block text-xs font-medium text-slate-700">Actual Loaded</span><input type="number" min="0" step="any" inputMode="decimal" value={quantities[item.item_id] ?? ''} disabled={busy} onChange={event => setQuantities({ ...quantities, [item.item_id]: event.target.value })} aria-invalid={attempted && Boolean(itemError)} aria-describedby={attempted && itemError ? `loading-error-${item.item_id}` : undefined} className={`mt-1 min-h-11 w-full rounded-lg border px-3 py-2 text-base outline-none focus:ring-2 focus:ring-blue-100 ${attempted && itemError ? 'border-red-400' : 'border-slate-300'}`} />{attempted && itemError && <span id={`loading-error-${item.item_id}`} className="mt-1 block text-xs text-red-600">{itemError}</span>}</label>; })}</div>
      </div>
      {backendError && <div role="alert" className="shrink-0 border-t border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700 sm:px-5">{backendError}</div>}
      <footer className="sticky bottom-0 z-10 grid shrink-0 grid-cols-2 gap-3 border-t bg-white px-4 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] sm:flex sm:justify-end sm:px-5">
        <button type="button" disabled={busy} onClick={onCancel} className="min-h-12 rounded-lg border px-4 py-3 text-sm font-medium text-slate-700 disabled:opacity-50 sm:min-w-28">Cancel</button>
        <button type="button" disabled={busy} onClick={() => void submit()} className="inline-flex min-h-12 items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-3 text-sm font-medium text-white disabled:opacity-60 sm:min-w-40">{busy && <Loader2 className="h-4 w-4 animate-spin" />}{action}</button>
      </footer>
    </div>
  </div>;
}

function Button({ children, onClick, busy }: { children: ReactNode; onClick: () => void | Promise<void>; busy: boolean }) {
  return <button type="button" onClick={() => void onClick()} disabled={busy} className="inline-flex items-center justify-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-60">{busy && <Loader2 className="h-4 w-4 animate-spin" />}{children}</button>;
}

function Input({ label, value, onChange, type = 'text', required = false, disabled = false, min }: { label: string; value: string; onChange: (value: string) => void; type?: string; required?: boolean; disabled?: boolean; min?: string }) {
  return <label className="block text-sm text-slate-700">{label}{required && <span className="text-red-500"> *</span>}<input type={type} min={min} value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2.5 disabled:bg-slate-100 disabled:text-slate-500" /></label>;
}

function Textarea({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return <label className="block text-sm text-slate-700">{label}<textarea rows={3} value={value} onChange={(event) => onChange(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2.5" /></label>;
}

function TableInput({ value, onChange, type = 'text' }: { value: string; onChange: (value: string) => void; type?: string }) {
  return <input type={type} min={type === 'number' ? '0.001' : undefined} step={type === 'number' ? 'any' : undefined} value={value} onChange={(event) => onChange(event.target.value)} className="w-full rounded-lg border border-slate-300 px-3 py-2" />;
}

function Select({ label, value, onChange, options }: { label: string; value: string; onChange: (value: string) => void; options: Array<{ value: string; label: string }> }) {
  return <label className="block text-sm text-slate-700">{label}<select value={value} onChange={(event) => onChange(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2.5"><option value="">Select</option>{options.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>;
}
