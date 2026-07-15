import { apiRequest } from './api';

export type DispatchPlannerJobStatus =
  | 'draft'
  | 'reserved'
  | 'assigned'
  | 'accepted'
  | 'clarification_requested'
  | 'rejected'
  | 'cancelled'
  | 'in_progress'
  | 'completed';

export type DispatchPlannerDriverResponseStatus =
  | 'pending'
  | 'accepted'
  | 'clarification_requested'
  | 'rejected';

export interface PlannerRequestRecord {
  id: string;
  request_id: string;
  customer_name: string;
  customer_phone: string;
  pickup_location: string;
  destination: string;
  vehicle_type_needed: string;
  urgency?: string | null;
  status: string;
  planning_status?: string | null;
  scheduled_start_time?: string | null;
  pricing_status?: string | null;
  load_description?: string | null;
  stops_count?: number;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface PlannerUserSummary {
  id: string;
  full_name: string;
  phone?: string | null;
  email?: string | null;
  role?: string | null;
  status?: string | null;
}

export interface PlannerVehicleSummary {
  id: string;
  registration_number: string;
  vehicle_type?: string | null;
  make?: string | null;
  model?: string | null;
  status?: string | null;
}

export interface PlannerAssignmentSummary {
  id: string;
  driver_id?: string | null;
  vehicle_id?: string | null;
  status?: string | null;
  weekly_target?: number | null;
  daily_target?: number | null;
  start_date?: string | null;
  end_date?: string | null;
}

export interface DispatchPlannerStopRecord {
  stop_id: string;
  stop_sequence?: number | null;
  stop_type?: string | null;
  location?: string | null;
  contact_name?: string | null;
  contact_phone?: string | null;
  load_note?: string | null;
  planned_arrival_time?: string | null;
  planned_departure_time?: string | null;
  stop_charge?: number | null;
  stop_status?: string | null;
  delivery_status?: string | null;
  delivered_at?: string | null;
  delivery_note?: string | null;
  delivered_by?: string | null;
}

export interface DispatchPlannerJobRecord {
  id: string;
  dispatch_job_id: string;
  dispatch_request_id: string;
  status: DispatchPlannerJobStatus;
  driver_response_status: DispatchPlannerDriverResponseStatus;
  driver_response_reason?: string | null;
  driver_responded_at?: string | null;
  vehicle_id?: string | null;
  driver_id?: string | null;
  assistant_id?: string | null;
  dispatcher_id?: string | null;
  primary_assignment_id?: string | null;
  vehicle_reservation_id?: string | null;
  driver_reservation_id?: string | null;
  linked_vehicle_movement_id?: string | null;
  pickup?: string | null;
  destination?: string | null;
  stops?: DispatchPlannerStopRecord[];
  dispatch_date?: string | null;
  dispatch_time?: string | null;
  scheduled_start_time?: string | null;
  expected_arrival_time?: string | null;
  expected_return_time?: string | null;
  distance_estimate_km?: number | null;
  goods_description?: string | null;
  quantity?: string | null;
  weight_category?: string | null;
  fragile?: boolean;
  refrigerated?: boolean;
  hazardous?: boolean;
  loading_notes?: string | null;
  customer_contact?: string | null;
  receiver_contact?: string | null;
  dispatch_instructions?: string | null;
  internal_notes?: string | null;
  conflict_summary?: string[];
  reservation_window?: {
    start_time?: string | null;
    end_time?: string | null;
  };
  created_at?: string | null;
  updated_at?: string | null;
  assigned_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  cancelled_at?: string | null;
  vehicle?: PlannerVehicleSummary | null;
  driver?: PlannerUserSummary | null;
  assistant?: PlannerUserSummary | null;
  dispatcher?: PlannerUserSummary | null;
  created_by_user?: PlannerUserSummary | null;
  updated_by_user?: PlannerUserSummary | null;
  primary_assignment?: PlannerAssignmentSummary | null;
}

export interface DispatchPlannerOptionsResponse {
  vehicles: PlannerVehicleSummary[];
  drivers: PlannerUserSummary[];
  assistants: PlannerUserSummary[];
  dispatchers: PlannerUserSummary[];
  job_statuses: DispatchPlannerJobStatus[];
  planning_statuses: string[];
  driver_response_statuses: DispatchPlannerDriverResponseStatus[];
}

export interface DispatchPlannerAvailabilityResponse {
  vehicles: Record<string, number>;
  drivers: Record<string, number>;
  dispatch: Record<string, number>;
  generated_at?: string | null;
  duration_ms?: number | null;
}

export interface DispatchPlannerConflictResponse {
  has_conflicts: boolean;
  vehicle_conflicts: string[];
  driver_conflicts: string[];
}

interface PlannerRequestsEnvelope {
  success: boolean;
  data: {
    requests: PlannerRequestRecord[];
    pagination: {
      page: number;
      page_size: number;
      total: number;
      total_pages: number;
    };
  };
}

interface PlannerJobsEnvelope {
  success: boolean;
  data: {
    jobs: DispatchPlannerJobRecord[];
    pagination: {
      page: number;
      page_size: number;
      total: number;
      total_pages: number;
    };
  };
}

interface PlannerJobEnvelope {
  success: boolean;
  data: {
    job: DispatchPlannerJobRecord;
  };
}

interface PlannerOptionsEnvelope {
  success: boolean;
  data: DispatchPlannerOptionsResponse;
}

interface PlannerAvailabilityEnvelope {
  success: boolean;
  data: DispatchPlannerAvailabilityResponse;
}

interface PlannerConflictEnvelope {
  success: boolean;
  data: DispatchPlannerConflictResponse;
}

function toQueryString(params: Record<string, string | number | undefined>) {
  const searchParams = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && String(value).trim() !== '') {
      searchParams.set(key, String(value));
    }
  });
  const query = searchParams.toString();
  return query ? `?${query}` : '';
}

export async function fetchPlannerRequests(params: {
  page?: number;
  page_size?: number;
  q?: string;
  planning_status?: string;
  urgency?: string;
} = {}) {
  const query = toQueryString(params);
  const response = await apiRequest<PlannerRequestsEnvelope>(`/dispatch-planner/requests${query}`, {
    cacheTtlMs: 4000,
    dedupeKey: `dispatch-planner-requests:${query || 'default'}`,
    componentName: 'DispatchPlanner',
    requestLabel: 'requests',
    cancelGroup: 'dispatch-planner-requests',
    replacePending: true,
  });
  return response.data;
}

export async function fetchPlannerOptions() {
  const response = await apiRequest<PlannerOptionsEnvelope>('/dispatch-planner/options', {
    cacheTtlMs: 15000,
    dedupeKey: 'dispatch-planner-options',
    componentName: 'DispatchPlanner',
    requestLabel: 'options',
  });
  return response.data;
}

export async function fetchPlannerAvailability() {
  const response = await apiRequest<PlannerAvailabilityEnvelope>('/dispatch-planner/availability', {
    cacheTtlMs: 5000,
    dedupeKey: 'dispatch-planner-availability',
    componentName: 'DispatchPlanner',
    requestLabel: 'availability',
  });
  return response.data;
}

export async function detectPlannerConflicts(payload: Record<string, unknown>) {
  const response = await apiRequest<PlannerConflictEnvelope>('/dispatch-planner/conflicts', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return response.data;
}

export async function fetchDispatchPlannerJobs(params: {
  page?: number;
  page_size?: number;
  status?: string;
} = {}) {
  const query = toQueryString(params);
  const response = await apiRequest<PlannerJobsEnvelope>(`/dispatch-planner/jobs${query}`, {
    cacheTtlMs: 3000,
    dedupeKey: `dispatch-planner-jobs:${query || 'default'}`,
    componentName: 'DispatchPlanner',
    requestLabel: 'jobs',
    cancelGroup: 'dispatch-planner-jobs',
    replacePending: true,
  });
  return response.data;
}

export async function fetchDispatchPlannerJob(jobId: string) {
  const response = await apiRequest<PlannerJobEnvelope>(`/dispatch-planner/jobs/${jobId}`, {
    cacheTtlMs: 3000,
    dedupeKey: `dispatch-planner-job:${jobId}`,
    componentName: 'DispatchPlanner',
    requestLabel: 'job-detail',
  });
  return response.data.job;
}

export async function saveDispatchPlannerDraft(requestId: string, payload: Record<string, unknown>) {
  const response = await apiRequest<PlannerJobEnvelope>(`/dispatch-planner/requests/${requestId}/draft`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return response.data.job;
}

export async function reserveDispatchPlannerJob(jobId: string) {
  const response = await apiRequest<PlannerJobEnvelope>(`/dispatch-planner/jobs/${jobId}/reserve`, {
    method: 'PATCH',
  });
  return response.data.job;
}

export async function assignDispatchPlannerJob(jobId: string) {
  const response = await apiRequest<PlannerJobEnvelope>(`/dispatch-planner/jobs/${jobId}/assign`, {
    method: 'PATCH',
  });
  return response.data.job;
}

export async function reassignDispatchPlannerJob(jobId: string, payload: Record<string, unknown>) {
  const response = await apiRequest<PlannerJobEnvelope>(`/dispatch-planner/jobs/${jobId}/reassign`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
  return response.data.job;
}
