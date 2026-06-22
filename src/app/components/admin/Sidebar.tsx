import { useMemo, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  Bell,
  Building2,
  ChevronDown,
  ClipboardList,
  DollarSign,
  FileText,
  Fuel,
  Landmark,
  LayoutDashboard,
  LogOut,
  MapPin,
  Receipt,
  Settings,
  Shield,
  ShieldAlert,
  TimerReset,
  Truck,
  Users,
  UsersRound,
  Wallet,
  Wrench,
} from 'lucide-react';
import type { UserRole } from '../../App';
import { filterAccessibleModules, type AppModule } from '../../lib/role-access';

const LOGO_URL = 'https://imagedelivery.net/h9fmMoa1o2c2P55TcWJGOg/42b18599-8959-49b5-c7a2-b78a9602ce00/public';

interface SidebarProps {
  userRole: Extract<UserRole, 'owner' | 'admin'>;
  activeSection?: string;
  onNavigate: (section: string) => void;
  isOpen: boolean;
  onToggle: () => void;
  onLogout: () => void;
}

type SidebarItem = {
  id: AppModule;
  label: string;
  icon: any;
  badge?: string;
};

type SidebarSection = {
  id: string;
  title: string;
  items: SidebarItem[];
};

const DASHBOARD_ITEM: SidebarItem = {
  id: 'dashboard',
  label: 'Dashboard',
  icon: LayoutDashboard,
};

const SECTIONS: SidebarSection[] = [
  {
    id: 'fleet-operations',
    title: 'Fleet Operations',
    items: [
      { id: 'vehicles', label: 'Vehicles', icon: Truck },
      { id: 'drivers', label: 'Drivers', icon: Users },
      { id: 'assignments', label: 'Assignments', icon: ClipboardList },
      { id: 'fleet-tracking', label: 'Fleet Tracking', icon: MapPin, badge: 'Live' },
    ],
  },
  {
    id: 'trips-customers',
    title: 'Trips & Customers',
    items: [
      { id: 'rides', label: 'Trip Logs', icon: MapPin },
      { id: 'customers', label: 'Customers', icon: UsersRound },
    ],
  },
  {
    id: 'finance',
    title: 'Finance',
    items: [
      { id: 'collections', label: 'Collections', icon: DollarSign },
      { id: 'deposits', label: 'Deposits', icon: Landmark },
      { id: 'driver-wallet', label: 'Driver Wallets', icon: Wallet },
      { id: 'finance-accounts', label: 'Finance Accounts', icon: Building2 },
      { id: 'expenses', label: 'Expenses', icon: Receipt },
    ],
  },
  {
    id: 'maintenance-compliance',
    title: 'Maintenance & Compliance',
    items: [
      { id: 'fault-approvals', label: 'Fault Approvals', icon: ShieldAlert },
      { id: 'incidents', label: 'Accidents & Incidents', icon: AlertTriangle },
      { id: 'maintenance', label: 'Maintenance Jobs', icon: Wrench },
      { id: 'preventive-maintenance', label: 'Preventive Maintenance', icon: TimerReset },
      { id: 'fuel', label: 'Fuel Management', icon: Fuel },
    ],
  },
  {
    id: 'performance-analytics',
    title: 'Performance & Analytics',
    items: [
      { id: 'driver-performance', label: 'Driver Performance', icon: Activity },
      { id: 'revenue', label: 'Vehicle Utilization', icon: DollarSign },
      { id: 'reports', label: 'Reports', icon: FileText },
    ],
  },
  {
    id: 'administration',
    title: 'Administration',
    items: [
      { id: 'accountability', label: 'Admin Accountability', icon: Landmark },
      { id: 'notifications', label: 'Notifications', icon: Bell, badge: '12' },
      { id: 'security', label: 'Security', icon: Shield },
      { id: 'settings', label: 'Settings', icon: Settings },
    ],
  },
];

const DEFAULT_OPEN_SECTIONS = SECTIONS.reduce<Record<string, boolean>>((accumulator, section) => {
  accumulator[section.id] = true;
  return accumulator;
}, {});

export default function Sidebar({
  userRole,
  activeSection = 'dashboard',
  onNavigate,
  isOpen,
  onToggle,
  onLogout,
}: SidebarProps) {
  const [openSections, setOpenSections] = useState<Record<string, boolean>>(DEFAULT_OPEN_SECTIONS);

  const visibleSections = useMemo(
    () =>
      SECTIONS.map((section) => ({
        ...section,
        items: filterAccessibleModules(userRole, section.items),
      })).filter((section) => section.items.length > 0),
    [userRole],
  );

  const canViewDashboard = Boolean(filterAccessibleModules(userRole, [DASHBOARD_ITEM]).length);
  const portalLabel = userRole === 'owner' ? 'Owner Portal' : 'Admin Portal';

  const handleNavigate = (section: string) => {
    onNavigate(section);
    if (typeof window !== 'undefined' && window.innerWidth < 1024) {
      onToggle();
    }
  };

  const toggleSection = (sectionId: string) => {
    setOpenSections((current) => ({
      ...current,
      [sectionId]: !current[sectionId],
    }));
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
              <p className="text-xs text-gray-400">{portalLabel}</p>
            </div>
          </div>
        </div>

        <nav className="flex-1 overflow-y-auto px-3 py-5">
          {canViewDashboard && (
            <div className="mb-5">
              <SidebarLink
                item={DASHBOARD_ITEM}
                isActive={activeSection === DASHBOARD_ITEM.id}
                onClick={handleNavigate}
              />
            </div>
          )}

          <div className="space-y-3">
            {visibleSections.map((section) => {
              const isExpanded = openSections[section.id] ?? true;
              const hasActiveItem = section.items.some((item) => item.id === activeSection);

              return (
                <div key={section.id} className="rounded-xl border border-gray-800/70 bg-slate-900/30">
                  <button
                    onClick={() => toggleSection(section.id)}
                    className={`flex w-full items-center justify-between gap-3 px-3 py-3 text-left transition-all ${
                      hasActiveItem ? 'text-white' : 'text-gray-300 hover:text-white'
                    }`}
                  >
                    <div>
                      <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-400">
                        {section.title}
                      </div>
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
                        <SidebarLink
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

function SidebarLink({
  item,
  isActive,
  onClick,
}: {
  item: SidebarItem;
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
        <span
          className={`rounded-full px-2 py-0.5 text-xs font-medium ${
            item.badge === 'Live' ? 'bg-[#10B981] text-white' : 'bg-[#EF4444] text-white'
          }`}
        >
          {item.badge}
        </span>
      )}
    </button>
  );
}
