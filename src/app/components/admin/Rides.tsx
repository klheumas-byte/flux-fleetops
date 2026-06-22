import { useEffect, useMemo, useState } from 'react';
import { BarChart3, Calendar, CarFront, Filter, Loader2, Search, Users } from 'lucide-react';
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { ApiRequestError } from '../../lib/api';
import { fetchRideSummary, fetchRides, type TripRecord, type TripSummary } from '../../lib/ride-masterdata-api';

export default function Rides() {
  const [rides, setRides] = useState<TripRecord[]>([]);
  const [summary, setSummary] = useState<TripSummary | null>(null);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [isLoading, setIsLoading] = useState(true);
  const [pageError, setPageError] = useState('');

  useEffect(() => {
    const loadRides = async () => {
      setIsLoading(true);
      setPageError('');
      try {
        const [nextRides, nextSummary] = await Promise.all([fetchRides(), fetchRideSummary()]);
        setRides(nextRides);
        setSummary(nextSummary);
      } catch (error) {
        if (error instanceof ApiRequestError) {
          setPageError(error.message);
        } else {
          setPageError('Unable to load trip operations right now.');
        }
      } finally {
        setIsLoading(false);
      }
    };

    void loadRides();
  }, []);

  const filteredRides = useMemo(
    () =>
      rides.filter((trip) => {
        const matchesSearch = [trip.trip_id, trip.customer?.full_name, trip.driver?.full_name, trip.pickup_area, trip.destination_area]
          .filter(Boolean)
          .some((value) => value?.toLowerCase().includes(search.toLowerCase()));
        const matchesStatus = statusFilter === 'all' || trip.status === statusFilter;
        return matchesSearch && matchesStatus;
      }),
    [rides, search, statusFilter],
  );

  if (isLoading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center gap-3 text-gray-500">
        <Loader2 className="h-5 w-5 animate-spin" />
        <span>Loading trip analytics...</span>
      </div>
    );
  }

  return (
    <div className="space-y-6 p-4 md:p-6">
      <div>
        <h1 className="text-2xl font-semibold text-[#0F172A]">Trips & Vehicle Utilization</h1>
        <p className="mt-1 text-sm text-gray-500">View trip logs, filter activity, and monitor fleet utilization by platform and purpose.</p>
      </div>

      {pageError && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {pageError}
        </div>
      )}

      <div className="grid grid-cols-2 gap-4 xl:grid-cols-5">
        {[
          { label: 'Trips Today', value: summary?.trips_today || 0, icon: Calendar, tint: 'bg-blue-100 text-blue-600' },
          { label: 'This Week', value: summary?.trips_this_week || 0, icon: CarFront, tint: 'bg-green-100 text-green-600' },
          { label: 'This Month', value: summary?.trips_this_month || 0, icon: Users, tint: 'bg-amber-100 text-amber-600' },
          { label: 'Vehicle Active Days', value: summary?.vehicle_active_days || 0, icon: BarChart3, tint: 'bg-purple-100 text-purple-600' },
          { label: 'Vehicle Idle Days', value: summary?.vehicle_idle_days || 0, icon: Filter, tint: 'bg-rose-100 text-rose-600' },
        ].map((card) => {
          const Icon = card.icon;
          return (
            <div key={card.label} className="rounded-2xl border border-gray-200 bg-white p-5">
              <div className={`mb-4 flex h-11 w-11 items-center justify-center rounded-xl ${card.tint}`}>
                <Icon className="h-5 w-5" />
              </div>
              <div className="text-2xl font-semibold text-[#0F172A]">{card.value}</div>
              <div className="mt-1 text-sm text-gray-500">{card.label}</div>
            </div>
          );
        })}
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <div className="rounded-2xl border border-gray-200 bg-white p-6">
          <h2 className="mb-4 text-lg font-semibold text-[#0F172A]">Trip Activity Trend</h2>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={summary?.activity_trends || []}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="date" stroke="#6b7280" />
              <YAxis stroke="#6b7280" />
              <Tooltip />
              <Legend />
              <Bar dataKey="trips" fill="#2563EB" name="Trips" />
              <Bar dataKey="vehicles_active" fill="#10B981" name="Vehicles active" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="rounded-2xl border border-gray-200 bg-white p-6">
          <h2 className="mb-4 text-lg font-semibold text-[#0F172A]">Trips By Platform</h2>
          <div className="space-y-3">
            {(summary?.trips_by_platform || []).slice(0, 6).map((entry) => (
              <div key={entry.label} className="flex items-center justify-between rounded-xl bg-gray-50 px-4 py-3">
                <div className="text-sm font-semibold text-[#0F172A]">{entry.label}</div>
                <div className="text-sm font-semibold text-[#0F172A]">{entry.count}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="rounded-2xl border border-gray-200 bg-white p-4">
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-[1fr_220px]">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-gray-400" />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search trip, customer, driver, pickup, or destination"
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
              <option value="Logged">Logged</option>
              <option value="Scheduled">Scheduled</option>
              <option value="Completed">Completed</option>
              <option value="Cancelled">Cancelled</option>
            </select>
          </div>
        </div>
      </div>

      <div className="rounded-2xl border border-gray-200 bg-white">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[980px]">
            <thead className="bg-gray-50">
              <tr>
                {['Trip', 'Customer', 'Driver', 'Route', 'Date', 'Platform', 'Purpose', 'Vehicle'].map((label) => (
                  <th key={label} className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-600">
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {filteredRides.map((trip) => (
                <tr key={trip.id} className="hover:bg-gray-50">
                  <td className="px-5 py-4">
                    <div className="font-semibold text-[#0F172A]">{trip.trip_id}</div>
                    <div className="text-xs text-gray-500">{trip.status}</div>
                  </td>
                  <td className="px-5 py-4">
                    <div className="font-medium text-gray-900">{trip.customer?.full_name || 'No customer'}</div>
                    <div className="text-xs text-gray-500">{trip.trip_source}</div>
                  </td>
                  <td className="px-5 py-4">
                    <div className="font-medium text-gray-900">{trip.driver?.full_name || 'Unassigned'}</div>
                    <div className="text-xs text-gray-500">{trip.start_time || '--'} - {trip.end_time || '--'}</div>
                  </td>
                  <td className="px-5 py-4">
                    <div className="text-sm text-gray-900">{trip.pickup_area}</div>
                    <div className="text-xs text-gray-500">to {trip.destination_area}</div>
                  </td>
                  <td className="px-5 py-4 text-sm text-gray-600">{trip.trip_date}</td>
                  <td className="px-5 py-4 text-sm text-gray-900">{trip.trip_source}</td>
                  <td className="px-5 py-4 text-sm text-gray-900">{trip.trip_purpose}</td>
                  <td className="px-5 py-4">
                    <div className="text-sm font-semibold text-[#0F172A]">
                      {trip.vehicle?.registration_number || 'Vehicle pending'}
                    </div>
                    <div className="text-xs text-gray-500">
                      {trip.odometer_start ?? '-'} / {trip.odometer_end ?? '-'}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!filteredRides.length && (
            <div className="px-6 py-16 text-center text-gray-500">
              No trips match your current filters.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
