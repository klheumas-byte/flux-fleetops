import { Bell, ChevronDown, Menu, Plug, Search, User } from 'lucide-react';
import type { UserRole } from '../../App';
import type { SessionUser } from '../../lib/auth-session';
import { canManageSmartLiving } from '../../lib/role-access';
import WorkspaceSwitcher from '../shared/WorkspaceSwitcher';

const LOGO_URL = 'https://imagedelivery.net/h9fmMoa1o2c2P55TcWJGOg/42b18599-8959-49b5-c7a2-b78a9602ce00/public';

interface TopNavProps {
  userRole: UserRole;
  activeSection?: string;
  onMenuToggle: () => void;
  onNavigate: (section: string) => void;
  unreadCount: number;
  currentUser?: SessionUser | null;
}

export default function TopNav({ userRole, currentUser, activeSection = 'dashboard', onMenuToggle, onNavigate, unreadCount }: TopNavProps) {
  const showSmartLiving = canManageSmartLiving(userRole);
  const operationalName = String(userRole).split('_').map(part => part[0]?.toUpperCase() + part.slice(1)).join(' ');
  const displayedProfile = currentUser
    ? { name: currentUser.full_name, email: currentUser.email || currentUser.username || currentUser.phone, badge: currentUser.role_name || operationalName }
    : { name: operationalName, email: 'Flux FleetOps', badge: operationalName };
  const pageTitle = activeSection.replaceAll('-', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());

  return <header className="sticky top-0 z-30 flex h-14 min-w-0 items-center justify-between gap-2 overflow-x-hidden border-b border-gray-200 bg-white/95 px-3 backdrop-blur sm:h-16 sm:px-4 lg:px-6">
    <div className="flex min-w-0 flex-1 items-center gap-2 sm:gap-4 lg:max-w-2xl">
      <button onClick={onMenuToggle} className="hidden rounded-lg p-2 transition-colors hover:bg-gray-100 lg:block" aria-label="Toggle navigation"><Menu className="h-5 w-5 text-gray-600" /></button>
      <img src={LOGO_URL} alt="" className="h-8 w-8 flex-shrink-0 rounded-full object-cover lg:hidden" />
      <h1 className="min-w-0 flex-1 truncate text-sm font-semibold text-slate-900 sm:text-base lg:hidden">{pageTitle}</h1>
      <div className="relative hidden min-w-0 flex-1 lg:block"><Search className="absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-gray-400" /><input type="search" placeholder="Search vehicles, drivers, trips, revenue…" className="w-full min-w-0 truncate rounded-lg border border-gray-200 bg-gray-50 py-2 pl-10 pr-4 text-sm outline-none focus:ring-2 focus:ring-blue-500" /></div>
    </div>
    <div className="flex min-w-0 items-center gap-1 sm:ml-4 sm:gap-3">
      {showSmartLiving && (
        <button
          type="button"
          onClick={() => onNavigate('smart-living-integration')}
          className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-blue-600 px-3 text-sm font-semibold text-white hover:bg-blue-700"
          aria-label="Open SmartLiving Integration"
          title="SmartLiving Integration"
        >
          <Plug className="h-4 w-4" />
          <span className="hidden xl:inline">SmartLiving</span>
        </button>
      )}
      <button aria-label={`Notifications${unreadCount ? `, ${unreadCount} unread` : ''}`} onClick={() => onNavigate('notifications')} className="relative rounded-lg p-2 hover:bg-gray-100"><Bell className="h-5 w-5 text-gray-600" />{unreadCount > 0 && <span className="absolute right-0 top-0 min-w-4 animate-pulse rounded-full bg-orange-500 px-1 text-center text-[10px] font-semibold leading-4 text-white [animation-iteration-count:3] motion-reduce:animate-none">{unreadCount > 99 ? '99+' : unreadCount}</span>}</button>
      <div className="flex min-w-0 items-center gap-2 border-l border-gray-200 pl-2 sm:gap-3 sm:pl-4">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-600"><User className="h-5 w-5 text-white" /></div>
        <div className="flex min-w-0 items-center gap-2">
          <div className="hidden min-w-0 sm:block"><div className="truncate text-sm font-medium text-gray-900">{displayedProfile.name}</div><div className="truncate text-xs text-gray-500">{displayedProfile.email}</div></div>
          <div className="hidden rounded bg-blue-600 px-2 py-0.5 text-xs font-medium text-white md:block">{displayedProfile.badge}</div>
          {currentUser?.branch && <div className="hidden rounded bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700 lg:block">{currentUser.branch}</div>}
          <WorkspaceSwitcher user={currentUser} className="[&_select]:max-w-24 sm:[&_select]:max-w-40" />
          <ChevronDown className="hidden h-4 w-4 text-gray-400 sm:block" />
        </div>
      </div>
    </div>
  </header>;
}
