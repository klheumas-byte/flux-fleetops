import { apiRequest } from './api';

export interface StockTransferItem { item_id: string; name: string; quantity: number; unit: string; sent_quantity?: number; expected_quantity?: number; received_quantity?: number; good_quantity?: number; damaged_quantity?: number; wrong_item_quantity?: number; missing_quantity?: number; notes?: string | null }
export interface TransferRecipient {
  recipient_user_id?: string | null; recipient_type?: 'fleetops_user' | 'external'; branch_id?: string | null; branch_name?: string | null;
  full_name: string; role?: string | null; primary_phone: string; secondary_phone?: string | null;
  email?: string | null; delivery_instructions?: string | null;
}
export interface StockTransferRecipientBranch { id: string; name: string; code?: string | null }
export interface StockTransferRecipientOption {
  id: string; full_name: string; role: string; role_name: string; branch_id: string; branch_name: string;
  primary_phone: string; secondary_phone?: string | null; email?: string | null;
}
export interface StockTransferRecipientOptions { branches: StockTransferRecipientBranch[]; receivers: StockTransferRecipientOption[] }
export interface ActualReceiver {
  receiver_type?: 'fleetops_user' | 'external'; user_id?: string | null; branch_id?: string | null; branch_name?: string | null;
  full_name: string; primary_contact: string; role?: string | null; initials?: string | null;
  signature?: string | null; notes?: string | null; acknowledged?: boolean;
}
export interface DeliveryExceptionItem {
  item_id: string; name?: string | null; unit: string; expected_quantity: number; received_quantity: number;
  exception_quantity: number; exception_type: 'missing' | 'damaged' | 'wrong_item' | 'excess';
  variance: number; notes: string; photos: string[];
}
export interface DeliveryExceptionSummary {
  exception_number: string; status: string; affected_item_count: number; exception_types: string[]; reported_at: string; investigation_status?: string | null; closure_summary?: CaseClosureSummary | null;
}
export interface InvestigationEvidence { evidence_id?: string; name?: string; file_name?: string; file_kind?: 'photo' | 'document'; content_type?: string | null; data_url: string; uploaded_at?: string }
export interface InvestigationAction { id: string; action_type: string; status: 'pending' | 'completed'; decision: string; responsibility: string; completed_at?: string | null; completion_notes?: string | null }
export interface InvestigationCostImpact {
  affected_items: Array<Record<string, unknown>>; estimated_loss: number; replacement_cost: number; recovered_amount: number; outstanding_amount: number; recovery_status: string;
}
export interface CaseClosureSummary {
  status?: string | null; exception_status?: string | null; replacement_status?: string | null; investigation_status?: string | null;
  root_cause?: string | null; responsibility?: string | null; decision?: string | null; linked_actions?: Array<Record<string, unknown>>;
  cost_impact?: InvestigationCostImpact | null; approved_by?: string | null; approved_on?: string | null; approval_comments?: string | null; closed_by?: string | null; closed_on?: string | null;
}
export interface DeliveryExceptionInvestigation {
  id: string; investigation_number: string; status: 'open' | 'under_investigation' | 'awaiting_approval' | 'approved' | 'actions_in_progress' | 'closed'; priority: string;
  investigator_id: string; investigator_name: string; investigator_role: string; root_cause?: string | null; responsibility?: string | null; decision?: string | null;
  cost_impact?: InvestigationCostImpact | null; closure_summary?: CaseClosureSummary | null;
  suspected_theft_confirmed?: boolean; approval?: { approved_by: string; approved_on?: string; approved_at: string; actor_role: string; approval_comments?: string | null } | null;
  notes: Array<{ note_id: string; text: string; actor_id: string; actor_role: string; created_at: string }>;
  evidence: InvestigationEvidence[]; linked_actions: InvestigationAction[];
  status_history: Array<{ status: string; timestamp: string; actor_id: string }>;
  audit_log: Array<{ event: string; actor_id?: string; actor_name?: string | null; actor_role?: string; timestamp: string; details?: Record<string, unknown> }>;
}
export interface StockTransfer {
  id: string; transfer_id: string; operation_type?: 'stock_transfer' | 'supplier_pickup'; origin_type?: string; sending_location: string; receiving_location: string;
  supplier?: { supplier_name: string; contact_person: string; primary_phone: string; secondary_phone?: string | null; email?: string | null; pickup_address: string; pickup_instructions?: string | null } | null;
  supplier_reference?: string | null;
  status: string; workflow_stage: string; dispatch_status: string; receiving_status: string; reservation_status: string;
  approved_by?: string | null; approved_at?: string | null;
  vehicle_id?: string | null; driver_id?: string | null; scheduled_at?: string | null;
  vehicle?: { id: string; registration_number?: string | null; make?: string | null; model?: string | null } | null;
  driver?: { id: string; full_name?: string | null } | null;
  destination_branch_id?: string | null; dispatch_date?: string | null; expected_arrival?: string | null; total_quantity?: number;
  received_by_user_id?: string | null; receiver_name?: string | null; receiver_role?: string | null; receiving_branch_id?: string | null; received_at?: string | null;
  branch_receiving_status?: 'VERIFIED' | 'RECEIVED_WITH_VARIANCE' | null; receipt_confirmation?: Record<string, unknown> | null;
  requested_date?: string | null; purpose?: string | null; notes?: string | null;
  recipient?: TransferRecipient | null;
  actual_receiver?: ActualReceiver | null;
  linked_delivery_exception_id?: string | null; delivery_exception_status?: string | null;
  delivery_exception_summary?: DeliveryExceptionSummary | null;
  verified_at?: string | null; verified_by?: string | null;
  acknowledged_at?: string | null;
  acknowledged_by?: string | null; supplier_arrived_at?: string | null; supplier_arrived_by?: string | null;
  supplier_handover?: { supplier_representative: string; phone?: string | null; notes?: string | null; recorded_at?: string | null } | null;
  pickup_confirmation?: { items: Array<{ item_id: string; name: string; unit: string; requested_quantity: number; available_quantity: number; collected_quantity: number; shortfall_quantity: number; shortfall_reason?: string | null }>; confirmed_by: string; confirmed_at: string; immutable: boolean } | null;
  collected_quantities?: Array<{ item_id: string; quantity: number }>;
  supplier_shortfall_ids?: string[];
  loaded_quantities?: Array<{ item_id: string; quantity: number }>; released_at?: string | null;
  started_at?: string | null; started_by?: string | null; arrived_at?: string | null; arrived_by?: string | null;
  linked_assignment_id?: string | null; linked_vehicle_movement_id?: string | null; item_count: number;
  linked_waybill_id?: string | null;
  custody_history?: Array<{ event: string; from?: string | null; to?: string | null; location?: string | null; recorded_at?: string | null; immutable?: boolean }>;
  transfer_items?: StockTransferItem[]; received_items?: StockTransferItem[];
  quantity_variance?: Array<{ item_id: string; expected_quantity: number; received_quantity: number; difference: number }>;
  variance_review?: { resolution: string; notes?: string | null; reviewed_by: string; reviewed_at: string } | null;
  audit_log?: Array<{ event: string; actor_id?: string; actor_name?: string | null; actor_role?: string; timestamp: string; details?: Record<string, unknown> }>;
  original_stock_transfer_id?: string | null; source_delivery_exception_id?: string | null; replacement_request_id?: string | null; linked_replacement_transfer_id?: string | null; linked_replacement_status?: string | null;
  investigation_users?: Array<{ id: string; full_name: string; role: string }>;
  delivery_exception?: { id: string; exception_number: string; status: string; operational_status?: string | null; resolved_at?: string | null; investigation_status?: string | null; items: DeliveryExceptionItem[]; actual_receiver: ActualReceiver; notes?: string | null; driver_id?: string | null; receiver_acknowledgement?: Record<string, unknown>; current_action?: Record<string, unknown> | null; action_history?: Array<Record<string, unknown>>; return_request?: ExceptionReturnRequest | null; replacement_request?: ExceptionReplacementRequest | null; operations_timeline?: ExceptionTimelineItem[]; investigation?: DeliveryExceptionInvestigation | null };
}
export interface ExceptionTimelineItem { key: string; label: string; completed: boolean; timestamp?: string | null }
export interface ExceptionReturnRequest { id: string; return_number: string; status: string; driver_id: string; vehicle_id: string; linked_waybill_id: string; linked_vehicle_movement_id: string; items: DeliveryExceptionItem[] }
export interface ExceptionReplacementRequest { id: string; replacement_number: string; status: string; linked_stock_transfer_id: string; linked_waybill_id: string; linked_vehicle_movement_id: string; completed_at?: string | null }
export async function fetchStockTransfers(params: { operation_type?: 'stock_transfer' | 'supplier_pickup'; active_tasks?: boolean } = {}) {
  const search = new URLSearchParams();
  if (params.operation_type) search.set('operation_type', params.operation_type);
  if (params.active_tasks) search.set('active_tasks', 'true');
  const query = search.size ? `?${search}` : '';
  const result = await apiRequest<{ transfers: StockTransfer[] }>(`/stock-transfers${query}`, { componentName: 'StockTransfers', requestLabel: 'list', dedupeKey: `stock-transfers:list:${params.operation_type || 'all'}:${params.active_tasks ? 'active' : 'all'}` });
  return result.data.transfers;
}
export function fetchSupplierPickupTasks() {
  return fetchStockTransfers({ operation_type: 'supplier_pickup', active_tasks: true });
}
export async function fetchStockTransfer(id: string) {
  const result = await apiRequest<{ transfer: StockTransfer }>(`/stock-transfers/${id}`, { componentName: 'StockTransfers', requestLabel: 'detail' });
  return result.data.transfer;
}
export async function createStockTransfer(payload: Record<string, unknown>) {
  const result = await apiRequest<{ transfer: StockTransfer }>('/stock-transfers', { method: 'POST', body: JSON.stringify(payload), componentName: 'StockTransfers', requestLabel: 'create' });
  return result.data.transfer;
}
export async function fetchStockTransferRecipientOptions(branchId?: string) {
  const query = branchId ? `?branch_id=${encodeURIComponent(branchId)}` : '';
  const result = await apiRequest<StockTransferRecipientOptions>(`/stock-transfers/recipient-options${query}`, { componentName: 'StockTransfers', requestLabel: 'recipient-options', dedupeKey: `stock-transfers:recipient-options:${branchId || 'branches'}` });
  return result.data;
}
export async function mutateStockTransfer(id: string, action: string, payload: Record<string, unknown> = {}) {
  const result = await apiRequest<{ transfer: StockTransfer }>(`/stock-transfers/${id}/${action}`, { method: 'PATCH', body: JSON.stringify(payload), componentName: 'StockTransfers', requestLabel: action, replacePending: true, cancelGroup: `stock-transfer:${id}:${action}` });
  return result.data.transfer;
}
