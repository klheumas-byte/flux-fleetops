import { apiRequest } from './api';
import type { DriverActiveAssignment } from './driver-api';

export type SessionUserRole = 'owner' | 'admin' | 'driver';
export type SessionAccountStatus = 'active' | 'inactive' | 'suspended';

export interface SessionDriverProfile {
  assigned_vehicle_id?: string | null;
  approval_status?: string | null;
}

export interface SessionUser {
  id: string;
  full_name: string;
  email: string;
  phone: string;
  role: SessionUserRole;
  status: SessionAccountStatus | string;
  driver_profile?: SessionDriverProfile | null;
}

interface AuthMeResponse {
  success: boolean;
  message: string;
  data: {
    user: SessionUser;
  };
}

export function getStoredSessionUser(): SessionUser | null {
  const storedUser = localStorage.getItem('flux_user');
  if (!storedUser) {
    return null;
  }

  try {
    return JSON.parse(storedUser) as SessionUser;
  } catch {
    return null;
  }
}

export function setStoredSessionUser(user: SessionUser) {
  localStorage.setItem('flux_user', JSON.stringify(user));
}

export function clearStoredSession() {
  localStorage.removeItem('flux_token');
  localStorage.removeItem('flux_user');
}

export async function fetchAuthenticatedUser(): Promise<SessionUser> {
  const response = await apiRequest<AuthMeResponse>('/auth/me');
  const user = response.data.user;
  setStoredSessionUser(user);
  return user;
}

export function getUserInitials(fullName: string) {
  return fullName
    .split(' ')
    .filter(Boolean)
    .map((part) => part[0]?.toUpperCase() || '')
    .join('')
    .slice(0, 2);
}

export function getAssignedVehicleLabel(
  user: SessionUser | null,
  activeAssignment?: DriverActiveAssignment | null,
) {
  return (
    activeAssignment?.vehicle?.registration_number ||
    user?.driver_profile?.assigned_vehicle_id ||
    'No vehicle assigned yet'
  );
}
