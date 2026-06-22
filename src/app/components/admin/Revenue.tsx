import { useEffect, useMemo, useState } from 'react';
import { Activity, BarChart3, Calendar, CarFront, Loader2, Route, Users } from 'lucide-react';
import { Bar, BarChart, CartesianGrid, Legend, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { ApiRequestError } from '../../lib/api';
import { fetchRideSummary, type TripSummary } from '../../lib/ride-masterdata-api';

export default function Revenue() {
  const [summary, setSummary] = useState<TripSummary | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [pageError, setPageError] = useState('');

  useEffect(() => {
    const loadDashboard = async () => {
      setIsLoading(true);
      setPageError('');
      try {
        const nextSummary = await fetchRideSummary();
        setSummary(nextSummary);
      } catch (error) {
        if (error instanceof ApiRequestError) {
          setPageError(error.message);
        } else {
          setPageError('Unable to load fleet utilization dashboard right now.');
        }
      } finally {
        setIsLoading(false);
      }
    };

    void loadDashboard();
  }, []);

  const topVehicles = useMemo(() => (summary?.vehicle_utilization || []).slice(0, 6), [summary]);

  if (isLoading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center gap-3 text-gray-500">
        <Loader2 className="h-5 w-5 animate-spin" />
        <span>Loading fleet utilization dashboard...</span>
      </div>
    );
  }

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Fleet Utilization Dashboard</h1>
          <p className="mt-1 text-gray-500">Trips by platform, trips by purpose, and active versus idle vehicle usage.</p>
        </div>
      </div>

      {pageError && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {pageError}
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 md:grid-cols-4">
        {[
          { label: 'Trips Today', value: summary?.trips_today || 0, icon: Calendar, tint: 'bg-blue-100 text-blue-600' },
          { label: 'Trips This Week', value: summary?.trips_this_week || 0, icon: Route, tint: 'bg-green-100 text-green-600' },
          { label: 'Trips This Month', value: summary?.trips_this_month || 0, icon: CarFront, tint: 'bg-amber-100 text-amber-600' },
          { label: 'Customer Linked Trips', value: summary?.customer_linked_trip_count || 0, icon: Users, tint: 'bg-purple-100 text-purple-600' },
        ].map((card) => {
          const Icon = card.icon;
          return (
            <div key={card.label} className="rounded-lg border border-gray-200 bg-white p-6">
              <div className={`mb-4 flex h-12 w-12 items-center justify-center rounded-lg ${card.tint}`}>
                <Icon className="h-6 w-6" />
              </div>
              <div className="mb-2 text-3xl font-semibold text-gray-900">{card.value}</div>
              <div className="text-sm text-gray-600">{card.label}</div>
            </div>
          );
        })}
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <h3 className="mb-4 text-lg font-semibold text-gray-900">Fleet Activity Trend</h3>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={summary?.activity_trends || []}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="date" stroke="#6b7280" />
              <YAxis stroke="#6b7280" />
              <Tooltip />
              <Legend />
              <Bar dataKey="trips" fill="#2563EB" name="Trips" />
              <Bar dataKey="vehicles_active" fill="#10B981" name="Vehicles Active" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <h3 className="mb-4 text-lg font-semibold text-gray-900">Trips By Platform</h3>
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie data={summary?.trips_by_platform || []} dataKey="count" nameKey="label" outerRadius={100} fill="#2563EB" label />
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <h3 className="mb-4 text-lg font-semibold text-gray-900">Trips By Purpose</h3>
          <div className="space-y-3">
            {(summary?.trips_by_purpose || []).map((entry) => (
              <div key={entry.label} className="flex items-center justify-between rounded-lg bg-gray-50 px-4 py-3">
                <div className="text-sm font-medium text-gray-900">{entry.label}</div>
                <div className="text-sm font-semibold text-gray-900">{entry.count}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <h3 className="mb-4 text-lg font-semibold text-gray-900">Utilization Totals</h3>
          <div className="space-y-4">
            <div className="rounded-lg bg-gray-50 px-4 py-4">
              <div className="mb-1 flex items-center gap-2 text-sm font-medium text-gray-700">
                <Activity className="h-4 w-4 text-green-600" />
                Vehicle Active Days
              </div>
              <div className="text-2xl font-semibold text-gray-900">{summary?.vehicle_active_days || 0}</div>
            </div>
            <div className="rounded-lg bg-gray-50 px-4 py-4">
              <div className="mb-1 flex items-center gap-2 text-sm font-medium text-gray-700">
                <BarChart3 className="h-4 w-4 text-rose-600" />
                Vehicle Idle Days
              </div>
              <div className="text-2xl font-semibold text-gray-900">{summary?.vehicle_idle_days || 0}</div>
            </div>
            <div className="rounded-lg bg-gray-50 px-4 py-4">
              <div className="mb-1 text-sm font-medium text-gray-700">Personal Trips Included In Usage</div>
              <div className="text-2xl font-semibold text-gray-900">{summary?.personal_trip_count || 0}</div>
            </div>
          </div>
        </div>
      </div>

      <div className="rounded-lg border border-gray-200 bg-white">
        <div className="border-b border-gray-200 px-6 py-4">
          <h3 className="text-lg font-semibold text-gray-900">Vehicle Utilization Summary</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-gray-50">
              <tr>
                {['Vehicle', 'Trips', 'Active Days', 'Idle Days'].map((label) => (
                  <th key={label} className="px-6 py-3 text-left text-xs font-semibold uppercase text-gray-600">
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {topVehicles.map((entry) => (
                <tr key={entry.vehicle.id} className="hover:bg-gray-50">
                  <td className="px-6 py-4 text-sm font-medium text-gray-900">{entry.vehicle.registration_number}</td>
                  <td className="px-6 py-4 text-sm text-gray-700">{entry.trip_count}</td>
                  <td className="px-6 py-4 text-sm text-gray-700">{entry.active_days}</td>
                  <td className="px-6 py-4 text-sm text-gray-700">{entry.idle_days}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!topVehicles.length && (
            <div className="px-6 py-16 text-center text-gray-500">No vehicle utilization data available yet.</div>
          )}
        </div>
      </div>
    </div>
  );
}
