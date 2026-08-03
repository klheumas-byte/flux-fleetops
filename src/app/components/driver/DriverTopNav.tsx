import { Bell, ChevronDown, Menu } from 'lucide-react';
import { getAssignedVehicleLabel, getUserInitials, type SessionUser } from '../../lib/auth-session';
import type { DriverActiveAssignment } from '../../lib/driver-api';
import WorkspaceSwitcher from '../shared/WorkspaceSwitcher';

const LOGO_URL = 'https://imagedelivery.net/h9fmMoa1o2c2P55TcWJGOg/42b18599-8959-49b5-c7a2-b78a9602ce00/public';

interface DriverTopNavProps {
  currentUser: SessionUser | null;
  activeAssignment: DriverActiveAssignment | null;
  activeSection?: string;
  onMenuToggle: () => void;
  onNavigate: (section: string) => void;
  unreadCount: number;
}

export default function DriverTopNav({ currentUser, activeAssignment, activeSection = 'dashboard', onMenuToggle, onNavigate, unreadCount }: DriverTopNavProps) {
  const pageTitle = activeSection.replaceAll('-', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
  return (
    <header className="sticky top-0 z-30 flex h-14 min-w-0 items-center justify-between border-b border-gray-200 bg-white/95 px-3 backdrop-blur sm:h-16 sm:px-6">
      <div className="flex min-w-0 items-center gap-3">
        <button onClick={onMenuToggle} className="hidden rounded-lg p-2 transition-colors hover:bg-gray-100 lg:block" aria-label="Toggle navigation"><Menu className="h-5 w-5 text-gray-600" /></button>
        <img src={LOGO_URL} alt="" className="h-8 w-8 rounded-full object-cover lg:hidden" />
        <span className="truncate text-sm font-semibold text-gray-900 sm:text-base lg:hidden">{pageTitle}</span>
      </div>
      <div className="flex min-w-0 items-center gap-1 sm:gap-4">
        <WorkspaceSwitcher user={currentUser} className="[&_select]:max-w-24 sm:[&_select]:max-w-40" />
        <button onClick={() => onNavigate('notifications')} aria-label={`Notifications${unreadCount ? `, ${unreadCount} unread` : ''}`} className="relative rounded-lg p-2 transition-colors hover:bg-gray-100">
          <Bell className="h-5 w-5 text-gray-600" />
          {unreadCount > 0 && <span aria-hidden="true" className="absolute right-0 top-0 min-w-4 animate-pulse rounded-full bg-orange-500 px-1 text-[10px] font-semibold leading-4 text-white [animation-iteration-count:3] motion-reduce:animate-none">{unreadCount > 99 ? '99+' : unreadCount}</span>}
        </button>
        <div className="flex min-w-0 items-center gap-2 border-l border-gray-200 pl-2 sm:gap-3 sm:pl-4">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-blue-500 to-purple-500 font-semibold text-white">{getUserInitials(currentUser?.full_name || 'Driver')}</div>
          <div className="hidden min-w-0 items-center gap-2 sm:flex">
            <div className="min-w-0"><div className="truncate text-sm font-medium text-gray-900">{currentUser?.full_name || 'Driver'}</div><div className="truncate text-xs text-gray-500">{getAssignedVehicleLabel(currentUser, activeAssignment)}</div></div>
            <div className="rounded bg-green-100 px-2 py-0.5 text-xs font-medium capitalize text-green-800">{currentUser?.role_name || currentUser?.selected_workspace || 'driver'}</div>
            <div className="hidden rounded bg-gray-100 px-2 py-0.5 text-xs font-medium capitalize text-gray-700 md:block">{currentUser?.status || 'unknown'}</div>
            <ChevronDown className="h-4 w-4 text-gray-400" />
          </div>
        </div>
      </div>
    </header>
  );
}
