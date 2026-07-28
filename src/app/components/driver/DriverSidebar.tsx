import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  Bell,
  Calendar,
  ChevronDown,
  Clock,
  ClipboardList,
  Fuel,
  LayoutDashboard,
  LogOut,
  PackageCheck,
  Plus,
  Pin,
  PinOff,
  Route,
  Search,
  Truck,
  UserCircle,
  Users,
  Wallet,
  WalletCards,
} from 'lucide-react';
import {
  getAssignedVehicleLabel,
  getUserInitials,
  type SessionUser,
} from '../../lib/auth-session';
import type { DriverActiveAssignment } from '../../lib/driver-api';
import { canDriverAccessModule, filterAccessibleModules, type AppModule } from '../../lib/role-access';
import { SIDEBAR_COUNT_KEY_BY_MODULE, type WorkQueueModuleCount } from '../../lib/notification-count';

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
  actionableCount?: number;
  actionableBadgeTone?: 'critical' | 'action_required' | 'reminder' | null;
  moduleCounts?: Record<string, WorkQueueModuleCount>;
  isCollapsed?: boolean;
  isPinned?: boolean;
  onPinToggle?: () => void;
  onPointerEnter?: () => void;
  onPointerLeave?: () => void;
}

type DriverSidebarItem = {
  id: AppModule;
  label: string;
  icon: any;
  badge?: string;
  badgeTone?: 'critical' | 'action_required' | 'reminder';
  badgeDescription?: string;
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
      { id: 'my-dispatch-opportunities', label: 'Dispatch Opportunities', icon: Search },
      { id: 'my-dispatches', label: 'My Dispatches', icon: Route },
      { id: 'my-operational-tasks', label: 'Operational Tasks', icon: ClipboardList },
      { id: 'digital-waybills', label: 'Digital Waybill', icon: PackageCheck },
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
      { id: 'my-earnings', label: 'My Earnings', icon: WalletCards },
      { id: 'my-dispatch-financials', label: 'Dispatch Financials', icon: WalletCards },
      { id: 'fuel-logs', label: 'Fuel Logs', icon: Fuel },
    ],
  },
  {
    id: 'performance-support',
    title: 'Performance & Support',
    items: [
      { id: 'my-performance', label: 'My Performance', icon: Activity },
      { id: 'incidents', label: 'Report Incident', icon: AlertTriangle },
      { id: 'report-fault', label: 'Report Fault', icon: AlertTriangle },
      { id: 'fault-history', label: 'Fault History', icon: Clock },
      { id: 'notifications', label: 'Notifications', icon: Bell },
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
  actionableCount = 0,
  actionableBadgeTone = null,
  moduleCounts = {},
  isCollapsed = false,
  isPinned = true,
  onPinToggle,
  onPointerEnter,
  onPointerLeave,
}: DriverSidebarProps) {
  const [openSections, setOpenSections] = useState<Record<string, boolean>>(DRIVER_DEFAULT_OPEN);
  const sidebarRef = useRef<HTMLDivElement>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);
  useEffect(() => {
    if (!isOpen || window.innerWidth >= 1024) return;
    restoreFocusRef.current = document.activeElement as HTMLElement;
    const sidebarElement = sidebarRef.current;
    sidebarElement?.querySelector<HTMLElement>('button')?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { onToggle(); return; }
      if (event.key !== 'Tab' || !sidebarElement) return;
      const focusable = [...sidebarElement.querySelectorAll<HTMLElement>('button:not([disabled]),a[href],input,select')];
      if (!focusable.length) return;
      const first = focusable[0]; const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => { document.removeEventListener('keydown', onKeyDown); restoreFocusRef.current?.focus(); };
  }, [isOpen, onToggle]);

  const visibleSections = useMemo(
    () =>
      DRIVER_SECTIONS.map((section) => ({
        ...section,
        items: filterAccessibleModules('driver', section.items)
          .filter((item) => canDriverAccessModule(currentUser?.driver_profile?.operating_mode, item.id))
          .filter((item) => item.id !== 'my-earnings' || currentUser?.driver_profile?.private_finance_enabled === true)
          .map((item) => {
          const countKey = SIDEBAR_COUNT_KEY_BY_MODULE[item.id];
          const result = countKey ? moduleCounts[countKey] : undefined;
          const count = result?.status === 'ok' ? Number(result.count) || 0 : 0;
          const criticalText = result?.critical_count ? `, including ${result.critical_count} critical` : '';
          return result
            ? { ...item, badge: count > 0 ? (count > 99 ? '99+' : String(count)) : undefined, badgeTone: result.priority || undefined, badgeDescription: `${count} ${item.label.toLowerCase()} require action${criticalText}` }
            : item.id === 'notifications'
            ? { ...item, badge: actionableCount > 0 ? String(actionableCount) : undefined, badgeTone: actionableBadgeTone || undefined }
            : item;
        }),
      })).filter((section) => section.items.length > 0),
    [actionableCount, actionableBadgeTone, currentUser?.driver_profile?.operating_mode, currentUser?.driver_profile?.private_finance_enabled, moduleCounts],
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
        ref={sidebarRef}
        onPointerEnter={onPointerEnter}
        onPointerLeave={onPointerLeave}
        className={`fixed left-0 top-0 z-50 flex h-screen w-72 flex-col bg-[#0F172A] transition-[width,transform] duration-300 motion-reduce:transition-none lg:translate-x-0 ${isCollapsed ? 'lg:w-20' : 'lg:w-72'} ${
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
            {!isCollapsed && <div>
              <h1 className="text-base font-semibold leading-tight text-white">Flux FleetOps</h1>
              <p className="text-xs text-gray-400">Driver Portal</p>
            </div>}
            <button type="button" onClick={onPinToggle} className={`ml-auto hidden rounded p-2 text-gray-300 hover:bg-slate-800 hover:text-white lg:block ${isCollapsed ? 'absolute right-1 top-1' : ''}`} aria-label={isPinned ? 'Use auto-collapse sidebar' : 'Pin sidebar open'} title={isPinned ? 'Auto-collapse sidebar' : 'Pin sidebar'}>{isPinned ? <PinOff className="h-4 w-4" /> : <Pin className="h-4 w-4" />}</button>
          </div>
        </div>

        <nav className="flex-1 overflow-y-auto px-3 py-5">
          <div className="mb-5">
            <DriverSidebarLink
              item={DRIVER_DASHBOARD_ITEM}
              isActive={activeSection === DRIVER_DASHBOARD_ITEM.id}
              onClick={handleNavigate}
              isCompact={isCollapsed}
            />
          </div>

          <div className="space-y-3">
            {visibleSections.map((section) => {
              const isExpanded = isCollapsed || (openSections[section.id] ?? true);
              const hasActiveItem = section.items.some((item) => item.id === activeSection);

              return (
                <div key={section.id} className={isCollapsed ? '' : 'rounded-xl border border-gray-800/70 bg-slate-900/30'}>
                  <button
                    onClick={() =>
                      setOpenSections((current) => ({
                        ...current,
                        [section.id]: !current[section.id],
                      }))
                    }
                    className={`${isCollapsed ? 'hidden' : 'flex'} w-full items-center justify-between gap-3 px-3 py-3 text-left transition-all ${
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
                    <div className={isCollapsed ? 'py-1' : 'border-t border-gray-800/70 px-2 py-2'}>
                      {section.items.map((item) => (
                        <DriverSidebarLink
                          key={item.id}
                          item={item}
                          isActive={activeSection === item.id}
                          onClick={handleNavigate}
                          isCompact={isCollapsed}
                        />
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </nav>

        {!isCollapsed && <div className="px-4 pb-4">
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
        </div>}

        <div className="space-y-3 border-t border-gray-700/50 p-4">
          <button
            onClick={onLogout}
            className={`flex w-full items-center rounded-lg px-3 py-2.5 text-gray-300 transition-all hover:bg-red-600/10 hover:text-red-400 ${isCollapsed ? 'justify-center' : 'gap-3'}`}
          >
            <LogOut className="h-5 w-5" />
            {!isCollapsed && <span className="flex-1 text-left text-sm font-medium">Logout</span>}
          </button>
          {!isCollapsed && <div className="text-center text-xs text-gray-500">(c) 2026 Flux Fleet</div>}
        </div>
      </div>
    </>
  );
}

function DriverSidebarLink({
  item,
  isActive,
  onClick,
  isCompact = false,
}: {
  item: DriverSidebarItem;
  isActive: boolean;
  onClick: (section: string) => void;
  isCompact?: boolean;
}) {
  const Icon = item.icon;

  return (
    <button
      onClick={() => {
        if (item.badge) sessionStorage.setItem('flux_work_queue_filter', JSON.stringify({ module: item.id, filter: 'needs_action', createdAt: Date.now() }));
        onClick(item.id);
      }}
      title={item.badgeDescription || item.label}
      aria-label={item.badgeDescription ? `${item.label}: ${item.badgeDescription}` : item.label}
      className={`relative mb-1 flex w-full items-center rounded-lg px-3 py-2.5 transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 ${isCompact ? 'justify-center' : 'gap-3'} ${
        isActive
          ? 'bg-[#2563EB] text-white'
          : 'text-gray-300 hover:bg-gray-800/50 hover:text-white'
      }`}
    >
      <Icon className="h-5 w-5" />
      {!isCompact && <span className="flex-1 text-left text-sm font-medium">{item.label}</span>}
      {item.badge && (
        <span aria-hidden="true" className={`${isCompact ? 'absolute right-0 top-0 min-w-4 px-1 text-[10px]' : 'px-2 py-0.5 text-xs'} rounded-full font-medium ${item.badgeTone === 'critical' ? 'bg-red-500 text-white' : item.badgeTone === 'reminder' ? 'bg-yellow-400 text-slate-900' : 'bg-orange-500 text-white'}`}>
          {item.badge}
        </span>
      )}
    </button>
  );
}
