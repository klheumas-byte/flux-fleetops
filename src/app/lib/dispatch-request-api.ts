import { ApiRequestError, apiRequest } from './api';

export type DispatchRequestStatus =
  | 'new'
  | 'reviewing'
  | 'pricing_pending'
  | 'approved'
  | 'rejected'
  | 'converted'
  | 'cancelled';

export type DispatchRequestType = string;
export type DispatchLoadType = string;
export type DispatchLoadWeightCategory = string;
export type DispatchLoadSizeCategory = string;
export type DispatchUrgency = string;
export type DispatchPaymentStatus = string;
export type DispatchVehicleTypeNeeded = string;
export type DispatchPricingStatus =
  | 'pricing_pending'
  | 'pricing_approved'
  | 'pricing_rejected'
  | 'pricing_revised';
export type DispatchScheduleType = 'immediate' | 'scheduled' | 'recurring';
export type DispatchRecurrencePattern = 'custom' | 'daily' | 'monthly' | 'weekly' | 'weekdays';
export type DispatchStopType = 'pickup' | 'dropoff' | 'checkpoint';
export type DispatchStopStatus = 'pending' | 'ready' | 'completed' | 'skipped' | 'cancelled';

export interface DispatchUserSummary {
  id: string;
  full_name: string;
  phone?: string | null;
  email?: string | null;
  role?: string | null;
  status?: string | null;
}

export interface DispatchRequestRecord {
  id: string;
  request_id: string;
  request_type: DispatchRequestType;
  customer_name: string;
  customer_phone: string;
  customer_company?: string | null;
  pickup_location: string;
  destination: string;
  vehicle_type_needed: DispatchVehicleTypeNeeded;
  load_type?: DispatchLoadType | null;
  load_weight_category?: DispatchLoadWeightCategory | null;
  load_size_category?: DispatchLoadSizeCategory | null;
  load_description?: string | null;
  preferred_pickup_date: string;
  preferred_pickup_time: string;
  expected_delivery_time?: string | null;
  urgency?: DispatchUrgency | null;
  proposed_charge: number;
  approved_charge?: number | null;
  pricing_status?: DispatchPricingStatus | null;
  pricing_notes?: string | null;
  distance_estimate_km?: number | null;
  fuel_estimate_amount?: number | null;
  fuel_estimate_cost?: number | null;
  other_expected_costs?: number | null;
  expected_net_revenue?: number | null;
  payment_status: DispatchPaymentStatus;
  schedule_type?: DispatchScheduleType | null;
  scheduled_start_time?: string | null;
  scheduled_end_time?: string | null;
  expected_return_time?: string | null;
  recurrence_pattern?: DispatchRecurrencePattern | null;
  recurrence_end_date?: string | null;
  schedule_notes?: string | null;
  stops?: DispatchRequestStopRecord[];
  stops_count?: number;
  pricing_history?: DispatchPricingHistoryEntry[];
  notes?: string | null;
  status: DispatchRequestStatus;
  rejection_reason?: string | null;
  cancellation_reason?: string | null;
  created_by?: string | null;
  reviewed_by?: string | null;
  approved_by?: string | null;
  rejected_by?: string | null;
  cancelled_by?: string | null;
  pricing_reviewed_by?: string | null;
  reviewed_at?: string | null;
  approved_at?: string | null;
  rejected_at?: string | null;
  cancelled_at?: string | null;
  pricing_reviewed_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  created_by_user?: DispatchUserSummary | null;
  reviewed_by_user?: DispatchUserSummary | null;
  approved_by_user?: DispatchUserSummary | null;
  rejected_by_user?: DispatchUserSummary | null;
  cancelled_by_user?: DispatchUserSummary | null;
  pricing_reviewed_by_user?: DispatchUserSummary | null;
}

export interface DispatchRequestStopRecord {
  stop_id: string;
  stop_sequence: number;
  stop_type: DispatchStopType;
  linked_movement_id?: string | null;
  location: string;
  contact_name?: string | null;
  contact_phone?: string | null;
  load_note?: string | null;
  planned_arrival_time?: string | null;
  planned_departure_time?: string | null;
  stop_charge?: number | null;
  stop_status?: DispatchStopStatus | null;
  delivery_status?: 'pending' | 'delivered' | null;
  delivered_at?: string | null;
  delivery_note?: string | null;
  delivered_by?: string | null;
}

export interface DispatchPricingHistoryEntry {
  id: string;
  action: string;
  actor_id?: string | null;
  acted_at?: string | null;
  pricing_status?: DispatchPricingStatus | null;
  proposed_charge?: number | null;
  approved_charge?: number | null;
  distance_estimate_km?: number | null;
  fuel_estimate_amount?: number | null;
  fuel_estimate_cost?: number | null;
  other_expected_costs?: number | null;
  expected_net_revenue?: number | null;
  pricing_notes?: string | null;
}

export interface DispatchRequestOptionsResponse {
  request_types: DispatchRequestType[];
  pickup_locations: string[];
  vehicle_types: DispatchVehicleTypeNeeded[];
  load_types: DispatchLoadType[];
  load_weight_categories: DispatchLoadWeightCategory[];
  load_size_categories: DispatchLoadSizeCategory[];
  urgencies: DispatchUrgency[];
  payment_statuses: DispatchPaymentStatus[];
  statuses: DispatchRequestStatus[];
  editable_statuses: DispatchRequestStatus[];
  pricing_statuses: DispatchPricingStatus[];
  schedule_types: DispatchScheduleType[];
  recurrence_patterns: DispatchRecurrencePattern[];
  stop_types: DispatchStopType[];
  stop_statuses: DispatchStopStatus[];
}

export interface DispatchRequestListResponse {
  requests: DispatchRequestRecord[];
  pagination: {
    page: number;
    page_size: number;
    total: number;
    total_pages: number;
  };
  filters: {
    q?: string | null;
    status?: string | null;
    vehicle_type_needed?: string | null;
    date_from?: string | null;
    date_to?: string | null;
  };
  generated_at?: string | null;
  duration_ms?: number | null;
}

interface DispatchRequestOptionsEnvelope {
  success: boolean;
  data: DispatchRequestOptionsResponse;
}

interface DispatchRequestListEnvelope {
  success: boolean;
  data: DispatchRequestListResponse;
}

interface DispatchRequestEnvelope {
  success: boolean;
  data: {
    request: DispatchRequestRecord;
  };
}

export async function fetchDispatchRequestOptions() {
  const response = await apiRequest<DispatchRequestOptionsEnvelope>('/dispatch-requests/options', {
    cacheTtlMs: 15000,
    dedupeKey: 'dispatch-requests-options',
    componentName: 'DispatchRequests',
    requestLabel: 'options',
  });
  return {
    ...response.data,
    pricing_statuses:
      response.data?.pricing_statuses?.length
        ? response.data.pricing_statuses
        : ['pricing_pending', 'pricing_approved', 'pricing_rejected', 'pricing_revised'],
    schedule_types:
      response.data?.schedule_types?.length
        ? response.data.schedule_types
        : ['immediate', 'scheduled', 'recurring'],
  };
}

export async function fetchDispatchRequests(params: {
  page?: number;
  page_size?: number;
  q?: string;
  status?: string;
  vehicle_type_needed?: string;
  date_from?: string;
  date_to?: string;
} = {}) {
  const searchParams = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && String(value).trim() !== '') {
      searchParams.set(key, String(value));
    }
  });
  const query = searchParams.toString();
  const response = await apiRequest<DispatchRequestListEnvelope>(`/dispatch-requests${query ? `?${query}` : ''}`, {
    cacheTtlMs: 5000,
    dedupeKey: `dispatch-requests-list:${query || 'default'}`,
    componentName: 'DispatchRequests',
    requestLabel: 'list',
    cancelGroup: 'dispatch-requests-list',
    replacePending: true,
  });
  return response.data;
}

export async function fetchDispatchRequestById(requestId: string) {
  const response = await apiRequest<DispatchRequestEnvelope>(`/dispatch-requests/${requestId}`, {
    cacheTtlMs: 5000,
    dedupeKey: `dispatch-request-detail:${requestId}`,
    componentName: 'DispatchRequests',
    requestLabel: 'detail',
  });
  return response.data.request;
}

export async function createDispatchRequest(payload: Record<string, unknown>) {
  const response = await apiRequest<DispatchRequestEnvelope>('/dispatch-requests', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return response.data.request;
}

export async function updateDispatchRequest(requestId: string, payload: Record<string, unknown>) {
  const response = await apiRequest<DispatchRequestEnvelope>(`/dispatch-requests/${requestId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
  return response.data.request;
}

export async function approveDispatchRequest(requestId: string, payload: Record<string, unknown>) {
  const response = await apiRequest<DispatchRequestEnvelope>(`/dispatch-requests/${requestId}/approve`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
  return response.data.request;
}

export async function rejectDispatchRequest(requestId: string, payload: Record<string, unknown>) {
  const response = await apiRequest<DispatchRequestEnvelope>(`/dispatch-requests/${requestId}/reject`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
  return response.data.request;
}

export async function cancelDispatchRequest(requestId: string, payload: Record<string, unknown>) {
  const response = await apiRequest<DispatchRequestEnvelope>(`/dispatch-requests/${requestId}/cancel`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
  return response.data.request;
}

export async function approveDispatchPricing(requestId: string, payload: Record<string, unknown>) {
  const response = await apiRequest<DispatchRequestEnvelope>(`/dispatch/requests/${requestId}/pricing/approve`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
  return response.data.request;
}

export async function rejectDispatchPricing(requestId: string, payload: Record<string, unknown>) {
  const response = await apiRequest<DispatchRequestEnvelope>(`/dispatch/requests/${requestId}/pricing/reject`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
  return response.data.request;
}

export async function reviseDispatchPricing(requestId: string, payload: Record<string, unknown>) {
  const response = await apiRequest<DispatchRequestEnvelope>(`/dispatch/requests/${requestId}/pricing/revise`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
  return response.data.request;
}

export async function updateDispatchSchedule(requestId: string, payload: Record<string, unknown>) {
  const response = await apiRequest<DispatchRequestEnvelope>(`/dispatch/requests/${requestId}/schedule`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
  return response.data.request;
}

export async function fetchDispatchSchedule(params: {
  page?: number;
  page_size?: number;
  status?: string;
  vehicle_type_needed?: string;
  pricing_status?: string;
  schedule_type?: string;
  date_from?: string;
  date_to?: string;
} = {}) {
  const searchParams = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && String(value).trim() !== '') {
      searchParams.set(key, String(value));
    }
  });
  const query = searchParams.toString();
  const requestOptions = {
    cacheTtlMs: 5000,
    dedupeKey: `dispatch-schedule-list:${query || 'default'}`,
    componentName: 'DispatchSchedule',
    requestLabel: 'schedule-list',
    cancelGroup: 'dispatch-schedule-list',
    replacePending: true,
  } as const;
  try {
    const response = await apiRequest<DispatchRequestListEnvelope>(
      `/dispatch-requests/schedule${query ? `?${query}` : ''}`,
      requestOptions,
    );
    return response.data;
  } catch (error) {
    if (!(error instanceof ApiRequestError) || error.status !== 404) {
      throw error;
    }
  }
  const fallbackResponse = await apiRequest<DispatchRequestListEnvelope>(
    `/dispatch/schedule${query ? `?${query}` : ''}`,
    requestOptions,
  );
  return fallbackResponse.data;
}

export async function addDispatchStop(requestId: string, payload: Record<string, unknown>) {
  const response = await apiRequest<DispatchRequestEnvelope>(`/dispatch/requests/${requestId}/stops`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return response.data.request;
}

export async function updateDispatchStop(requestId: string, stopId: string, payload: Record<string, unknown>) {
  const response = await apiRequest<DispatchRequestEnvelope>(`/dispatch/requests/${requestId}/stops/${stopId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
  return response.data.request;
}

export async function deleteDispatchStop(requestId: string, stopId: string) {
  const response = await apiRequest<DispatchRequestEnvelope>(`/dispatch/requests/${requestId}/stops/${stopId}`, {
    method: 'DELETE',
  });
  return response.data.request;
}

export async function confirmDispatchStopDelivery(
  requestId: string,
  stopId: string,
  payload: {
    movement_id?: string;
    delivered_at?: string;
    delivery_note?: string;
  } = {},
) {
  const response = await apiRequest<DispatchRequestEnvelope>(`/dispatch/requests/${requestId}/stops/${stopId}/deliver`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
  return response.data.request;
}
