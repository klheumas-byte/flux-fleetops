import { useMemo, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  Bell,
  Calendar,
  ChevronDown,
  Clock,
  Fuel,
  LayoutDashboard,
  LogOut,
  Plus,
  Truck,
  UserCircle,
  Users,
  Wallet,
} from 'lucide-react';
import {
  getAssignedVehicleLabel,
  getUserInitials,
  type SessionUser,
} from '../../lib/auth-session';
import type { DriverActiveAssignment } from '../../lib/driver-api';
import { filterAccessibleModules, type AppModule } from '../../lib/role-access';

const LOGO_URL =
  'https://imagedelivery.net/h9fmMoa1o2c2P55TcWJGOg/42b18599-8959-49b5-c7a2-b78a9602ce00/public';

interface DriverSidebarProps {
  currentUser: SessionUser | null;
  activeAssignment: DriverActiveAssignment | null;
  activeSection?: string;
  onNavigate: (section: string) => void;
  isOpen: boolean;
  onToggle: () => void;
  onLogout?: () => void;
}

type DriverSidebarItem = {
  id: AppModule;
  label: string;
  icon: any;
  badge?: string;
};

type DriverSidebarSection = {
  id: string;
  title: string;
  items: DriverSidebarItem[];
};

const DRIVER_DASHBOARD_ITEM: DriverSidebarItem = {
  id: 'dashboard',
  label: 'Dashboard',
  icon: LayoutDashboard,
};

const DRIVER_SECTIONS: DriverSidebarSection[] = [
  {
    id: 'daily-operations',
    title: 'Daily Operations',
    items: [
      { id: 'my-vehicle', label: 'My Vehicle', icon: Truck },
      { id: 'calendar', label: 'Scheduled Bookings', icon: Calendar },
      { id: 'create-ride', label: 'Log Trip', icon: Plus },
      { id: 'ride-history', label: 'Trip History', icon: Clock },
      { id: 'customers', label: 'Customers', icon: Users },
    ],
  },
  {
    id: 'wallet-fuel',
    title: 'Wallet & Fuel',
    items: [
      { id: 'my-wallet', label: 'My Wallet', icon: Wallet },
      { id: 'fuel-logs', label: 'Fuel Logs', icon: Fuel },
    ],
  },
  {
    id: 'performance-support',
    title: 'Performance & Support',
    items: [
      { id: 'my-performance', label: 'My Performance', icon: Activity },
      { id: 'report-fault', label: 'Report Fault', icon: AlertTriangle },
      { id: 'fault-history', label: 'Fault History', icon: Clock },
      { id: 'notifications', label: 'Notifications', icon: Bell, badge: '3' },
      { id: 'my-profile', label: 'My Profile', icon: UserCircle },
    ],
  },
];

const DRIVER_DEFAULT_OPEN = DRIVER_SECTIONS.reduce<Record<string, boolean>>((accumulator, section) => {
  accumulator[section.id] = true;
  return accumulator;
}, {});

export default function DriverSidebar({
  currentUser,
  activeAssignment,
  activeSection = 'dashboard',
  onNavigate,
  isOpen,
  onToggle,
  onLogout,
}: DriverSidebarProps) {
  const [openSections, setOpenSections] = useState<Record<string, boolean>>(DRIVER_DEFAULT_OPEN);

  const visibleSections = useMemo(
    () =>
      DRIVER_SECTIONS.map((section) => ({
        ...section,
        items: filterAccessibleModules('driver', section.items),
      })).filter((section) => section.items.length > 0),
    [],
  );

  const handleNavigate = (section: string) => {
    onNavigate(section);
    if (typeof window !== 'undefined' && window.innerWidth < 1024) {
      onToggle();
    }
  };

  return (
    <>
      {isOpen && (
        <div className="fixed inset-0 z-40 bg-black/50 lg:hidden" onClick={onToggle}></div>
      )}

      <div
        className={`fixed left-0 top-0 z-50 flex h-screen w-72 flex-col bg-[#0F172A] transition-transform duration-300 ease-in-out ${
          isOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="border-b border-gray-700/50 p-5">
          <div className="flex items-center gap-3">
            <img
              src={LOGO_URL}
              alt="Flux FleetOps"
              className="h-10 w-10 flex-shrink-0 rounded-full object-cover shadow-md"
            />
            <div>
              <h1 className="text-base font-semibold leading-tight text-white">Flux FleetOps</h1>
              <p className="text-xs text-gray-400">Driver Portal</p>
            </div>
          </div>
        </div>

        <nav className="flex-1 overflow-y-auto px-3 py-5">
          <div className="mb-5">
            <DriverSidebarLink
              item={DRIVER_DASHBOARD_ITEM}
              isActive={activeSection === DRIVER_DASHBOARD_ITEM.id}
              onClick={handleNavigate}
            />
          </div>

          <div className="space-y-3">
            {visibleSections.map((section) => {
              const isExpanded = openSections[section.id] ?? true;
              const hasActiveItem = section.items.some((item) => item.id === activeSection);

              return (
                <div key={section.id} className="rounded-xl border border-gray-800/70 bg-slate-900/30">
                  <button
                    onClick={() =>
                      setOpenSections((current) => ({
                        ...current,
                        [section.id]: !current[section.id],
                      }))
                    }
                    className={`flex w-full items-center justify-between gap-3 px-3 py-3 text-left transition-all ${
                      hasActiveItem ? 'text-white' : 'text-gray-300 hover:text-white'
                    }`}
                  >
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-400">
                      {section.title}
                    </div>
                    <ChevronDown
                      className={`h-4 w-4 flex-shrink-0 text-gray-400 transition-transform ${
                        isExpanded ? 'rotate-180' : ''
                      }`}
                    />
                  </button>

                  {isExpanded && (
                    <div className="border-t border-gray-800/70 px-2 py-2">
                      {section.items.map((item) => (
                        <DriverSidebarLink
                          key={item.id}
                          item={item}
                          isActive={activeSection === item.id}
                          onClick={handleNavigate}
                        />
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </nav>

        <div className="px-4 pb-4">
          <div className="rounded-xl border border-gray-700/60 bg-slate-800/80 px-3 py-3">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[#2563EB] text-sm font-semibold text-white">
                {getUserInitials(currentUser?.full_name || 'Driver')}
              </div>
              <div className="min-w-0">
                <div className="truncate text-sm font-medium text-white">
                  {currentUser?.full_name || 'Driver'}
                </div>
                <div className="text-xs capitalize text-gray-400">
                  {currentUser?.role || 'driver'}
                </div>
              </div>
            </div>
            <div className="mt-3 flex items-center justify-between text-xs">
              <span className="text-gray-400">Account</span>
              <span className="font-medium capitalize text-green-300">
                {currentUser?.status || 'unknown'}
              </span>
            </div>
            <div className="mt-2 text-xs text-gray-400">
              {getAssignedVehicleLabel(currentUser, activeAssignment)}
            </div>
          </div>
        </div>

        <div className="space-y-3 border-t border-gray-700/50 p-4">
          <button
            onClick={onLogout}
            className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-gray-300 transition-all hover:bg-red-600/10 hover:text-red-400"
          >
            <LogOut className="h-5 w-5" />
            <span className="flex-1 text-left text-sm font-medium">Logout</span>
          </button>
          <div className="text-center text-xs text-gray-500">(c) 2026 Flux Fleet</div>
        </div>
      </div>
    </>
  );
}

function DriverSidebarLink({
  item,
  isActive,
  onClick,
}: {
  item: DriverSidebarItem;
  isActive: boolean;
  onClick: (section: string) => void;
}) {
  const Icon = item.icon;

  return (
    <button
      onClick={() => onClick(item.id)}
      className={`mb-1 flex w-full items-center gap-3 rounded-lg px-3 py-2.5 transition-all ${
        isActive
          ? 'bg-[#2563EB] text-white'
          : 'text-gray-300 hover:bg-gray-800/50 hover:text-white'
      }`}
    >
      <Icon className="h-5 w-5" />
      <span className="flex-1 text-left text-sm font-medium">{item.label}</span>
      {item.badge && (
        <span className="rounded-full bg-[#EF4444] px-2 py-0.5 text-xs font-medium text-white">
          {item.badge}
        </span>
      )}
    </button>
  );
}
