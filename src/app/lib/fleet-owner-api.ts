import { apiRequest } from './api';

export interface FleetOwnerDashboardData {
  filters: { start_date: string; end_date: string; vehicle_id?: string | null };
  summary: {
    total_linked_vehicles: number;
    available_vehicles: number;
    active_vehicles: number;
    maintenance_or_fault_vehicles: number;
    today_company_collections: number;
    period_company_collections: number;
    weekly_target_achievement_percent: number;
    trips_completed: number;
    upcoming_maintenance: number;
    open_faults: number;
  };
  current_drivers: Array<{ vehicle_id: string; driver_id: string; driver_name?: string | null }>;
  vehicles: Array<{ id: string; registration_number: string; make?: string; model?: string; status?: string }>;
  profitability: {
    totals: Record<string, number>;
    by_vehicle: Record<string, Record<string, number | boolean | string>>;
    period: { start_date: string; end_date: string };
  };
}

interface Envelope<T> {
  data: T;
}

function queryString(filters: Record<string, string | undefined>) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => value && params.set(key, value));
  const value = params.toString();
  return value ? `?${value}` : '';
}

export async function fetchFleetOwnerDashboard(filters: {
  start_date?: string;
  end_date?: string;
  vehicle_id?: string;
}) {
  const response = await apiRequest<Envelope<FleetOwnerDashboardData>>(
    `/fleet-owner/dashboard${queryString(filters)}`,
  );
  return response.data;
}

export async function fetchFleetOwnerVehicle(
  vehicleId: string,
  filters: { start_date?: string; end_date?: string },
) {
  const response = await apiRequest<Envelope<Record<string, any>>>(
    `/fleet-owner/vehicles/${vehicleId}${queryString(filters)}`,
  );
  return response.data;
}

export async function fetchFleetOwnerAccounts() {
  const response = await apiRequest<Envelope<{ fleet_owners: Array<Record<string, any>> }>>(
    '/fleet-owner/accounts',
  );
  return response.data.fleet_owners;
}

export async function createFleetOwnerAccount(payload: Record<string, unknown>) {
  const response = await apiRequest<Envelope<{ fleet_owner: Record<string, any> }>>(
    '/fleet-owner/accounts',
    { method: 'POST', body: JSON.stringify(payload) },
  );
  return response.data.fleet_owner;
}

export async function updateFleetOwnerAccount(id: string, payload: Record<string, unknown>) {
  const response = await apiRequest<Envelope<{ fleet_owner: Record<string, any> }>>(
    `/fleet-owner/accounts/${id}`,
    { method: 'PATCH', body: JSON.stringify(payload) },
  );
  return response.data.fleet_owner;
}

export async function linkFleetOwnerVehicles(id: string, vehicleIds: string[]) {
  return apiRequest(`/fleet-owner/accounts/${id}/vehicles`, {
    method: 'POST',
    body: JSON.stringify({ vehicle_ids: vehicleIds }),
  });
}

export async function fetchFleetOwnerParticipationRequests(status?: string) {
  const response = await apiRequest<Envelope<{ requests: Array<Record<string, any>> }>>(
    `/fleet-owner/requests${status ? `?status=${encodeURIComponent(status)}` : ''}`,
  );
  return response.data.requests;
}

export async function reviewFleetOwnerParticipationRequest(id: string, status: 'approved' | 'rejected', reviewNote?: string) {
  const response = await apiRequest<Envelope<{ request: Record<string, any> }>>(
    `/fleet-owner/requests/${id}/review`,
    { method: 'PATCH', body: JSON.stringify({ status, review_note: reviewNote }) },
  );
  return response.data.request;
}
