import { useEffect, useMemo, useState } from 'react';
import {
  AlertCircle,
  Calendar,
  Fuel,
  Loader2,
  ShieldAlert,
  Target,
  TrendingUp,
  Wrench,
} from 'lucide-react';
import { ApiRequestError } from '../../lib/api';
import { fetchDriverAnalyticsDetail, type DriverPerformanceRecord } from '../../lib/analytics-api';
import { getStoredSessionUser } from '../../lib/auth-session';

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

export default function MyPerformance() {
  const currentUser = getStoredSessionUser();
  const defaultRange = buildCurrentWeekRange();
  const [startDate, setStartDate] = useState(defaultRange.start);
  const [endDate, setEndDate] = useState(defaultRange.end);
  const [record, setRecord] = useState<DriverPerformanceRecord | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [pageError, setPageError] = useState('');

  useEffect(() => {
    if (!currentUser?.id) {
      setIsLoading(false);
      setPageError('Unable to resolve the current driver profile.');
      return;
    }

    const loadPerformance = async () => {
      setIsLoading(true);
      setPageError('');
      try {
        const response = await fetchDriverAnalyticsDetail(currentUser.id, {
          start_date: startDate,
          end_date: endDate,
        });
        setRecord(response.driver_performance);
      } catch (error) {
        if (error instanceof ApiRequestError) {
          setPageError(error.message);
        } else {
          setPageError('Unable to load your performance analytics right now.');
        }
      } finally {
        setIsLoading(false);
      }
    };

    void loadPerformance();
  }, [currentUser?.id, endDate, startDate]);

  const progressWidth = useMemo(
    () => `${Math.min(record?.target_achievement_percentage || 0, 100)}%`,
    [record?.target_achievement_percentage],
  );

  return (
    <div className="space-y-6 p-6">
      <div className="rounded-xl bg-gradient-to-r from-[#0F172A] to-[#2563EB] p-6 text-white">
        <h1 className="text-2xl font-semibold">My Performance</h1>
        <p className="mt-1 text-blue-100">
          Weekly target progress, customer generation, fuel efficiency, payment consistency, and fault history in one place.
        </p>
        <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
          <label className="text-sm text-blue-100">
            <div className="mb-2 flex items-center gap-2 font-medium text-white">
              <Calendar className="h-4 w-4" />
              Start date
            </div>
            <input
              type="date"
              value={startDate}
              onChange={(event) => setStartDate(event.target.value)}
              className="w-full rounded-lg border border-white/20 bg-white/10 px-3 py-2.5 text-white placeholder:text-white/60 focus:border-transparent focus:ring-2 focus:ring-white/70"
            />
          </label>
          <label className="text-sm text-blue-100">
            <div className="mb-2 flex items-center gap-2 font-medium text-white">
              <Calendar className="h-4 w-4" />
              End date
            </div>
            <input
              type="date"
              value={endDate}
              onChange={(event) => setEndDate(event.target.value)}
              className="w-full rounded-lg border border-white/20 bg-white/10 px-3 py-2.5 text-white placeholder:text-white/60 focus:border-transparent focus:ring-2 focus:ring-white/70"
            />
          </label>
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
          <span>Loading your performance...</span>
        </div>
      ) : record ? (
        <>
          <div className="grid grid-cols-1 gap-6 md:grid-cols-4">
            <div className="rounded-xl border border-gray-200 bg-white p-6">
              <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-blue-100">
                <Target className="h-6 w-6 text-blue-600" />
              </div>
              <div className="text-3xl font-bold text-[#0F172A]">{formatCurrency(record.weekly_target)}</div>
              <div className="mt-1 text-sm text-gray-600">Weekly target</div>
            </div>

            <div className="rounded-xl border border-gray-200 bg-white p-6">
              <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-green-100">
                <TrendingUp className="h-6 w-6 text-green-600" />
              </div>
              <div className="text-3xl font-bold text-[#0F172A]">{formatCurrency(record.amount_collected)}</div>
              <div className="mt-1 text-sm text-gray-600">Amount collected</div>
            </div>

            <div className="rounded-xl border border-gray-200 bg-white p-6">
              <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-amber-100">
                <Fuel className="h-6 w-6 text-amber-600" />
              </div>
              <div className="text-3xl font-bold text-[#0F172A]">{record.average_fuel_cost_per_km.toFixed(2)}</div>
              <div className="mt-1 text-sm text-gray-600">Fuel cost per km</div>
            </div>

            <div className="rounded-xl border border-gray-200 bg-white p-6">
              <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-purple-100">
                <TrendingUp className="h-6 w-6 text-purple-600" />
              </div>
              <div className="text-3xl font-bold text-[#0F172A]">{record.overall_driver_score.toFixed(1)}</div>
              <div className="mt-1 text-sm text-gray-600">Overall score</div>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-6 md:grid-cols-4">
            <div className="rounded-xl border border-gray-200 bg-white p-6">
              <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-cyan-100">
                <TrendingUp className="h-6 w-6 text-cyan-600" />
              </div>
              <div className="text-3xl font-bold text-[#0F172A]">{record.customers_generated}</div>
              <div className="mt-1 text-sm text-gray-600">Customers generated</div>
            </div>
            <div className="rounded-xl border border-gray-200 bg-white p-6">
              <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-blue-100">
                <Calendar className="h-6 w-6 text-blue-600" />
              </div>
              <div className="text-3xl font-bold text-[#0F172A]">{record.recurring_customers}</div>
              <div className="mt-1 text-sm text-gray-600">Recurring customers</div>
            </div>
            <div className="rounded-xl border border-gray-200 bg-white p-6">
              <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-emerald-100">
                <Calendar className="h-6 w-6 text-emerald-600" />
              </div>
              <div className="text-3xl font-bold text-[#0F172A]">{record.scheduled_customers}</div>
              <div className="mt-1 text-sm text-gray-600">Scheduled customers</div>
            </div>
            <div className="rounded-xl border border-gray-200 bg-white p-6">
              <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-amber-100">
                <Target className="h-6 w-6 text-amber-600" />
              </div>
              <div className="text-3xl font-bold text-[#0F172A]">{record.business_leads_captured}</div>
              <div className="mt-1 text-sm text-gray-600">Business leads captured</div>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <div className="rounded-xl border border-gray-200 bg-white p-6">
              <h2 className="text-lg font-semibold text-[#0F172A]">Weekly target progress</h2>
              <p className="mt-1 text-sm text-gray-600">
                {formatCurrency(record.amount_collected)} of {formatCurrency(record.weekly_target)} approved
              </p>
              <div className="mt-5 h-3 overflow-hidden rounded-full bg-gray-100">
                <div className="h-full rounded-full bg-[#2563EB]" style={{ width: progressWidth }} />
              </div>
              <div className="mt-3 flex items-center justify-between text-sm">
                <span className="text-gray-600">{record.target_achievement_percentage.toFixed(1)}% achieved</span>
                <span className="text-amber-700">{formatCurrency(record.outstanding_balance)} outstanding</span>
              </div>
            </div>

            <div className="rounded-xl border border-gray-200 bg-white p-6">
              <h2 className="text-lg font-semibold text-[#0F172A]">Payment consistency</h2>
              <div className="mt-4 grid grid-cols-2 gap-4">
                <div className="rounded-lg bg-gray-50 p-4">
                  <div className="text-sm text-gray-500">Consistency score</div>
                  <div className="mt-1 text-2xl font-semibold text-[#0F172A]">
                    {record.payment_consistency_percentage.toFixed(1)}%
                  </div>
                </div>
                <div className="rounded-lg bg-gray-50 p-4">
                  <div className="text-sm text-gray-500">Late payments</div>
                  <div className="mt-1 text-2xl font-semibold text-[#0F172A]">
                    {record.number_of_late_payments}
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            <div className="rounded-xl border border-gray-200 bg-white p-6">
              <div className="mb-4 flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-green-100">
                  <Fuel className="h-5 w-5 text-green-600" />
                </div>
                <div>
                  <h2 className="text-lg font-semibold text-[#0F172A]">Fuel efficiency</h2>
                  <p className="text-sm text-gray-500">{record.fuel_logs_count} approved logs</p>
                </div>
              </div>
              <div className="space-y-2 text-sm text-gray-700">
                <div className="flex items-center justify-between">
                  <span>Total fuel spend</span>
                  <span className="font-medium">{formatCurrency(record.fuel_spend)}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span>Average fuel cost per km</span>
                  <span className="font-medium">{record.average_fuel_cost_per_km.toFixed(2)}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span>Fuel efficiency score</span>
                  <span className="font-medium">{record.fuel_efficiency_score.toFixed(1)}</span>
                </div>
              </div>
            </div>

            <div className="rounded-xl border border-gray-200 bg-white p-6">
              <div className="mb-4 flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-red-100">
                  <ShieldAlert className="h-5 w-5 text-red-600" />
                </div>
                <div>
                  <h2 className="text-lg font-semibold text-[#0F172A]">Fault history</h2>
                  <p className="text-sm text-gray-500">Reported during this range</p>
                </div>
              </div>
              <div className="space-y-2 text-sm text-gray-700">
                <div className="flex items-center justify-between">
                  <span>Total fault reports</span>
                  <span className="font-medium">{record.number_of_fault_reports}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span>Critical faults</span>
                  <span className="font-medium">{record.number_of_critical_faults}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span>Assignment status</span>
                  <span className="font-medium capitalize">{record.active_assignment_status}</span>
                </div>
              </div>
            </div>

            <div className="rounded-xl border border-gray-200 bg-white p-6">
              <div className="mb-4 flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-amber-100">
                  <Wrench className="h-5 w-5 text-amber-600" />
                </div>
                <div>
                  <h2 className="text-lg font-semibold text-[#0F172A]">Maintenance impact</h2>
                  <p className="text-sm text-gray-500">Downtime and workshop activity</p>
                </div>
              </div>
              <div className="space-y-2 text-sm text-gray-700">
                <div className="flex items-center justify-between">
                  <span>Maintenance jobs</span>
                  <span className="font-medium">{record.detail.maintenance_summary.jobs_count}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span>Days lost</span>
                  <span className="font-medium">{record.maintenance_days_lost}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span>Vehicle</span>
                  <span className="font-medium">{record.vehicle?.registration_number || 'Unassigned'}</span>
                </div>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
              <div className="border-b border-gray-200 px-6 py-4">
                <h2 className="text-lg font-semibold text-[#0F172A]">Recent collections</h2>
              </div>
              <div className="divide-y divide-gray-200">
                {record.detail.recent_collections.length ? (
                  record.detail.recent_collections.map((entry) => (
                    <div key={entry.id} className="flex items-center justify-between gap-4 px-6 py-4">
                      <div>
                        <div className="text-sm font-medium text-gray-900">{entry.collection_date || 'No date'}</div>
                        <div className="text-xs capitalize text-gray-500">
                          {entry.payment_method || 'other'} • {entry.status}
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="font-semibold text-[#0F172A]">{formatCurrency(entry.amount)}</div>
                        <div className={`text-xs ${entry.is_late ? 'text-red-600' : 'text-green-600'}`}>
                          {entry.is_late ? 'Late' : 'On time'}
                        </div>
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="px-6 py-10 text-center text-sm text-gray-500">No collections recorded in this range.</div>
                )}
              </div>
            </div>

            <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
              <div className="border-b border-gray-200 px-6 py-4">
                <h2 className="text-lg font-semibold text-[#0F172A]">Recent fault history</h2>
              </div>
              <div className="divide-y divide-gray-200">
                {record.detail.fault_history.length ? (
                  record.detail.fault_history.map((entry) => (
                    <div key={entry.id} className="px-6 py-4">
                      <div className="flex items-center justify-between gap-4">
                        <div className="font-medium text-gray-900">{entry.description}</div>
                        <div className="text-xs capitalize text-gray-500">{entry.severity}</div>
                      </div>
                      <div className="mt-1 text-xs text-gray-500">
                        {entry.reported_at || 'No report date'} • {entry.status}
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="px-6 py-10 text-center text-sm text-gray-500">No fault reports in this range.</div>
                )}
              </div>
            </div>
          </div>
        </>
      ) : (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          <div className="flex items-center gap-2">
            <AlertCircle className="h-4 w-4" />
            No performance record is available for the current filter range.
          </div>
        </div>
      )}
    </div>
  );
}
