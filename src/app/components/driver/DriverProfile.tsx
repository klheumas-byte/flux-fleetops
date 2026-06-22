import type { ElementType } from 'react';
import {
  Calendar,
  CreditCard,
  Mail,
  Phone,
  Shield,
  User,
} from 'lucide-react';
import {
  getAssignedVehicleLabel,
  getUserInitials,
  type SessionUser,
} from '../../lib/auth-session';

interface DriverProfileProps {
  currentUser: SessionUser | null;
}

function InfoRow({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: string;
  icon: ElementType;
}) {
  return (
    <div className="flex items-center gap-4 border-b border-gray-100 py-3.5 last:border-0">
      <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg bg-blue-50">
        <Icon className="h-[18px] w-[18px] text-blue-600" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="mb-0.5 text-xs text-gray-500">{label}</p>
        <p className="truncate text-sm text-gray-900">{value}</p>
      </div>
    </div>
  );
}

export default function DriverProfile({ currentUser }: DriverProfileProps) {
  const driverProfile = currentUser?.driver_profile || null;

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="relative overflow-hidden bg-gradient-to-br from-[#0F172A] via-[#1E3A5F] to-[#2563EB] px-6 pb-16 pt-8">
        <div className="absolute inset-0 opacity-10">
          <div className="absolute right-8 top-4 h-32 w-32 rounded-full bg-white/20 blur-xl" />
          <div className="absolute bottom-0 left-1/2 h-32 w-64 rounded-full bg-blue-300/30 blur-2xl" />
        </div>

        <div className="relative mx-auto max-w-2xl">
          <div className="flex flex-col items-center text-center">
            <div className="mb-4 flex h-24 w-24 items-center justify-center rounded-full border-4 border-white/20 bg-gradient-to-br from-blue-400 to-blue-600 shadow-xl">
              <span className="text-3xl font-semibold text-white">
                {getUserInitials(currentUser?.full_name || 'Driver')}
              </span>
            </div>

            <h1 className="mb-1 text-2xl font-semibold text-white">
              {currentUser?.full_name || 'Driver'}
            </h1>
            <p className="mb-3 text-sm text-blue-200">
              {currentUser?.phone || 'No phone'} · {currentUser?.email || 'No email'}
            </p>

            <div className="flex flex-wrap items-center justify-center gap-3">
              <div className="rounded-full bg-white/10 px-3 py-1.5 text-xs font-medium text-white backdrop-blur-sm capitalize">
                {currentUser?.role || 'driver'}
              </div>
              <div className="rounded-full bg-green-500/20 px-3 py-1.5 text-xs font-medium capitalize text-green-300 backdrop-blur-sm">
                {currentUser?.status || 'unknown'}
              </div>
              <div className="rounded-full bg-white/10 px-3 py-1.5 text-xs font-medium text-white backdrop-blur-sm">
                {getAssignedVehicleLabel(currentUser)}
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="mx-auto -mt-8 max-w-2xl px-4 pb-10">
        <div className="space-y-4">
          <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
            <h3 className="mb-1 text-sm font-semibold text-gray-900">Contact Details</h3>
            <p className="mb-4 text-xs text-gray-500">Real logged-in driver identity</p>
            <InfoRow label="Full Name" value={currentUser?.full_name || 'Not available'} icon={User} />
            <InfoRow label="Phone Number" value={currentUser?.phone || 'Not available'} icon={Phone} />
            <InfoRow label="Email Address" value={currentUser?.email || 'Not available'} icon={Mail} />
          </div>

          <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
            <h3 className="mb-1 text-sm font-semibold text-gray-900">Driver Account</h3>
            <p className="mb-4 text-xs text-gray-500">Verified from the authenticated backend session</p>
            <InfoRow label="Role" value={currentUser?.role || 'driver'} icon={Shield} />
            <InfoRow
              label="Account Status"
              value={currentUser?.status || 'unknown'}
              icon={Calendar}
            />
            <InfoRow
              label="Assigned Vehicle"
              value={getAssignedVehicleLabel(currentUser)}
              icon={CreditCard}
            />
          </div>

          <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
            <h3 className="mb-1 text-sm font-semibold text-gray-900">Driver Profile Fields</h3>
            <p className="mb-4 text-xs text-gray-500">Available from the current user record</p>
            <InfoRow
              label="Approval Status"
              value={driverProfile?.approval_status || 'Not available'}
              icon={Shield}
            />
            <InfoRow
              label="Assigned Vehicle ID"
              value={driverProfile?.assigned_vehicle_id || 'No vehicle assigned yet'}
              icon={CreditCard}
            />
          </div>

          <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
            <p className="text-sm text-amber-800">
              Wallet, trip history, documents, and performance metrics are intentionally not connected on this step.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
