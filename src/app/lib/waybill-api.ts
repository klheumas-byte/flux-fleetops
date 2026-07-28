import { apiRequest } from './api';

export type WaybillStatus = 'draft' | 'approved' | 'driver_confirmed' | 'loaded' | 'in_transit' | 'delivered' | 'verified' | 'completed';

export interface WaybillItem {
  item_id: string;
  sku: string;
  name: string;
  unit: string;
  expected_quantity: number;
  loaded_quantity?: number | null;
  received_quantity?: number | null;
  variance?: number | null;
  item_condition?: 'correct' | 'missing' | 'damaged' | 'wrong_item' | 'excess' | null;
  exception_quantity?: number | null;
  missing_quantity?: number | null;
  excess_quantity?: number | null;
  exception_status?: 'clear' | 'exception' | null;
  exception_notes?: string | null;
  exception_photos?: string[];
  notes?: string | null;
  serial_numbers?: string[];
  photos?: string[];
}

export interface Waybill {
  id: string;
  waybill_number: string;
  source_type: string;
  source_id: string;
  source_key: string;
  source_reference?: string | null;
  movement_id: string;
  vehicle_id?: string | null;
  driver_id?: string | null;
  scheduled_at?: string | null;
  origin?: string | null;
  destination?: string | null;
  recipient?: import('./stock-transfer-api').TransferRecipient | null;
  actual_receiver?: import('./stock-transfer-api').ActualReceiver | null;
  linked_delivery_exception_id?: string | null;
  delivery_exception_status?: string | null;
  delivery_exception_summary?: DeliveryExceptionSummary | null;
  locked_at?: string | null;
  receipt_pending?: boolean;
  status: WaybillStatus;
  items: WaybillItem[];
  item_count: number;
  has_variance: boolean;
  variance_review?: { resolution: string; notes?: string | null; reviewed_at: string } | null;
  confirmations: Array<Record<string, unknown>>;
  custody_events: Array<Record<string, unknown>>;
  signatures: Record<string, Record<string, unknown>>;
  audit_log?: Array<Record<string, unknown>>;
  notes?: string | null;
  created_at: string;
  updated_at: string;
}

export interface DeliveryExceptionSummary {
  exception_number: string;
  status: string;
  affected_item_count: number;
  exception_types: string[];
  reported_at: string;
  operational_status?: string | null;
}

export interface WaybillProduct { item_id: string; sku: string; name: string; unit: string }

export async function fetchWaybills() {
  const response = await apiRequest<{ waybills: Waybill[] }>('/waybills', {
    componentName: 'DigitalWaybills', requestLabel: 'list', dedupeKey: 'waybills:list',
  });
  return response.data.waybills;
}

export async function fetchWaybill(id: string) {
  const response = await apiRequest<{ waybill: Waybill }>(`/waybills/${id}`, {
    componentName: 'DigitalWaybills', requestLabel: 'detail',
  });
  return response.data.waybill;
}

export async function updateWaybillItems(id: string, items: WaybillItem[], notes?: string) {
  const response = await apiRequest<{ waybill: Waybill }>(`/waybills/${id}/items`, {
    method: 'PUT', body: JSON.stringify({ items, notes }), componentName: 'DigitalWaybills', requestLabel: 'items',
  });
  return response.data.waybill;
}

export async function transitionWaybill(id: string, status: WaybillStatus, payload: Record<string, unknown> = {}) {
  const response = await apiRequest<{ waybill: Waybill }>(`/waybills/${id}/transition/${status}`, {
    method: 'PATCH', body: JSON.stringify(payload), componentName: 'DigitalWaybills', requestLabel: status,
    replacePending: true, cancelGroup: `waybill:${id}:transition`,
  });
  return response.data.waybill;
}

export async function confirmWaybill(id: string, payload: Record<string, unknown> = {}) {
  const response = await apiRequest<{ waybill: Waybill }>(`/waybills/${id}/confirm`, {
    method: 'POST', body: JSON.stringify(payload), componentName: 'DigitalWaybills', requestLabel: 'confirm',
  });
  return response.data.waybill;
}

export async function reviewWaybillVariance(id: string, resolution: string, notes?: string) {
  const response = await apiRequest<{ waybill: Waybill }>(`/waybills/${id}/variance-review`, {
    method: 'PATCH', body: JSON.stringify({ resolution, notes }), componentName: 'DigitalWaybills', requestLabel: 'variance-review',
  });
  return response.data.waybill;
}

export async function saveWaybillSignature(id: string, party: 'sender' | 'receiver', signature: string, signedByName: string) {
  const response = await apiRequest<{ waybill: Waybill }>(`/waybills/${id}/signatures/${party}`, {
    method: 'POST', body: JSON.stringify({ signature, signed_by_name: signedByName }), componentName: 'DigitalWaybills', requestLabel: `${party}-signature`,
  });
  return response.data.waybill;
}

export async function searchWaybillProducts(query: string) {
  const response = await apiRequest<{ products: WaybillProduct[] }>(`/waybills/products?q=${encodeURIComponent(query)}`, {
    componentName: 'DigitalWaybills', requestLabel: 'product-search', dedupeKey: `waybill-products:${query}`,
  });
  return response.data.products;
}
