import { Bell, ChevronDown, Menu } from 'lucide-react';
import {
  getAssignedVehicleLabel,
  getUserInitials,
  type SessionUser,
} from '../../lib/auth-session';
import type { DriverActiveAssignment } from '../../lib/driver-api';

const LOGO_URL =
  'https://imagedelivery.net/h9fmMoa1o2c2P55TcWJGOg/42b18599-8959-49b5-c7a2-b78a9602ce00/public';

interface DriverTopNavProps {
  currentUser: SessionUser | null;
  activeAssignment: DriverActiveAssignment | null;
  onMenuToggle: () => void;
  onNavigate: (section: string) => void;
  actionableCount: number;
}

export default function DriverTopNav({
  currentUser,
  activeAssignment,
  onMenuToggle,
  onNavigate,
  actionableCount,
}: DriverTopNavProps) {
  return (
    <div className="flex h-16 min-w-0 items-center justify-between border-b border-gray-200 bg-white px-4 sm:px-6">
      <div className="flex min-w-0 items-center gap-3">
        <button
          onClick={onMenuToggle}
          className="rounded-lg p-2 transition-colors hover:bg-gray-100"
        >
          <Menu className="h-5 w-5 text-gray-600" />
        </button>
        <img
          src={LOGO_URL}
          alt="Flux FleetOps"
          className="h-8 w-8 rounded-full object-cover lg:hidden"
        />
        <span className="text-base font-semibold text-gray-900 lg:hidden">Flux FleetOps</span>
      </div>

      <div className="flex min-w-0 items-center gap-2 sm:gap-4">
        <button onClick={() => onNavigate('notifications')} aria-label={`Notifications${actionableCount ? `, ${actionableCount} actions pending` : ''}`} className="relative rounded-lg p-2 transition-colors hover:bg-gray-100">
          <Bell className="h-5 w-5 text-gray-600" />
          {actionableCount > 0 && <span aria-hidden="true" className="absolute right-0 top-0 min-w-4 rounded-full bg-orange-500 px-1 text-[10px] font-semibold leading-4 text-white">{actionableCount > 99 ? '99+' : actionableCount}</span>}
        </button>

        <div className="flex min-w-0 items-center gap-2 border-l border-gray-200 pl-2 sm:gap-3 sm:pl-4">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-blue-500 to-purple-500 font-semibold text-white">
            {getUserInitials(currentUser?.full_name || 'Driver')}
          </div>
          <div className="hidden min-w-0 items-center gap-2 sm:flex">
            <div className="min-w-0">
              <div className="truncate text-sm font-medium text-gray-900">
                {currentUser?.full_name || 'Driver'}
              </div>
              <div className="truncate text-xs text-gray-500">
                {getAssignedVehicleLabel(currentUser, activeAssignment)}
              </div>
            </div>
            <div className="rounded bg-green-100 px-2 py-0.5 text-xs font-medium capitalize text-green-800">
              {currentUser?.role || 'driver'}
            </div>
            <div className="hidden rounded bg-gray-100 px-2 py-0.5 text-xs font-medium capitalize text-gray-700 md:block">
              {currentUser?.status || 'unknown'}
            </div>
            <ChevronDown className="h-4 w-4 text-gray-400" />
          </div>
        </div>
      </div>
    </div>
  );
}
