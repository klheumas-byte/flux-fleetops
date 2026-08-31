import type { FuelLevelDetails } from './fuel-gauge';
import { apiRequest } from './api';

export type DriverOperationalTaskType = 'supplier_pickup' | 'stock_transfer' | 'operational_request' | 'dispatch' | 'smart_living_delivery';

export interface DriverOperationalTask {
  id: string;
  task_key: string;
  operation_type: DriverOperationalTaskType;
  operation_subtype?: string | null;
  operation_label: string;
  reference: string;
  title: string;
  schedule?: string | null;
  origin?: string | null;
  destination?: string | null;
  vehicle?: {
    id: string;
    registration_number: string;
    make?: string | null;
    model?: string | null;
  } | null;
  status: string;
  status_label: string;
  current_action: { key: string; label: string };
  linked_waybill_id?: string | null;
  stops?: Array<{
    sequence?: number | null;
    customer?: string | null;
    phone?: string | null;
    location?: string | null;
    products?: Array<{ name?: string | null; quantity?: number | null }>;
    field_agent?: string | null;
    branch?: string | null;
    date?: string | null;
    time?: string | null;
    status?: string | null;
  }>;
  updated_at?: string | null;
}

export async function fetchDriverOperationalTasks() {
  const response = await apiRequest<{ tasks: DriverOperationalTask[]; count: number }>('/driver/operational-tasks', {
    componentName: 'DriverOperationalTasks',
    requestLabel: 'summary',
    dedupeKey: 'driver-operational-tasks',
  });
  return response.data;
}

export interface DriverOperationsSummary {
  counts: {
    current_task: number;
    today: number;
    upcoming: number;
    pending_acceptance: number;
    completed_today: number;
  };
  current_task: DriverOperationalTask | null;
  upcoming_tasks: DriverOperationalTask[];
  generated_at: string;
}

export async function fetchDriverOperationsSummary() {
  const response = await apiRequest<DriverOperationsSummary>('/driver/operations-summary', {
    cacheTtlMs: 5000,
    componentName: 'DriverOperationsDashboard',
    requestLabel: 'operations-summary',
    dedupeKey: 'driver-operations-summary',
  });
  return response.data;
}

export interface DriverAssignedVehicle {
  id: string;
  registration_number: string;
  vehicle_type?: string | null;
  make?: string | null;
  model?: string | null;
  year?: number | null;
  color?: string | null;
  transmission?: string | null;
  fuel_type?: string | null;
  tank_capacity_litres?: number | null;
  current_fuel_level?: number | null;
  current_fuel_level_details?: FuelLevelDetails | null;
  insurance_expiry?: string | null;
  insurance_profile?: {
    insurance_company?: string | null;
    policy_number?: string | null;
    insurance_type?: string | null;
    claims_officer_name?: string | null;
    claims_officer_phone?: string | null;
    claims_officer_email?: string | null;
    emergency_contact?: string | null;
    expiry_date?: string | null;
  } | null;
  roadworthy_expiry?: string | null;
}

export interface DriverActiveAssignment {
  assignment_id: string;
  driver_id: string;
  vehicle_id: string;
  weekly_target: number;
  daily_target: number;
  target_enabled: boolean;
  target_amount?: number | null;
  target_frequency: 'daily' | 'weekly';
  operating_mode: 'operations_only' | 'target_only' | 'hybrid';
  start_date: string | null;
  start_time?: string | null;
  expected_end_at?: string | null;
  status: string;
  vehicle: DriverAssignedVehicle | null;
}

export interface DriverLatestCollection {
  id: string;
  driver_id: string;
  vehicle_id: string;
  assignment_id: string;
  amount: number;
  submitted_amount?: number | null;
  admin_received_amount?: number | null;
  collection_date: string;
  payment_method: string;
  reference_number?: string | null;
  notes?: string | null;
  driver_note?: string | null;
  admin_approval_note?: string | null;
  status: string;
  received_by_admin_id?: string | null;
  approved_by_admin_id?: string | null;
  submitted_by_driver_id?: string | null;
  rejected_by_admin_id?: string | null;
  submitted_at?: string | null;
  approved_at?: string | null;
  rejected_at?: string | null;
  rejection_reason?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface DriverDashboardSummary {
  driver_id: string;
  active_assignment: {
    id: string;
    driver_id: string;
    vehicle_id: string;
    weekly_target: number;
    daily_target: number;
    start_date: string | null;
    end_date?: string | null;
    status: string;
    assigned_by?: string | null;
    created_by?: string | null;
    created_at?: string | null;
    updated_at?: string | null;
    ended_at?: string | null;
  } | null;
  vehicle: DriverAssignedVehicle | null;
  weekly_target: number;
  daily_target: number;
  amount_paid_this_week: number;
  outstanding_balance: number;
  achievement_percentage: number;
  total_collections_this_week: number;
  latest_collections: DriverLatestCollection[];
  today_collection_total: number;
  weekly_cycle?: {
    payment_deadline?: string | null;
  } | null;
}

export interface DriverWalletLedgerEntry {
  date: string | null;
  type: string;
  description: string;
  debit: number;
  credit: number;
  balance_after: number;
  reference_id: string | null;
}

export interface DriverWeeklyCyclePayment {
  id: string | null;
  amount: number;
  submitted_amount?: number | null;
  admin_received_amount?: number | null;
  status: string;
  collection_date: string | null;
  payment_method: string | null;
  reference_number: string | null;
  driver_note?: string | null;
  admin_approval_note?: string | null;
  rejection_reason: string | null;
  is_late: boolean;
}

export interface DriverWeeklyCycle {
  cycle_key: string;
  assignment_id: string;
  week_start: string;
  week_end: string;
  payment_deadline: string;
  weekly_target: number;
  submitted_total: number;
  approved_total: number;
  outstanding_balance: number;
  achievement_percentage: number;
  status: 'open' | 'completed' | 'overdue' | string;
  payments: DriverWeeklyCyclePayment[];
}

export interface DriverWalletData {
  driver_id: string;
  active_assignment_id: string | null;
  weekly_target: number;
  daily_target: number;
  total_debits: number;
  total_credits: number;
  outstanding_balance: number;
  achievement_percentage: number;
  weekly_cycle: DriverWeeklyCycle | null;
  weekly_history: DriverWeeklyCycle[];
  ledger_entries: DriverWalletLedgerEntry[];
}

export interface DriverDispatchStop {
  stop_id: string;
  stop_sequence?: number | null;
  stop_type?: string | null;
  location?: string | null;
  contact_name?: string | null;
  contact_phone?: string | null;
  load_note?: string | null;
  planned_arrival_time?: string | null;
  planned_departure_time?: string | null;
  stop_status?: string | null;
  delivery_status?: string | null;
  delivered_at?: string | null;
  delivery_note?: string | null;
  completed_at?: string | null;
  completion_note?: string | null;
}

export interface DriverDispatchTimelineEntry {
  event_id: string;
  event_type: string;
  title: string;
  status: string;
  note?: string | null;
  updated_by?: string | null;
  timestamp?: string | null;
}

export interface DispatchFuelAccountability {
  opening_fuel_level?: number | null;
  opening_fuel_recorded_at?: string | null;
  opening_odometer?: number | null;
  closing_fuel_level?: number | null;
  closing_fuel_recorded_at?: string | null;
  closing_odometer?: number | null;
  total_fuel_litres_added?: number;
  total_fuel_cost?: number;
  distance_travelled?: number | null;
  estimated_fuel_consumed?: number | null;
  estimated_fuel_efficiency?: number | null;
  litre_values_are_estimates?: boolean;
  tank_capacity_litres?: number | null;
  fuel_summary_status?: string;
  legacy_opening_missing?: boolean;
}

export interface DriverDispatchJob {
  id: string;
  dispatch_job_id: string;
  dispatch_request_id: string;
  status: string;
  driver_workflow_status?: string | null;
  is_paused?: boolean;
  paused_at?: string | null;
  paused_reason?: string | null;
  driver_response_status: string;
  driver_response_reason?: string | null;
  scheduled_start_time?: string | null;
  expected_arrival_time?: string | null;
  expected_return_time?: string | null;
  schedule_valid?: boolean;
  schedule_warning?: string | null;
  pickup?: string | null;
  destination?: string | null;
  goods_description?: string | null;
  quantity?: string | null;
  weight_category?: string | null;
  loading_notes?: string | null;
  dispatch_instructions?: string | null;
  customer_contact?: string | null;
  receiver_contact?: string | null;
  stops?: DriverDispatchStop[];
  vehicle?: DriverAssignedVehicle | null;
  dispatcher?: {
    id: string;
    full_name: string;
    phone?: string | null;
    email?: string | null;
  } | null;
  timeline?: DriverDispatchTimelineEntry[];
  fuel_accountability?: DispatchFuelAccountability;
}

export interface DriverDispatchWorkspaceSummary {
  todays_dispatches: number;
  upcoming_dispatches: number;
  current_active_dispatch: DriverDispatchJob | null;
  pending_acceptance: number;
  completed_today: number;
}

export interface DriverDispatchWorkspacePage {
  jobs: DriverDispatchJob[];
  pagination: {
    page: number;
    page_size: number;
    total: number;
    total_pages: number;
  };
  section: string;
  summary?: DriverDispatchWorkspaceSummary;
}

interface DriverActiveAssignmentResponse {
  success: boolean;
  message: string;
  data: {
    assignment: DriverActiveAssignment | null;
  };
}

interface DriverDashboardSummaryResponse {
  success: boolean;
  message: string;
  data: {
    summary: DriverDashboardSummary;
  };
}

interface DriverWalletResponse {
  success: boolean;
  message: string;
  data: {
    wallet: DriverWalletData;
  };
}

interface DriverDispatchJobsResponse {
  success: boolean;
  message: string;
  data: {
    jobs: DriverDispatchJob[];
    pagination?: DriverDispatchWorkspacePage['pagination'];
    section?: string;
    summary?: DriverDispatchWorkspaceSummary;
  };
}

interface DriverDispatchJobResponse {
  success: boolean;
  message: string;
  data: {
    job: DriverDispatchJob;
  };
}

interface DriverPaymentSubmissionResponse {
  success: boolean;
  message: string;
  data: {
    payment: DriverLatestCollection;
  };
}

export async function fetchDriverActiveAssignment(): Promise<DriverActiveAssignment | null> {
  const response = await apiRequest<DriverActiveAssignmentResponse>('/driver/active-assignment', {
    cacheTtlMs: 10000,
    dedupeKey: 'driver-active-assignment',
    componentName: 'DriverPortal',
    requestLabel: 'active-assignment',
  });
  return response.data.assignment;
}

export async function fetchDriverDashboardSummary(): Promise<DriverDashboardSummary> {
  const response = await apiRequest<DriverDashboardSummaryResponse>('/driver/dashboard-summary', {
    cacheTtlMs: 10000,
    dedupeKey: 'driver-dashboard-summary',
    componentName: 'DriverPortal',
    requestLabel: 'dashboard-summary',
  });
  return response.data.summary;
}

export async function fetchDriverWallet(): Promise<DriverWalletData> {
  const response = await apiRequest<DriverWalletResponse>('/driver/wallet', {
    cacheTtlMs: 10000,
    dedupeKey: 'driver-wallet',
    componentName: 'DriverPortal',
    requestLabel: 'wallet',
  });
  return response.data.wallet;
}

export async function submitDriverPayment(payload: {
  amount: number;
  collection_date: string;
  payment_method: 'cash' | 'momo' | 'bank' | 'other';
  reference_number?: string;
  notes?: string;
}): Promise<DriverLatestCollection> {
  const response = await apiRequest<DriverPaymentSubmissionResponse>('/driver/payments', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return response.data.payment;
}

export async function fetchDriverDispatchJobs(): Promise<DriverDispatchJob[]> {
  const response = await apiRequest<DriverDispatchJobsResponse>('/driver/dispatch-jobs', {
    cacheTtlMs: 5000,
    dedupeKey: 'driver-dispatch-jobs',
    componentName: 'DriverDashboard',
    requestLabel: 'dispatch-jobs',
  });
  return response.data.jobs || [];
}

export async function fetchDriverDispatchWorkspace(options: {
  section: 'upcoming' | 'active' | 'completed' | 'cancelled';
  page?: number;
  pageSize?: number;
  includeSummary?: boolean;
}): Promise<DriverDispatchWorkspacePage> {
  const query = new URLSearchParams({
    section: options.section,
    page: String(options.page || 1),
    page_size: String(options.pageSize || 10),
    include_summary: options.includeSummary ? 'true' : 'false',
  });
  const response = await apiRequest<DriverDispatchJobsResponse>(`/driver/dispatch-jobs?${query.toString()}`, {
    cacheTtlMs: 5000,
    dedupeKey: `driver-dispatch-workspace:${query.toString()}`,
    componentName: 'DriverDispatches',
    requestLabel: 'dispatch-workspace',
  });
  return {
    jobs: response.data.jobs || [],
    pagination: response.data.pagination || {
      page: 1,
      page_size: options.pageSize || 10,
      total: response.data.jobs?.length || 0,
      total_pages: 1,
    },
    section: response.data.section || options.section,
    summary: response.data.summary,
  };
}

export async function fetchDriverDispatchJob(jobId: string): Promise<DriverDispatchJob> {
  const response = await apiRequest<DriverDispatchJobResponse>(`/driver/dispatch-jobs/${jobId}`, {
    cacheTtlMs: 3000,
    dedupeKey: `driver-dispatch-job:${jobId}`,
    componentName: 'DriverDispatches',
    requestLabel: 'dispatch-detail',
  });
  return response.data.job;
}

export async function confirmDriverDispatchOpeningFuel(jobId: string, payload: {
  opening_fuel_level: number;
  opening_odometer?: number;
  inspection_note?: string;
  opening_fuel_photo?: string;
}): Promise<{ summary: DispatchFuelAccountability }> {
  const response = await apiRequest<{
    success: boolean;
    data: { summary: DispatchFuelAccountability };
  }>(`/driver/dispatch-jobs/${jobId}/fuel/opening`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
  return response.data;
}

export async function acceptDriverDispatchJob(jobId: string): Promise<DriverDispatchJob> {
  const response = await apiRequest<DriverDispatchJobResponse>(`/driver/dispatch-jobs/${jobId}/accept`, {
    method: 'PATCH',
  });
  return response.data.job;
}

export async function clarifyDriverDispatchJob(jobId: string, payload: { reason: string }): Promise<DriverDispatchJob> {
  const response = await apiRequest<DriverDispatchJobResponse>(`/driver/dispatch-jobs/${jobId}/clarify`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
  return response.data.job;
}

export async function rejectDriverDispatchJob(jobId: string, payload: { reason: string }): Promise<DriverDispatchJob> {
  const response = await apiRequest<DriverDispatchJobResponse>(`/driver/dispatch-jobs/${jobId}/reject`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
  return response.data.job;
}

export async function updateDriverDispatchWorkflow(jobId: string, payload: {
  action: 'start' | 'pause' | 'resume' | 'goods_loaded' | 'stop_completed' | 'delivery_completed' | 'end';
  note?: string;
  stop_id?: string;
  movement_id?: string;
}): Promise<DriverDispatchJob> {
  const response = await apiRequest<DriverDispatchJobResponse>(`/driver/dispatch-jobs/${jobId}/workflow`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
  return response.data.job;
}
