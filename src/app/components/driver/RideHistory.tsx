import { useEffect, useMemo, useState } from 'react';
import { Calendar, CarFront, Clock, Filter, Loader2, MapPin, Navigation, Search } from 'lucide-react';
import { ApiRequestError } from '../../lib/api';
import { fetchRideSummary, fetchRides, type TripRecord, type TripSummary } from '../../lib/ride-masterdata-api';
import { useDebouncedValue } from '../../lib/use-debounced-value';

function formatDate(value?: string | null) {
  if (!value) return 'Not available';
  const date = new Date(`${value}T00:00:00`);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString();
}

function formatCurrency(value?: number | null) {
  return `GHS ${Number(value || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export default function RideHistory() {
  const [rides, setRides] = useState<TripRecord[]>([]);
  const [summary, setSummary] = useState<TripSummary | null>(null);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [isLoading, setIsLoading] = useState(true);
  const [pageError, setPageError] = useState('');
  const debouncedSearch = useDebouncedValue(search, 250);

  useEffect(() => {
    const loadHistory = async () => {
      setIsLoading(true);
      setPageError('');
      try {
        const [ridesResult, summaryResult] = await Promise.allSettled([fetchRides({ q: debouncedSearch, limit: 50 }), fetchRideSummary()]);
        setRides(ridesResult.status === 'fulfilled' ? ridesResult.value : []);
        setSummary(summaryResult.status === 'fulfilled' ? summaryResult.value : null);

        if (ridesResult.status === 'rejected') {
          throw ridesResult.reason;
        }

        if (summaryResult.status === 'rejected') {
          console.warn('[Flux Ride History] Summary request failed while rides loaded.', summaryResult.reason);
        }
      } catch (error) {
        if (error instanceof ApiRequestError) {
          setPageError(error.message);
        } else {
          setPageError('Unable to load trip history right now.');
        }
      } finally {
        setIsLoading(false);
      }
    };
    void loadHistory();
  }, [debouncedSearch]);

  const filteredRides = useMemo(
    () =>
      rides.filter((trip) => {
        const matchesStatus = statusFilter === 'all' || trip.status === statusFilter;
        return matchesStatus;
      }),
    [rides, statusFilter],
  );

  if (isLoading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center gap-3 text-gray-500">
        <Loader2 className="h-5 w-5 animate-spin" />
        <span>Loading trip history...</span>
      </div>
    );
  }

  return (
    <div className="space-y-6 p-4 md:p-6">
      <div className="rounded-2xl bg-gradient-to-r from-[#0F172A] to-[#1e293b] p-6 text-white">
        <h1 className="text-2xl font-semibold">Trip History</h1>
        <p className="mt-1 text-sm text-gray-300">Your logged trips, platform usage, and vehicle activity record.</p>
      </div>

      {pageError && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {pageError}
        </div>
      )}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {[
          { label: 'Trips Today', value: summary?.trips_today || 0, icon: Calendar, tint: 'bg-blue-100 text-blue-600' },
          { label: 'This Week', value: summary?.trips_this_week || 0, icon: CarFront, tint: 'bg-green-100 text-green-600' },
          { label: 'This Month', value: summary?.trips_this_month || 0, icon: Clock, tint: 'bg-purple-100 text-purple-600' },
          { label: 'Completed', value: summary?.completed_trips || 0, icon: Navigation, tint: 'bg-amber-100 text-amber-600' },
        ].map((card) => {
          const Icon = card.icon;
          return (
            <div key={card.label} className="rounded-2xl border border-gray-200 bg-white p-4">
              <div className={`mb-3 flex h-10 w-10 items-center justify-center rounded-xl ${card.tint}`}>
                <Icon className="h-5 w-5" />
              </div>
              <div className="text-2xl font-semibold text-[#0F172A]">{card.value}</div>
              <div className="mt-1 text-sm text-gray-500">{card.label}</div>
            </div>
          );
        })}
      </div>

      {summary?.earnings && (
        <div className="space-y-4 rounded-2xl border border-gray-200 bg-white p-4">
          <div>
            <h2 className="font-semibold text-[#0F172A]">My Trip Earnings</h2>
            <p className="text-sm text-gray-500">Completed trips only. These figures do not affect weekly remittance.</p>
          </div>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            {([
              ['Today', summary.earnings.today],
              ['This Week', summary.earnings.week],
              ['This Month', summary.earnings.month],
            ] as const).map(([label, period]) => (
              <div key={label} className="rounded-xl bg-slate-50 p-4">
                <div className="text-sm font-medium text-slate-700">{label} · {period.trip_count} trips</div>
                <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
                  <div><span className="text-gray-500">Gross</span><strong className="block break-words text-slate-900">{formatCurrency(period.gross_charged)}</strong></div>
                  <div><span className="text-gray-500">Fees</span><strong className="block break-words text-amber-700">{formatCurrency(period.platform_fees)}</strong></div>
                  <div><span className="text-gray-500">Net</span><strong className="block break-words text-emerald-700">{formatCurrency(period.net_earnings)}</strong></div>
                </div>
              </div>
            ))}
          </div>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {([
              ['This Month by Source', summary.earnings.month.source_breakdown],
              ['This Month by Payment Method', summary.earnings.month.payment_method_breakdown],
            ] as const).map(([label, rows]) => (
              <div key={label} className="rounded-xl border border-gray-100 p-3">
                <div className="text-sm font-medium text-slate-800">{label}</div>
                <div className="mt-2 space-y-2 text-sm">
                  {rows.map((row) => <div key={row.label} className="flex items-center justify-between gap-3"><span>{row.label} · {row.trip_count}</span><strong>{formatCurrency(row.net_earnings)} net</strong></div>)}
                  {!rows.length && <span className="text-gray-500">No completed earnings yet.</span>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="rounded-2xl border border-gray-200 bg-white p-4">
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-[1fr_220px]">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-gray-400" />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search trip, customer, pickup, or destination"
              className="w-full rounded-xl border border-gray-300 px-10 py-2.5 text-sm"
            />
          </div>
          <div className="relative">
            <Filter className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
            <select
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value)}
              className="w-full rounded-xl border border-gray-300 px-9 py-2.5 text-sm"
            >
              <option value="all">All statuses</option>
              <option value="Completed">Completed</option>
              <option value="Logged">Logged</option>
              <option value="Scheduled">Scheduled</option>
              <option value="Cancelled">Cancelled</option>
            </select>
          </div>
        </div>
      </div>

      <div className="rounded-2xl border border-gray-200 bg-white">
        <div className="divide-y divide-gray-200">
          {filteredRides.map((trip) => (
            <div key={trip.id} className="px-5 py-4">
              <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="text-base font-semibold text-[#0F172A]">{trip.trip_id}</span>
                    <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700">
                      {trip.status}
                    </span>
                  </div>
                  <div className="text-sm text-gray-600">
                    {trip.customer?.full_name || trip.customer_name_snapshot || 'No customer'} - {trip.trip_source} - {trip.trip_purpose}
                  </div>
                  <div className="grid grid-cols-1 gap-1 text-sm text-gray-500">
                    <div className="flex items-center gap-2">
                      <MapPin className="h-4 w-4 text-[#2563EB]" />
                      {trip.pickup_area}
                    </div>
                    <div className="flex items-center gap-2">
                      <Navigation className="h-4 w-4 text-[#10B981]" />
                      {trip.destination_area}
                    </div>
                    <div className="flex items-center gap-2">
                      <Calendar className="h-4 w-4 text-amber-600" />
                      {formatDate(trip.trip_date)}
                    </div>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3 sm:flex sm:items-center">
                  {trip.actual_fare != null && (
                    <div className="rounded-xl bg-emerald-50 px-4 py-3">
                      <div className="text-xs text-emerald-700">Gross / Fee / Net</div>
                      <div className="text-sm font-semibold text-emerald-900">{formatCurrency(trip.actual_fare)} / {formatCurrency(trip.platform_fee)} / {formatCurrency(trip.net_earnings)}</div>
                      <div className="text-xs text-emerald-700">{trip.payment_method || 'Payment not specified'}</div>
                    </div>
                  )}
                  <div className="rounded-xl bg-gray-50 px-4 py-3">
                    <div className="text-xs text-gray-500">Vehicle</div>
                    <div className="text-sm font-semibold text-[#0F172A]">
                      {trip.vehicle?.registration_number || 'Pending'}
                    </div>
                  </div>
                  <div className="rounded-xl bg-gray-50 px-4 py-3">
                    <div className="text-xs text-gray-500">Time</div>
                    <div className="text-sm font-semibold text-[#0F172A]">
                      {trip.start_time || '--'} - {trip.end_time || '--'}
                    </div>
                  </div>
                  <div className="rounded-xl bg-gray-50 px-4 py-3">
                    <div className="text-xs text-gray-500">Odometer</div>
                    <div className="text-sm font-semibold text-[#0F172A]">
                      {trip.odometer_start ?? '-'} / {trip.odometer_end ?? '-'}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          ))}
          {!filteredRides.length && (
            <div className="px-6 py-16 text-center text-gray-500">
              No matching records found.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
