import { apiRequest } from './api';
import type { DriverActiveAssignment } from './driver-api';

export type SessionUserRole = 'system_administrator' | 'operations_administrator' | 'operations_manager' | 'driver' | 'field_agent' | 'issuing_receiving_officer' | 'finance_officer' | 'owner' | 'admin' | 'dispatcher' | 'customer_service' | 'fleet_owner' | 'personal_vehicle_owner' | (string & {});
export type SessionAccountStatus = 'active' | 'disabled' | 'inactive' | 'suspended';

export interface SessionDriverProfile {
  assigned_vehicle_id?: string | null;
  approval_status?: string | null;
  operating_mode?: 'operations_only' | 'target_only' | 'hybrid';
  target_enabled?: boolean;
  target_amount?: number | null;
  target_frequency?: 'daily' | 'weekly';
  private_finance_enabled?: boolean;
  manual_availability_status?: 'available' | 'temporarily_unavailable';
  manual_availability_reason?: string | null;
}

export interface SessionUser {
  id: string;
  full_name: string;
  email: string;
  phone: string;
  role: SessionUserRole | string;
  user_type?: string | null;
  role_ids?: string[];
  roles?: { id: string; code: string; name: string; active: boolean; dashboard?: string }[];
  selected_workspace?: string | null;
  role_name?: string;
  permissions?: string[];
  permission_grants?: string[];
  permission_denials?: string[];
  dashboard?: string;
  data_scope?: string;
  username?: string | null;
  branch?: string | null;
  primary_branch_id?: string | null;
  allowed_branch_ids?: string[];
  operational_scope?: 'COMPANY_WIDE' | 'BRANCH' | 'PERSONAL_ONLY';
  home_branch_id?: string | null;
  created_by?: string | null;
  status: SessionAccountStatus | string;
  active?: boolean;
  driver_profile?: SessionDriverProfile | null;
  must_change_password?: boolean;
  default_password_active?: boolean;
  created_at?: string | null;
  last_login?: string | null;
  password_changed_at?: string | null;
}

function normalizeSessionUserRole(role: string | null | undefined): SessionUserRole | null {
  const normalized = String(role || '').trim().toLowerCase();
  return /^[a-z0-9_]+$/.test(normalized) ? normalized : null;
}

export function getActiveSessionRole(user: SessionUser | null | undefined): SessionUserRole | null {
  if (!user) return null;
  const selected = normalizeSessionUserRole(user.selected_workspace);
  if (selected && (user.roles || []).some((role) => role.active !== false && normalizeSessionUserRole(role.code) === selected)) {
    return selected;
  }
  return normalizeSessionUserRole(user.role || user.user_type);
}

function normalizeSessionUser(user: SessionUser): SessionUser {
  const rawRoles = Array.isArray(user.roles) ? user.roles : [];
  const roleCodes = [
    ...(Array.isArray(user.role_ids) ? user.role_ids : []),
    ...rawRoles.map((role) => role.code || role.id),
    user.role,
    user.user_type,
  ].map(normalizeSessionUserRole).filter((role): role is SessionUserRole => Boolean(role));
  const uniqueRoleCodes = [...new Set(roleCodes)];
  const normalizedRole = normalizeSessionUserRole(user.role || user.user_type) || uniqueRoleCodes[0] || null;
  const roles = uniqueRoleCodes.map((code) => {
    const source = rawRoles.find((role) => normalizeSessionUserRole(role.code || role.id) === code);
    return {
      id: source?.id || code,
      code,
      name: source?.name || code.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase()),
      active: source?.active !== false,
      dashboard: source?.dashboard || 'dashboard',
    };
  });
  const requestedWorkspace = normalizeSessionUserRole(user.selected_workspace);
  const selectedWorkspace = requestedWorkspace && roles.some((role) => role.code === requestedWorkspace && role.active)
    ? requestedWorkspace
    : roles.find((role) => role.active)?.code || normalizedRole;
  const workspaceRole = roles.find((role) => role.code === selectedWorkspace);
  return {
    ...user,
    role: normalizedRole || user.role,
    role_ids: uniqueRoleCodes,
    roles,
    selected_workspace: selectedWorkspace,
    role_name: workspaceRole?.name || user.role_name,
    dashboard: workspaceRole?.dashboard || user.dashboard || 'dashboard',
    status: String(user.status || '').trim().toLowerCase() || 'inactive',
  };
}

export function getWorkspaceLandingPage(role: string | null | undefined, configuredDashboard?: string | null) {
  const code = normalizeSessionUserRole(role);
  if (code === 'dispatcher' || code === 'customer_service') return 'dispatch-requests';
  const configured = String(configuredDashboard || '').trim();
  if (!configured || configured === 'dashboard' || configured.endsWith('-dashboard')) return 'dashboard';
  return configured;
}

interface AuthMeResponse {
  success: boolean;
  message: string;
  data: {
    user: SessionUser;
    access_token?: string;
  };
}

export function getStoredSessionUser(): SessionUser | null {
  const storedUser = localStorage.getItem('flux_user');
  if (!storedUser) {
    return null;
  }

  try {
    const parsedUser = normalizeSessionUser(JSON.parse(storedUser) as SessionUser);
    return normalizeSessionUserRole(parsedUser.role) ? (parsedUser as SessionUser) : null;
  } catch {
    return null;
  }
}

export function setStoredSessionUser(user: SessionUser) {
  localStorage.setItem('flux_user', JSON.stringify(normalizeSessionUser(user)));
}

export function clearStoredSession() {
  localStorage.removeItem('flux_token');
  localStorage.removeItem('flux_user');
}

export async function fetchAuthenticatedUser(): Promise<SessionUser> {
  const response = await apiRequest<AuthMeResponse>('/auth/me');
  if (response.data.access_token) {
    localStorage.setItem('flux_token', response.data.access_token);
  }
  const user = normalizeSessionUser(response.data.user);
  if (!normalizeSessionUserRole(user.role)) {
    throw new Error('Invalid session role.');
  }
  setStoredSessionUser(user);
  return user as SessionUser;
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
