import { Suspense, lazy, useEffect, useState } from 'react';
import { Toaster, toast } from 'sonner';
import Login from './components/Login';
import { API_BASE_URL } from './lib/api';
import { ApiRequestError } from './lib/api';
import {
  clearStoredSession,
  fetchAuthenticatedUser,
  getStoredSessionUser,
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
import Dashboard from './components/admin/Dashboard';
import FleetTracking from './components/admin/FleetTracking';
import Vehicles from './components/admin/Vehicles';
import Drivers from './components/admin/Drivers';
import DriverApproval from './components/admin/DriverApproval';
import Collections from './components/admin/Collections';
import Deposits from './components/admin/Deposits';
import Expenses from './components/admin/Expenses';
import FinanceAccounts from './components/admin/FinanceAccounts';
import Revenue from './components/admin/Revenue';
import DriverWallet from './components/admin/DriverWallet';
import AdminAccountability from './components/admin/AdminAccountability';
import Customers from './components/admin/Customers';
import FuelManagement from './components/admin/Fuel';
import FaultApprovals from './components/admin/FaultApprovals';
import Maintenance from './components/admin/Maintenance';
import PreventiveMaintenance from './components/admin/PreventiveMaintenance';
import Assignments from './components/admin/Assignments';
import DriverPerformance from './components/admin/DriverPerformance';
import Rides from './components/admin/Rides';
import Security from './components/admin/Security';
import Settings from './components/admin/Settings';
import DriverLayout from './components/driver/DriverLayout';
import DriverDashboard from './components/driver/DriverDashboard';
import CreateRide from './components/driver/CreateRide';
import CustomerManagement from './components/driver/CustomerManagement';
import DriverCalendar from './components/driver/DriverCalendar';
import MyVehicle from './components/driver/MyVehicle';
import MyWallet from './components/driver/MyWallet';
import RideHistory from './components/driver/RideHistory';
import FuelLogs from './components/driver/FuelLogs';
import FaultHistory from './components/driver/FaultHistory';
import MyPerformance from './components/driver/MyPerformance';
import ReportFault from './components/driver/ReportFault';
import DriverNotifications from './components/driver/DriverNotifications';
import DriverProfile from './components/driver/DriverProfile';
import AccessDenied from './components/shared/AccessDenied';
import { canAccessModule, type AppModule } from './lib/role-access';

const Reports = lazy(() => import('./components/admin/Reports'));
const Notifications = lazy(() => import('./components/admin/Notifications'));
const VehicleDetails = lazy(() => import('./components/admin/VehicleDetails'));

export type UserRole = SessionUserRole;
export type AuthUser = SessionUser;

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

        setCurrentUser(verifiedUser);
        setUserRole(verifiedUser.role);
        setIsLoggedIn(true);
        setCurrentPage('dashboard');
        setSelectedVehicleId(null);
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

  const handleLogin = (user: AuthUser) => {
    setCurrentUser(user);
    setUserRole(user.role);
    setIsLoggedIn(true);
    setCurrentPage('dashboard');
    setSelectedVehicleId(null);
  };

  const handleOpenVehicleDetails = (vehicleId: string) => {
    console.info('[Flux Performance] Opening vehicle details', { vehicleId });
    setSelectedVehicleId(vehicleId);
    setCurrentPage('vehicle-details');
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
    setCurrentPage('vehicles');
  };

  const handleMissingVehicleRecord = () => {
    setSelectedVehicleId(null);
    setCurrentPage('vehicles');
    toast.warning('That vehicle is no longer available. We took you back to the vehicle list.', {
      position: 'bottom-right',
      id: 'vehicle-missing-redirect',
    });
  };

  const renderProtectedPage = (moduleId: AppModule, node: React.ReactNode) => {
    if (!canAccessModule(userRole, moduleId)) {
      return <AccessDenied />;
    }
    return node;
  };

  const refreshDriverPortalData = async () => {
    const [assignment, summary, wallet] = await Promise.all([
      fetchDriverActiveAssignment(),
      fetchDriverDashboardSummary(),
      fetchDriverWallet(),
    ]);
    setDriverActiveAssignment(assignment);
    setDriverDashboardSummary(summary);
    setDriverWalletData(wallet);
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
    return null;
  }

  if (!isLoggedIn) {
    return <Login onLogin={handleLogin} />;
  }

  if (userRole === 'owner' || userRole === 'admin') {
    return (
      <>
        <Toaster position="bottom-right" richColors closeButton />
        <AdminLayout
          userRole={userRole}
          activeSection={currentPage}
          onNavigate={setCurrentPage}
          onLogout={handleLogout}
        >
          <Suspense fallback={<div className="p-6 text-sm text-gray-500">Loading page...</div>}>
          {currentPage === 'dashboard' && renderProtectedPage('dashboard', <Dashboard onNavigate={setCurrentPage} userRole={userRole} />)}
          {currentPage === 'fleet-tracking' && renderProtectedPage('fleet-tracking', <FleetTracking />)}
          {currentPage === 'vehicles' && renderProtectedPage('vehicles', <Vehicles onOpenVehicleDetails={handleOpenVehicleDetails} />)}
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
          {currentPage === 'driver-wallet' && renderProtectedPage('driver-wallet', <DriverWallet />)}
          {currentPage === 'accountability' && renderProtectedPage('accountability', <AdminAccountability />)}
          {currentPage === 'customers' && renderProtectedPage('customers', <Customers userRole={userRole} />)}
          {currentPage === 'fuel' && renderProtectedPage('fuel', <FuelManagement />)}
          {currentPage === 'fault-approvals' && renderProtectedPage('fault-approvals', <FaultApprovals />)}
          {currentPage === 'maintenance' && renderProtectedPage('maintenance', <Maintenance />)}
          {currentPage === 'preventive-maintenance' && renderProtectedPage('preventive-maintenance', <PreventiveMaintenance />)}
          {currentPage === 'driver-performance' && renderProtectedPage('driver-performance', <DriverPerformance />)}
          {currentPage === 'reports' && renderProtectedPage('reports', <Reports />)}
          {currentPage === 'notifications' && renderProtectedPage('notifications', <Notifications />)}
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
        <DriverLayout
          activeSection={currentPage}
          onNavigate={setCurrentPage}
          onLogout={handleLogout}
          currentUser={currentUser}
          activeAssignment={driverActiveAssignment}
        >
          {currentPage === 'dashboard' && renderProtectedPage('dashboard', (
            <DriverDashboard
              currentUser={currentUser}
              activeAssignment={driverActiveAssignment}
              dashboardSummary={driverDashboardSummary}
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
          {currentPage === 'create-ride' && renderProtectedPage('create-ride', <CreateRide />)}
          {currentPage === 'ride-history' && renderProtectedPage('ride-history', <RideHistory />)}
          {currentPage === 'customers' && renderProtectedPage('customers', <CustomerManagement />)}
          {currentPage === 'calendar' && renderProtectedPage('calendar', <DriverCalendar />)}
          {currentPage === 'fuel-logs' && renderProtectedPage('fuel-logs', <FuelLogs />)}
          {currentPage === 'my-performance' && renderProtectedPage('my-performance', <MyPerformance />)}
          {currentPage === 'report-fault' && (
            renderProtectedPage('report-fault', <ReportFault
              currentUser={currentUser}
              activeAssignment={driverActiveAssignment}
            />)
          )}
          {currentPage === 'fault-history' && renderProtectedPage('fault-history', <FaultHistory />)}
          {currentPage === 'notifications' && renderProtectedPage('notifications', <DriverNotifications />)}
          {currentPage === 'my-profile' && renderProtectedPage('my-profile', <DriverProfile currentUser={currentUser} />)}
        </DriverLayout>
      </>
    );
  }

  return <Login onLogin={handleLogin} />;
}
