import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  Bell,
  Building2,
  Calendar,
  ChevronDown,
  ClipboardList,
  DollarSign,
  FileBadge2,
  FileText,
  Fuel,
  Landmark,
  LayoutDashboard,
  LogOut,
  MapPin,
  PackageCheck,
  Pin,
  PinOff,
  Route,
  Receipt,
  Search,
  Settings,
  Shield,
  ShieldAlert,
  TimerReset,
  Truck,
  Users,
  UsersRound,
  Wrench,
} from 'lucide-react';
import type { UserRole } from '../../App';
import { filterAccessibleModules, type AppModule } from '../../lib/role-access';
import { SIDEBAR_COUNT_KEY_BY_MODULE, type WorkQueueModuleCount } from '../../lib/notification-count';

const LOGO_URL = 'https://imagedelivery.net/h9fmMoa1o2c2P55TcWJGOg/42b18599-8959-49b5-c7a2-b78a9602ce00/public';

interface SidebarProps {
  userRole: Extract<UserRole, 'owner' | 'admin' | 'dispatcher' | 'customer_service'>;
  activeSection?: string;
  onNavigate: (section: string) => void;
  isOpen: boolean;
  onToggle: () => void;
  onLogout: () => void;
  actionableCount?: number;
  actionableBadgeTone?: 'critical' | 'action_required' | 'reminder' | null;
  moduleCounts?: Record<string, WorkQueueModuleCount>;
  isCollapsed?: boolean;
  isPinned?: boolean;
  onPinToggle?: () => void;
  onPointerEnter?: () => void;
  onPointerLeave?: () => void;
}

type SidebarItem = {
  id: AppModule;
  label: string;
  icon: any;
  badge?: string;
  badgeTone?: 'critical' | 'action_required' | 'reminder';
  badgeDescription?: string;
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
      { id: 'vehicle-movements', label: 'Vehicle Movements', icon: Route },
      { id: 'dispatch-financials', label: 'Dispatch Financials', icon: FileBadge2 },
      { id: 'dispatch-opportunities', label: 'Dispatch Opportunities', icon: Search },
      { id: 'dispatch-returns', label: 'Vehicle Return & Handover', icon: TimerReset },
      { id: 'dispatch-requests', label: 'Dispatch Requests', icon: PackageCheck },
      { id: 'dispatch-planner', label: 'Dispatch Planner', icon: Calendar },
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
      { id: 'notifications', label: 'Notifications', icon: Bell },
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
  actionableCount = 0,
  actionableBadgeTone = null,
  moduleCounts = {},
  isCollapsed = false,
  isPinned = true,
  onPinToggle,
  onPointerEnter,
  onPointerLeave,
}: SidebarProps) {
  const [openSections, setOpenSections] = useState<Record<string, boolean>>(DEFAULT_OPEN_SECTIONS);
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
      SECTIONS.map((section) => ({
        ...section,
        items: filterAccessibleModules(userRole, section.items).map((item) => {
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
    [userRole, actionableCount, actionableBadgeTone, moduleCounts],
  );

  const canViewDashboard = Boolean(filterAccessibleModules(userRole, [DASHBOARD_ITEM]).length);
  const portalLabel =
    userRole === 'owner'
      ? 'Owner Portal'
      : userRole === 'admin'
      ? 'Admin Portal'
      : 'Operations Portal';

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
              <p className="text-xs text-gray-400">{portalLabel}</p>
            </div>}
            <button type="button" onClick={onPinToggle} className={`ml-auto hidden rounded p-2 text-gray-300 hover:bg-slate-800 hover:text-white lg:block ${isCollapsed ? 'absolute right-1 top-1' : ''}`} aria-label={isPinned ? 'Use auto-collapse sidebar' : 'Pin sidebar open'} title={isPinned ? 'Auto-collapse sidebar' : 'Pin sidebar'}>{isPinned ? <PinOff className="h-4 w-4" /> : <Pin className="h-4 w-4" />}</button>
          </div>
        </div>

        <nav className="flex-1 overflow-y-auto px-3 py-5">
          {canViewDashboard && (
            <div className="mb-5">
              <SidebarLink
                item={DASHBOARD_ITEM}
                isActive={activeSection === DASHBOARD_ITEM.id}
                onClick={handleNavigate}
                isCompact={isCollapsed}
              />
            </div>
          )}

          <div className="space-y-3">
            {visibleSections.map((section) => {
              const isExpanded = isCollapsed || (openSections[section.id] ?? true);
              const hasActiveItem = section.items.some((item) => item.id === activeSection);

              return (
                <div key={section.id} className={isCollapsed ? '' : 'rounded-xl border border-gray-800/70 bg-slate-900/30'}>
                  <button
                    onClick={() => toggleSection(section.id)}
                    className={`${isCollapsed ? 'hidden' : 'flex'} w-full items-center justify-between gap-3 px-3 py-3 text-left transition-all ${
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
                    <div className={isCollapsed ? 'py-1' : 'border-t border-gray-800/70 px-2 py-2'}>
                      {section.items.map((item) => (
                        <SidebarLink
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

function SidebarLink({
  item,
  isActive,
  onClick,
  isCompact = false,
}: {
  item: SidebarItem;
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
        <span
          aria-hidden="true"
          className={`${isCompact ? 'absolute right-0 top-0 min-w-4 px-1 text-[10px]' : 'px-2 py-0.5 text-xs'} rounded-full font-medium ${
            item.badge === 'Live' ? 'bg-[#10B981] text-white' : item.badgeTone === 'critical' ? 'bg-red-500 text-white' : item.badgeTone === 'reminder' ? 'bg-yellow-400 text-slate-900' : 'bg-orange-500 text-white'
          }`}
        >
          {item.badge}
        </span>
      )}
    </button>
  );
}
