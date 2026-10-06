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
  | 'fleet-owners'
  | 'vehicle-details'
  | 'drivers'
  | 'driver-approval'
  | 'assignments'
  | 'vehicle-movements'
  | 'operations-control'
  | 'operational-requests'
  | 'stock-transfers'
  | 'supplier-pickup'
  | 'digital-waybills'
  | 'dispatch-financials'
  | 'dispatch-opportunities'
  | 'dispatch-returns'
  | 'dispatch-requests'
  | 'dispatch-planner'
  | 'collections'
  | 'driver-remittances'
  | 'deposits'
  | 'expenses'
  | 'finance-accounts'
  | 'funding-ledger'
  | 'revenue'
  | 'driver-wallet'
  | 'accountability'
  | 'customers'
  | 'fuel'
  | 'incidents'
  | 'fault-approvals'
  | 'maintenance'
  | 'preventive-maintenance'
  | 'driver-performance'
  | 'reports'
  | 'notifications'
  | 'security'
  | 'settings'
  | 'users'
  | 'roles-permissions'
  | 'branches'
  | 'audit-logs'
  | 'smart-living-deliveries'
  | 'smart-living-integration'
  | 'branch-operations'
  | 'branch-team'
  | 'my-vehicle'
  | 'my-wallet'
  | 'my-earnings'
  | 'my-dispatch-financials'
  | 'my-dispatch-opportunities'
  | 'my-dispatches'
  | 'my-operational-tasks'
  | 'personal-vehicle-use'
  | 'create-ride'
  | 'ride-history'
  | 'calendar'
  | 'fuel-logs'
  | 'my-performance'
  | 'report-fault'
  | 'fault-history'
  | 'my-profile';

type RolePermissions = Record<RoleCapability, boolean>;
type RoleMatrix = Partial<Record<SessionUserRole, RolePermissions>>;

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

const DISPATCH_PORTAL_ACCESS: RolePermissions = {
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

// Named aliases make elevated-role grants explicit instead of conflating them
// with the owner/admin roles used by global integrations such as SmartLiving.
const SYSTEM_ADMIN_ACCESS = FULL_ACCESS;
const OPERATIONS_ADMIN_ACCESS = OPERATIONAL_ADMIN;

export const SMARTLIVING_GLOBAL_ADMIN_ROLES: readonly SessionUserRole[] = ['owner', 'admin'];

export function canManageSmartLiving(role: SessionUserRole | null | undefined) {
  return Boolean(role && SMARTLIVING_GLOBAL_ADMIN_ROLES.includes(role));
}

export const MODULE_ACCESS_MATRIX: Record<AppModule, RoleMatrix> = {
  users: { owner: FULL_ACCESS },
  'roles-permissions': { owner: FULL_ACCESS },
  branches: { owner: FULL_ACCESS },
  'audit-logs': { owner: FULL_ACCESS },
  'smart-living-deliveries': { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, driver: DRIVER_ACCESS },
  'smart-living-integration': {
    owner: FULL_ACCESS,
    admin: OPERATIONAL_ADMIN,
  },
  'branch-operations': { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN },
  'branch-team': { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN },
  dashboard: { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, driver: DRIVER_ACCESS, fleet_owner: { ...NO_ACCESS, can_view: true } },
  'fleet-tracking': { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, driver: NO_ACCESS },
  vehicles: { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, driver: NO_ACCESS },
  'fleet-owners': { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, driver: NO_ACCESS },
  'vehicle-details': { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, driver: NO_ACCESS },
  drivers: { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, driver: NO_ACCESS },
  'driver-approval': { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, driver: NO_ACCESS },
  assignments: { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, driver: NO_ACCESS },
  'vehicle-movements': { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, driver: NO_ACCESS },
  'operations-control': { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN },
  'operational-requests': { owner: FULL_ACCESS, admin: { ...OPERATIONAL_ADMIN, can_approve: true }, driver: NO_ACCESS },
  'stock-transfers': { owner: FULL_ACCESS, admin: { ...OPERATIONAL_ADMIN, can_approve: true }, driver: NO_ACCESS },
  'supplier-pickup': { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, driver: NO_ACCESS },
  'digital-waybills': { owner: FULL_ACCESS, admin: { ...OPERATIONAL_ADMIN, can_approve: true, can_export: true }, driver: DRIVER_ACCESS },
  'dispatch-financials': { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, driver: NO_ACCESS },
  'dispatch-opportunities': {
    owner: FULL_ACCESS,
    admin: OPERATIONAL_ADMIN,
    dispatcher: DISPATCH_PORTAL_ACCESS,
    customer_service: DISPATCH_PORTAL_ACCESS,
    driver: NO_ACCESS,
  },
  'dispatch-returns': {
    owner: FULL_ACCESS,
    admin: OPERATIONAL_ADMIN,
    dispatcher: DISPATCH_PORTAL_ACCESS,
    customer_service: NO_ACCESS,
    driver: NO_ACCESS,
  },
  'dispatch-requests': {
    owner: FULL_ACCESS,
    admin: OPERATIONAL_ADMIN,
    dispatcher: DISPATCH_PORTAL_ACCESS,
    customer_service: DISPATCH_PORTAL_ACCESS,
    driver: NO_ACCESS,
  },
  'dispatch-planner': {
    owner: FULL_ACCESS,
    admin: OPERATIONAL_ADMIN,
    dispatcher: DISPATCH_PORTAL_ACCESS,
    customer_service: DISPATCH_PORTAL_ACCESS,
    driver: NO_ACCESS,
  },
  collections: { owner: FULL_ACCESS, admin: { ...OPERATIONAL_ADMIN, can_approve: true }, driver: NO_ACCESS },
  'driver-remittances': { owner: FULL_ACCESS, admin: { ...OPERATIONAL_ADMIN, can_approve: true }, driver: NO_ACCESS },
  deposits: { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, driver: NO_ACCESS },
  expenses: { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, finance_officer: OPERATIONAL_ADMIN, driver: NO_ACCESS },
  'finance-accounts': { owner: FULL_ACCESS, admin: FULL_ACCESS, driver: NO_ACCESS },
  'funding-ledger': { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, finance_officer: OPERATIONAL_ADMIN, driver: NO_ACCESS },
  revenue: { owner: FULL_ACCESS, admin: NO_ACCESS, driver: NO_ACCESS },
  'driver-wallet': { owner: NO_ACCESS, admin: NO_ACCESS, driver: NO_ACCESS },
  accountability: { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, driver: NO_ACCESS },
  customers: { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, driver: DRIVER_ACCESS },
  fuel: { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, driver: NO_ACCESS },
  incidents: { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, driver: DRIVER_ACCESS },
  'fault-approvals': { owner: FULL_ACCESS, admin: { ...OPERATIONAL_ADMIN, can_approve: true }, driver: NO_ACCESS },
  // Drivers have no access to the admin maintenance module itself.
  // Assigned-vehicle maintenance visibility is exposed only inside the driver "my-vehicle"
  // experience through driver-scoped backend endpoints.
  maintenance: { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, driver: NO_ACCESS },
  'preventive-maintenance': { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, driver: NO_ACCESS },
  'driver-performance': { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, driver: NO_ACCESS },
  reports: { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, driver: NO_ACCESS },
  notifications: { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, driver: DRIVER_ACCESS },
  security: { owner: FULL_ACCESS, admin: NO_ACCESS, driver: NO_ACCESS },
  settings: { owner: FULL_ACCESS, admin: OPERATIONAL_ADMIN, driver: NO_ACCESS },
  'my-vehicle': { owner: NO_ACCESS, admin: NO_ACCESS, driver: DRIVER_ACCESS },
  'my-wallet': { owner: NO_ACCESS, admin: NO_ACCESS, driver: DRIVER_ACCESS },
  'my-earnings': { owner: NO_ACCESS, admin: NO_ACCESS, driver: { ...DRIVER_ACCESS, can_delete: true, can_export: true } },
  'my-dispatch-financials': { owner: NO_ACCESS, admin: NO_ACCESS, driver: DRIVER_ACCESS },
  'my-dispatch-opportunities': { owner: NO_ACCESS, admin: NO_ACCESS, driver: DRIVER_ACCESS },
  'my-dispatches': { owner: NO_ACCESS, admin: NO_ACCESS, driver: DRIVER_ACCESS },
  'my-operational-tasks': { owner: NO_ACCESS, admin: NO_ACCESS, driver: DRIVER_ACCESS },
  'personal-vehicle-use': { owner: NO_ACCESS, admin: NO_ACCESS, driver: DRIVER_ACCESS },
  'create-ride': { owner: NO_ACCESS, admin: NO_ACCESS, driver: DRIVER_ACCESS },
  'ride-history': { owner: NO_ACCESS, admin: NO_ACCESS, driver: DRIVER_ACCESS },
  calendar: { owner: NO_ACCESS, admin: NO_ACCESS, driver: DRIVER_ACCESS },
  'fuel-logs': { owner: NO_ACCESS, admin: NO_ACCESS, driver: DRIVER_ACCESS },
  'my-performance': { owner: NO_ACCESS, admin: NO_ACCESS, driver: DRIVER_ACCESS },
  'report-fault': {
    owner: FULL_ACCESS,
    admin: OPERATIONAL_ADMIN,
    operations_administrator: OPERATIONS_ADMIN_ACCESS,
    system_administrator: SYSTEM_ADMIN_ACCESS,
    driver: DRIVER_ACCESS,
  },
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
  if (moduleId === 'smart-living-integration') {
    return canManageSmartLiving(role) && Boolean(MODULE_ACCESS_MATRIX[moduleId]?.[role]?.[capability]);
  }
  if (moduleId === 'dashboard') return true;
  const roleAccess = Boolean(MODULE_ACCESS_MATRIX[moduleId]?.[role]?.[capability]);
  const requiredPermission = MODULE_REQUIRED_PERMISSION[moduleId];
  if (requiredPermission && typeof localStorage !== 'undefined') {
    try {
      const stored = JSON.parse(localStorage.getItem('flux_user') || '{}') as {
        permissions?: string[];
        permission_denials?: string[];
      };
      const required = Array.isArray(requiredPermission) ? requiredPermission : [requiredPermission];
      if (required.some(permission => stored.permission_denials?.includes(permission))) return false;
      if (stored.permissions?.includes('*') || required.some(permission => stored.permissions?.includes(permission))) return true;
      // Built-in role access is authoritative even when a browser session was
      // issued before a new permission was added. Explicit denials above still
      // take precedence; custom roles continue to rely on server permissions.
      if (roleAccess) return true;
      if (Array.isArray(stored.permissions)) return false;
    } catch {
      // Fall through for legacy sessions created before server-issued permissions.
    }
  }
  return roleAccess;
}

const MODULE_REQUIRED_PERMISSION: Partial<Record<AppModule, string | string[]>> = {
  dashboard: 'operations.view', users: 'users.manage_operational',
  'roles-permissions': 'roles.manage', branches: 'branches.manage', 'audit-logs': 'audit.view',
  vehicles: 'vehicle.view', 'vehicle-details': 'vehicle.view', 'vehicle-movements': 'vehicle.manage',
  drivers: 'driver.view', assignments: 'driver.assign',
  'dispatch-planner': 'delivery.create', 'dispatch-requests': 'delivery.create',
  'dispatch-returns': 'delivery.update', 'dispatch-opportunities': 'delivery.update',
  'operational-requests': 'operations.view', maintenance: 'maintenance.view',
  'stock-transfers': ['stock_transfers.view_incoming', 'stock_transfers.view_history'],
  'preventive-maintenance': 'maintenance.view', 'fault-approvals': 'fault.view',
  reports: 'operations.reports', notifications: 'notifications.view', settings: 'system.configure',
  security: 'security.manage', expenses: 'expenses.manage', fuel: 'fuel.expenses',
  'finance-accounts': 'finance.view', 'my-dispatches': 'delivery.view_own',
  'driver-remittances': 'finance.view',
  'funding-ledger': 'finance.view',
  'my-operational-tasks': 'delivery.view_own', 'my-vehicle': 'vehicle.view_assigned',
  'personal-vehicle-use': 'personal_vehicle_use.create',
  'report-fault': 'fault.report', 'ride-history': 'trip.view_own',
  'smart-living-deliveries': ['delivery_scheduler.view','delivery_schedule.view_assigned','loading_schedule.view','deliveries.view','deliveries.view_own','deliveries.view_assigned'],
  'smart-living-integration': 'integrations.manage',
  'branch-operations': 'branch_operations.view',
  'branch-team': 'branch_operations.manage_team',
};

export function filterAccessibleModules<T extends { id: AppModule }>(
  role: SessionUserRole | null | undefined,
  items: T[],
) {
  return items.filter((item) => canAccessModule(role, item.id));
}

const DRIVER_OPERATIONS_MODULES = new Set<AppModule>([
  'my-dispatch-financials',
  'my-dispatch-opportunities',
  'my-dispatches',
  'my-operational-tasks',
  'personal-vehicle-use',
  'digital-waybills',
  'create-ride',
  'ride-history',
  'fuel-logs',
  'smart-living-deliveries',
]);
const DRIVER_TARGET_MODULES = new Set<AppModule>(['my-wallet', 'my-earnings', 'my-performance', 'calendar', 'customers']);
const DRIVER_COMMON_MODULES = new Set<AppModule>([
  'dashboard', 'notifications', 'my-profile', 'my-vehicle',
  'incidents', 'report-fault', 'fault-history',
]);

export function canDriverAccessModule(
  operatingMode: 'operations_only' | 'target_only' | 'hybrid' | null | undefined,
  moduleId: AppModule,
) {
  const mode = operatingMode || 'hybrid';
  if (DRIVER_COMMON_MODULES.has(moduleId)) return true;
  if (mode === 'hybrid') return true;
  if (mode === 'operations_only') return DRIVER_OPERATIONS_MODULES.has(moduleId);
  return DRIVER_TARGET_MODULES.has(moduleId);
}
