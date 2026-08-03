import { Suspense, lazy, startTransition, useEffect, useState } from 'react';
import { Toaster, toast } from 'sonner';
import Login from './components/Login';
import { API_BASE_URL } from './lib/api';
import { ApiRequestError, resetAuthExpirySignal } from './lib/api';
import {
  clearStoredSession,
  fetchAuthenticatedUser,
  getWorkspaceLandingPage,
  getStoredSessionUser,
  setStoredSessionUser,
  type SessionUser,
  type SessionUserRole,
} from './lib/auth-session';
import {
  fetchDriverActiveAssignment,
  fetchDriverDashboardSummary,
  fetchDriverWallet,
  type DriverActiveAssignment,
  type DriverDashboardSummary,
  type DriverWalletData,
} from './lib/driver-api';
import AdminLayout from './components/admin/AdminLayout';
import DriverLayout from './components/driver/DriverLayout';
import AccessDenied from './components/shared/AccessDenied';
import ChangePassword from './components/ChangePassword';
import NotificationSoundController from './components/shared/NotificationSoundController';
import { canAccessModule, canDriverAccessModule, type AppModule } from './lib/role-access';

const Dashboard = lazy(() => import('./components/admin/Dashboard'));
const FleetTracking = lazy(() => import('./components/admin/FleetTracking'));
const Vehicles = lazy(() => import('./components/admin/Vehicles'));
const VehicleMovements = lazy(() => import('./components/admin/VehicleMovements'));
const OperationalRequests = lazy(() => import('./components/shared/OperationalRequests'));
const StockTransfers = lazy(() => import('./components/shared/StockTransfers'));
const SupplierPickup = lazy(() => import('./components/shared/SupplierPickup'));
const OperationalTasks = lazy(() => import('./components/driver/OperationalTasks'));
const DigitalWaybills = lazy(() => import('./components/shared/DigitalWaybills'));
const DispatchFinancials = lazy(() => import('./components/admin/DispatchFinancials'));
const DispatchOpportunitiesReview = lazy(() => import('./components/admin/DispatchOpportunitiesReview'));
const DispatchReturns = lazy(() => import('./components/admin/DispatchReturns'));
const DispatchRequests = lazy(() => import('./components/admin/DispatchRequests'));
const DispatchPlanner = lazy(() => import('./components/admin/DispatchPlanner'));
const Drivers = lazy(() => import('./components/admin/Drivers'));
const DriverApproval = lazy(() => import('./components/admin/DriverApproval'));
const Collections = lazy(() => import('./components/admin/Collections'));
const Deposits = lazy(() => import('./components/admin/Deposits'));
const Expenses = lazy(() => import('./components/admin/Expenses'));
const FinanceAccounts = lazy(() => import('./components/admin/FinanceAccounts'));
const Revenue = lazy(() => import('./components/admin/Revenue'));
const AdminAccountability = lazy(() => import('./components/admin/AdminAccountability'));
const Customers = lazy(() => import('./components/admin/Customers'));
const FuelManagement = lazy(() => import('./components/admin/Fuel'));
const FaultApprovals = lazy(() => import('./components/admin/FaultApprovals'));
const Maintenance = lazy(() => import('./components/admin/Maintenance'));
const PreventiveMaintenance = lazy(() => import('./components/admin/PreventiveMaintenance'));
const Assignments = lazy(() => import('./components/admin/Assignments'));
const DriverPerformance = lazy(() => import('./components/admin/DriverPerformance'));
const Rides = lazy(() => import('./components/admin/Rides'));
const Security = lazy(() => import('./components/admin/Security'));
const Settings = lazy(() => import('./components/admin/Settings'));
const DriverDashboard = lazy(() => import('./components/driver/DriverDashboard'));
const CreateRide = lazy(() => import('./components/driver/CreateRide'));
const CustomerManagement = lazy(() => import('./components/driver/CustomerManagement'));
const DriverCalendar = lazy(() => import('./components/driver/DriverCalendar'));
const MyVehicle = lazy(() => import('./components/driver/MyVehicle'));
const MyWallet = lazy(() => import('./components/driver/MyWallet'));
const MyEarnings = lazy(() => import('./components/driver/MyEarnings'));
const MyDispatchFinancials = lazy(() => import('./components/driver/MyDispatchFinancials'));
const DispatchOpportunities = lazy(() => import('./components/driver/DispatchOpportunities'));
const MyDispatches = lazy(() => import('./components/driver/MyDispatches'));
const RideHistory = lazy(() => import('./components/driver/RideHistory'));
const FuelLogs = lazy(() => import('./components/driver/FuelLogs'));
const FaultHistory = lazy(() => import('./components/driver/FaultHistory'));
const MyPerformance = lazy(() => import('./components/driver/MyPerformance'));
const ReportFault = lazy(() => import('./components/driver/ReportFault'));
const DriverNotifications = lazy(() => import('./components/driver/DriverNotifications'));
const DriverProfile = lazy(() => import('./components/driver/DriverProfile'));
const IncidentsModule = lazy(() => import('./components/shared/IncidentsModule'));
const Reports = lazy(() => import('./components/admin/Reports'));
const Notifications = lazy(() => import('./components/admin/Notifications'));
const VehicleDetails = lazy(() => import('./components/admin/VehicleDetails'));
const FleetOwners = lazy(() => import('./components/admin/FleetOwners'));
const FleetOwnerPortal = lazy(() => import('./components/fleet-owner/FleetOwnerPortal'));
const PersonalVehiclePortal = lazy(() => import('./components/personal/PersonalVehiclePortal'));
const RbacConsole = lazy(() => import('./components/admin/RbacConsole'));
const RoleDashboard = lazy(() => import('./components/admin/RoleDashboard'));
const SmartLivingDeliveries = lazy(() => import('./components/shared/SmartLivingDeliveries'));
const BranchManagement = lazy(() => import('./components/admin/BranchManagement'));

export type UserRole = SessionUserRole;
export type AuthUser = SessionUser;

function getDefaultPageForRole(role: UserRole | null | undefined) {
  return getWorkspaceLandingPage(role);
}

export default function App() {
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [userRole, setUserRole] = useState<UserRole | null>(null);
  const [currentUser, setCurrentUser] = useState<AuthUser | null>(null);
  const [driverActiveAssignment, setDriverActiveAssignment] = useState<DriverActiveAssignment | null>(null);
  const [driverDashboardSummary, setDriverDashboardSummary] = useState<DriverDashboardSummary | null>(null);
  const [driverWalletData, setDriverWalletData] = useState<DriverWalletData | null>(null);
  const [currentPage, setCurrentPage] = useState('dashboard');
  const [selectedVehicleId, setSelectedVehicleId] = useState<string | null>(null);
  const [isAuthReady, setIsAuthReady] = useState(false);

  const loadingFallback = <><div className="fixed inset-x-0 top-0 z-[100] h-1 overflow-hidden bg-blue-100"><div className="h-full w-1/2 animate-pulse bg-blue-600" /></div><div className="p-6 text-sm text-gray-500">Loading page...</div></>;

  const navigateToPage = (page: string, options?: { vehicleId?: string | null; replaceHistory?: boolean }) => {
    const nextVehicleId = options?.vehicleId ?? (page === 'vehicle-details' ? selectedVehicleId : null);
    startTransition(() => {
      setCurrentPage(page);
      if (page !== 'vehicle-details') {
        setSelectedVehicleId(null);
      } else {
        setSelectedVehicleId(nextVehicleId || null);
      }
    });

    if (typeof window !== 'undefined') {
      const historyState = { page, selectedVehicleId: page === 'vehicle-details' ? nextVehicleId || null : null };
      if (options?.replaceHistory) {
        window.history.replaceState(historyState, '');
      } else {
        window.history.pushState(historyState, '');
      }
    }
  };

  const clearAuthState = () => {
    clearStoredSession();
    setIsLoggedIn(false);
    setUserRole(null);
    setCurrentUser(null);
    setDriverActiveAssignment(null);
    setDriverDashboardSummary(null);
    setDriverWalletData(null);
    setCurrentPage('dashboard');
    setSelectedVehicleId(null);
    setIsAuthReady(true);
    if (typeof window !== 'undefined') {
      window.history.replaceState({ page: 'dashboard', selectedVehicleId: null }, '');
    }
  };

  useEffect(() => {
    const handleAuthExpired = () => {
      clearAuthState();
    };

    window.addEventListener('flux-auth-expired', handleAuthExpired);
    return () => {
      window.removeEventListener('flux-auth-expired', handleAuthExpired);
    };
  }, []);

  useEffect(() => {
    const token = localStorage.getItem('flux_token');
    const storedUser = getStoredSessionUser();

    if (!token || !storedUser) {
      setIsAuthReady(true);
      return;
    }

    const verifySession = async () => {
      try {
        if (!storedUser?.role || !storedUser?.id) {
          clearAuthState();
          return;
        }

        const verifiedUser = await fetchAuthenticatedUser();
        if (!verifiedUser?.role || !verifiedUser?.id) {
          clearAuthState();
          return;
        }

        const activeWorkspace = (verifiedUser.selected_workspace || verifiedUser.role) as UserRole;
        setCurrentUser(verifiedUser);
        setUserRole(activeWorkspace);
        setIsLoggedIn(true);
        resetAuthExpirySignal();
        navigateToPage(getWorkspaceLandingPage(activeWorkspace, verifiedUser.dashboard), { replaceHistory: true, vehicleId: null });
      } catch (error) {
        if (error instanceof ApiRequestError && error.status === 401) {
          clearAuthState();
          return;
        }
        clearAuthState();
      } finally {
        setIsAuthReady(true);
      }
    };

    void verifySession();
  }, []);

  useEffect(() => {
    const handleWorkspaceChange = (event: Event) => {
      const detail = (event as CustomEvent<{ role?: string; user?: AuthUser; dashboard?: string }>).detail;
      if (!detail?.role || !detail.user) return;
      setCurrentUser(detail.user);
      setUserRole(detail.role as UserRole);
      navigateToPage(detail.dashboard || getDefaultPageForRole(detail.role as UserRole), { replaceHistory: true, vehicleId: null });
    };
    window.addEventListener('flux-workspace-changed', handleWorkspaceChange);
    return () => window.removeEventListener('flux-workspace-changed', handleWorkspaceChange);
  }, []);

  useEffect(() => {
    if (!isLoggedIn || userRole !== 'driver') return;
    let cancelled = false;
    const refreshMutableDriverAccess = async () => {
      try {
        const verifiedUser = await fetchAuthenticatedUser();
        if (cancelled) return;
        setCurrentUser((current) => {
          const before = JSON.stringify(current?.driver_profile || {});
          const after = JSON.stringify(verifiedUser.driver_profile || {});
          return before === after ? current : verifiedUser;
        });
      } catch {
        // The shared API layer handles expired sessions; a transient refresh
        // failure must not interrupt the driver's current safety workflow.
      }
    };
    void refreshMutableDriverAccess();
    const intervalId = window.setInterval(refreshMutableDriverAccess, 15000);
    window.addEventListener('focus', refreshMutableDriverAccess);
    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
      window.removeEventListener('focus', refreshMutableDriverAccess);
    };
  }, [isLoggedIn, userRole]);

  const handleLogin = (user: AuthUser) => {
    setStoredSessionUser(user);
    resetAuthExpirySignal();
    const normalizedRole = String(user.selected_workspace || user.role || '').trim().toLowerCase() as UserRole;
    setCurrentUser(user);
    setUserRole(normalizedRole);
    setIsLoggedIn(true);
    navigateToPage(getWorkspaceLandingPage(normalizedRole, user.dashboard), { replaceHistory: true, vehicleId: null });
  };

  const handleOpenVehicleDetails = (vehicleId: string) => {
    console.info('[Flux Performance] Opening vehicle details', { vehicleId });
    navigateToPage('vehicle-details', { vehicleId });
  };

  useEffect(() => {
    if (currentPage === 'vehicle-details' && selectedVehicleId) {
      console.info('[Flux Performance] Vehicle details route opened', {
        vehicleId: selectedVehicleId,
        currentPage,
        routePath: `/vehicles/${selectedVehicleId}`,
      });
    }
  }, [currentPage, selectedVehicleId]);

  const handleBackToVehicles = () => {
    navigateToPage('vehicles');
  };

  const handleMissingVehicleRecord = () => {
    setSelectedVehicleId(null);
    navigateToPage('vehicles');
    toast.warning('That vehicle is no longer available. We took you back to the vehicle list.', {
      position: 'bottom-right',
      id: 'vehicle-missing-redirect',
    });
  };

  const renderProtectedPage = (moduleId: AppModule, node: React.ReactNode) => {
    if (
      !canAccessModule(userRole, moduleId) ||
      (userRole === 'driver' &&
        !canDriverAccessModule(currentUser?.driver_profile?.operating_mode, moduleId))
    ) {
      return <AccessDenied />;
    }
    return node;
  };

  const refreshDriverPortalData = async () => {
    const [assignmentResult, summaryResult, walletResult] = await Promise.allSettled([
      fetchDriverActiveAssignment(),
      fetchDriverDashboardSummary(),
      fetchDriverWallet(),
    ]);

    setDriverActiveAssignment(assignmentResult.status === 'fulfilled' ? assignmentResult.value : null);
    setDriverDashboardSummary(summaryResult.status === 'fulfilled' ? summaryResult.value : null);
    setDriverWalletData(walletResult.status === 'fulfilled' ? walletResult.value : null);

    if (
      assignmentResult.status === 'rejected' &&
      assignmentResult.reason instanceof ApiRequestError &&
      assignmentResult.reason.status === 401
    ) {
      throw assignmentResult.reason;
    }
  };

  useEffect(() => {
    if (!isLoggedIn || userRole !== 'driver') {
      setDriverActiveAssignment(null);
      setDriverDashboardSummary(null);
      setDriverWalletData(null);
      return;
    }

    const loadDriverPortalData = async () => {
      try {
        await refreshDriverPortalData();
      } catch (error) {
        if (error instanceof ApiRequestError && error.status === 401) {
          clearAuthState();
          return;
        }

        console.error('[Flux Driver] Failed to load active assignment.', error);
        setDriverActiveAssignment(null);
        setDriverDashboardSummary(null);
        setDriverWalletData(null);
      }
    };

    void loadDriverPortalData();
  }, [isLoggedIn, userRole]);

  useEffect(() => {
    const handlePopState = (event: PopStateEvent) => {
      const state = event.state as { page?: string; selectedVehicleId?: string | null } | null;
      if (!state?.page) {
        setCurrentPage('dashboard');
        setSelectedVehicleId(null);
        return;
      }
      setCurrentPage(state.page);
      setSelectedVehicleId(state.selectedVehicleId || null);
    };

    window.addEventListener('popstate', handlePopState);
    return () => {
      window.removeEventListener('popstate', handlePopState);
    };
  }, []);

  const handlePortalBack = () => {
    if (typeof window !== 'undefined' && window.history.length > 1) {
      window.history.back();
      return;
    }
    navigateToPage('dashboard', { replaceHistory: true, vehicleId: null });
  };

  const getBackLabel = () => {
    switch (currentPage) {
      case 'vehicle-details':
        return 'Back to Vehicles';
      case 'drivers':
      case 'driver-approval':
      case 'driver-performance':
        return 'Back to Drivers';
      case 'customers':
      case 'calendar':
        return userRole === 'driver' ? 'Back to Driver Dashboard' : 'Back to Customers';
      case 'incidents':
        return 'Back to Incidents';
      case 'maintenance':
      case 'preventive-maintenance':
      case 'report-fault':
      case 'fault-history':
      case 'fault-approvals':
        return 'Back to Maintenance';
      case 'rides':
      case 'create-ride':
      case 'ride-history':
        return 'Back to Bookings';
      default:
        return userRole === 'owner'
          ? 'Back to Owner Dashboard'
          : userRole === 'admin'
            ? 'Back to Admin Dashboard'
            : 'Back to Driver Dashboard';
    }
  };

  const showBackButton = currentPage !== 'dashboard';

  const handleLogout = async () => {
    const token = localStorage.getItem('flux_token');

    clearAuthState();

    if (!token) {
      return;
    }

    try {
      await fetch(`${API_BASE_URL}/auth/logout`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });
    } catch (error) {
      console.error('[Flux Auth] Backend logout failed after local logout.', error);
    }
  };

  if (!isAuthReady) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-50 p-6" aria-live="polite">
        <section className="text-center">
          <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-blue-600 text-2xl font-bold text-white shadow-lg shadow-blue-200">
            F
          </div>
          <h1 className="text-lg font-semibold text-slate-900">Flux FleetOps</h1>
          <p className="mt-2 text-sm text-slate-500">Checking your session...</p>
          <div className="mx-auto mt-5 h-1.5 w-40 overflow-hidden rounded-full bg-slate-200">
            <div className="h-full w-1/2 animate-pulse rounded-full bg-blue-600" />
          </div>
        </section>
      </main>
    );
  }

  if (!isLoggedIn) {
    return <Login onLogin={handleLogin} />;
  }

  if (currentUser?.must_change_password) {
    return <ChangePassword onLogout={handleLogout} onChanged={(user) => {
      setStoredSessionUser(user);
      setCurrentUser(user);
      setUserRole(String(user.selected_workspace || user.role).trim().toLowerCase() as UserRole);
    }} />;
  }

  if (userRole !== 'driver' && userRole !== 'fleet_owner' && userRole !== 'personal_vehicle_owner') {
    return (
      <>
        <Toaster position="bottom-right" richColors closeButton />
        <NotificationSoundController />
        <AdminLayout
          userRole={userRole}
          currentUser={currentUser}
          activeSection={currentPage}
          onNavigate={navigateToPage}
          onLogout={handleLogout}
          showBackButton={showBackButton}
          backLabel={getBackLabel()}
          onBack={handlePortalBack}
        >
          <Suspense fallback={loadingFallback}>
          {currentPage === 'dashboard' && (userRole === 'owner' || userRole === 'admin') && renderProtectedPage('dashboard', <Dashboard onNavigate={navigateToPage} userRole={userRole} />)}
          {currentPage === 'dashboard' && !['owner','admin','dispatcher','customer_service'].includes(userRole) && currentUser && renderProtectedPage('dashboard', <RoleDashboard user={currentUser} onNavigate={navigateToPage} />)}
          {currentPage === 'users' && renderProtectedPage('users', <RbacConsole view="users" />)}
          {currentPage === 'roles-permissions' && renderProtectedPage('roles-permissions', <RbacConsole view="roles-permissions" />)}
          {currentPage === 'branches' && renderProtectedPage('branches', <BranchManagement />)}
          {currentPage === 'audit-logs' && renderProtectedPage('audit-logs', <RbacConsole view="audit-logs" />)}
          {currentPage === 'smart-living-deliveries' && renderProtectedPage('smart-living-deliveries', <SmartLivingDeliveries />)}
          {currentPage === 'fleet-tracking' && renderProtectedPage('fleet-tracking', <FleetTracking />)}
          {currentPage === 'vehicles' && renderProtectedPage('vehicles', <Vehicles onOpenVehicleDetails={handleOpenVehicleDetails} />)}
          {currentPage === 'fleet-owners' && renderProtectedPage('fleet-owners', <FleetOwners />)}
          {currentPage === 'vehicle-movements' && renderProtectedPage('vehicle-movements', <VehicleMovements />)}
          {currentPage === 'operational-requests' && renderProtectedPage('operational-requests', <OperationalRequests />)}
          {currentPage === 'stock-transfers' && renderProtectedPage('stock-transfers', <StockTransfers />)}
          {currentPage === 'supplier-pickup' && renderProtectedPage('supplier-pickup', <SupplierPickup />)}
          {currentPage === 'digital-waybills' && renderProtectedPage('digital-waybills', <DigitalWaybills />)}
          {currentPage === 'dispatch-financials' && renderProtectedPage('dispatch-financials', <DispatchFinancials />)}
          {currentPage === 'dispatch-opportunities' && renderProtectedPage('dispatch-opportunities', <DispatchOpportunitiesReview />)}
          {currentPage === 'dispatch-returns' && renderProtectedPage('dispatch-returns', <DispatchReturns />)}
          {currentPage === 'dispatch-requests' && renderProtectedPage('dispatch-requests', <DispatchRequests />)}
          {currentPage === 'dispatch-planner' && renderProtectedPage('dispatch-planner', <DispatchPlanner />)}
          {currentPage === 'vehicle-details' &&
            renderProtectedPage('vehicle-details', selectedVehicleId ? (
              <VehicleDetails vehicleId={selectedVehicleId} onBack={handleBackToVehicles} onMissingRecord={handleMissingVehicleRecord} />
            ) : (
              <Vehicles onOpenVehicleDetails={handleOpenVehicleDetails} />
            ))}
          {currentPage === 'drivers' && renderProtectedPage('drivers', <Drivers />)}
          {currentPage === 'driver-approval' && renderProtectedPage('driver-approval', <DriverApproval />)}
          {currentPage === 'assignments' && renderProtectedPage('assignments', <Assignments />)}
          {currentPage === 'collections' && renderProtectedPage('collections', <Collections />)}
          {currentPage === 'deposits' && renderProtectedPage('deposits', <Deposits />)}
          {currentPage === 'expenses' && renderProtectedPage('expenses', <Expenses />)}
          {currentPage === 'finance-accounts' && renderProtectedPage('finance-accounts', <FinanceAccounts />)}
          {currentPage === 'revenue' && renderProtectedPage('revenue', <Revenue />)}
          {currentPage === 'rides' && renderProtectedPage('dashboard', <Rides />)}
          {currentPage === 'accountability' && renderProtectedPage('accountability', <AdminAccountability />)}
          {currentPage === 'customers' && (userRole === 'owner' || userRole === 'admin') && renderProtectedPage('customers', <Customers userRole={userRole} />)}
          {currentPage === 'fuel' && renderProtectedPage('fuel', <FuelManagement />)}
          {currentPage === 'incidents' && renderProtectedPage('incidents', <IncidentsModule role={userRole} />)}
          {currentPage === 'fault-approvals' && renderProtectedPage('fault-approvals', <FaultApprovals />)}
          {currentPage === 'maintenance' && renderProtectedPage('maintenance', <Maintenance />)}
          {currentPage === 'preventive-maintenance' && renderProtectedPage('preventive-maintenance', <PreventiveMaintenance onNavigate={navigateToPage} />)}
          {currentPage === 'driver-performance' && renderProtectedPage('driver-performance', <DriverPerformance />)}
          {currentPage === 'reports' && renderProtectedPage('reports', <Reports />)}
          {currentPage === 'notifications' && renderProtectedPage('notifications', <Notifications onNavigate={navigateToPage} />)}
          {currentPage === 'security' && renderProtectedPage('security', <Security />)}
          {currentPage === 'settings' && renderProtectedPage('settings', <Settings />)}
          </Suspense>
        </AdminLayout>
      </>
    );
  }

  if (userRole === 'driver') {
    return (
      <>
        <Toaster position="bottom-right" richColors closeButton />
        <NotificationSoundController />
        <DriverLayout
          activeSection={currentPage}
          onNavigate={navigateToPage}
          onLogout={handleLogout}
          currentUser={currentUser}
          activeAssignment={driverActiveAssignment}
          showBackButton={showBackButton}
          backLabel={getBackLabel()}
          onBack={handlePortalBack}
        >
          <Suspense fallback={loadingFallback}>
            {currentPage === 'dashboard' && renderProtectedPage('dashboard', (
              <DriverDashboard
                currentUser={currentUser}
                activeAssignment={driverActiveAssignment}
                dashboardSummary={driverDashboardSummary}
                onNavigate={navigateToPage}
              />
            ))}
            {currentPage === 'my-vehicle' && (
              renderProtectedPage('my-vehicle', <MyVehicle
                currentUser={currentUser}
                activeAssignment={driverActiveAssignment}
              />)
            )}
            {currentPage === 'my-wallet' && (
              renderProtectedPage('my-wallet', <MyWallet
                currentUser={currentUser}
                walletData={driverWalletData}
                onRefresh={refreshDriverPortalData}
              />)
            )}
            {currentPage === 'my-earnings' && currentUser.driver_profile?.private_finance_enabled === true && renderProtectedPage('my-earnings', <MyEarnings />)}
            {currentPage === 'my-dispatch-financials' && renderProtectedPage('my-dispatch-financials', <MyDispatchFinancials />)}
            {currentPage === 'my-dispatch-opportunities' && renderProtectedPage('my-dispatch-opportunities', <DispatchOpportunities />)}
            {currentPage === 'my-dispatches' && renderProtectedPage('my-dispatches', <MyDispatches />)}
            {currentPage === 'my-operational-tasks' && renderProtectedPage('my-operational-tasks', <OperationalTasks onNavigate={navigateToPage} />)}
            {currentPage === 'smart-living-deliveries' && renderProtectedPage('smart-living-deliveries', <SmartLivingDeliveries />)}
            {currentPage === 'digital-waybills' && renderProtectedPage('digital-waybills', <DigitalWaybills driverMode />)}
            {currentPage === 'create-ride' && renderProtectedPage('create-ride', <CreateRide />)}
            {currentPage === 'ride-history' && renderProtectedPage('ride-history', <RideHistory />)}
            {currentPage === 'customers' && renderProtectedPage('customers', <CustomerManagement />)}
            {currentPage === 'calendar' && renderProtectedPage('calendar', <DriverCalendar />)}
            {currentPage === 'fuel-logs' && renderProtectedPage('fuel-logs', <FuelLogs />)}
            {currentPage === 'my-performance' && renderProtectedPage('my-performance', <MyPerformance />)}
            {currentPage === 'incidents' && renderProtectedPage('incidents', (
              <IncidentsModule role="driver" currentUser={currentUser} activeAssignment={driverActiveAssignment} />
            ))}
            {currentPage === 'report-fault' && (
              renderProtectedPage('report-fault', <ReportFault
                currentUser={currentUser}
                activeAssignment={driverActiveAssignment}
              />)
            )}
            {currentPage === 'fault-history' && renderProtectedPage('fault-history', <FaultHistory />)}
            {currentPage === 'notifications' && renderProtectedPage('notifications', <DriverNotifications onNavigate={navigateToPage} />)}
            {currentPage === 'my-profile' && renderProtectedPage('my-profile', <DriverProfile currentUser={currentUser} />)}
          </Suspense>
        </DriverLayout>
      </>
    );
  }

  if (userRole === 'fleet_owner' && currentUser) {
    return (
      <>
        <Toaster position="bottom-right" richColors closeButton />
        <NotificationSoundController />
        <Suspense fallback={loadingFallback}>
          <FleetOwnerPortal currentUser={currentUser} onLogout={handleLogout} />
        </Suspense>
      </>
    );
  }

  if (userRole === 'personal_vehicle_owner' && currentUser) {
    return (
      <>
        <Toaster position="bottom-right" richColors closeButton />
        <NotificationSoundController />
        <Suspense fallback={loadingFallback}>
          <PersonalVehiclePortal currentUser={currentUser} onLogout={handleLogout} />
        </Suspense>
      </>
    );
  }

  return <Login onLogin={handleLogin} />;
}
