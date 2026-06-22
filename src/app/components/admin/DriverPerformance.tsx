import { useEffect, useMemo, useState } from 'react';
import {
  Award,
  Calendar,
  Download,
  Filter,
  Fuel,
  Loader2,
  ShieldAlert,
  Target,
  TrendingUp,
  Truck,
  Users,
} from 'lucide-react';
import { ApiRequestError } from '../../lib/api';
import {
  fetchDriverAnalytics,
  fetchDriverAnalyticsLeaderboard,
  type DriverPerformanceRecord,
  type DriverLeaderboardEntry,
  type DriverAnalyticsFilters,
} from '../../lib/analytics-api';

function formatCurrency(value: number) {
  return `GHS ${value.toLocaleString()}`;
}

function buildCurrentWeekRange() {
  const now = new Date();
  const day = now.getDay();
  const mondayDelta = day === 0 ? -6 : 1 - day;
  const monday = new Date(now);
  monday.setDate(now.getDate() + mondayDelta);
  const saturday = new Date(monday);
  saturday.setDate(monday.getDate() + 5);
  return {
    start: monday.toISOString().slice(0, 10),
    end: saturday.toISOString().slice(0, 10),
  };
}

function downloadCsv(records: DriverPerformanceRecord[]) {
  const header = [
    'Driver',
    'Vehicle',
    'Weekly Target',
    'Amount Collected',
    'Outstanding Balance',
    'Customers Generated',
    'Recurring Customers',
    'Scheduled Customers',
    'Business Leads Captured',
    'Achievement %',
    'Late Payments',
    'Fuel Spend',
    'Fuel Logs',
    'Avg Fuel Cost Per KM',
    'Fault Reports',
    'Critical Faults',
    'Maintenance Days Lost',
    'Assignment Status',
    'Overall Score',
  ];
  const rows = records.map((record) => [
    record.driver.full_name,
    record.vehicle?.registration_number || 'Unassigned',
    record.weekly_target,
    record.amount_collected,
    record.outstanding_balance,
    record.customers_generated,
    record.recurring_customers,
    record.scheduled_customers,
    record.business_leads_captured,
    record.target_achievement_percentage,
    record.number_of_late_payments,
    record.fuel_spend,
    record.fuel_logs_count,
    record.average_fuel_cost_per_km,
    record.number_of_fault_reports,
    record.number_of_critical_faults,
    record.maintenance_days_lost,
    record.active_assignment_status,
    record.overall_driver_score,
  ]);
  const csv = [header, ...rows]
    .map((row) => row.map((item) => `"${String(item).replace(/"/g, '""')}"`).join(','))
    .join('\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'driver-performance-analytics.csv';
  link.click();
  URL.revokeObjectURL(url);
}

export default function DriverPerformance() {
  const defaultRange = buildCurrentWeekRange();
  const [filters, setFilters] = useState<DriverAnalyticsFilters>({
    start_date: defaultRange.start,
    end_date: defaultRange.end,
  });
  const [records, setRecords] = useState<DriverPerformanceRecord[]>([]);
  const [leaderboard, setLeaderboard] = useState<DriverLeaderboardEntry[]>([]);
  const [vehicleOptions, setVehicleOptions] = useState<Array<{ id: string; registration_number: string }>>([]);
  const [adminOptions, setAdminOptions] = useState<Array<{ id: string; full_name: string }>>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [pageError, setPageError] = useState('');

  const sessionUser = localStorage.getItem('flux_user');
  const currentRole = sessionUser ? JSON.parse(sessionUser).role : null;

  useEffect(() => {
    if (currentRole === 'driver') {
      setIsLoading(false);
      return;
    }

    const loadAnalytics = async () => {
      setIsLoading(true);
      setPageError('');
      try {
        const [analyticsResponse, leaderboardResponse] = await Promise.all([
          fetchDriverAnalytics(filters),
          fetchDriverAnalyticsLeaderboard(filters),
        ]);
        setRecords(analyticsResponse.drivers);
        setVehicleOptions(
          analyticsResponse.available_filters.vehicles.map((vehicle) => ({
            id: vehicle.id,
            registration_number: vehicle.registration_number,
          })),
        );
        setAdminOptions(
          analyticsResponse.available_filters.admins.map((admin) => ({
            id: admin.id,
            full_name: admin.full_name,
          })),
        );
        setLeaderboard(leaderboardResponse.leaderboard);
      } catch (error) {
        if (error instanceof ApiRequestError) {
          setPageError(error.message);
        } else {
          setPageError('Unable to load driver performance analytics right now.');
        }
      } finally {
        setIsLoading(false);
      }
    };

    void loadAnalytics();
  }, [currentRole, filters]);

  const summary = useMemo(() => {
    const totalDrivers = records.length;
    const totalCollected = records.reduce((sum, item) => sum + item.amount_collected, 0);
    const totalOutstanding = records.reduce((sum, item) => sum + item.outstanding_balance, 0);
    const totalCustomersGenerated = records.reduce((sum, item) => sum + item.customers_generated, 0);
    const averageScore =
      totalDrivers > 0
        ? records.reduce((sum, item) => sum + item.overall_driver_score, 0) / totalDrivers
        : 0;
    return {
      totalDrivers,
      totalCollected,
      totalOutstanding,
      totalCustomersGenerated,
      averageScore,
    };
  }, [records]);

  const scorecards = useMemo(
    () => [...records].sort((a, b) => b.overall_driver_score - a.overall_driver_score).slice(0, 6),
    [records],
  );

  if (currentRole === 'driver') {
    return (
      <div className="p-6">
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Drivers do not have access to fleet-wide driver analytics.
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-[#0F172A]">Driver Performance</h1>
          <p className="mt-1 text-gray-600">
            Collections, customer generation, target delivery, fuel use, faults, maintenance downtime, and scorecards in one view.
          </p>
        </div>
        <button
          onClick={() => downloadCsv(records)}
          className="flex items-center gap-2 rounded-lg bg-[#2563EB] px-4 py-2.5 font-medium text-white transition-all hover:bg-[#1d4ed8]"
        >
          <Download className="h-5 w-5" />
          Export Table
        </button>
      </div>

      <div className="rounded-xl border border-gray-200 bg-white p-4">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-5">
          <label className="text-sm text-gray-700">
            <div className="mb-2 flex items-center gap-2 font-medium">
              <Calendar className="h-4 w-4 text-gray-500" />
              Start date
            </div>
            <input
              type="date"
              value={filters.start_date || ''}
              onChange={(event) => setFilters((current) => ({ ...current, start_date: event.target.value }))}
              className="w-full rounded-lg border border-gray-300 px-3 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
            />
          </label>

          <label className="text-sm text-gray-700">
            <div className="mb-2 flex items-center gap-2 font-medium">
              <Calendar className="h-4 w-4 text-gray-500" />
              End date
            </div>
            <input
              type="date"
              value={filters.end_date || ''}
              onChange={(event) => setFilters((current) => ({ ...current, end_date: event.target.value }))}
              className="w-full rounded-lg border border-gray-300 px-3 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
            />
          </label>

          <label className="text-sm text-gray-700">
            <div className="mb-2 flex items-center gap-2 font-medium">
              <Truck className="h-4 w-4 text-gray-500" />
              Vehicle
            </div>
            <select
              value={filters.vehicle_id || ''}
              onChange={(event) =>
                setFilters((current) => ({
                  ...current,
                  vehicle_id: event.target.value || undefined,
                }))
              }
              className="w-full rounded-lg border border-gray-300 px-3 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
            >
              <option value="">All vehicles</option>
              {vehicleOptions.map((vehicle) => (
                <option key={vehicle.id} value={vehicle.id}>
                  {vehicle.registration_number}
                </option>
              ))}
            </select>
          </label>

          <label className="text-sm text-gray-700">
            <div className="mb-2 flex items-center gap-2 font-medium">
              <Users className="h-4 w-4 text-gray-500" />
              Admin
            </div>
            <select
              value={filters.admin_id || ''}
              onChange={(event) =>
                setFilters((current) => ({
                  ...current,
                  admin_id: event.target.value || undefined,
                }))
              }
              className="w-full rounded-lg border border-gray-300 px-3 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
            >
              <option value="">All admins</option>
              {adminOptions.map((admin) => (
                <option key={admin.id} value={admin.id}>
                  {admin.full_name}
                </option>
              ))}
            </select>
          </label>

          <div className="flex items-end">
            <button
              onClick={() =>
                setFilters({
                  start_date: defaultRange.start,
                  end_date: defaultRange.end,
                })
              }
              className="flex w-full items-center justify-center gap-2 rounded-lg border border-gray-300 px-3 py-2.5 font-medium text-gray-700 transition-all hover:bg-gray-50"
            >
              <Filter className="h-4 w-4" />
              Reset Filters
            </button>
          </div>
        </div>
      </div>

      {pageError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {pageError}
        </div>
      )}

      {isLoading ? (
        <div className="flex items-center justify-center gap-3 rounded-xl border border-gray-200 bg-white px-6 py-20 text-gray-500">
          <Loader2 className="h-5 w-5 animate-spin" />
          <span>Loading driver analytics...</span>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-6 md:grid-cols-4">
            <div className="rounded-xl border border-gray-200 bg-white p-6">
              <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-blue-100">
                <Users className="h-6 w-6 text-blue-600" />
              </div>
              <div className="text-3xl font-bold text-[#0F172A]">{summary.totalDrivers}</div>
              <div className="mt-1 text-sm text-gray-600">Drivers in view</div>
            </div>

            <div className="rounded-xl border border-gray-200 bg-white p-6">
              <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-green-100">
                <TrendingUp className="h-6 w-6 text-green-600" />
              </div>
              <div className="text-3xl font-bold text-[#0F172A]">{formatCurrency(summary.totalCollected)}</div>
              <div className="mt-1 text-sm text-gray-600">Approved collections</div>
            </div>

            <div className="rounded-xl border border-gray-200 bg-white p-6">
              <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-amber-100">
                <Target className="h-6 w-6 text-amber-600" />
              </div>
              <div className="text-3xl font-bold text-[#0F172A]">{formatCurrency(summary.totalOutstanding)}</div>
              <div className="mt-1 text-sm text-gray-600">Outstanding balance</div>
            </div>

            <div className="rounded-xl border border-gray-200 bg-white p-6">
              <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-purple-100">
                <Award className="h-6 w-6 text-purple-600" />
              </div>
              <div className="text-3xl font-bold text-[#0F172A]">{summary.averageScore.toFixed(1)}</div>
              <div className="mt-1 text-sm text-gray-600">Average score</div>
            </div>
          </div>

          <div className="rounded-xl border border-gray-200 bg-white p-6">
            <div className="mb-5 flex items-center justify-between">
              <div>
                <h2 className="text-lg font-semibold text-[#0F172A]">Customer Generation Snapshot</h2>
                <p className="mt-1 text-sm text-gray-600">Customer growth signals by driver for the selected period</p>
              </div>
              <Users className="h-5 w-5 text-[#2563EB]" />
            </div>
            <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
              <div className="rounded-lg bg-gray-50 p-4">
                <div className="text-sm text-gray-500">Generated</div>
                <div className="mt-1 text-2xl font-semibold text-[#0F172A]">{summary.totalCustomersGenerated}</div>
              </div>
              <div className="rounded-lg bg-gray-50 p-4">
                <div className="text-sm text-gray-500">Recurring</div>
                <div className="mt-1 text-2xl font-semibold text-[#0F172A]">{records.reduce((sum, item) => sum + item.recurring_customers, 0)}</div>
              </div>
              <div className="rounded-lg bg-gray-50 p-4">
                <div className="text-sm text-gray-500">Scheduled</div>
                <div className="mt-1 text-2xl font-semibold text-[#0F172A]">{records.reduce((sum, item) => sum + item.scheduled_customers, 0)}</div>
              </div>
              <div className="rounded-lg bg-gray-50 p-4">
                <div className="text-sm text-gray-500">Business Leads</div>
                <div className="mt-1 text-2xl font-semibold text-[#0F172A]">{records.reduce((sum, item) => sum + item.business_leads_captured, 0)}</div>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <div className="rounded-xl border border-gray-200 bg-white p-6">
              <div className="mb-5 flex items-center justify-between">
                <div>
                  <h2 className="text-lg font-semibold text-[#0F172A]">Leaderboard</h2>
                  <p className="mt-1 text-sm text-gray-600">Ranked by overall driver score</p>
                </div>
                <Award className="h-5 w-5 text-[#F59E0B]" />
              </div>
              <div className="space-y-3">
                {leaderboard.slice(0, 5).map((entry) => (
                  <div key={entry.driver.id} className="flex items-center gap-4 rounded-lg bg-gray-50 px-4 py-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-full bg-[#0F172A] text-sm font-semibold text-white">
                      #{entry.rank}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-medium text-[#0F172A]">{entry.driver.full_name}</div>
                      <div className="text-xs text-gray-500">
                        {entry.vehicle?.registration_number || 'No vehicle'} • {entry.customers_generated} customers generated
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="font-semibold text-[#2563EB]">{entry.overall_driver_score.toFixed(1)}</div>
                      <div className="text-xs text-gray-500">Score</div>
                    </div>
                  </div>
                ))}
                {leaderboard.length === 0 && (
                  <div className="py-10 text-center text-sm text-gray-500">
                    No leaderboard data available for this filter set.
                  </div>
                )}
              </div>
            </div>

            <div className="rounded-xl border border-gray-200 bg-white p-6">
              <div className="mb-5">
                <h2 className="text-lg font-semibold text-[#0F172A]">Driver Scorecards</h2>
                <p className="mt-1 text-sm text-gray-600">A quick scan of the strongest and weakest signals per driver</p>
              </div>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                {scorecards.map((record) => (
                  <div key={record.driver.id} className="rounded-xl border border-gray-200 bg-gray-50 p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="font-semibold text-[#0F172A]">{record.driver.full_name}</div>
                        <div className="text-xs text-gray-500">
                          {record.vehicle?.registration_number || 'No active vehicle'}
                        </div>
                      </div>
                      <div className="rounded-full bg-[#2563EB]/10 px-2.5 py-1 text-xs font-semibold text-[#2563EB]">
                        {record.overall_driver_score.toFixed(1)}
                      </div>
                    </div>
                    <div className="mt-4 space-y-2 text-sm text-gray-700">
                      <div className="flex items-center justify-between">
                        <span className="flex items-center gap-2"><Target className="h-4 w-4 text-blue-500" />Target</span>
                        <span>{record.target_achievement_percentage.toFixed(1)}%</span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="flex items-center gap-2"><Fuel className="h-4 w-4 text-green-500" />Fuel</span>
                        <span>{record.average_fuel_cost_per_km.toFixed(2)} / km</span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="flex items-center gap-2"><ShieldAlert className="h-4 w-4 text-red-500" />Faults</span>
                        <span>{record.number_of_critical_faults} critical</span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="flex items-center gap-2"><Users className="h-4 w-4 text-cyan-500" />Customers</span>
                        <span>{record.customers_generated} generated</span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
            <div className="border-b border-gray-200 px-6 py-4">
              <h2 className="text-lg font-semibold text-[#0F172A]">Export-ready table</h2>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="border-b border-gray-200 bg-gray-50">
                  <tr>
                    <th className="px-6 py-4 text-left text-xs font-semibold uppercase text-gray-700">Driver</th>
                    <th className="px-6 py-4 text-left text-xs font-semibold uppercase text-gray-700">Vehicle</th>
                    <th className="px-6 py-4 text-left text-xs font-semibold uppercase text-gray-700">Target</th>
                    <th className="px-6 py-4 text-left text-xs font-semibold uppercase text-gray-700">Collected</th>
                    <th className="px-6 py-4 text-left text-xs font-semibold uppercase text-gray-700">Outstanding</th>
                    <th className="px-6 py-4 text-left text-xs font-semibold uppercase text-gray-700">Customers</th>
                    <th className="px-6 py-4 text-left text-xs font-semibold uppercase text-gray-700">Fuel</th>
                    <th className="px-6 py-4 text-left text-xs font-semibold uppercase text-gray-700">Faults</th>
                    <th className="px-6 py-4 text-left text-xs font-semibold uppercase text-gray-700">Score</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {records.map((record) => (
                    <tr key={record.driver.id} className="hover:bg-gray-50">
                      <td className="px-6 py-4">
                        <div className="font-medium text-[#0F172A]">{record.driver.full_name}</div>
                        <div className="text-xs text-gray-500">{record.driver.phone}</div>
                      </td>
                      <td className="px-6 py-4 text-gray-700">
                        {record.vehicle?.registration_number || 'Unassigned'}
                      </td>
                      <td className="px-6 py-4 text-gray-700">{formatCurrency(record.weekly_target)}</td>
                      <td className="px-6 py-4 text-green-700">{formatCurrency(record.amount_collected)}</td>
                      <td className="px-6 py-4 text-amber-700">{formatCurrency(record.outstanding_balance)}</td>
                      <td className="px-6 py-4 text-gray-700">
                        {record.customers_generated} gen / {record.recurring_customers} recurring
                      </td>
                      <td className="px-6 py-4 text-gray-700">
                        {formatCurrency(record.fuel_spend)} / {record.fuel_logs_count} logs
                      </td>
                      <td className="px-6 py-4 text-gray-700">
                        {record.number_of_fault_reports} total / {record.number_of_critical_faults} critical
                      </td>
                      <td className="px-6 py-4">
                        <div className="font-semibold text-[#2563EB]">{record.overall_driver_score.toFixed(1)}</div>
                        <div className="text-xs capitalize text-gray-500">{record.active_assignment_status}</div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {records.length === 0 && (
                <div className="px-6 py-12 text-center text-gray-500">
                  No driver analytics matched the current filters.
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
