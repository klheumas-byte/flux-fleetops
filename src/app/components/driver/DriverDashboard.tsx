import { useEffect, useState } from 'react';
import {
  AlertCircle,
  CarFront,
  Calendar,
  CheckCircle,
  Clock,
  Fuel,
  Navigation,
  Plus,
  Target,
  Wallet,
} from 'lucide-react';
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import {
  getAssignedVehicleLabel,
  type SessionUser,
} from '../../lib/auth-session';
import type { DriverActiveAssignment, DriverDashboardSummary } from '../../lib/driver-api';
import { apiRequestSafe } from '../../lib/api';
import type { BookingSummary } from '../../lib/customer-booking-api';

interface DriverDashboardProps {
  currentUser: SessionUser | null;
  activeAssignment: DriverActiveAssignment | null;
  dashboardSummary: DriverDashboardSummary | null;
}

function formatCurrency(value: number) {
  return `GHS ${value.toLocaleString()}`;
}

export default function DriverDashboard({
  currentUser,
  activeAssignment,
  dashboardSummary,
}: DriverDashboardProps) {
  const [bookingSummary, setBookingSummary] = useState<BookingSummary | null>(null);
  const [bookingSummaryError, setBookingSummaryError] = useState('');
  const [bookingSummaryNotice, setBookingSummaryNotice] = useState('');

  const loadBookingSummary = async () => {
      setBookingSummaryError('');
      setBookingSummaryNotice('');
      const response = await apiRequestSafe<{ data: { summary: BookingSummary } }>('/bookings/summary', {
        fallbackData: { data: { summary: null as unknown as BookingSummary } },
        cacheTtlMs: 15000,
      });
      setBookingSummary(response.data?.data?.summary || null);
      if (!response.ok) {
        setBookingSummaryError(response.error || 'Unable to load booking insights right now.');
      } else if (!response.data?.data?.summary) {
        setBookingSummaryNotice('No booking insights are available yet.');
      }
  };

  useEffect(() => {
    void loadBookingSummary();
  }, []);

  const stats = {
    weeklyTarget: dashboardSummary?.weekly_target || 0,
    amountPaid: dashboardSummary?.approved_total_this_week || dashboardSummary?.amount_paid_this_week || 0,
    submittedTotal: dashboardSummary?.submitted_total_this_week || 0,
    outstandingBalance: dashboardSummary?.outstanding_balance || 0,
    todaysCollections: dashboardSummary?.today_collection_total || 0,
    dailyTarget: dashboardSummary?.daily_target || 0,
    achievementPercentage: dashboardSummary?.achievement_percentage || 0,
  };

  const weeklyProgress = [
    { day: 'Mon', revenue: 0, trips: 0 },
    { day: 'Tue', revenue: 0, trips: 0 },
    { day: 'Wed', revenue: 0, trips: 0 },
    { day: 'Thu', revenue: 0, trips: 0 },
    { day: 'Fri', revenue: 0, trips: 0 },
    { day: 'Sat', revenue: 0, trips: 0 },
    { day: 'Sun', revenue: 0, trips: 0 },
  ];

  const quickActions = [
    { label: 'Create Booking', icon: Plus, color: 'bg-blue-500' },
    { label: 'Create Reminder', icon: Clock, color: 'bg-purple-500' },
    { label: 'Schedule Follow-Up', icon: Calendar, color: 'bg-amber-500' },
    { label: 'View Calendar', icon: Navigation, color: 'bg-green-500' },
  ];

  const assignedVehicleLabel = getAssignedVehicleLabel(currentUser, activeAssignment);
  const assignmentStatus = activeAssignment?.status || 'not assigned';

  return (
    <div className="space-y-6 p-6">
      <div className="rounded-lg bg-gradient-to-r from-blue-600 to-purple-600 p-6 text-white">
        <h1 className="mb-2 text-2xl font-semibold">
          Welcome back, {currentUser?.full_name || 'Driver'}!
        </h1>
        <p className="text-blue-100">Your portal now reflects your real active assignment, vehicle, and weekly financial summary.</p>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <div className="rounded-lg bg-white/20 px-3 py-1.5 backdrop-blur-sm">
            <span className="text-sm font-medium">Vehicle: {assignedVehicleLabel}</span>
          </div>
          <div className="rounded-lg bg-white/20 px-3 py-1.5 backdrop-blur-sm">
            <span className="text-sm font-medium capitalize">Assignment: {assignmentStatus}</span>
          </div>
          <div className="flex items-center gap-1.5 rounded-lg bg-green-500/20 px-3 py-1.5 backdrop-blur-sm">
            <div className="h-2 w-2 rounded-full bg-green-400"></div>
            <span className="text-sm font-medium capitalize">{currentUser?.status || 'unknown'}</span>
          </div>
          <div className="rounded-lg bg-white/20 px-3 py-1.5 backdrop-blur-sm">
            <span className="text-sm font-medium capitalize">Role: {currentUser?.role || 'driver'}</span>
          </div>
          <div className="rounded-lg bg-white/20 px-3 py-1.5 backdrop-blur-sm">
            <span className="text-sm font-medium">
              Deadline: {dashboardSummary?.weekly_cycle?.payment_deadline || 'N/A'}
            </span>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-4">
        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-blue-100">
            <Target className="h-6 w-6 text-blue-600" />
          </div>
          <div className="mb-2 text-3xl font-semibold text-gray-900">
            {formatCurrency(stats.weeklyTarget)}
          </div>
          <div className="text-sm text-gray-600">Weekly Target</div>
          <div className="mt-2 text-xs text-gray-500">From your active assignment</div>
        </div>

        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-green-100">
            <Wallet className="h-6 w-6 text-green-600" />
          </div>
          <div className="mb-2 text-3xl font-semibold text-green-600">
            {formatCurrency(stats.amountPaid)}
          </div>
          <div className="text-sm text-gray-600">Approved Total</div>
          <div className="mt-2 text-xs text-gray-500">
            {dashboardSummary?.total_collections_this_week || 0} collections this week
          </div>
        </div>

        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-red-100">
            <AlertCircle className="h-6 w-6 text-red-600" />
          </div>
          <div className="mb-2 text-3xl font-semibold text-red-600">
            {formatCurrency(stats.outstandingBalance)}
          </div>
          <div className="text-sm text-gray-600">Outstanding Balance</div>
          <div className="mt-2 text-xs text-gray-500">Weekly target minus payments this week</div>
        </div>

        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-purple-100">
            <CarFront className="h-6 w-6 text-purple-600" />
          </div>
          <div className="mb-2 text-3xl font-semibold text-gray-900">
            {formatCurrency(stats.todaysCollections)}
          </div>
          <div className="text-sm text-gray-600">Today&apos;s Collections</div>
          <div className="mt-2 text-xs text-gray-500">0 when nothing has been recorded today</div>
        </div>
      </div>

      {bookingSummaryError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <span>{bookingSummaryError}</span>
            <button
              onClick={() => void loadBookingSummary()}
              className="rounded-lg border border-red-200 bg-white px-3 py-2 text-xs font-medium text-red-700 hover:bg-red-100"
            >
              Retry
            </button>
          </div>
        </div>
      )}

      {bookingSummaryNotice && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          {bookingSummaryNotice}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        {[
          { label: 'Scheduled Today', value: bookingSummary?.scheduled_today ?? 0, icon: Calendar, tint: 'bg-blue-100 text-blue-600' },
          { label: 'Upcoming Bookings', value: bookingSummary?.upcoming_bookings ?? 0, icon: Navigation, tint: 'bg-emerald-100 text-emerald-600' },
          { label: 'Overdue Reminders', value: bookingSummary?.overdue_reminders ?? 0, icon: Clock, tint: 'bg-rose-100 text-rose-600' },
          { label: 'Follow-Ups Due Today', value: bookingSummary?.follow_ups_due_today ?? 0, icon: CheckCircle, tint: 'bg-amber-100 text-amber-600' },
        ].map((card) => {
          const Icon = card.icon;
          return (
            <div key={card.label} className="rounded-lg border border-gray-200 bg-white p-5">
              <div className={`mb-4 flex h-11 w-11 items-center justify-center rounded-xl ${card.tint}`}>
                <Icon className="h-5 w-5" />
              </div>
              <div className="text-3xl font-semibold text-[#0F172A]">{card.value}</div>
              <div className="mt-1 text-sm text-gray-500">{card.label}</div>
            </div>
          );
        })}
      </div>

      <div className="rounded-lg border border-gray-200 bg-white p-6">
        <h3 className="mb-4 text-lg font-semibold text-gray-900">Quick Actions</h3>
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          {quickActions.map((action) => {
            const Icon = action.icon;
            return (
              <button
                key={action.label}
                className="flex flex-col items-center gap-3 rounded-lg bg-gray-50 p-6 transition-colors hover:bg-gray-100"
              >
                <div className={`flex h-12 w-12 items-center justify-center rounded-lg ${action.color}`}>
                  <Icon className="h-6 w-6 text-white" />
                </div>
                <span className="text-sm font-medium text-gray-900">{action.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <h3 className="mb-4 text-lg font-semibold text-gray-900">Weekly Revenue</h3>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={weeklyProgress}>
              <CartesianGrid stroke="#f0f0f0" strokeDasharray="3 3" />
              <XAxis dataKey="day" stroke="#6b7280" />
              <YAxis stroke="#6b7280" />
              <Tooltip />
              <Legend />
              <Bar dataKey="revenue" fill="#10B981" name="Revenue (GHS)" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <h3 className="mb-4 text-lg font-semibold text-gray-900">Driver Summary</h3>
          <div className="space-y-4">
            <div className="flex items-center gap-3 rounded-lg bg-gray-50 p-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-100">
                <Navigation className="h-5 w-5 text-blue-600" />
              </div>
              <div>
                <div className="text-sm font-medium text-gray-900">Logged-in Driver</div>
                <div className="text-sm text-gray-500">{currentUser?.full_name || 'Driver'}</div>
              </div>
            </div>
            <div className="flex items-center gap-3 rounded-lg bg-gray-50 p-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-green-100">
                <CheckCircle className="h-5 w-5 text-green-600" />
              </div>
              <div>
                <div className="text-sm font-medium text-gray-900">Account Status</div>
                <div className="text-sm capitalize text-gray-500">{currentUser?.status || 'unknown'}</div>
              </div>
            </div>
            <div className="flex items-center gap-3 rounded-lg bg-gray-50 p-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-purple-100">
                <Wallet className="h-5 w-5 text-purple-600" />
              </div>
              <div>
                <div className="text-sm font-medium text-gray-900">Assigned Vehicle</div>
                <div className="text-sm text-gray-500">{assignedVehicleLabel}</div>
              </div>
            </div>
            <div className="flex items-center gap-3 rounded-lg bg-gray-50 p-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-red-100">
                <Target className="h-5 w-5 text-red-600" />
              </div>
              <div>
                <div className="text-sm font-medium text-gray-900">Targets</div>
                <div className="text-sm text-gray-500">
                  Weekly {formatCurrency(stats.weeklyTarget)} / Daily {formatCurrency(stats.dailyTarget)}
                </div>
              </div>
            </div>
            <div className="flex items-center gap-3 rounded-lg bg-gray-50 p-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-amber-100">
                <CheckCircle className="h-5 w-5 text-amber-600" />
              </div>
              <div>
                <div className="text-sm font-medium text-gray-900">Week Cycle</div>
                <div className="text-sm text-gray-500">
                  Submitted {formatCurrency(stats.submittedTotal)} / Approved {formatCurrency(stats.amountPaid)}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="rounded-lg border border-gray-200 bg-white">
        <div className="border-b border-gray-200 p-6">
          <h3 className="text-lg font-semibold text-gray-900">Latest Collections</h3>
        </div>
        {dashboardSummary?.latest_collections?.length ? (
          <div className="divide-y divide-gray-200">
            {dashboardSummary.latest_collections.map((collection) => (
              <div key={collection.id} className="flex items-center justify-between gap-4 px-6 py-4">
                <div>
                  <div className="text-sm font-medium text-gray-900 capitalize">
                    {collection.payment_method} collection
                  </div>
                  <div className="text-xs text-gray-500">
                    {collection.collection_date} / {collection.status}
                  </div>
                </div>
                <div className="text-sm font-semibold text-green-600">
                  {formatCurrency(collection.amount || 0)}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="px-6 py-10 text-center text-gray-500">
            No collections recorded yet for this week.
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <div className="mb-4 flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-green-100">
              <Wallet className="h-5 w-5 text-green-600" />
            </div>
            <div>
              <h3 className="text-sm font-medium text-gray-600">Amount Paid This Week</h3>
              <p className="text-2xl font-semibold text-gray-900">{formatCurrency(stats.amountPaid)}</p>
            </div>
          </div>
          <div className="text-sm text-gray-500">Based on received and approved collections this week</div>
        </div>

        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <div className="mb-4 flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-purple-100">
              <Target className="h-5 w-5 text-purple-600" />
            </div>
            <div>
              <h3 className="text-sm font-medium text-gray-600">Daily Target</h3>
              <p className="text-2xl font-semibold text-gray-900">
                {formatCurrency(stats.dailyTarget)}
              </p>
            </div>
          </div>
          <div className="text-sm text-gray-500">From your active assignment</div>
        </div>

        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <div className="mb-4 flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-100">
              <CheckCircle className="h-5 w-5 text-blue-600" />
            </div>
            <div>
              <h3 className="text-sm font-medium text-gray-600">Achievement</h3>
              <p className="text-2xl font-semibold text-gray-900">
                {stats.achievementPercentage.toFixed(2)}%
              </p>
            </div>
          </div>
          <div className="text-sm text-gray-500">Weekly payment progress against target</div>
        </div>
      </div>
    </div>
  );
}
