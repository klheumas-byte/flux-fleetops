import { useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowLeft,
  Calendar,
  Car,
  CheckCircle2,
  Clock3,
  DollarSign,
  FileCheck2,
  Fuel,
  ShieldCheck,
  Truck,
  Wrench,
} from 'lucide-react';
import { apiRequest, ApiRequestError } from '../../lib/api';
import { usePageToastFeedback } from '../../lib/use-page-toast-feedback';

type DetailTab =
  | 'overview'
  | 'assignment'
  | 'investment'
  | 'recovery'
  | 'maintenance'
  | 'compliance'
  | 'economics';

interface VehicleDetailsProps {
  vehicleId: string;
  onBack: () => void;
  onMissingRecord?: () => void;
}

interface Vehicle {
  id: string;
  registration_number: string;
  vehicle_type: string;
  make: string;
  model: string;
  year: number;
  color: string | null;
  transmission: string;
  fuel_type: string;
  chassis_number: string | null;
  engine_number: string | null;
  insurance_expiry: string | null;
  roadworthy_expiry: string | null;
  default_weekly_target: number;
  default_daily_target: number;
  current_odometer?: number | null;
  purchase_cost?: number | null;
  shipping_cost?: number | null;
  clearing_cost?: number | null;
  insurance_cost?: number | null;
  roadworthy_cost?: number | null;
  ama_permit_cost?: number | null;
  vehicle_license_cost?: number | null;
  tracker_cost?: number | null;
  branding_cost?: number | null;
  initial_repairs_cost?: number | null;
  registration_cost?: number | null;
  other_setup_cost?: number | null;
  status: string;
  assigned_driver_id: string | null;
  vehicle_cost_items?: Array<{
    id: string;
    item_name: string;
    amount: number;
    date: string;
    notes?: string | null;
  }>;
  economics?: {
    investment?: {
      purchase_cost?: number;
      shipping_cost?: number;
      clearing_cost?: number;
      insurance_cost?: number;
      roadworthy_cost?: number;
      ama_permit_cost?: number;
      vehicle_license_cost?: number;
      tracker_cost?: number;
      branding_cost?: number;
      initial_repairs_cost?: number;
      registration_cost?: number;
      other_setup_cost?: number;
      custom_cost_total?: number;
      total_vehicle_investment?: number;
    };
    recovery?: {
      amount_recovered?: number;
      remaining_balance?: number;
      recovery_percentage?: number;
      estimated_recovery_weeks?: number;
      estimated_recovery_months?: number;
      estimated_break_even_date?: string | null;
      status?: string;
      recovery_status?: string;
    };
    operating_costs?: {
      fuel_cost?: number;
      maintenance_cost?: number;
      repair_cost?: number;
      expense_cost?: number;
      compliance_renewal_cost?: number;
      company_vehicle_costs?: number;
      include_fuel_in_profitability?: boolean;
      monthly?: number;
      quarterly?: number;
      annual?: number;
      lifetime?: number;
    };
    profitability?: {
      gross_revenue?: number;
      operating_costs?: number;
      company_vehicle_costs?: number;
      net_profit?: number;
      profit_margin?: number;
      roi?: number;
    };
    performance?: {
      trips_today?: number;
      trips_this_month?: number;
      utilization_percentage?: number;
      active_days?: number;
      idle_days?: number;
      downtime_days?: number;
    };
    health?: {
      score?: number;
      category?: string;
      fault_frequency?: number;
      critical_faults?: number;
    };
    fuel_analytics?: {
      fuel_by_vehicle?: number;
      fuel_by_station?: Array<{ station_name?: string | null; amount?: number }>;
      fuel_by_driver?: Array<{ driver_id?: string | null; amount?: number }>;
      monthly_trend?: Array<{ month?: string; amount?: number }>;
    };
  };
  created_by: string;
  created_at: string;
  updated_at: string;
}

interface VehicleResponse {
  success: boolean;
  message: string;
  data: {
    vehicle: Vehicle;
  };
}

interface VehicleEconomicsResponse {
  success: boolean;
  message: string;
  data: {
    economics: Vehicle['economics'];
    vehicle_cost_items: NonNullable<Vehicle['vehicle_cost_items']>;
    purchase_cost?: number | null;
    shipping_cost?: number | null;
    clearing_cost?: number | null;
    insurance_cost?: number | null;
    roadworthy_cost?: number | null;
    ama_permit_cost?: number | null;
    vehicle_license_cost?: number | null;
    tracker_cost?: number | null;
    branding_cost?: number | null;
    initial_repairs_cost?: number | null;
    registration_cost?: number | null;
    other_setup_cost?: number | null;
  };
}

interface PreventiveSchedule {
  id: string;
  vehicle_id: string;
  title: string;
  maintenance_type: string;
  next_due_date?: string | null;
  next_due_odometer?: number | null;
  recurrence_type?: string;
  status: string;
}

interface PreventiveSchedulesResponse {
  success: boolean;
  data: {
    schedules: PreventiveSchedule[];
  };
}

interface ComplianceRecord {
  id: string;
  vehicle_id: string;
  compliance_item_name: string;
  provider_or_authority_name?: string | null;
  expiry_date?: string | null;
  status: string;
}

interface ComplianceRecordsResponse {
  success: boolean;
  data: {
    records: ComplianceRecord[];
  };
}

const tabs: Array<{ id: DetailTab; label: string; icon: typeof Car }> = [
  { id: 'overview', label: 'Overview', icon: Car },
  { id: 'assignment', label: 'Assignment', icon: Truck },
  { id: 'investment', label: 'Investment', icon: DollarSign },
  { id: 'recovery', label: 'Recovery', icon: CheckCircle2 },
  { id: 'maintenance', label: 'Maintenance', icon: Wrench },
  { id: 'compliance', label: 'Compliance', icon: FileCheck2 },
  { id: 'economics', label: 'Economics', icon: Fuel },
];

function formatCurrency(value: number | null | undefined) {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return '-';
  }

  return `GHS ${value.toLocaleString()}`;
}

function formatLabel(value: string | null | undefined) {
  if (!value) {
    return '-';
  }

  return value
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function formatDate(value: string | null | undefined) {
  if (!value) {
    return '-';
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return date.toLocaleDateString();
}

function StatCard({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: string | number;
  icon: typeof Car;
}) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-lg bg-blue-50">
        <Icon className="h-5 w-5 text-blue-600" />
      </div>
      <div className="text-2xl font-semibold text-[#0F172A]">{value}</div>
      <div className="mt-1 text-sm text-gray-500">{label}</div>
    </div>
  );
}

function EmptyPanel({ label }: { label: string }) {
  return (
    <div className="rounded-xl border border-dashed border-gray-300 bg-gray-50 px-4 py-10 text-center text-sm text-gray-500">
      {label}
    </div>
  );
}

function resolveVehicleDetailsError(error: unknown) {
  if (error instanceof ApiRequestError) {
    if (error.status === 0 && /timed out/i.test(error.message)) {
      return 'Unable to load vehicle details. Please try again.';
    }
    return error.message || 'Unable to load vehicle details. Please try again.';
  }

  return 'Unable to load vehicle details. Please try again.';
}

export default function VehicleDetails({ vehicleId, onBack, onMissingRecord }: VehicleDetailsProps) {
  const [activeTab, setActiveTab] = useState<DetailTab>('overview');
  const [vehicle, setVehicle] = useState<Vehicle | null>(null);
  const [maintenance, setMaintenance] = useState<PreventiveSchedule[]>([]);
  const [compliance, setCompliance] = useState<ComplianceRecord[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isTabLoading, setIsTabLoading] = useState(false);
  const [hasLoadedEconomics, setHasLoadedEconomics] = useState(false);
  const [pageError, setPageError] = useState('');
  const [tabError, setTabError] = useState('');
  const overviewRequestSequence = useRef(0);
  const hasVehicle = Boolean(vehicle?.id);
  usePageToastFeedback(pageError, tabError);

  useEffect(() => {
    setActiveTab('overview');
    setHasLoadedEconomics(false);
    setMaintenance([]);
    setCompliance([]);
    setPageError('');
    setTabError('');
  }, [vehicleId]);

  useEffect(() => {
    let isMounted = true;

    const loadVehicleDetails = async () => {
      const requestSequence = overviewRequestSequence.current + 1;
      overviewRequestSequence.current = requestSequence;
      const pageLoadStartedAt = performance.now();
      const timeoutHandle = window.setTimeout(() => {
        if (!isMounted || overviewRequestSequence.current !== requestSequence) {
          return;
        }
        console.error('[Flux Performance] Vehicle details watchdog timeout', {
          vehicleId,
          requestSequence,
          durationMs: Number((performance.now() - pageLoadStartedAt).toFixed(2)),
        });
        setPageError('Unable to load vehicle details. Please try again.');
        setVehicle(null);
        setIsLoading(false);
      }, 10000);

      console.info('[Flux Performance] Vehicle details request start', {
        vehicleId,
        requestSequence,
        endpoint: `/vehicles/${vehicleId}?include_economics=false`,
      });
      setIsLoading(true);
      setPageError('');
      setTabError('');
      setVehicle(null);

      try {
        const vehicleResponse = await apiRequest<VehicleResponse>(`/vehicles/${vehicleId}?include_economics=false`, {
          cacheTtlMs: 15000,
          timeoutMs: 10000,
          dedupeKey: `vehicle-detail:${vehicleId}`,
        });

        if (!isMounted) {
          return;
        }

        setVehicle(vehicleResponse.data.vehicle);
        console.info('[Flux Performance] Vehicle details API response', {
          vehicleId,
          requestSequence,
          vehicle: vehicleResponse.data.vehicle,
        });
        console.info('[Flux Performance] Vehicle details request end', {
          vehicleId,
          requestSequence,
          status: 'success',
          durationMs: Number((performance.now() - pageLoadStartedAt).toFixed(2)),
        });
      } catch (error) {
        console.error('[Flux Performance] Vehicle details request end', {
          vehicleId,
          requestSequence,
          status: 'error',
          durationMs: Number((performance.now() - pageLoadStartedAt).toFixed(2)),
          error,
        });
        if (!isMounted) {
          return;
        }
        if (error instanceof ApiRequestError && error.status === 404) {
          onMissingRecord?.();
          return;
        }
        setPageError(resolveVehicleDetailsError(error));
        setVehicle(null);
      } finally {
        window.clearTimeout(timeoutHandle);
        if (isMounted) {
          setIsLoading(false);
        }
      }
    };

    void loadVehicleDetails();

    return () => {
      isMounted = false;
    };
  }, [vehicleId]);

  useEffect(() => {
    let isMounted = true;

    const loadTabData = async () => {
      if (!hasVehicle) {
        return;
      }

      const needsEconomics = activeTab === 'investment' || activeTab === 'recovery' || activeTab === 'economics';
      const needsMaintenance = activeTab === 'maintenance';
      const needsCompliance = activeTab === 'compliance';

      if (!needsEconomics && !needsMaintenance && !needsCompliance) {
        return;
      }

      if (needsEconomics && hasLoadedEconomics) {
        return;
      }
      if (needsMaintenance && maintenance.length > 0) {
        return;
      }
      if (needsCompliance && compliance.length > 0) {
        return;
      }

      setIsTabLoading(true);
      setTabError('');
      try {
        if (needsEconomics) {
          console.info('[Flux Performance] Vehicle economics requested', { vehicleId, activeTab });
          const response = await apiRequest<VehicleEconomicsResponse>(`/vehicles/${vehicleId}/economics`, {
            cacheTtlMs: 15000,
            timeoutMs: 10000,
            dedupeKey: `vehicle-economics:${vehicleId}`,
          });
          if (!isMounted) {
            return;
          }
          setVehicle((currentVehicle) =>
            currentVehicle
              ? {
                  ...currentVehicle,
                  purchase_cost: response.data.purchase_cost ?? currentVehicle.purchase_cost,
                  shipping_cost: response.data.shipping_cost ?? currentVehicle.shipping_cost,
                  clearing_cost: response.data.clearing_cost ?? currentVehicle.clearing_cost,
                  insurance_cost: response.data.insurance_cost ?? currentVehicle.insurance_cost,
                  roadworthy_cost: response.data.roadworthy_cost ?? currentVehicle.roadworthy_cost,
                  ama_permit_cost: response.data.ama_permit_cost ?? currentVehicle.ama_permit_cost,
                  vehicle_license_cost:
                    response.data.vehicle_license_cost ?? currentVehicle.vehicle_license_cost,
                  tracker_cost: response.data.tracker_cost ?? currentVehicle.tracker_cost,
                  branding_cost: response.data.branding_cost ?? currentVehicle.branding_cost,
                  initial_repairs_cost:
                    response.data.initial_repairs_cost ?? currentVehicle.initial_repairs_cost,
                  registration_cost: response.data.registration_cost ?? currentVehicle.registration_cost,
                  other_setup_cost: response.data.other_setup_cost ?? currentVehicle.other_setup_cost,
                  vehicle_cost_items: response.data.vehicle_cost_items || [],
                  economics: response.data.economics || {},
                }
              : currentVehicle,
          );
          setHasLoadedEconomics(true);
        } else if (needsMaintenance) {
          const response = await apiRequest<PreventiveSchedulesResponse>(
            `/preventive-maintenance?vehicle_id=${vehicleId}`,
            { cacheTtlMs: 15000, timeoutMs: 10000, dedupeKey: `vehicle-maintenance:${vehicleId}` },
          );
          if (!isMounted) {
            return;
          }
          setMaintenance(response.data?.schedules || []);
        } else {
          const response = await apiRequest<ComplianceRecordsResponse>(
            `/preventive-maintenance/compliance/records?vehicle_id=${vehicleId}`,
            { cacheTtlMs: 15000, timeoutMs: 10000, dedupeKey: `vehicle-compliance:${vehicleId}` },
          );
          if (!isMounted) {
            return;
          }
          setCompliance(response.data?.records || []);
        }
      } catch (error) {
        console.error('[Flux Performance] Vehicle tab load failed', { vehicleId, activeTab, error });
        if (!isMounted) {
          return;
        }
        setTabError(
          activeTab === 'investment' || activeTab === 'recovery' || activeTab === 'economics'
            ? 'Unable to load vehicle details. Please try again.'
            : error instanceof ApiRequestError
              ? error.message
              : 'Unable to load vehicle tab data right now.',
        );
      } finally {
        if (isMounted) {
          setIsTabLoading(false);
        }
      }
    };

    void loadTabData();

    return () => {
      isMounted = false;
    };
  }, [activeTab, vehicleId, hasVehicle, hasLoadedEconomics, maintenance.length, compliance.length]);

  const investmentItems = useMemo(
    () => [
      ['Purchase Cost', vehicle?.economics?.investment?.purchase_cost ?? vehicle?.purchase_cost],
      ['Shipping Cost', vehicle?.economics?.investment?.shipping_cost ?? vehicle?.shipping_cost],
      ['Clearing Cost', vehicle?.economics?.investment?.clearing_cost ?? vehicle?.clearing_cost],
      ['Insurance Cost', vehicle?.economics?.investment?.insurance_cost ?? vehicle?.insurance_cost],
      ['Roadworthy Cost', vehicle?.economics?.investment?.roadworthy_cost ?? vehicle?.roadworthy_cost],
      ['AMA Permit Cost', vehicle?.economics?.investment?.ama_permit_cost ?? vehicle?.ama_permit_cost],
      ['Vehicle License Cost', vehicle?.economics?.investment?.vehicle_license_cost ?? vehicle?.vehicle_license_cost],
      ['Tracker Cost', vehicle?.economics?.investment?.tracker_cost ?? vehicle?.tracker_cost],
      ['Branding Cost', vehicle?.economics?.investment?.branding_cost ?? vehicle?.branding_cost],
      ['Initial Repairs Cost', vehicle?.economics?.investment?.initial_repairs_cost ?? vehicle?.initial_repairs_cost],
      ['Registration Cost', vehicle?.economics?.investment?.registration_cost ?? vehicle?.registration_cost],
      ['Other Setup Cost', vehicle?.economics?.investment?.other_setup_cost ?? vehicle?.other_setup_cost],
      ['Custom Cost Total', vehicle?.economics?.investment?.custom_cost_total],
      ['Total Vehicle Investment', vehicle?.economics?.investment?.total_vehicle_investment],
    ],
    [vehicle],
  );

  if (isLoading) {
    return (
      <div className="space-y-6 p-4 sm:p-6">
        <button
          type="button"
          onClick={onBack}
          className="inline-flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Vehicles
        </button>
        <div className="rounded-xl border border-gray-200 bg-white px-6 py-16 text-center text-gray-500">
          <div className="space-y-4">
            <div className="mx-auto h-6 w-40 animate-pulse rounded bg-gray-100" />
            <div className="mx-auto h-4 w-56 animate-pulse rounded bg-gray-100" />
          </div>
        </div>
      </div>
    );
  }

  if (!vehicle) {
    return (
      <div className="space-y-6 p-4 sm:p-6">
        <button
          type="button"
          onClick={onBack}
          className="inline-flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Vehicles
        </button>
        <EmptyPanel label={pageError || 'Vehicle details could not be loaded.'} />
      </div>
    );
  }

  const recovery = vehicle.economics?.recovery;
  const operatingCosts = vehicle.economics?.operating_costs;
  const profitability = vehicle.economics?.profitability;
  const vehiclePerformance = vehicle.economics?.performance;
  const health = vehicle.economics?.health;
  const fuelAnalytics = vehicle.economics?.fuel_analytics;
  const economicsTabsActive = activeTab === 'investment' || activeTab === 'recovery' || activeTab === 'economics';

  return (
    <div className="space-y-6 p-4 sm:p-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <button
            type="button"
            onClick={onBack}
            className="mb-3 inline-flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to Vehicles
          </button>
          <h1 className="break-words text-2xl font-semibold text-[#0F172A]">
            {vehicle.registration_number}
          </h1>
          <p className="mt-1 break-words text-sm text-gray-500">
            {vehicle.make} {vehicle.model} • {vehicle.year} • {formatLabel(vehicle.vehicle_type)}
          </p>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-3 text-sm text-gray-600">
          <div>Status: <span className="font-medium text-[#0F172A]">{formatLabel(vehicle.status)}</span></div>
          <div className="mt-1">Assigned Driver: <span className="font-medium text-[#0F172A]">{vehicle.assigned_driver_id ? `Driver ID: ${vehicle.assigned_driver_id.slice(0, 8)}...` : 'Unassigned'}</span></div>
        </div>
      </div>

      {hasLoadedEconomics && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatCard label="Trips Today" value={vehiclePerformance?.trips_today ?? '-'} icon={Truck} />
          <StatCard label="Trips This Month" value={vehiclePerformance?.trips_this_month ?? '-'} icon={Calendar} />
          <StatCard label="Utilization" value={vehiclePerformance?.utilization_percentage != null ? `${vehiclePerformance.utilization_percentage}%` : '-'} icon={Clock3} />
          <StatCard label="Health Score" value={health?.score != null ? `${health.score}/100` : '-'} icon={ShieldCheck} />
        </div>
      )}

      <div className="overflow-x-auto">
        <div className="inline-flex min-w-full gap-2 rounded-xl border border-gray-200 bg-white p-2">
          {tabs.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              type="button"
              onClick={() => setActiveTab(id)}
              className={`inline-flex items-center gap-2 whitespace-nowrap rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
                activeTab === id
                  ? 'bg-[#2563EB] text-white'
                  : 'text-gray-600 hover:bg-gray-100'
              }`}
            >
              <Icon className="h-4 w-4" />
              {label}
            </button>
          ))}
        </div>
      </div>

      {activeTab === 'overview' && (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <div className="rounded-xl border border-gray-200 bg-white p-5">
            <h2 className="text-lg font-semibold text-[#0F172A]">Vehicle Overview</h2>
            <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
              <DetailRow label="Registration" value={vehicle.registration_number} />
              <DetailRow label="Vehicle Type" value={formatLabel(vehicle.vehicle_type)} />
              <DetailRow label="Make / Model" value={`${vehicle.make} ${vehicle.model}`} />
              <DetailRow label="Year" value={vehicle.year} />
              <DetailRow label="Color" value={vehicle.color} />
              <DetailRow label="Transmission" value={formatLabel(vehicle.transmission)} />
              <DetailRow label="Fuel Type" value={formatLabel(vehicle.fuel_type)} />
              <DetailRow label="Chassis Number" value={vehicle.chassis_number} />
              <DetailRow label="Engine Number" value={vehicle.engine_number} />
              <DetailRow
                label="Current Odometer"
                value={vehicle.current_odometer != null ? `${vehicle.current_odometer.toLocaleString()} km` : '-'}
              />
              <DetailRow label="Created" value={formatDate(vehicle.created_at)} />
            </div>
          </div>
          <div className="rounded-xl border border-gray-200 bg-white p-5">
            <h2 className="text-lg font-semibold text-[#0F172A]">Expiry Snapshot</h2>
            <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
              <DetailRow label="Insurance Expiry" value={formatDate(vehicle.insurance_expiry)} />
              <DetailRow label="Roadworthy Expiry" value={formatDate(vehicle.roadworthy_expiry)} />
              <DetailRow label="Weekly Target" value={formatCurrency(vehicle.default_weekly_target)} />
              <DetailRow label="Daily Target" value={formatCurrency(vehicle.default_daily_target)} />
              <DetailRow label="Active Days" value={vehiclePerformance?.active_days ?? 0} />
              <DetailRow label="Idle Days" value={vehiclePerformance?.idle_days ?? 0} />
              <DetailRow label="Downtime Days" value={vehiclePerformance?.downtime_days ?? 0} />
              <DetailRow label="Health Category" value={health?.category} />
            </div>
          </div>
        </div>
      )}

      {activeTab === 'assignment' && (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <div className="rounded-xl border border-gray-200 bg-white p-5">
            <h2 className="text-lg font-semibold text-[#0F172A]">Assignment</h2>
            <div className="mt-4 grid grid-cols-1 gap-3">
              <DetailRow
                label="Assigned Driver"
                value={vehicle.assigned_driver_id ? `Driver ID: ${vehicle.assigned_driver_id}` : 'Unassigned'}
              />
              <DetailRow label="Vehicle Status" value={formatLabel(vehicle.status)} />
              <DetailRow label="Updated At" value={formatDate(vehicle.updated_at)} />
              <DetailRow label="Created By" value={vehicle.created_by} />
            </div>
          </div>
          <div className="rounded-xl border border-gray-200 bg-white p-5">
            <h2 className="text-lg font-semibold text-[#0F172A]">Targets</h2>
            <div className="mt-4 grid grid-cols-1 gap-3">
              <DetailRow label="Default Weekly Target" value={formatCurrency(vehicle.default_weekly_target)} />
              <DetailRow label="Default Daily Target" value={formatCurrency(vehicle.default_daily_target)} />
              <DetailRow label="Trips Today" value={vehiclePerformance?.trips_today ?? 0} />
              <DetailRow label="Trips This Month" value={vehiclePerformance?.trips_this_month ?? 0} />
            </div>
          </div>
        </div>
      )}

      {activeTab === 'investment' && (
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <h2 className="text-lg font-semibold text-[#0F172A]">Investment</h2>
          {tabError && <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700">{tabError}</div>}
          {isTabLoading && economicsTabsActive ? (
            <TabSkeleton />
          ) : vehicle.economics?.investment ? (
            <>
              <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {investmentItems.map(([label, value]) => (
                  <DetailRow key={label} label={label} value={formatCurrency(value as number | null | undefined)} />
                ))}
              </div>
              <div className="mt-6">
                <h3 className="text-sm font-semibold uppercase tracking-wide text-gray-500">Custom Cost Items</h3>
                {vehicle.vehicle_cost_items && vehicle.vehicle_cost_items.length > 0 ? (
                  <div className="mt-3 overflow-x-auto">
                    <table className="min-w-full divide-y divide-gray-200 text-sm">
                      <thead className="bg-gray-50">
                        <tr>
                          {['Item', 'Amount', 'Date', 'Notes'].map((header) => (
                            <th key={header} className="px-4 py-3 text-left font-semibold text-gray-600">
                              {header}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-200">
                        {vehicle.vehicle_cost_items.map((item) => (
                          <tr key={item.id}>
                            <td className="px-4 py-3 text-gray-900">{item.item_name}</td>
                            <td className="px-4 py-3 text-gray-600">{formatCurrency(item.amount)}</td>
                            <td className="px-4 py-3 text-gray-600">{formatDate(item.date)}</td>
                            <td className="px-4 py-3 text-gray-600">{item.notes || '-'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <EmptyPanel label="No custom vehicle cost items recorded yet." />
                )}
              </div>
            </>
          ) : (
            <EmptyPanel label="Investment data is restricted for your role or not available yet." />
          )}
        </div>
      )}

      {activeTab === 'recovery' && (
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <h2 className="text-lg font-semibold text-[#0F172A]">Capital Recovery</h2>
          {tabError && <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700">{tabError}</div>}
          {isTabLoading && economicsTabsActive ? (
            <TabSkeleton />
          ) : recovery && Object.keys(recovery).length > 0 ? (
            <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
              <DetailRow label="Amount Recovered" value={formatCurrency(recovery.amount_recovered)} />
              <DetailRow label="Remaining Balance" value={formatCurrency(recovery.remaining_balance)} />
              <DetailRow label="Recovery %" value={`${recovery.recovery_percentage ?? 0}%`} />
              <DetailRow label="Recovery Status" value={recovery.recovery_status || recovery.status} />
              <DetailRow label="Estimated Recovery Weeks" value={recovery.estimated_recovery_weeks ?? 0} />
              <DetailRow label="Estimated Recovery Months" value={recovery.estimated_recovery_months ?? 0} />
              <DetailRow label="Break-Even Forecast" value={formatDate(recovery.estimated_break_even_date)} />
            </div>
          ) : (
            <EmptyPanel label="Recovery data is restricted for your role or not available yet." />
          )}
        </div>
      )}

      {activeTab === 'maintenance' && (
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <h2 className="text-lg font-semibold text-[#0F172A]">Maintenance</h2>
          {tabError && <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700">{tabError}</div>}
          {isTabLoading ? (
            <TabSkeleton />
          ) : maintenance.length > 0 ? (
            <div className="mt-4 overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200 text-sm">
                <thead className="bg-gray-50">
                  <tr>
                    {['Item', 'Recurrence', 'Next Due Date', 'Next Due Odometer', 'Status'].map((header) => (
                      <th key={header} className="px-4 py-3 text-left font-semibold text-gray-600">
                        {header}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {maintenance.map((item) => (
                    <tr key={item.id}>
                      <td className="px-4 py-3 text-gray-900">{item.title || formatLabel(item.maintenance_type)}</td>
                      <td className="px-4 py-3 text-gray-600">{formatLabel(item.recurrence_type)}</td>
                      <td className="px-4 py-3 text-gray-600">{formatDate(item.next_due_date)}</td>
                      <td className="px-4 py-3 text-gray-600">{item.next_due_odometer ?? '-'}</td>
                      <td className="px-4 py-3 text-gray-600">{formatLabel(item.status)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyPanel label="No preventive maintenance schedules found for this vehicle." />
          )}
        </div>
      )}

      {activeTab === 'compliance' && (
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <h2 className="text-lg font-semibold text-[#0F172A]">Compliance</h2>
          {tabError && <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700">{tabError}</div>}
          {isTabLoading ? (
            <TabSkeleton />
          ) : compliance.length > 0 ? (
            <div className="mt-4 overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200 text-sm">
                <thead className="bg-gray-50">
                  <tr>
                    {['Item', 'Authority', 'Expiry Date', 'Status'].map((header) => (
                      <th key={header} className="px-4 py-3 text-left font-semibold text-gray-600">
                        {header}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {compliance.map((item) => (
                    <tr key={item.id}>
                      <td className="px-4 py-3 text-gray-900">{item.compliance_item_name}</td>
                      <td className="px-4 py-3 text-gray-600">{item.provider_or_authority_name || '-'}</td>
                      <td className="px-4 py-3 text-gray-600">{formatDate(item.expiry_date)}</td>
                      <td className="px-4 py-3 text-gray-600">{formatLabel(item.status)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyPanel label="No compliance records found for this vehicle." />
          )}
        </div>
      )}

      {activeTab === 'economics' && (
        isTabLoading && economicsTabsActive ? (
          <TabSkeleton />
        ) : (
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            {tabError && <div className="xl:col-span-2 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700">{tabError}</div>}
            <div className="rounded-xl border border-gray-200 bg-white p-5">
              <h2 className="text-lg font-semibold text-[#0F172A]">Operating Costs</h2>
              <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
                <DetailRow label="Company Vehicle Costs" value={formatCurrency(operatingCosts?.company_vehicle_costs)} />
                <DetailRow label="Maintenance Costs" value={formatCurrency(operatingCosts?.maintenance_cost)} />
                <DetailRow label="Repair Costs" value={formatCurrency(operatingCosts?.repair_cost)} />
                <DetailRow label="Expense Costs" value={formatCurrency(operatingCosts?.expense_cost)} />
                <DetailRow label="Compliance Renewal Costs" value={formatCurrency(operatingCosts?.compliance_renewal_cost)} />
                <DetailRow label="Fuel Included In Profitability" value={operatingCosts?.include_fuel_in_profitability ? 'Yes' : 'No'} />
                <DetailRow label="Monthly Operating Costs" value={formatCurrency(operatingCosts?.monthly)} />
                <DetailRow label="Annual Operating Costs" value={formatCurrency(operatingCosts?.annual)} />
              </div>
            </div>
            <div className="rounded-xl border border-gray-200 bg-white p-5">
              <h2 className="text-lg font-semibold text-[#0F172A]">Performance & Profitability</h2>
              <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
                <DetailRow label="Gross Revenue" value={formatCurrency(profitability?.gross_revenue)} />
                <DetailRow label="Net Profit" value={formatCurrency(profitability?.net_profit)} />
                <DetailRow label="Profit Margin" value={profitability?.profit_margin != null ? `${profitability.profit_margin}%` : '-'} />
                <DetailRow label="ROI" value={profitability?.roi != null ? `${profitability.roi}%` : '-'} />
                <DetailRow label="Fuel By Vehicle" value={formatCurrency(fuelAnalytics?.fuel_by_vehicle)} />
                <DetailRow label="Fault Frequency" value={health?.fault_frequency ?? 0} />
                <DetailRow label="Critical Faults" value={health?.critical_faults ?? 0} />
                <DetailRow label="Health Category" value={health?.category} />
              </div>
            </div>
          </div>
        )
      )}
    </div>
  );
}

function TabSkeleton() {
  return (
    <div className="mt-4 space-y-3">
      {Array.from({ length: 4 }).map((_, index) => (
        <div key={index} className="h-12 animate-pulse rounded-lg bg-gray-100" />
      ))}
    </div>
  );
}

function DetailRow({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3">
      <div className="text-xs font-semibold uppercase tracking-wide text-gray-500">{label}</div>
      <div className="mt-1 break-words text-sm font-medium text-[#0F172A]">
        {value === null || value === undefined || value === '' ? '-' : value}
      </div>
    </div>
  );
}
