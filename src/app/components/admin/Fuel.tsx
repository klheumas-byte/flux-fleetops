import { useEffect, useMemo, useState } from 'react';
import {
  AlertCircle,
  CheckCircle2,
  DollarSign,
  Droplets,
  Filter,
  Fuel,
  Loader2,
  MapPin,
  Pencil,
  Plus,
  RefreshCw,
  ShieldAlert,
  Store,
  XCircle,
} from 'lucide-react';
import { apiRequest, ApiRequestError } from '../../lib/api';

type FuelStationStatus = 'active' | 'inactive';
type FuelLogStatus = 'submitted' | 'approved' | 'rejected';

interface FuelStation {
  id: string;
  station_name: string;
  brand_name: string | null;
  location: string | null;
  city: string | null;
  contact_number: string | null;
  status: FuelStationStatus;
}

interface UserSummary {
  id: string;
  full_name: string;
}

interface VehicleSummary {
  id: string;
  registration_number: string;
  make?: string | null;
  model?: string | null;
}

interface FuelLog {
  id: string;
  vehicle_id: string;
  driver_id: string | null;
  fuel_station_id: string;
  fuel_date: string;
  fuel_type: string;
  litres: number;
  amount: number;
  price_per_litre: number;
  odometer_reading: number;
  receipt_image: string | null;
  notes: string | null;
  status: FuelLogStatus;
  rejection_reason: string | null;
  cost_per_km: number | null;
  distance_since_last_fill: number | null;
  abnormal_spending: boolean;
  created_at: string | null;
  vehicle?: VehicleSummary | null;
  driver?: UserSummary | null;
  fuel_station?: FuelStation | null;
}

interface FuelAnalytics {
  total_fuel_spend: number;
  total_litres: number;
  average_price_per_litre: number;
  fuel_spend_by_station: { station_name: string; total_amount: number }[];
  fuel_spend_by_vehicle: { vehicle_registration: string; total_amount: number }[];
  fuel_spend_by_driver: { driver_name: string; total_amount: number }[];
  abnormal_fuel_spending: FuelLog[];
}

interface FuelLogsResponse {
  success: boolean;
  data: {
    logs: FuelLog[];
    analytics: FuelAnalytics;
  };
}

interface FuelStationsResponse {
  success: boolean;
  data: {
    stations: FuelStation[];
  };
}

interface FuelStationMutationResponse {
  success: boolean;
  data: {
    station: FuelStation;
  };
}

interface FuelLogMutationResponse {
  success: boolean;
  data: {
    log: FuelLog;
  };
}

interface StationFormState {
  station_name: string;
  brand_name: string;
  location: string;
  city: string;
  contact_number: string;
}

const initialStationForm: StationFormState = {
  station_name: '',
  brand_name: '',
  location: '',
  city: '',
  contact_number: '',
};

function formatCurrency(value: number) {
  return `GHS ${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatDate(value: string | null | undefined) {
  if (!value) {
    return 'Not provided';
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleDateString();
}

function statusClassName(status: FuelLogStatus) {
  switch (status) {
    case 'approved':
      return 'border-green-200 bg-green-100 text-green-700';
    case 'rejected':
      return 'border-red-200 bg-red-100 text-red-700';
    default:
      return 'border-amber-200 bg-amber-100 text-amber-700';
  }
}

export default function FuelManagement() {
  const [logs, setLogs] = useState<FuelLog[]>([]);
  const [stations, setStations] = useState<FuelStation[]>([]);
  const [analytics, setAnalytics] = useState<FuelAnalytics>({
    total_fuel_spend: 0,
    total_litres: 0,
    average_price_per_litre: 0,
    fuel_spend_by_station: [],
    fuel_spend_by_vehicle: [],
    fuel_spend_by_driver: [],
    abnormal_fuel_spending: [],
  });
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [pageError, setPageError] = useState('');
  const [actionError, setActionError] = useState('');
  const [dateFilter, setDateFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | FuelLogStatus>('all');
  const [stationFilter, setStationFilter] = useState('all');
  const [vehicleFilter, setVehicleFilter] = useState('all');
  const [driverFilter, setDriverFilter] = useState('all');
  const [showStationModal, setShowStationModal] = useState(false);
  const [editingStation, setEditingStation] = useState<FuelStation | null>(null);
  const [stationForm, setStationForm] = useState<StationFormState>(initialStationForm);
  const [showRejectModal, setShowRejectModal] = useState(false);
  const [rejectingLog, setRejectingLog] = useState<FuelLog | null>(null);
  const [rejectionReason, setRejectionReason] = useState('');

  const loadFuelData = async () => {
    setIsLoading(true);
    setPageError('');
    try {
      const [logsResult, stationsResult] = await Promise.allSettled([
        apiRequest<FuelLogsResponse>('/fuel-logs', {
          cacheTtlMs: 10000,
          dedupeKey: 'fuel-logs-admin',
          componentName: 'AdminFuel',
          requestLabel: 'fuel-logs',
        }),
        apiRequest<FuelStationsResponse>('/fuel-stations', {
          cacheTtlMs: 15000,
          dedupeKey: 'fuel-stations',
          componentName: 'AdminFuel',
          requestLabel: 'fuel-stations',
        }),
      ]);

      if (logsResult.status === 'rejected') {
        throw logsResult.reason;
      }

      setLogs(Array.isArray(logsResult.value.data?.logs) ? logsResult.value.data.logs : []);
      setAnalytics(logsResult.value.data?.analytics || analytics);

      if (stationsResult.status === 'fulfilled') {
        setStations(Array.isArray(stationsResult.value.data?.stations) ? stationsResult.value.data.stations : []);
      } else {
        console.warn('[Flux Fuel] Station directory failed while logs loaded.', stationsResult.reason);
        setStations([]);
      }
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setPageError(error.message);
      } else {
        setPageError('Unable to load fuel data right now.');
      }
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void loadFuelData();
  }, []);

  const filteredLogs = useMemo(
    () =>
      logs.filter((log) => {
        const matchesDate = !dateFilter || log.fuel_date === dateFilter;
        const matchesStatus = statusFilter === 'all' || log.status === statusFilter;
        const matchesStation = stationFilter === 'all' || log.fuel_station_id === stationFilter;
        const matchesVehicle = vehicleFilter === 'all' || log.vehicle_id === vehicleFilter;
        const matchesDriver = driverFilter === 'all' || log.driver_id === driverFilter;
        return matchesDate && matchesStatus && matchesStation && matchesVehicle && matchesDriver;
      }),
    [dateFilter, driverFilter, logs, stationFilter, statusFilter, vehicleFilter],
  );

  const vehicles = useMemo(() => {
    const map = new Map<string, VehicleSummary>();
    logs.forEach((log) => {
      if (log.vehicle) {
        map.set(log.vehicle.id, log.vehicle);
      }
    });
    return Array.from(map.values());
  }, [logs]);

  const drivers = useMemo(() => {
    const map = new Map<string, UserSummary>();
    logs.forEach((log) => {
      if (log.driver) {
        map.set(log.driver.id, log.driver);
      }
    });
    return Array.from(map.values());
  }, [logs]);

  const submittedCount = logs.filter((log) => log.status === 'submitted').length;
  const approvedCount = logs.filter((log) => log.status === 'approved').length;

  const openCreateStationModal = () => {
    setEditingStation(null);
    setStationForm(initialStationForm);
    setActionError('');
    setShowStationModal(true);
  };

  const openEditStationModal = (station: FuelStation) => {
    setEditingStation(station);
    setStationForm({
      station_name: station.station_name,
      brand_name: station.brand_name || '',
      location: station.location || '',
      city: station.city || '',
      contact_number: station.contact_number || '',
    });
    setActionError('');
    setShowStationModal(true);
  };

  const handleStationSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setIsSubmitting(true);
    setActionError('');
    try {
      const payload = {
        station_name: stationForm.station_name,
        brand_name: stationForm.brand_name,
        location: stationForm.location,
        city: stationForm.city,
        contact_number: stationForm.contact_number,
      };
      if (editingStation) {
        await apiRequest<FuelStationMutationResponse>(`/fuel-stations/${editingStation.id}`, {
          method: 'PATCH',
          body: JSON.stringify(payload),
        });
      } else {
        await apiRequest<FuelStationMutationResponse>('/fuel-stations', {
          method: 'POST',
          body: JSON.stringify(payload),
        });
      }
      setShowStationModal(false);
      setStationForm(initialStationForm);
      await loadFuelData();
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setActionError(error.message);
      } else {
        setActionError('Unable to save fuel station right now.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleStationStatusToggle = async (station: FuelStation) => {
    setIsSubmitting(true);
    setActionError('');
    try {
      await apiRequest<FuelStationMutationResponse>(`/fuel-stations/${station.id}/status`, {
        method: 'PATCH',
        body: JSON.stringify({
          status: station.status === 'active' ? 'inactive' : 'active',
        }),
      });
      await loadFuelData();
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setActionError(error.message);
      } else {
        setActionError('Unable to update fuel station status right now.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleApproveLog = async (logId: string) => {
    setIsSubmitting(true);
    setActionError('');
    try {
      await apiRequest<FuelLogMutationResponse>(`/fuel-logs/${logId}/approve`, {
        method: 'PATCH',
      });
      await loadFuelData();
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setActionError(error.message);
      } else {
        setActionError('Unable to approve fuel log right now.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleRejectLog = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!rejectingLog) {
      return;
    }
    setIsSubmitting(true);
    setActionError('');
    try {
      await apiRequest<FuelLogMutationResponse>(`/fuel-logs/${rejectingLog.id}/reject`, {
        method: 'PATCH',
        body: JSON.stringify({ rejection_reason: rejectionReason }),
      });
      setShowRejectModal(false);
      setRejectingLog(null);
      setRejectionReason('');
      await loadFuelData();
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setActionError(error.message);
      } else {
        setActionError('Unable to reject fuel log right now.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="space-y-6 p-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Fuel Management</h1>
          <p className="mt-1 text-gray-500">Track fuel purchases, approvals, stations, and spending performance.</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={() => void loadFuelData()}
            className="inline-flex items-center gap-2 rounded-lg border border-gray-300 px-4 py-2.5 font-medium text-gray-700 transition-all hover:bg-gray-50"
          >
            <RefreshCw className="h-4 w-4" />
            Refresh
          </button>
          <button
            onClick={openCreateStationModal}
            className="inline-flex items-center gap-2 rounded-lg bg-[#2563EB] px-4 py-2.5 font-medium text-white transition-all hover:bg-[#1d4ed8]"
          >
            <Plus className="h-4 w-4" />
            Add Fuel Station
          </button>
        </div>
      </div>

      {pageError && <Banner tone="red" message={pageError} />}
      {actionError && <Banner tone="amber" message={actionError} />}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <MetricCard icon={DollarSign} title="Total Fuel Spend" value={formatCurrency(analytics.total_fuel_spend)} tone="red" />
        <MetricCard icon={Droplets} title="Total Litres" value={`${analytics.total_litres.toLocaleString()} L`} tone="blue" />
        <MetricCard icon={Fuel} title="Average Price / Litre" value={formatCurrency(analytics.average_price_per_litre)} tone="amber" />
        <MetricCard icon={ShieldAlert} title="Abnormal Spending" value={String(analytics.abnormal_fuel_spending.length)} tone="rose" />
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <SummaryPanel title="Fuel Spend By Station" items={analytics.fuel_spend_by_station.map((item) => ({ label: item.station_name, value: formatCurrency(item.total_amount) }))} />
        <SummaryPanel title="Fuel Spend By Vehicle" items={analytics.fuel_spend_by_vehicle.map((item) => ({ label: item.vehicle_registration, value: formatCurrency(item.total_amount) }))} />
        <SummaryPanel title="Fuel Spend By Driver" items={analytics.fuel_spend_by_driver.map((item) => ({ label: item.driver_name, value: formatCurrency(item.total_amount) }))} />
      </div>

      <div className="rounded-xl border border-gray-200 bg-white p-4">
        <div className="flex flex-col gap-4 lg:flex-row">
          <div className="flex items-center gap-2 text-sm font-medium text-gray-600">
            <Filter className="h-4 w-4" />
            Filters
          </div>
          <div className="grid flex-1 grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-5">
            <input
              type="date"
              value={dateFilter}
              onChange={(event) => setDateFilter(event.target.value)}
              className="rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
            />
            <select
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value as 'all' | FuelLogStatus)}
              className="rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
            >
              <option value="all">All Statuses</option>
              <option value="submitted">Submitted</option>
              <option value="approved">Approved</option>
              <option value="rejected">Rejected</option>
            </select>
            <select
              value={stationFilter}
              onChange={(event) => setStationFilter(event.target.value)}
              className="rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
            >
              <option value="all">All Stations</option>
              {stations.map((station) => (
                <option key={station.id} value={station.id}>
                  {station.station_name}
                </option>
              ))}
            </select>
            <select
              value={vehicleFilter}
              onChange={(event) => setVehicleFilter(event.target.value)}
              className="rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
            >
              <option value="all">All Vehicles</option>
              {vehicles.map((vehicle) => (
                <option key={vehicle.id} value={vehicle.id}>
                  {vehicle.registration_number}
                </option>
              ))}
            </select>
            <select
              value={driverFilter}
              onChange={(event) => setDriverFilter(event.target.value)}
              className="rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
            >
              <option value="all">All Drivers</option>
              {drivers.map((driver) => (
                <option key={driver.id} value={driver.id}>
                  {driver.full_name}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[1.7fr_1fr]">
        <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
          <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
            <div>
              <h2 className="text-lg font-semibold text-gray-900">Fuel Logs</h2>
              <p className="mt-1 text-sm text-gray-600">
                {submittedCount} pending approval, {approvedCount} approved
              </p>
            </div>
          </div>

          {isLoading ? (
            <LoadingState label="Loading fuel logs..." />
          ) : filteredLogs.length === 0 ? (
            <EmptyState label="No fuel logs recorded yet." />
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    {['Date', 'Vehicle', 'Driver', 'Station', 'Amount', 'Odometer', 'Status', 'Action'].map((header) => (
                      <th key={header} className="px-6 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">
                        {header}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200 bg-white">
                  {filteredLogs.map((log) => (
                    <tr key={log.id} className={log.abnormal_spending ? 'bg-red-50/40' : 'hover:bg-gray-50'}>
                      <td className="px-6 py-4 text-sm text-gray-700">
                        <div className="font-medium text-gray-900">{formatDate(log.fuel_date)}</div>
                        <div className="text-xs text-gray-500">{log.fuel_type}</div>
                      </td>
                      <td className="px-6 py-4 text-sm text-gray-700">
                        <div className="font-medium text-gray-900">{log.vehicle?.registration_number || 'Vehicle'}</div>
                        <div className="text-xs text-gray-500">{[log.vehicle?.make, log.vehicle?.model].filter(Boolean).join(' ') || 'Fleet vehicle'}</div>
                      </td>
                      <td className="px-6 py-4 text-sm text-gray-700">{log.driver?.full_name || 'Unassigned'}</td>
                      <td className="px-6 py-4 text-sm text-gray-700">{log.fuel_station?.station_name || 'Station'}</td>
                      <td className="px-6 py-4 text-sm text-gray-700">
                        <div className="font-medium text-gray-900">{formatCurrency(log.amount)}</div>
                        <div className="text-xs text-gray-500">
                          {log.litres.toLocaleString()} L at {formatCurrency(log.price_per_litre)}
                        </div>
                      </td>
                      <td className="px-6 py-4 text-sm text-gray-700">
                        <div>{log.odometer_reading.toLocaleString()} km</div>
                        <div className="text-xs text-gray-500">
                          {log.cost_per_km != null ? `${log.cost_per_km.toFixed(2)} / km` : 'No previous odometer'}
                        </div>
                      </td>
                      <td className="px-6 py-4 text-sm">
                        <div className="flex flex-col gap-2">
                          <span className={`inline-flex w-fit rounded-full border px-2.5 py-1 text-xs font-medium ${statusClassName(log.status)}`}>
                            {log.status}
                          </span>
                          {log.abnormal_spending && (
                            <span className="inline-flex w-fit rounded-full border border-red-200 bg-red-100 px-2.5 py-1 text-xs font-medium text-red-700">
                              Abnormal
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="px-6 py-4 text-sm">
                        {log.status === 'submitted' ? (
                          <div className="flex flex-wrap gap-2">
                            <button
                              disabled={isSubmitting}
                              onClick={() => void handleApproveLog(log.id)}
                              className="inline-flex items-center gap-1 rounded-lg border border-green-200 bg-green-50 px-3 py-1.5 text-xs font-medium text-green-700 hover:bg-green-100 disabled:opacity-70"
                            >
                              <CheckCircle2 className="h-3.5 w-3.5" />
                              Approve
                            </button>
                            <button
                              disabled={isSubmitting}
                              onClick={() => {
                                setRejectingLog(log);
                                setRejectionReason('');
                                setShowRejectModal(true);
                              }}
                              className="inline-flex items-center gap-1 rounded-lg border border-red-200 bg-red-50 px-3 py-1.5 text-xs font-medium text-red-700 hover:bg-red-100 disabled:opacity-70"
                            >
                              <XCircle className="h-3.5 w-3.5" />
                              Reject
                            </button>
                          </div>
                        ) : log.status === 'rejected' ? (
                          <span className="text-xs text-red-600">{log.rejection_reason || 'Rejected'}</span>
                        ) : (
                          <span className="text-xs text-green-600">Approved</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
          <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
            <div>
              <h2 className="text-lg font-semibold text-gray-900">Fuel Stations</h2>
              <p className="mt-1 text-sm text-gray-600">{stations.filter((station) => station.status === 'active').length} active stations</p>
            </div>
          </div>

          {isLoading ? (
            <LoadingState label="Loading fuel stations..." />
          ) : stations.length === 0 ? (
            <EmptyState label="No fuel stations created yet." />
          ) : (
            <div className="divide-y divide-gray-200">
              {stations.map((station) => (
                <div key={station.id} className="space-y-3 px-6 py-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="flex items-center gap-2">
                        <Store className="h-4 w-4 text-[#2563EB]" />
                        <h3 className="text-sm font-semibold text-gray-900">{station.station_name}</h3>
                      </div>
                      <p className="mt-1 text-xs text-gray-500">
                        {[station.brand_name, station.location, station.city].filter(Boolean).join(' • ') || 'No location details yet'}
                      </p>
                    </div>
                    <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${station.status === 'active' ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-600'}`}>
                      {station.status}
                    </span>
                  </div>

                  <div className="flex flex-wrap gap-2">
                    <button
                      onClick={() => openEditStationModal(station)}
                      className="inline-flex items-center gap-1 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
                    >
                      <Pencil className="h-3.5 w-3.5" />
                      Edit
                    </button>
                    <button
                      disabled={isSubmitting}
                      onClick={() => void handleStationStatusToggle(station)}
                      className="inline-flex items-center gap-1 rounded-lg border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-100 disabled:opacity-70"
                    >
                      {station.status === 'active' ? 'Deactivate' : 'Activate'}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {showStationModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4 py-6">
          <div className="w-full max-w-2xl rounded-xl border border-gray-200 bg-white shadow-2xl">
            <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
              <div>
                <h2 className="text-xl font-semibold text-gray-900">
                  {editingStation ? 'Edit Fuel Station' : 'Add Fuel Station'}
                </h2>
                <p className="mt-1 text-sm text-gray-500">Manage active station options for driver fuel logs.</p>
              </div>
              <button onClick={() => setShowStationModal(false)} className="rounded-lg p-2 hover:bg-gray-100">
                <XCircle className="h-5 w-5 text-gray-500" />
              </button>
            </div>

            <form onSubmit={handleStationSubmit} className="space-y-5 px-6 py-5">
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <TextField label="Station Name" value={stationForm.station_name} onChange={(value) => setStationForm((current) => ({ ...current, station_name: value }))} />
                <TextField label="Brand Name" value={stationForm.brand_name} onChange={(value) => setStationForm((current) => ({ ...current, brand_name: value }))} />
                <TextField label="Location" value={stationForm.location} onChange={(value) => setStationForm((current) => ({ ...current, location: value }))} />
                <TextField label="City" value={stationForm.city} onChange={(value) => setStationForm((current) => ({ ...current, city: value }))} />
                <div className="md:col-span-2">
                  <TextField label="Contact Number" value={stationForm.contact_number} onChange={(value) => setStationForm((current) => ({ ...current, contact_number: value }))} />
                </div>
              </div>

              <div className="flex items-center justify-end gap-3 border-t border-gray-200 pt-4">
                <button
                  type="button"
                  onClick={() => setShowStationModal(false)}
                  className="rounded-lg border border-gray-300 px-4 py-2.5 font-medium text-gray-700 hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="inline-flex items-center gap-2 rounded-lg bg-[#2563EB] px-4 py-2.5 font-medium text-white hover:bg-[#1d4ed8] disabled:opacity-70"
                >
                  {isSubmitting && <Loader2 className="h-4 w-4 animate-spin" />}
                  {editingStation ? 'Save Changes' : 'Create Station'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {showRejectModal && rejectingLog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4 py-6">
          <div className="w-full max-w-xl rounded-xl border border-gray-200 bg-white shadow-2xl">
            <div className="border-b border-gray-200 px-6 py-4">
              <h2 className="text-xl font-semibold text-gray-900">Reject Fuel Log</h2>
              <p className="mt-1 text-sm text-gray-500">Provide the reason for rejecting this fuel log.</p>
            </div>
            <form onSubmit={handleRejectLog} className="space-y-5 px-6 py-5">
              <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                Rejection reason is required.
              </div>
              <textarea
                value={rejectionReason}
                onChange={(event) => setRejectionReason(event.target.value)}
                className="min-h-[120px] w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                placeholder="Explain why this fuel log is being rejected."
                required
              />
              <div className="flex items-center justify-end gap-3 border-t border-gray-200 pt-4">
                <button
                  type="button"
                  onClick={() => setShowRejectModal(false)}
                  className="rounded-lg border border-gray-300 px-4 py-2.5 font-medium text-gray-700 hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="inline-flex items-center gap-2 rounded-lg bg-red-600 px-4 py-2.5 font-medium text-white hover:bg-red-700 disabled:opacity-70"
                >
                  {isSubmitting && <Loader2 className="h-4 w-4 animate-spin" />}
                  Reject Fuel Log
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

function Banner({ tone, message }: { tone: 'red' | 'amber'; message: string }) {
  const classes =
    tone === 'red'
      ? 'border-red-200 bg-red-50 text-red-700'
      : 'border-amber-200 bg-amber-50 text-amber-800';
  return <div className={`rounded-lg border px-4 py-3 text-sm ${classes}`}>{message}</div>;
}

function MetricCard({
  icon: Icon,
  title,
  value,
  tone,
}: {
  icon: typeof Fuel;
  title: string;
  value: string;
  tone: 'red' | 'blue' | 'amber' | 'rose';
}) {
  const toneClasses = {
    red: 'bg-red-100 text-red-600',
    blue: 'bg-blue-100 text-blue-600',
    amber: 'bg-amber-100 text-amber-600',
    rose: 'bg-rose-100 text-rose-600',
  }[tone];

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5">
      <div className={`mb-3 flex h-10 w-10 items-center justify-center rounded-lg ${toneClasses}`}>
        <Icon className="h-5 w-5" />
      </div>
      <div className="text-2xl font-semibold text-gray-900">{value}</div>
      <div className="text-sm text-gray-600">{title}</div>
    </div>
  );
}

function SummaryPanel({
  title,
  items,
}: {
  title: string;
  items: { label: string; value: string }[];
}) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white">
      <div className="border-b border-gray-200 px-6 py-4">
        <h2 className="text-lg font-semibold text-gray-900">{title}</h2>
      </div>
      <div className="space-y-3 px-6 py-5">
        {items.length === 0 ? (
          <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 px-4 py-6 text-center text-sm text-gray-500">
            No approved fuel data available yet.
          </div>
        ) : (
          items.slice(0, 6).map((item) => (
            <div key={`${title}-${item.label}`} className="flex items-center justify-between gap-4 rounded-lg border border-gray-100 bg-gray-50 px-4 py-3">
              <span className="text-sm text-gray-700">{item.label}</span>
              <span className="text-sm font-semibold text-gray-900">{item.value}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function TextField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-gray-700">{label}</label>
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
      />
    </div>
  );
}

function LoadingState({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-center gap-3 px-6 py-14 text-gray-500">
      <Loader2 className="h-5 w-5 animate-spin" />
      <span>{label}</span>
    </div>
  );
}

function EmptyState({ label }: { label: string }) {
  return <div className="px-6 py-14 text-center text-gray-500">{label}</div>;
}
