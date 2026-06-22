import { Search, Bell, User, ChevronDown, Menu } from 'lucide-react';
import type { UserRole } from '../../App';

const LOGO_URL = 'https://imagedelivery.net/h9fmMoa1o2c2P55TcWJGOg/42b18599-8959-49b5-c7a2-b78a9602ce00/public';

interface TopNavProps {
  userRole: Extract<UserRole, 'owner' | 'admin'>;
  onMenuToggle: () => void;
}

export default function TopNav({ userRole, onMenuToggle }: TopNavProps) {
  const profile =
    userRole === 'owner'
      ? {
          name: 'Owner User',
          email: 'owner@fluxfleet.com',
          badge: 'Owner',
        }
      : {
          name: 'Admin User',
          email: 'admin@fluxfleet.com',
          badge: 'Admin',
        };

  return (
    <div className="flex h-16 min-w-0 items-center justify-between gap-3 overflow-x-hidden border-b border-gray-200 bg-white px-3 sm:px-4 lg:px-6">
      {/* Menu Toggle & Search */}
      <div className="flex min-w-0 flex-1 items-center gap-2 sm:gap-4 lg:max-w-2xl">
        <button
          onClick={onMenuToggle}
          className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
        >
          <Menu className="w-5 h-5 text-gray-600" />
        </button>
        <img
          src={LOGO_URL}
          alt="Flux FleetOps"
          className="w-8 h-8 rounded-full object-cover lg:hidden flex-shrink-0"
        />
        <div className="relative min-w-0 flex-1">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" />
          <input
            type="text"
            placeholder="Search vehicles, drivers, trips, revenue..."
            className="w-full min-w-0 truncate rounded-lg border border-gray-200 bg-gray-50 py-2 pl-10 pr-4 text-sm focus:border-transparent focus:outline-none focus:ring-2 focus:ring-[#2563EB]"
          />
        </div>
      </div>

      {/* Right Section */}
      <div className="ml-2 flex min-w-0 items-center gap-2 sm:ml-4 sm:gap-4">
        {/* Notifications */}
        <button className="relative p-2 hover:bg-gray-100 rounded-lg transition-colors">
          <Bell className="w-5 h-5 text-gray-600" />
          <span className="absolute top-1 right-1 w-2 h-2 bg-[#EF4444] rounded-full"></span>
        </button>

        {/* User Profile */}
        <div className="flex min-w-0 items-center gap-2 border-l border-gray-200 pl-2 sm:gap-3 sm:pl-4">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#2563EB]">
            <User className="w-5 h-5 text-white" />
          </div>
          <div className="flex min-w-0 items-center gap-2">
            <div className="hidden min-w-0 sm:block">
              <div className="truncate text-sm font-medium text-gray-900">{profile.name}</div>
              <div className="truncate text-xs text-gray-500">{profile.email}</div>
            </div>
            <div className="hidden rounded bg-[#2563EB] px-2 py-0.5 text-xs font-medium text-white md:block">
              {profile.badge}
            </div>
            <ChevronDown className="w-4 h-4 text-gray-400" />
          </div>
        </div>
      </div>
    </div>
  );
}
