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
import {
  createFuelInstruction,
  fetchOperationOptions,
  fetchOperationRequests,
  mutateOperationRequest,
  type OperationOptions,
  type OperationRequest,
} from '../../lib/operational-request-api';

type FuelStationStatus = 'active' | 'inactive';
type FuelLogStatus = 'submitted' | 'recorded' | 'approved' | 'rejected';

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
  station_name?: string | null;
  fuel_instruction_id?: string | null;
  fuel_classification?: 'operational_fuel' | 'weekly_remittance_fuel';
  fuel_date: string;
  fuel_type: string;
  litres: number;
  amount: number;
  price_per_litre: number;
  odometer_reading: number | null;
  receipt_image: string | { provider?: string; thumbnail_url?: string; public_url?: string } | null;
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

type FuelClassificationFilter = 'all' | 'operational_fuel' | 'weekly_remittance_fuel';

interface FuelPurchaseFormState {
  vehicle_id: string;
  driver_id: string;
  authorized_amount: string;
  authorized_litres: string;
  finance_account_id: string;
  fuel_station_id: string;
  station_name: string;
  purpose: string;
  notes: string;
  idempotency_key: string;
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

function newFuelPurchaseForm(): FuelPurchaseFormState {
  return {
    vehicle_id: '', driver_id: '', authorized_amount: '', authorized_litres: '',
    finance_account_id: '', fuel_station_id: '', station_name: '', purpose: '', notes: '',
    idempotency_key: globalThis.crypto?.randomUUID?.() || `fuel-${Date.now()}-${Math.random()}`,
  };
}

interface TreasuryAccount {
  id: string;
  account_name: string;
  account_type: 'cash' | 'momo' | 'bank';
  provider_name?: string | null;
  status: 'active' | 'inactive';
}

interface TreasuryAccountsResponse {
  success: boolean;
  data: { accounts: TreasuryAccount[] };
}

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
    case 'recorded':
      return 'border-green-200 bg-green-100 text-green-700';
    case 'rejected':
      return 'border-red-200 bg-red-100 text-red-700';
    default:
      return 'border-amber-200 bg-amber-100 text-amber-700';
  }
}

function fuelPurchaseStatus(purchase: OperationRequest) {
  if (purchase.status === 'completed') return 'Verified';
  if (purchase.status === 'awaiting_verification') return purchase.verification_status === 'flagged' ? 'Flagged' : 'Awaiting Verification';
  if (purchase.status === 'scheduled' && purchase.acknowledged_at) return 'Accepted';
  if (purchase.status === 'scheduled') return 'Assigned';
  if (purchase.status === 'movement_in_progress') return 'Accepted';
  return purchase.status.replaceAll('_', ' ');
}

export default function FuelManagement() {
  const [logs, setLogs] = useState<FuelLog[]>([]);
  const [stations, setStations] = useState<FuelStation[]>([]);
  const [fuelPurchases, setFuelPurchases] = useState<OperationRequest[]>([]);
  const [operationOptions, setOperationOptions] = useState<OperationOptions | null>(null);
  const [treasuryAccounts, setTreasuryAccounts] = useState<TreasuryAccount[]>([]);
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
  const [classificationFilter, setClassificationFilter] = useState<FuelClassificationFilter>('all');
  const [showPurchaseModal, setShowPurchaseModal] = useState(false);
  const [purchaseForm, setPurchaseForm] = useState<FuelPurchaseFormState>(newFuelPurchaseForm);
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
      const [logsResult, stationsResult, purchasesResult, optionsResult, accountsResult] = await Promise.allSettled([
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
        fetchOperationRequests({ operation_type: 'fuel_station_visit', page_size: 100 }),
        fetchOperationOptions({ include_availability: false }),
        apiRequest<TreasuryAccountsResponse>('/finance/accounts', {
          cacheTtlMs: 10_000,
          dedupeKey: 'fuel-management:treasury-accounts',
          componentName: 'AdminFuel',
          requestLabel: 'treasury-accounts',
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
      if (purchasesResult.status === 'fulfilled') {
        setFuelPurchases(purchasesResult.value.requests.filter((item) => Boolean(item.fuel_instruction)));
      } else {
        setFuelPurchases([]);
      }
      if (optionsResult.status === 'fulfilled') setOperationOptions(optionsResult.value);
      if (accountsResult.status === 'fulfilled') {
        setTreasuryAccounts((accountsResult.value.data?.accounts || []).filter((account) => account.status === 'active' && ['cash', 'momo', 'bank'].includes(account.account_type)));
      } else {
        setTreasuryAccounts([]);
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
        const matchesClassification = classificationFilter === 'all' || log.fuel_classification === classificationFilter;
        return matchesDate && matchesStatus && matchesStation && matchesVehicle && matchesDriver && matchesClassification;
      }),
    [classificationFilter, dateFilter, driverFilter, logs, stationFilter, statusFilter, vehicleFilter],
  );

  const visibleFuelPurchases = useMemo(
    () => classificationFilter === 'weekly_remittance_fuel' ? [] : fuelPurchases,
    [classificationFilter, fuelPurchases],
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
  const approvedCount = logs.filter((log) => ['approved', 'recorded'].includes(log.status)).length;

  const openCreatePurchaseModal = () => {
    setPurchaseForm(newFuelPurchaseForm());
    setActionError('');
    setShowPurchaseModal(true);
  };

  const handleCreatePurchase = async (event: React.FormEvent) => {
    event.preventDefault();
    setIsSubmitting(true);
    setActionError('');
    try {
      await createFuelInstruction({
        ...purchaseForm,
        authorized_amount: purchaseForm.authorized_amount ? Number(purchaseForm.authorized_amount) : null,
        authorized_litres: purchaseForm.authorized_litres ? Number(purchaseForm.authorized_litres) : null,
        fuel_station_id: purchaseForm.fuel_station_id || null,
      });
      setShowPurchaseModal(false);
      setPurchaseForm(newFuelPurchaseForm());
      await loadFuelData();
    } catch (error) {
      setActionError(error instanceof ApiRequestError || error instanceof Error ? error.message : 'Unable to create the Fuel Purchase.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handlePurchaseDecision = async (purchase: OperationRequest, decision: 'verified' | 'flagged') => {
    const reason = decision === 'flagged' ? window.prompt('Why is this Fuel Purchase being flagged?') : null;
    if (decision === 'flagged' && !reason) return;
    setIsSubmitting(true);
    setActionError('');
    try {
      await mutateOperationRequest(purchase.id, 'verify', { decision, reason });
      await loadFuelData();
    } catch (error) {
      setActionError(error instanceof ApiRequestError || error instanceof Error ? error.message : 'Unable to review the Fuel Purchase.');
    } finally {
      setIsSubmitting(false);
    }
  };

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
            onClick={openCreatePurchaseModal}
            className="inline-flex items-center gap-2 rounded-lg bg-[#2563EB] px-4 py-2.5 font-medium text-white transition-all hover:bg-[#1d4ed8]"
          >
            <Plus className="h-4 w-4" />
            Create Fuel Purchase
          </button>
          <button
            onClick={() => void loadFuelData()}
            className="inline-flex items-center gap-2 rounded-lg border border-gray-300 px-4 py-2.5 font-medium text-gray-700 transition-all hover:bg-gray-50"
          >
            <RefreshCw className="h-4 w-4" />
            Refresh
          </button>
          <button
            onClick={openCreateStationModal}
            className="inline-flex items-center gap-2 rounded-lg border border-gray-300 px-4 py-2.5 font-medium text-gray-700 transition-all hover:bg-gray-50"
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
        <div className="mb-4 flex flex-wrap gap-2" aria-label="Fuel classification filter">
          {([
            ['all', 'All'],
            ['operational_fuel', 'Operational Fuel'],
            ['weekly_remittance_fuel', 'Weekly Remittance Fuel'],
          ] as const).map(([value, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => setClassificationFilter(value)}
              className={`rounded-full px-4 py-2 text-sm font-medium ${classificationFilter === value ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'}`}
            >
              {label}
            </button>
          ))}
        </div>
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
              <option value="recorded">Recorded (Weekly Remittance)</option>
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

      {classificationFilter !== 'weekly_remittance_fuel' && (
        <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
          <div className="border-b border-gray-200 px-6 py-4">
            <h2 className="text-lg font-semibold text-gray-900">Operational Fuel Purchases</h2>
            <p className="mt-1 text-sm text-gray-600">Company-funded instructions and their linked driver task status.</p>
          </div>
          {isLoading ? <LoadingState label="Loading fuel purchases..." /> : visibleFuelPurchases.length === 0 ? <EmptyState label="No operational fuel purchases found." /> : (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50"><tr>{['Instruction', 'Vehicle / Driver', 'Authorized', 'Actual', 'Treasury', 'Status', 'Action'].map((header) => <th key={header} className="px-6 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">{header}</th>)}</tr></thead>
                <tbody className="divide-y divide-gray-200">
                  {visibleFuelPurchases.map((purchase) => {
                    const instruction = purchase.fuel_instruction!;
                    return <tr key={purchase.id}>
                      <td className="px-6 py-4 text-sm"><div className="font-medium text-gray-900">{purchase.title}</div><div className="text-xs text-gray-500">{purchase.request_id}</div></td>
                      <td className="px-6 py-4 text-sm"><div>{purchase.vehicle?.registration_number || 'Vehicle'}</div><div className="text-xs text-gray-500">{purchase.driver?.full_name || 'Driver'}</div></td>
                      <td className="px-6 py-4 text-sm">{[instruction.authorized_amount != null ? formatCurrency(instruction.authorized_amount) : '', instruction.authorized_litres != null ? `${instruction.authorized_litres} L` : ''].filter(Boolean).join(' / ')}</td>
                      <td className="px-6 py-4 text-sm">{[instruction.actual_amount != null ? formatCurrency(instruction.actual_amount) : '', instruction.actual_litres != null ? `${instruction.actual_litres} L` : ''].filter(Boolean).join(' / ') || 'Awaiting driver'}</td>
                      <td className="px-6 py-4 text-sm">{instruction.finance_account_snapshot?.account_name || 'Treasury account'}</td>
                      <td className="px-6 py-4 text-sm">{fuelPurchaseStatus(purchase)}</td>
                      <td className="px-6 py-4 text-sm">{purchase.status === 'awaiting_verification' && purchase.verification_status !== 'flagged' ? <div className="flex gap-2"><button disabled={isSubmitting} onClick={() => void handlePurchaseDecision(purchase, 'verified')} className="rounded-lg bg-green-600 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-60">Verify</button><button disabled={isSubmitting} onClick={() => void handlePurchaseDecision(purchase, 'flagged')} className="rounded-lg border border-red-200 bg-red-50 px-3 py-1.5 text-xs font-medium text-red-700 disabled:opacity-60">Flag</button></div> : <span className="text-xs text-gray-500">{purchase.status === 'completed' ? 'Verified and posted' : purchase.verification_status === 'flagged' ? 'Awaiting driver correction' : 'Driver task in progress'}</span>}</td>
                    </tr>;
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[1.7fr_1fr]">
        <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
          <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
            <div>
              <h2 className="text-lg font-semibold text-gray-900">Fuel Logs</h2>
              <p className="mt-1 text-sm text-gray-600">
                {submittedCount} pending approval, {approvedCount} recorded / approved
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
                    {['Date', 'Class', 'Vehicle', 'Driver', 'Station', 'Amount', 'Odometer', 'Status', 'Action'].map((header) => (
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
                      <td className="px-6 py-4 text-sm"><span className="inline-flex rounded-full bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700">{log.fuel_classification === 'weekly_remittance_fuel' ? 'Weekly Remittance' : 'Operational'}</span></td>
                      <td className="px-6 py-4 text-sm text-gray-700">
                        <div className="font-medium text-gray-900">{log.vehicle?.registration_number || 'Vehicle'}</div>
                        <div className="text-xs text-gray-500">{[log.vehicle?.make, log.vehicle?.model].filter(Boolean).join(' ') || 'Fleet vehicle'}</div>
                      </td>
                      <td className="px-6 py-4 text-sm text-gray-700">{log.driver?.full_name || 'Unassigned'}</td>
                      <td className="px-6 py-4 text-sm text-gray-700">{log.fuel_station?.station_name || log.station_name || 'Station'}</td>
                      <td className="px-6 py-4 text-sm text-gray-700">
                        <div className="font-medium text-gray-900">{formatCurrency(log.amount)}</div>
                        <div className="text-xs text-gray-500">
                          {log.litres.toLocaleString()} L at {formatCurrency(log.price_per_litre)}
                        </div>
                      </td>
                      <td className="px-6 py-4 text-sm text-gray-700">
                        <div>{log.odometer_reading != null ? `${log.odometer_reading.toLocaleString()} km` : 'Odometer unavailable'}</div>
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
                        {log.fuel_instruction_id ? (
                          <span className="text-xs text-blue-600">Review linked Fuel Purchase above</span>
                        ) : log.status === 'submitted' ? (
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
                        ) : log.status === 'recorded' ? (
                          <span className="text-xs text-green-600">Recorded automatically — no approval required</span>
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

      {showPurchaseModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4 py-6">
          <div className="max-h-[92vh] w-full max-w-3xl overflow-y-auto rounded-xl border border-gray-200 bg-white shadow-2xl">
            <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
              <div><h2 className="text-xl font-semibold text-gray-900">Create Fuel Purchase</h2><p className="mt-1 text-sm text-gray-500">Operational / Company-Funded fuel instruction.</p></div>
              <button type="button" onClick={() => setShowPurchaseModal(false)} className="rounded-lg p-2 hover:bg-gray-100"><XCircle className="h-5 w-5 text-gray-500" /></button>
            </div>
            <form onSubmit={handleCreatePurchase} className="space-y-5 px-6 py-5">
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <SelectField label="Vehicle" value={purchaseForm.vehicle_id} required onChange={(value) => setPurchaseForm((current) => ({ ...current, vehicle_id: value }))} options={(operationOptions?.vehicles || []).map((item) => ({ value: item.id, label: `${item.registration_number}${item.make ? ` — ${item.make} ${item.model || ''}` : ''}` }))} />
                <SelectField label="Driver" value={purchaseForm.driver_id} required onChange={(value) => setPurchaseForm((current) => ({ ...current, driver_id: value }))} options={(operationOptions?.drivers || []).map((item) => ({ value: item.id, label: item.full_name }))} />
                <NumberField label="Authorized GHS" value={purchaseForm.authorized_amount} onChange={(value) => setPurchaseForm((current) => ({ ...current, authorized_amount: value }))} />
                <NumberField label="Authorized litres" value={purchaseForm.authorized_litres} onChange={(value) => setPurchaseForm((current) => ({ ...current, authorized_litres: value }))} />
                <SelectField label="Treasury source" value={purchaseForm.finance_account_id} required onChange={(value) => setPurchaseForm((current) => ({ ...current, finance_account_id: value }))} options={treasuryAccounts.map((item) => ({ value: item.id, label: `${item.account_name} — ${item.account_type.toUpperCase()}${item.provider_name ? ` / ${item.provider_name}` : ''}` }))} />
                <SelectField label="Known station (optional)" value={purchaseForm.fuel_station_id} onChange={(value) => setPurchaseForm((current) => ({ ...current, fuel_station_id: value }))} options={stations.filter((item) => item.status === 'active').map((item) => ({ value: item.id, label: item.station_name }))} />
                <TextField label="Station / vendor (optional)" value={purchaseForm.station_name} onChange={(value) => setPurchaseForm((current) => ({ ...current, station_name: value }))} />
                <TextField label="Purpose (optional)" value={purchaseForm.purpose} onChange={(value) => setPurchaseForm((current) => ({ ...current, purpose: value }))} />
                <div className="md:col-span-2"><label className="mb-2 block text-sm font-medium text-gray-700">Notes (optional)</label><textarea value={purchaseForm.notes} onChange={(event) => setPurchaseForm((current) => ({ ...current, notes: event.target.value }))} className="min-h-24 w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:ring-2 focus:ring-blue-500" /></div>
              </div>
              <p className="text-xs text-gray-500">At least one authorization value—GHS or litres—is required. Treasury is posted only after verification.</p>
              <div className="flex justify-end gap-3 border-t border-gray-200 pt-4"><button type="button" onClick={() => setShowPurchaseModal(false)} className="rounded-lg border border-gray-300 px-4 py-2.5 font-medium text-gray-700">Cancel</button><button type="submit" disabled={isSubmitting} className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 font-medium text-white disabled:opacity-60">{isSubmitting && <Loader2 className="h-4 w-4 animate-spin" />}Create & Assign Task</button></div>
            </form>
          </div>
        </div>
      )}

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

function NumberField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return <div><label className="mb-2 block text-sm font-medium text-gray-700">{label}</label><input type="number" min="0" step="0.01" value={value} onChange={(event) => onChange(event.target.value)} className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:ring-2 focus:ring-blue-500" /></div>;
}

function SelectField({ label, value, onChange, options, required = false }: { label: string; value: string; onChange: (value: string) => void; options: Array<{ value: string; label: string }>; required?: boolean }) {
  return <div><label className="mb-2 block text-sm font-medium text-gray-700">{label}</label><select value={value} required={required} onChange={(event) => onChange(event.target.value)} className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:ring-2 focus:ring-blue-500"><option value="">Select</option>{options.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></div>;
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
