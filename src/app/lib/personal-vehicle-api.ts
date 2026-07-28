import { apiRequest } from './api';

type Envelope<T> = { data: T };
export type PersonalVehicle = Record<string, any> & { id: string; registration_number: string; vehicle_type: string; status: string };

function query(values: Record<string, string | number | undefined | null>) {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => value !== undefined && value !== null && value !== '' && params.set(key, String(value)));
  return params.size ? `?${params}` : '';
}

export async function fetchPersonalDashboard(filters: Record<string, string>) {
  return (await apiRequest<Envelope<Record<string, any>>>(`/personal-vehicles/dashboard${query(filters)}`)).data;
}
export async function fetchPersonalVehicles() {
  return (await apiRequest<Envelope<{ vehicles: PersonalVehicle[] }>>('/personal-vehicles/vehicles')).data.vehicles;
}
export async function createPersonalVehicle(payload: Record<string, unknown>) {
  return (await apiRequest<Envelope<{ vehicle: PersonalVehicle }>>('/personal-vehicles/vehicles', { method: 'POST', body: JSON.stringify(payload) })).data.vehicle;
}
export async function updatePersonalVehicle(id: string, payload: Record<string, unknown>) {
  return (await apiRequest<Envelope<{ vehicle: PersonalVehicle }>>(`/personal-vehicles/vehicles/${id}`, { method: 'PATCH', body: JSON.stringify(payload) })).data.vehicle;
}
export async function fetchPersonalRecords(kind: string, filters: Record<string, string | number>) {
  return (await apiRequest<Envelope<{ records: any[]; pagination: any }>>(`/personal-vehicles/records/${kind}${query(filters)}`)).data;
}
export async function createPersonalRecord(kind: string, payload: Record<string, unknown>) {
  return (await apiRequest<Envelope<{ record: any }>>(`/personal-vehicles/records/${kind}`, { method: 'POST', body: JSON.stringify(payload) })).data.record;
}
export async function updatePersonalRecord(kind: string, id: string, payload: Record<string, unknown>) {
  return (await apiRequest<Envelope<{ record: any }>>(`/personal-vehicles/records/${kind}/${id}`, { method: 'PATCH', body: JSON.stringify(payload) })).data.record;
}
export async function renewPersonalDocument(id: string, payload: Record<string, unknown>) {
  return (await apiRequest<Envelope<{ document: any }>>(`/personal-vehicles/documents/${id}/renew`, { method: 'POST', body: JSON.stringify(payload) })).data.document;
}
export async function fetchPersonalTimeline(filters: Record<string, string | number>) {
  return (await apiRequest<Envelope<{ events: any[]; pagination: any }>>(`/personal-vehicles/timeline${query(filters)}`)).data;
}
export async function fetchPersonalExpenseSummary(filters: Record<string, string>) {
  return (await apiRequest<Envelope<Record<string, any>>>(`/personal-vehicles/expenses/summary${query(filters)}`)).data;
}
export async function fetchPersonalProfile() {
  return (await apiRequest<Envelope<{ user: any }>>('/personal-vehicles/profile')).data.user;
}
export async function updatePersonalProfile(payload: Record<string, unknown>) {
  return (await apiRequest<Envelope<{ user: any }>>('/personal-vehicles/profile', { method: 'PATCH', body: JSON.stringify(payload) })).data.user;
}
