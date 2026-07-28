import type { FuelLevelDetails } from './fuel-gauge';
import { apiRequest } from './api';

export type VehicleMovementType =
  | 'customer_dispatch'
  | 'personal_use'
  | 'fuel_purchase'
  | 'maintenance'
  | 'workshop'
  | 'maintenance_transport'
  | 'workshop_transport'
  | 'assignment_handover'
  | 'internal_company_delivery'
  | 'stock_transfer'
  | 'fuel_station_visit'
  | 'compliance_inspection_visit'
  | 'administrative_errand'
  | 'vehicle_repositioning'
  | 'vehicle_transfer'
  | 'internal_company_movement'
  | 'emergency'
  | 'other';

export type VehicleMovementStatus =
  | 'draft'
  | 'pending_approval'
  | 'approved'
  | 'checked_out'
  | 'in_progress'
  | 'returned'
  | 'closed'
  | 'cancelled';

export interface UserSummary {
  id: string;
  full_name: string;
  phone?: string | null;
  email?: string | null;
  role?: string | null;
  status?: string | null;
}

export interface VehicleSummary {
  id: string;
  registration_number: string;
  vehicle_type?: string | null;
  make?: string | null;
  model?: string | null;
  status?: string | null;
  tank_capacity_litres?: number | null;
  current_fuel_level?: number | null;
  current_fuel_level_details?: FuelLevelDetails | null;
}

export interface AssignmentSummary {
  id: string;
  driver_id: string;
  vehicle_id: string;
  weekly_target?: number | null;
  daily_target?: number | null;
  start_date?: string | null;
  end_date?: string | null;
  status?: string | null;
  driver?: UserSummary | null;
  vehicle?: VehicleSummary | null;
}

export interface VehicleMovementRecord {
  id: string;
  movement_id: string;
  vehicle_id: string;
  driver_id?: string | null;
  movement_custodian_id?: string | null;
  custody_state?: string | null;
  current_custody_location?: string | null;
  custody_version?: number;
  pending_custody_transfer?: {
    event_id?: string | null;
    to_user_id?: string | null;
    to_location?: string | null;
    initiated_by?: string | null;
    initiated_at?: string | null;
  } | null;
  custody_events?: Array<{
    event_id: string;
    event_key?: string | null;
    event_type: string;
    from_user_id?: string | null;
    from_location?: string | null;
    to_user_id?: string | null;
    to_location?: string | null;
    initiated_by?: string | null;
    accepted_by?: string | null;
    occurred_at?: string | null;
    accepted_at?: string | null;
    condition_summary?: string | null;
    fuel_level?: number | null;
    odometer?: number | null;
    odometer_available: boolean;
    odometer_unavailable_reason?: string | null;
    notes?: string | null;
    evidence?: Array<{ url?: string | null; type?: string | null; label?: string | null }>;
  }> | null;
  permanent_driver_id?: string | null;
  maintenance_job_id?: string | null;
  preventive_schedule_id?: string | null;
  maintenance_assignee_id?: string | null;
  assignment_id?: string | null;
  dispatch_job_id?: string | null;
  reservation_id?: string | null;
  movement_type: VehicleMovementType;
  status: VehicleMovementStatus;
  requested_departure_time?: string | null;
  departure_time?: string | null;
  expected_return_time?: string | null;
  actual_return_time?: string | null;
  origin?: string | null;
  destination?: string | null;
  purpose?: string | null;
  instructions?: string | null;
  custodian_response_status?: 'pending' | 'accepted' | 'rejected' | null;
  custodian_response_reason?: string | null;
  workshop_name?: string | null;
  mechanic_name?: string | null;
  work_performed?: string | null;
  parts_changed?: string[] | null;
  test_result?: string | null;
  completion_status?: 'awaiting_admin_verification' | 'approved' | 'returned_for_correction' | 'rejected' | null;
  physical_completion_status?: string | null;
  handover_kind?: string | null;
  handover_sequence?: number | null;
  transport_direction?: 'outbound' | 'return' | null;
  transport_mode?: string | null;
  opening_odometer?: number | null;
  opening_condition_summary?: string | null;
  closing_odometer?: number | null;
  closing_condition_summary?: string | null;
  opening_fuel_level?: number | null;
  closing_fuel_level?: number | null;
  opening_fuel_level_details?: FuelLevelDetails | null;
  closing_fuel_level_details?: FuelLevelDetails | null;
  opening_fuel_level_legacy_value?: string | number | null;
  closing_fuel_level_legacy_value?: string | number | null;
  opening_fuel_level_warning?: string | null;
  closing_fuel_level_warning?: string | null;
  delivery_status?: 'pending' | 'delivered' | null;
  delivered_at?: string | null;
  delivery_note?: string | null;
  delivered_by?: string | null;
  notes?: string | null;
  cancellation_reason?: string | null;
  approved_by?: string | null;
  approved_at?: string | null;
  checked_out_by?: string | null;
  checked_out_at?: string | null;
  returned_by?: string | null;
  returned_at?: string | null;
  closed_by?: string | null;
  closed_at?: string | null;
  created_by?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  vehicle?: VehicleSummary | null;
  driver?: UserSummary | null;
  movement_custodian?: UserSummary | null;
  permanent_driver?: UserSummary | null;
  maintenance_assignee?: UserSummary | null;
  assignment?: AssignmentSummary | null;
  created_by_user?: UserSummary | null;
  approved_by_user?: UserSummary | null;
  checked_out_by_user?: UserSummary | null;
  returned_by_user?: UserSummary | null;
  closed_by_user?: UserSummary | null;
  delivered_by_user?: UserSummary | null;
}

export interface VehicleMovementListResponse {
  movements: VehicleMovementRecord[];
  pagination: {
    page: number;
    page_size: number;
    total: number;
    total_pages: number;
  };
  filters: {
    vehicle_id?: string | null;
    driver_id?: string | null;
    status?: string | null;
    movement_type?: string | null;
    q?: string | null;
    date_from?: string | null;
    date_to?: string | null;
  };
  generated_at?: string | null;
  duration_ms?: number | null;
}

export interface VehicleMovementOptionsResponse {
  movement_types: VehicleMovementType[];
  creatable_movement_types?: VehicleMovementType[];
  statuses: VehicleMovementStatus[];
  open_statuses: VehicleMovementStatus[];
  drivers: UserSummary[];
  vehicles: VehicleSummary[];
  assignments: AssignmentSummary[];
}

interface VehicleMovementListEnvelope {
  success: boolean;
  data: VehicleMovementListResponse;
}

interface VehicleMovementEnvelope {
  success: boolean;
  data: {
    movement: VehicleMovementRecord;
  };
}

interface VehicleMovementOptionsEnvelope {
  success: boolean;
  data: VehicleMovementOptionsResponse;
}

export async function fetchVehicleMovementOptions() {
  const response = await apiRequest<VehicleMovementOptionsEnvelope>('/vehicle-movements/options', {
    cacheTtlMs: 15000,
    dedupeKey: 'vehicle-movements-options',
    componentName: 'VehicleMovements',
    requestLabel: 'options',
  });
  return response.data;
}

export async function fetchVehicleMovements(params: {
  page?: number;
  page_size?: number;
  q?: string;
  vehicle_id?: string;
  driver_id?: string;
  status?: string;
  movement_type?: string;
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
  const response = await apiRequest<VehicleMovementListEnvelope>(`/vehicle-movements${query ? `?${query}` : ''}`, {
    cacheTtlMs: 5000,
    dedupeKey: `vehicle-movements-list:${query || 'default'}`,
    componentName: 'VehicleMovements',
    requestLabel: 'list',
    cancelGroup: 'vehicle-movements-list',
    replacePending: true,
  });
  return response.data;
}

export async function fetchVehicleMovementById(movementId: string) {
  const response = await apiRequest<VehicleMovementEnvelope>(`/vehicle-movements/${movementId}`, {
    cacheTtlMs: 5000,
    dedupeKey: `vehicle-movement-detail:${movementId}`,
    componentName: 'VehicleMovements',
    requestLabel: 'detail',
  });
  return response.data.movement;
}

export async function createVehicleMovement(payload: Record<string, unknown>) {
  const response = await apiRequest<VehicleMovementEnvelope>('/vehicle-movements', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return response.data.movement;
}

export async function updateVehicleMovement(movementId: string, payload: Record<string, unknown>) {
  const response = await apiRequest<VehicleMovementEnvelope>(`/vehicle-movements/${movementId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
  return response.data.movement;
}

async function patchVehicleMovementAction(movementId: string, action: string, payload?: Record<string, unknown>) {
  const response = await apiRequest<VehicleMovementEnvelope>(`/vehicle-movements/${movementId}/${action}`, {
    method: 'PATCH',
    body: JSON.stringify(payload || {}),
  });
  return response.data.movement;
}

export async function approveVehicleMovement(movementId: string) {
  return patchVehicleMovementAction(movementId, 'approve');
}

export async function checkOutVehicleMovement(movementId: string, payload: Record<string, unknown>) {
  return patchVehicleMovementAction(movementId, 'check-out', payload);
}

export async function startVehicleMovement(movementId: string, payload?: Record<string, unknown>) {
  return patchVehicleMovementAction(movementId, 'start', payload);
}

export async function returnVehicleMovement(movementId: string, payload: Record<string, unknown>) {
  return patchVehicleMovementAction(movementId, 'return', payload);
}

export async function closeVehicleMovement(movementId: string) {
  return patchVehicleMovementAction(movementId, 'close');
}

export async function cancelVehicleMovement(movementId: string, payload: Record<string, unknown>) {
  return patchVehicleMovementAction(movementId, 'cancel', payload);
}

export async function confirmVehicleMovementDelivery(movementId: string, payload: {
  delivery_status?: 'delivered';
  delivered_at?: string;
  delivery_note?: string;
}) {
  return patchVehicleMovementAction(movementId, 'deliver', payload);
}

export async function respondToMaintenanceMovement(movementId: string, response: 'accepted' | 'rejected', reason?: string) {
  return patchVehicleMovementAction(movementId, 'maintenance-response', { response, reason });
}

export async function submitMaintenanceMovementCompletion(movementId: string, payload: Record<string, unknown>) {
  return patchVehicleMovementAction(movementId, 'submit-maintenance-completion', payload);
}

export async function reviewMaintenanceMovementCompletion(movementId: string, decision: 'approved' | 'returned_for_correction' | 'rejected', reason?: string) {
  return patchVehicleMovementAction(movementId, 'review-maintenance-completion', { decision, reason });
}
