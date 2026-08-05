import { apiRequest } from './api';

export type DispatchOpportunityStatus =
  | 'draft'
  | 'submitted'
  | 'under_review'
  | 'needs_clarification'
  | 'approved'
  | 'converted_to_dispatch_request'
  | 'rejected'
  | 'withdrawn';

export interface DispatchOpportunityUserSummary {
  id: string;
  full_name: string;
  phone?: string | null;
  email?: string | null;
  role?: string | null;
  status?: string | null;
}

export interface DispatchOpportunityRecord {
  id: string;
  opportunity_id: string;
  customer_name?: string | null;
  customer_phone?: string | null;
  customer_company?: string | null;
  pickup_location?: string | null;
  pickup_landmark?: string | null;
  destination?: string | null;
  destination_landmark?: string | null;
  trip_purpose?: 'PASSENGER' | 'GOODS' | 'MIXED' | 'OTHER';
  load_description?: string | null;
  load_type?: string | null;
  load_weight_category?: string | null;
  load_size_category?: string | null;
  vehicle_type_needed?: string | null;
  preferred_pickup_date?: string | null;
  preferred_pickup_time?: string | null;
  proposed_charge?: number | null;
  dispatch_classification?: 'COMMERCIAL' | 'COMPLIMENTARY' | 'COST_CONTRIBUTION';
  complimentary_reason?: string | null;
  contribution_amount?: number | null;
  contribution_purpose?: string | null;
  contribution_payment_method?: string | null;
  contribution_reconciliation_status?: string | null;
  approved_charge?: number | null;
  payment_status?: string | null;
  notes?: string | null;
  review_notes?: string | null;
  clarification_request?: string | null;
  rejection_reason?: string | null;
  withdrawal_reason?: string | null;
  status: DispatchOpportunityStatus;
  submitted_by_driver_id?: string | null;
  reviewed_by?: string | null;
  approved_by?: string | null;
  rejected_by?: string | null;
  withdrawn_by?: string | null;
  converted_by?: string | null;
  dispatch_request_id?: string | null;
  dispatch_request_record_id?: string | null;
  submitted_at?: string | null;
  reviewed_at?: string | null;
  approved_at?: string | null;
  rejected_at?: string | null;
  withdrawn_at?: string | null;
  converted_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  submitted_by_driver?: DispatchOpportunityUserSummary | null;
  reviewed_by_user?: DispatchOpportunityUserSummary | null;
  approved_by_user?: DispatchOpportunityUserSummary | null;
  rejected_by_user?: DispatchOpportunityUserSummary | null;
  withdrawn_by_user?: DispatchOpportunityUserSummary | null;
  converted_by_user?: DispatchOpportunityUserSummary | null;
}

export interface DispatchOpportunityOptionsResponse {
  pickup_locations: string[];
  vehicle_types: string[];
  load_types: string[];
  load_weight_categories: string[];
  load_size_categories: string[];
  payment_statuses: string[];
  statuses: DispatchOpportunityStatus[];
  driver_editable_statuses: DispatchOpportunityStatus[];
  trip_purposes: Array<'PASSENGER' | 'GOODS' | 'MIXED' | 'OTHER'>;
  dispatch_classifications: Array<'COMMERCIAL' | 'COMPLIMENTARY' | 'COST_CONTRIBUTION'>;
}

export interface DispatchOpportunityListResponse {
  opportunities: DispatchOpportunityRecord[];
  pagination: {
    page: number;
    page_size: number;
    total: number;
    total_pages: number;
  };
  filters: {
    q?: string | null;
    status?: string | null;
    driver_id?: string | null;
    date_from?: string | null;
    date_to?: string | null;
  };
  generated_at?: string | null;
  duration_ms?: number | null;
}

interface DispatchOpportunityOptionsEnvelope {
  success: boolean;
  data: DispatchOpportunityOptionsResponse;
}

interface DispatchOpportunityListEnvelope {
  success: boolean;
  data: DispatchOpportunityListResponse;
}

interface DispatchOpportunityEnvelope {
  success: boolean;
  data: {
    opportunity: DispatchOpportunityRecord;
  };
}

interface DispatchOpportunityConvertEnvelope {
  success: boolean;
  data: {
    opportunity: DispatchOpportunityRecord;
    dispatch_request: {
      id: string;
      request_id: string;
      status: string;
    };
  };
}

function buildQuery(params: Record<string, unknown>) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && String(value).trim() !== '') {
      query.set(key, String(value));
    }
  });
  return query.toString();
}

export async function fetchDriverDispatchOpportunityOptions() {
  const response = await apiRequest<DispatchOpportunityOptionsEnvelope>('/driver/dispatch-opportunities/options', {
    cacheTtlMs: 15000,
    dedupeKey: 'driver-dispatch-opportunities-options',
    componentName: 'DriverDispatchOpportunities',
    requestLabel: 'options',
  });
  return response.data;
}

export async function fetchDriverDispatchOpportunities(params: {
  page?: number;
  page_size?: number;
  q?: string;
  status?: string;
  date_from?: string;
  date_to?: string;
} = {}) {
  const query = buildQuery(params);
  const response = await apiRequest<DispatchOpportunityListEnvelope>(`/driver/dispatch-opportunities${query ? `?${query}` : ''}`, {
    cacheTtlMs: 5000,
    dedupeKey: `driver-dispatch-opportunities-list:${query || 'default'}`,
    componentName: 'DriverDispatchOpportunities',
    requestLabel: 'list',
    cancelGroup: 'driver-dispatch-opportunities-list',
    replacePending: true,
  });
  return response.data;
}

export async function fetchDriverDispatchOpportunityById(opportunityId: string) {
  const response = await apiRequest<DispatchOpportunityEnvelope>(`/driver/dispatch-opportunities/${opportunityId}`, {
    cacheTtlMs: 3000,
    dedupeKey: `driver-dispatch-opportunity-detail:${opportunityId}`,
    componentName: 'DriverDispatchOpportunities',
    requestLabel: 'detail',
  });
  return response.data.opportunity;
}

export async function createDriverDispatchOpportunity(payload: Record<string, unknown>) {
  const response = await apiRequest<DispatchOpportunityEnvelope>('/driver/dispatch-opportunities', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return response.data.opportunity;
}

export async function updateDriverDispatchOpportunity(opportunityId: string, payload: Record<string, unknown>) {
  const response = await apiRequest<DispatchOpportunityEnvelope>(`/driver/dispatch-opportunities/${opportunityId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
  return response.data.opportunity;
}

export async function submitDriverDispatchOpportunity(opportunityId: string) {
  const response = await apiRequest<DispatchOpportunityEnvelope>(`/driver/dispatch-opportunities/${opportunityId}/submit`, {
    method: 'PATCH',
    body: JSON.stringify({}),
  });
  return response.data.opportunity;
}

export async function withdrawDriverDispatchOpportunity(opportunityId: string, payload?: { withdrawal_reason?: string }) {
  const response = await apiRequest<DispatchOpportunityEnvelope>(`/driver/dispatch-opportunities/${opportunityId}/withdraw`, {
    method: 'PATCH',
    body: JSON.stringify(payload || {}),
  });
  return response.data.opportunity;
}

export async function fetchDispatchOpportunityOptions() {
  const response = await apiRequest<DispatchOpportunityOptionsEnvelope>('/dispatch-opportunities/options', {
    cacheTtlMs: 15000,
    dedupeKey: 'dispatch-opportunities-options',
    componentName: 'DispatchOpportunitiesReview',
    requestLabel: 'options',
  });
  return response.data;
}

export async function fetchDispatchOpportunities(params: {
  page?: number;
  page_size?: number;
  q?: string;
  status?: string;
  driver_id?: string;
  date_from?: string;
  date_to?: string;
} = {}) {
  const query = buildQuery(params);
  const response = await apiRequest<DispatchOpportunityListEnvelope>(`/dispatch-opportunities${query ? `?${query}` : ''}`, {
    cacheTtlMs: 5000,
    dedupeKey: `dispatch-opportunities-list:${query || 'default'}`,
    componentName: 'DispatchOpportunitiesReview',
    requestLabel: 'list',
    cancelGroup: 'dispatch-opportunities-list',
    replacePending: true,
  });
  return response.data;
}

export async function fetchDispatchOpportunityById(opportunityId: string) {
  const response = await apiRequest<DispatchOpportunityEnvelope>(`/dispatch-opportunities/${opportunityId}`, {
    cacheTtlMs: 3000,
    dedupeKey: `dispatch-opportunity-detail:${opportunityId}`,
    componentName: 'DispatchOpportunitiesReview',
    requestLabel: 'detail',
  });
  return response.data.opportunity;
}

async function patchDispatchOpportunityAction(opportunityId: string, action: string, payload?: Record<string, unknown>) {
  const response = await apiRequest<DispatchOpportunityEnvelope>(`/dispatch-opportunities/${opportunityId}/${action}`, {
    method: 'PATCH',
    body: JSON.stringify(payload || {}),
  });
  return response.data.opportunity;
}

export async function reviewDispatchOpportunity(opportunityId: string, payload: Record<string, unknown>) {
  return patchDispatchOpportunityAction(opportunityId, 'review', payload);
}

export async function requestDispatchOpportunityClarification(opportunityId: string, payload: Record<string, unknown>) {
  return patchDispatchOpportunityAction(opportunityId, 'clarification', payload);
}

export async function approveDispatchOpportunity(opportunityId: string, payload: Record<string, unknown>) {
  return patchDispatchOpportunityAction(opportunityId, 'approve', payload);
}

export async function rejectDispatchOpportunity(opportunityId: string, payload: Record<string, unknown>) {
  return patchDispatchOpportunityAction(opportunityId, 'reject', payload);
}

export async function convertDispatchOpportunity(opportunityId: string, payload?: Record<string, unknown>) {
  const response = await apiRequest<DispatchOpportunityConvertEnvelope>(`/dispatch-opportunities/${opportunityId}/convert`, {
    method: 'POST',
    body: JSON.stringify(payload || {}),
  });
  return response.data;
}
