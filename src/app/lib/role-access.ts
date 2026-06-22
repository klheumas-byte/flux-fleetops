import type { SessionUserRole } from './auth-session';

export type RoleCapability =
  | 'can_view'
  | 'can_create'
  | 'can_edit'
  | 'can_delete'
  | 'can_export'
  | 'can_approve'
  | 'can_view_sensitive_finance';

export type AppModule =
  | 'dashboard'
  | 'fleet-tracking'
  | 'vehicles'
  | 'vehicle-details'
  | 'drivers'
  | 'driver-approval'
  | 'assignments'
  | 'collections'
  | 'deposits'
  | 'expenses'
  | 'finance-accounts'
  | 'revenue'
  | 'driver-wallet'
  | 'accountability'
  | 'customers'
  | 'fuel'
  | 'fault-approvals'
  | 'maintenance'
  | 'preventive-maintenance'
  | 'driver-performance'
  | 'reports'
  | 'notifications'
  | 'security'
  | 'settings'
  | 'my-vehicle'
  | 'my-wallet'
  | 'create-ride'
  | 'ride-history'
  | 'calendar'
  | 'fuel-logs'
  | 'my-performance'
  | 'report-fault'
  | 'fault-history'
  | 'my-profile';

type RolePermissions = Record<RoleCapability, boolean>;
type RoleMatrix = Record<SessionUserRole, RolePermissions>;

const FULL_ACCESS: RolePermissions = {
  can_view: true,
  can_create: true,
  can_edit: true,
  can_delete: true,
  can_export: true,
  can_approve: true,
  can_view_sensitive_finance: true,
};

const OPERATIONAL_ADMIN: RolePermissions = {
  can_view: true,
  can_create: true,
  can_edit: true,
  can_delete: false,
  can_export: false,
  can_approve: false,
  can_view_sensitive_finance: false,
};

const DRIVER_ACCESS: RolePermissions = {
  can_view: true,
  can_create: true,
  can_edit: true,
  can_delete: false,
  can_export: false,
  can_approve: false,
  can_view_sensitive_finance: false,
};

const NO_ACCESS: RolePermissions = {
  can_view: false,
  can_create: false,
  can_edit: false,
  can_delete: false,
  can_export: false,
  can_approve: false,
  can_view_sensitive_finance: false,
};

export const MODULE_ACCESS_MATRIX: Record<AppModule, RoleMatrix> = {
  dashboard: { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, driver: DRIVER_ACCESS },
  'fleet-tracking': { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, driver: NO_ACCESS },
  vehicles: { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, driver: NO_ACCESS },
  'vehicle-details': { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, driver: NO_ACCESS },
  drivers: { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, driver: NO_ACCESS },
  'driver-approval': { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, driver: NO_ACCESS },
  assignments: { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, driver: NO_ACCESS },
  collections: { owner: FULL_ACCESS, admin: { ...OPERATIONAL_ADMIN, can_approve: true }, driver: NO_ACCESS },
  deposits: { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, driver: NO_ACCESS },
  expenses: { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, driver: NO_ACCESS },
  'finance-accounts': { owner: FULL_ACCESS, admin: NO_ACCESS, driver: NO_ACCESS },
  revenue: { owner: FULL_ACCESS, admin: NO_ACCESS, driver: NO_ACCESS },
  'driver-wallet': { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, driver: NO_ACCESS },
  accountability: { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, driver: NO_ACCESS },
  customers: { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, driver: DRIVER_ACCESS },
  fuel: { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, driver: NO_ACCESS },
  'fault-approvals': { owner: FULL_ACCESS, admin: { ...OPERATIONAL_ADMIN, can_approve: true }, driver: NO_ACCESS },
  maintenance: { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, driver: NO_ACCESS },
  'preventive-maintenance': { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, driver: NO_ACCESS },
  'driver-performance': { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, driver: NO_ACCESS },
  reports: { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, driver: NO_ACCESS },
  notifications: { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, driver: DRIVER_ACCESS },
  security: { owner: FULL_ACCESS, admin: NO_ACCESS, driver: NO_ACCESS },
  settings: { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, driver: NO_ACCESS },
  'my-vehicle': { owner: NO_ACCESS, admin: NO_ACCESS, driver: DRIVER_ACCESS },
  'my-wallet': { owner: NO_ACCESS, admin: NO_ACCESS, driver: DRIVER_ACCESS },
  'create-ride': { owner: NO_ACCESS, admin: NO_ACCESS, driver: DRIVER_ACCESS },
  'ride-history': { owner: NO_ACCESS, admin: NO_ACCESS, driver: DRIVER_ACCESS },
  calendar: { owner: NO_ACCESS, admin: NO_ACCESS, driver: DRIVER_ACCESS },
  'fuel-logs': { owner: NO_ACCESS, admin: NO_ACCESS, driver: DRIVER_ACCESS },
  'my-performance': { owner: NO_ACCESS, admin: NO_ACCESS, driver: DRIVER_ACCESS },
  'report-fault': { owner: NO_ACCESS, admin: NO_ACCESS, driver: DRIVER_ACCESS },
  'fault-history': { owner: NO_ACCESS, admin: NO_ACCESS, driver: DRIVER_ACCESS },
  'my-profile': { owner: NO_ACCESS, admin: NO_ACCESS, driver: DRIVER_ACCESS },
};

export function canAccessModule(
  role: SessionUserRole | null | undefined,
  moduleId: AppModule,
  capability: RoleCapability = 'can_view',
) {
  if (!role) {
    return false;
  }
  return Boolean(MODULE_ACCESS_MATRIX[moduleId]?.[role]?.[capability]);
}

export function filterAccessibleModules<T extends { id: AppModule }>(
  role: SessionUserRole | null | undefined,
  items: T[],
) {
  return items.filter((item) => canAccessModule(role, item.id));
}
