import { type FormEvent, useEffect, useMemo, useRef, useState } from 'react';
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
import { apiRequest, apiRequestSafe, ApiRequestError, isRequestAborted } from '../../lib/api';
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
  insurance_profile?: {
    insurance_company?: string | null;
    policy_number?: string | null;
    insurance_type?: string | null;
    start_date?: string | null;
    expiry_date?: string | null;
    coverage_duration_months?: number | null;
    claims_officer_name?: string | null;
    claims_officer_phone?: string | null;
    claims_officer_email?: string | null;
    emergency_contact?: string | null;
    excess_amount?: number | null;
    covered_risks?: string[];
    excluded_risks?: string[];
  };
  roadworthy_expiry: string | null;
  default_weekly_target: number;
  default_daily_target: number;
  operating_fleet_name?: string | null;
  asset_owner_type?: string | null;
  asset_owner_name?: string | null;
  asset_owner_contact?: {
    phone?: string | null;
    email?: string | null;
    address?: string | null;
  } | null;
  ownership_notes?: string | null;
  ownership_start_date?: string | null;
  recovery_basis_type?: string | null;
  original_purchase_price?: number | null;
  original_purchase_date?: string | null;
  current_estimated_value?: number | null;
  custom_recovery_value?: number | null;
  capital_basis_for_recovery?: number | null;
  capital_recovery_tracking_enabled?: boolean;
  ownership_summary?: {
    operating_fleet_name?: string | null;
    asset_owner_type?: string | null;
    asset_owner_name?: string | null;
    ownership_start_date?: string | null;
    recovery_basis_type?: string | null;
    capital_basis_for_recovery?: number | null;
  } | null;
  ownership_history?: Array<{
    transfer_id?: string;
    previous_owner?: string | null;
    new_owner?: string | null;
    ownership_type?: string | null;
    transfer_date?: string | null;
    effective_date?: string | null;
    transfer_value?: number | null;
    previous_recovery_balance?: number | null;
    new_capital_basis?: number | null;
    transfer_reason?: string | null;
    notes?: string | null;
    approved_by?: string | null;
    created_at?: string | null;
    current_record?: boolean;
  }>;
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
  assigned_driver_details?: {
    id?: string | null;
    full_name?: string | null;
    phone?: string | null;
    email?: string | null;
    status?: string | null;
    license_number?: string | null;
  } | null;
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
      original_purchase_price?: number;
      original_purchase_date?: string | null;
      current_estimated_value?: number;
      custom_recovery_value?: number;
      recovery_basis_type?: string | null;
      capital_basis_for_recovery?: number;
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
      capital_basis_for_recovery?: number;
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
    operating_fleet_name?: string | null;
    asset_owner_type?: string | null;
    asset_owner_name?: string | null;
    ownership_summary?: Vehicle['ownership_summary'] | null;
    original_purchase_price?: number | null;
    original_purchase_date?: string | null;
    current_estimated_value?: number | null;
    custom_recovery_value?: number | null;
    capital_basis_for_recovery?: number | null;
    recovery_basis_type?: string | null;
  };
}

interface TransferOwnershipFormState {
  asset_owner_name: string;
  asset_owner_type: string;
  asset_owner_phone: string;
  asset_owner_email: string;
  asset_owner_address: string;
  transfer_date: string;
  effective_date: string;
  transfer_value: string;
  recovery_basis_type: string;
  custom_recovery_value: string;
  current_estimated_value: string;
  capital_recovery_tracking_enabled: string;
  reason: string;
  notes: string;
}

const TRANSFER_OWNER_TYPES = [
  'Axelera Owned',
  'Existing Company Asset',
  'Managed Third-Party Vehicle',
  'Investor-Funded Vehicle',
  'Leased Vehicle',
  'Partner Vehicle',
] as const;

const TRANSFER_RECOVERY_BASIS_TYPES = [
  'Original Purchase Cost',
  'Current Estimated Value',
  'Custom Recovery Value',
] as const;

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
  } | PreventiveSchedule[];
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

function getAssignedDriverSummary(vehicle: Vehicle) {
  if (!vehicle.assigned_driver_id) {
    return {
      headline: 'Unassigned',
      phone: 'Unassigned',
      email: 'Unassigned',
      status: 'Unassigned',
      licenseNumber: 'Unassigned',
    };
  }

  const details = vehicle.assigned_driver_details;
  if (!details?.full_name && !details?.phone && !details?.email && !details?.status && !details?.license_number) {
    return {
      headline: 'Assigned driver details unavailable',
      phone: 'Assigned driver details unavailable',
      email: 'Assigned driver details unavailable',
      status: 'Assigned driver details unavailable',
      licenseNumber: 'Assigned driver details unavailable',
    };
  }

  return {
    headline: details?.full_name || 'Assigned driver details unavailable',
    phone: details?.phone || 'Assigned driver details unavailable',
    email: details?.email || 'Assigned driver details unavailable',
    status: details?.status ? formatLabel(details.status) : 'Assigned driver details unavailable',
    licenseNumber: details?.license_number || 'Assigned driver details unavailable',
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

function normalizeCurrencyInput(value: string) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
}

function calculateTransferCapitalBasis(form: TransferOwnershipFormState, currentVehicle: Vehicle | null) {
  if (!currentVehicle) {
    return 0;
  }

  const trackingEnabled = form.capital_recovery_tracking_enabled !== 'false';
  if (form.asset_owner_type === 'Leased Vehicle' && !trackingEnabled) {
    return 0;
  }
  if (form.recovery_basis_type === 'Custom Recovery Value') {
    return normalizeCurrencyInput(form.custom_recovery_value);
  }
  if (form.recovery_basis_type === 'Current Estimated Value') {
    return normalizeCurrencyInput(form.current_estimated_value);
  }
  return (
    currentVehicle.economics?.investment?.total_vehicle_investment
    ?? currentVehicle.capital_basis_for_recovery
    ?? currentVehicle.purchase_cost
    ?? 0
  );
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
  const storedUser = typeof window !== 'undefined' ? localStorage.getItem('flux_user') : null;
  const currentUserRole = storedUser ? JSON.parse(storedUser).role : null;
  const [activeTab, setActiveTab] = useState<DetailTab>('overview');
  const [vehicle, setVehicle] = useState<Vehicle | null>(null);
  const [maintenance, setMaintenance] = useState<PreventiveSchedule[]>([]);
  const [compliance, setCompliance] = useState<ComplianceRecord[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isTabLoading, setIsTabLoading] = useState(false);
  const [hasLoadedEconomics, setHasLoadedEconomics] = useState(false);
  const [hasLoadedMaintenance, setHasLoadedMaintenance] = useState(false);
  const [hasLoadedCompliance, setHasLoadedCompliance] = useState(false);
  const [pageError, setPageError] = useState('');
  const [tabError, setTabError] = useState('');
  const [refreshSeed, setRefreshSeed] = useState(0);
  const [isTransferModalOpen, setIsTransferModalOpen] = useState(false);
  const [isSubmittingTransfer, setIsSubmittingTransfer] = useState(false);
  const [transferError, setTransferError] = useState('');
  const overviewRequestSequence = useRef(0);
  const hasVehicle = Boolean(vehicle?.id);
  usePageToastFeedback(pageError, tabError);

  useEffect(() => {
    setActiveTab('overview');
    setHasLoadedEconomics(false);
    setHasLoadedMaintenance(false);
    setHasLoadedCompliance(false);
    setMaintenance([]);
    setCompliance([]);
    setPageError('');
    setTabError('');
    setIsTransferModalOpen(false);
    setTransferError('');
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
          componentName: 'VehicleDetails',
          requestLabel: 'vehicle-overview',
          cancelGroup: `vehicle-details:${vehicleId}`,
          replacePending: true,
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
        if (!isRequestAborted(error)) {
          setPageError(resolveVehicleDetailsError(error));
          setVehicle(null);
        }
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
  }, [vehicleId, refreshSeed]);

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
      if (needsMaintenance && hasLoadedMaintenance) {
        return;
      }
      if (needsCompliance && hasLoadedCompliance) {
        return;
      }

      setIsTabLoading(true);
      setTabError('');
      try {
        if (needsEconomics) {
          console.info('[Flux Performance] Vehicle economics requested', { vehicleId, activeTab });
          const response = await apiRequestSafe<VehicleEconomicsResponse | null>(`/vehicles/${vehicleId}/economics`, {
            cacheTtlMs: 15000,
            timeoutMs: 10000,
            dedupeKey: `vehicle-economics:${vehicleId}`,
            componentName: 'VehicleDetails',
            requestLabel: 'vehicle-economics',
            cancelGroup: 'vehicle-economics',
            replacePending: true,
            fallbackData: null,
          });
          if (!isMounted) {
            return;
          }
          if (!response.ok) {
            if (response.status !== 'aborted') {
              setTabError('Economics data is not available right now. The rest of the vehicle page is still available.');
            }
            return;
          }
          setVehicle((currentVehicle) =>
            currentVehicle
              ? {
                  ...currentVehicle,
                  purchase_cost: response.data?.data.purchase_cost ?? currentVehicle.purchase_cost,
                  shipping_cost: response.data?.data.shipping_cost ?? currentVehicle.shipping_cost,
                  clearing_cost: response.data?.data.clearing_cost ?? currentVehicle.clearing_cost,
                  insurance_cost: response.data?.data.insurance_cost ?? currentVehicle.insurance_cost,
                  roadworthy_cost: response.data?.data.roadworthy_cost ?? currentVehicle.roadworthy_cost,
                  ama_permit_cost: response.data?.data.ama_permit_cost ?? currentVehicle.ama_permit_cost,
                  vehicle_license_cost:
                    response.data?.data.vehicle_license_cost ?? currentVehicle.vehicle_license_cost,
                  tracker_cost: response.data?.data.tracker_cost ?? currentVehicle.tracker_cost,
                  branding_cost: response.data?.data.branding_cost ?? currentVehicle.branding_cost,
                  initial_repairs_cost:
                    response.data?.data.initial_repairs_cost ?? currentVehicle.initial_repairs_cost,
                  registration_cost: response.data?.data.registration_cost ?? currentVehicle.registration_cost,
                  other_setup_cost: response.data?.data.other_setup_cost ?? currentVehicle.other_setup_cost,
                  operating_fleet_name: response.data?.data.operating_fleet_name ?? currentVehicle.operating_fleet_name,
                  asset_owner_type: response.data?.data.asset_owner_type ?? currentVehicle.asset_owner_type,
                  asset_owner_name: response.data?.data.asset_owner_name ?? currentVehicle.asset_owner_name,
                  ownership_summary: response.data?.data.ownership_summary ?? currentVehicle.ownership_summary,
                  original_purchase_price:
                    response.data?.data.original_purchase_price ?? currentVehicle.original_purchase_price,
                  original_purchase_date:
                    response.data?.data.original_purchase_date ?? currentVehicle.original_purchase_date,
                  current_estimated_value:
                    response.data?.data.current_estimated_value ?? currentVehicle.current_estimated_value,
                  custom_recovery_value:
                    response.data?.data.custom_recovery_value ?? currentVehicle.custom_recovery_value,
                  capital_basis_for_recovery:
                    response.data?.data.capital_basis_for_recovery ?? currentVehicle.capital_basis_for_recovery,
                  recovery_basis_type:
                    response.data?.data.recovery_basis_type ?? currentVehicle.recovery_basis_type,
                  vehicle_cost_items: response.data?.data.vehicle_cost_items || [],
                  economics: response.data?.data.economics || {},
                }
              : currentVehicle,
          );
          setHasLoadedEconomics(true);
        } else if (needsMaintenance) {
          const response = await apiRequestSafe<PreventiveSchedulesResponse | null>(
            `/preventive-maintenance/vehicle/${vehicleId}`,
            {
              cacheTtlMs: 15000,
              timeoutMs: 10000,
              dedupeKey: `vehicle-maintenance:${vehicleId}`,
              componentName: 'VehicleDetails',
              requestLabel: 'vehicle-maintenance-tab',
              cancelGroup: 'vehicle-maintenance',
              replacePending: true,
              fallbackData: null,
            },
          );
          if (!isMounted) {
            return;
          }
          if (!response.ok) {
            if (response.status !== 'aborted') {
              setTabError('Maintenance data is not available right now. Try again in a moment.');
            }
            setMaintenance([]);
            return;
          }
          const schedules = Array.isArray(response.data?.data)
            ? response.data?.data
            : response.data?.data?.schedules || [];
          setTabError('');
          setMaintenance(schedules);
          setHasLoadedMaintenance(true);
        } else {
          const response = await apiRequestSafe<ComplianceRecordsResponse | null>(
            `/preventive-maintenance/compliance/records?vehicle_id=${vehicleId}`,
            {
              cacheTtlMs: 15000,
              timeoutMs: 10000,
              dedupeKey: `vehicle-compliance:${vehicleId}`,
              componentName: 'VehicleDetails',
              requestLabel: 'vehicle-compliance-tab',
              cancelGroup: 'vehicle-compliance',
              replacePending: true,
              fallbackData: null,
            },
          );
          if (!isMounted) {
            return;
          }
          if (!response.ok) {
            if (response.status !== 'aborted') {
              setTabError('Compliance data is not available right now. Try again in a moment.');
            }
            setCompliance([]);
            return;
          }
          setCompliance(response.data?.data?.records || []);
          setHasLoadedCompliance(true);
        }
      } catch (error) {
        console.error('[Flux Performance] Vehicle tab load failed', { vehicleId, activeTab, error });
        if (!isMounted) {
          return;
        }
        if (!isRequestAborted(error)) {
          setTabError(
            activeTab === 'investment' || activeTab === 'recovery' || activeTab === 'economics'
              ? 'Unable to load vehicle details. Please try again.'
              : error instanceof ApiRequestError
                ? error.message
                : 'Unable to load vehicle tab data right now.',
          );
        }
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
  }, [activeTab, vehicleId, hasVehicle, hasLoadedEconomics, hasLoadedMaintenance, hasLoadedCompliance]);

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

  const transferFormDefaults: TransferOwnershipFormState = useMemo(
    () => ({
      asset_owner_name: vehicle?.asset_owner_name || vehicle?.ownership_summary?.asset_owner_name || '',
      asset_owner_type: vehicle?.asset_owner_type || vehicle?.ownership_summary?.asset_owner_type || 'Axelera Owned',
      asset_owner_phone: vehicle?.asset_owner_contact?.phone || '',
      asset_owner_email: vehicle?.asset_owner_contact?.email || '',
      asset_owner_address: vehicle?.asset_owner_contact?.address || '',
      transfer_date: new Date().toISOString().slice(0, 10),
      effective_date: new Date().toISOString().slice(0, 10),
      transfer_value: '',
      recovery_basis_type: vehicle?.recovery_basis_type || 'Original Purchase Cost',
      custom_recovery_value: vehicle?.custom_recovery_value != null ? String(vehicle.custom_recovery_value) : '',
      current_estimated_value: vehicle?.current_estimated_value != null ? String(vehicle.current_estimated_value) : '',
      capital_recovery_tracking_enabled: vehicle?.capital_recovery_tracking_enabled === false ? 'false' : 'true',
      reason: '',
      notes: '',
    }),
    [vehicle],
  );
  const [transferForm, setTransferForm] = useState<TransferOwnershipFormState>(transferFormDefaults);

  useEffect(() => {
    setTransferForm(transferFormDefaults);
  }, [transferFormDefaults]);

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
  const assignedDriverSummary = getAssignedDriverSummary(vehicle);
  const economicsTabsActive = activeTab === 'investment' || activeTab === 'recovery' || activeTab === 'economics';
  const canTransferOwnership = currentUserRole === 'owner' || currentUserRole === 'admin';
  const transferCapitalBasisPreview = calculateTransferCapitalBasis(transferForm, vehicle);
  const ownershipHistory = vehicle.ownership_history || [];

  const handleTransferFieldChange = (field: keyof TransferOwnershipFormState, value: string) => {
    setTransferForm((current) => ({ ...current, [field]: value }));
  };

  const handleSubmitTransfer = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!vehicle) {
      return;
    }
    if (!transferForm.asset_owner_name.trim()) {
      setTransferError('Please enter the new asset owner name.');
      return;
    }
    if (!transferForm.reason.trim()) {
      setTransferError('Please add a reason for this ownership transfer.');
      return;
    }
    if (transferForm.recovery_basis_type === 'Current Estimated Value' && !transferForm.current_estimated_value.trim()) {
      setTransferError('Please enter the current estimated value for this recovery basis.');
      return;
    }
    if (transferForm.recovery_basis_type === 'Custom Recovery Value' && !transferForm.custom_recovery_value.trim()) {
      setTransferError('Please enter the custom recovery value for this transfer.');
      return;
    }

    setIsSubmittingTransfer(true);
    setTransferError('');
    try {
      await apiRequest(`/vehicles/${vehicle.id}/transfer-ownership`, {
        method: 'POST',
        body: JSON.stringify({
          ...transferForm,
          transfer_value: transferForm.transfer_value ? normalizeCurrencyInput(transferForm.transfer_value) : null,
          custom_recovery_value: transferForm.custom_recovery_value
            ? normalizeCurrencyInput(transferForm.custom_recovery_value)
            : null,
          current_estimated_value: transferForm.current_estimated_value
            ? normalizeCurrencyInput(transferForm.current_estimated_value)
            : null,
          capital_basis_for_recovery: transferCapitalBasisPreview,
          ownership_notes: transferForm.notes,
        }),
      });
      setIsTransferModalOpen(false);
      setRefreshSeed((current) => current + 1);
    } catch (error) {
      setTransferError(
        error instanceof ApiRequestError
          ? error.message
          : 'We could not complete the ownership transfer right now.',
      );
    } finally {
      setIsSubmittingTransfer(false);
    }
  };

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
        <div className="flex flex-col gap-3 sm:items-end">
          {canTransferOwnership ? (
            <button
              type="button"
              onClick={() => {
                setTransferError('');
                setIsTransferModalOpen(true);
              }}
              className="inline-flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm font-medium text-blue-700 hover:bg-blue-100"
            >
              <DollarSign className="h-4 w-4" />
              Transfer Ownership
            </button>
          ) : null}
          <div className="rounded-xl border border-gray-200 bg-white px-4 py-3 text-sm text-gray-600">
            <div>Status: <span className="font-medium text-[#0F172A]">{formatLabel(vehicle.status)}</span></div>
            <div className="mt-1">Assigned Driver: <span className="font-medium text-[#0F172A]">{assignedDriverSummary.headline}</span></div>
            <div className="mt-1">Asset Owner: <span className="font-medium text-[#0F172A]">{vehicle.asset_owner_name || 'Axelera'}</span></div>
          </div>
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
              <DetailRow label="Assigned Driver" value={assignedDriverSummary.headline} />
              <DetailRow label="Driver Phone" value={assignedDriverSummary.phone} />
              <DetailRow label="Driver Email" value={assignedDriverSummary.email} />
              <DetailRow label="Driver Status" value={assignedDriverSummary.status} />
              <DetailRow label="License Number" value={assignedDriverSummary.licenseNumber} />
              <DetailRow label="Operating Fleet" value={vehicle.operating_fleet_name || vehicle.ownership_summary?.operating_fleet_name} />
              <DetailRow label="Asset Owner" value={vehicle.asset_owner_name || vehicle.ownership_summary?.asset_owner_name} />
              <DetailRow label="Ownership Type" value={vehicle.asset_owner_type || vehicle.ownership_summary?.asset_owner_type} />
              <DetailRow label="Ownership Start Date" value={formatDate(vehicle.ownership_start_date || vehicle.ownership_summary?.ownership_start_date)} />
              <DetailRow label="Recovery Basis" value={vehicle.recovery_basis_type || vehicle.ownership_summary?.recovery_basis_type} />
              <DetailRow label="Capital Basis" value={formatCurrency(vehicle.capital_basis_for_recovery || vehicle.ownership_summary?.capital_basis_for_recovery)} />
              <DetailRow
                label="Current Odometer"
                value={vehicle.current_odometer != null ? `${vehicle.current_odometer.toLocaleString()} km` : '-'}
              />
              <DetailRow label="Created" value={formatDate(vehicle.created_at)} />
            </div>
            {(vehicle.asset_owner_contact?.phone || vehicle.asset_owner_contact?.email || vehicle.asset_owner_contact?.address || vehicle.ownership_notes) && (
              <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
                <div className="text-sm font-semibold text-[#0F172A]">Owner Contact</div>
                <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <DetailRow label="Phone" value={vehicle.asset_owner_contact?.phone} />
                  <DetailRow label="Email" value={vehicle.asset_owner_contact?.email} />
                  <DetailRow label="Address" value={vehicle.asset_owner_contact?.address} />
                  <DetailRow label="Notes" value={vehicle.ownership_notes} />
                </div>
              </div>
            )}
          </div>
          <div className="rounded-xl border border-gray-200 bg-white p-5">
            <h2 className="text-lg font-semibold text-[#0F172A]">Expiry Snapshot</h2>
            <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
              <DetailRow label="Insurance Expiry" value={formatDate(vehicle.insurance_expiry)} />
              <DetailRow label="Insurance Provider" value={vehicle.insurance_profile?.insurance_company} />
              <DetailRow label="Policy Number" value={vehicle.insurance_profile?.policy_number} />
              <DetailRow label="Insurance Type" value={vehicle.insurance_profile?.insurance_type} />
              <DetailRow label="Roadworthy Expiry" value={formatDate(vehicle.roadworthy_expiry)} />
              <DetailRow label="Weekly Target" value={formatCurrency(vehicle.default_weekly_target)} />
              <DetailRow label="Daily Target" value={formatCurrency(vehicle.default_daily_target)} />
              <DetailRow label="Active Days" value={vehiclePerformance?.active_days ?? 0} />
              <DetailRow label="Idle Days" value={vehiclePerformance?.idle_days ?? 0} />
              <DetailRow label="Downtime Days" value={vehiclePerformance?.downtime_days ?? 0} />
              <DetailRow label="Health Category" value={health?.category} />
            </div>
            {(vehicle.insurance_profile?.claims_officer_name || vehicle.insurance_profile?.claims_officer_phone || vehicle.insurance_profile?.claims_officer_email) && (
              <div className="mt-4 rounded-xl border border-blue-100 bg-blue-50/60 p-4">
                <div className="text-sm font-semibold text-[#0F172A]">Claims Officer</div>
                <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <DetailRow label="Name" value={vehicle.insurance_profile?.claims_officer_name} />
                  <DetailRow label="Phone" value={vehicle.insurance_profile?.claims_officer_phone} />
                  <DetailRow label="Email" value={vehicle.insurance_profile?.claims_officer_email} />
                  <DetailRow label="Emergency Contact" value={vehicle.insurance_profile?.emergency_contact} />
                  <DetailRow label="Coverage Duration" value={vehicle.insurance_profile?.coverage_duration_months != null ? `${vehicle.insurance_profile.coverage_duration_months} month(s)` : '-'} />
                  <DetailRow label="Excess / Deductible" value={formatCurrency(vehicle.insurance_profile?.excess_amount)} />
                </div>
                <div className="mt-3 text-sm text-gray-600">
                  Covered risks: {(vehicle.insurance_profile?.covered_risks || []).join(', ') || 'Not set'}
                </div>
                <div className="mt-1 text-sm text-gray-600">
                  Excluded risks: {(vehicle.insurance_profile?.excluded_risks || []).join(', ') || 'Not set'}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {activeTab === 'assignment' && (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <div className="rounded-xl border border-gray-200 bg-white p-5">
            <h2 className="text-lg font-semibold text-[#0F172A]">Assignment</h2>
            <div className="mt-4 grid grid-cols-1 gap-3">
              <DetailRow label="Assigned Driver" value={assignedDriverSummary.headline} />
              <DetailRow label="Phone" value={assignedDriverSummary.phone} />
              <DetailRow label="Email" value={assignedDriverSummary.email} />
              <DetailRow label="Driver Status" value={assignedDriverSummary.status} />
              <DetailRow label="License Number" value={assignedDriverSummary.licenseNumber} />
              <DetailRow label="Vehicle Status" value={formatLabel(vehicle.status)} />
              <DetailRow label="Updated At" value={formatDate(vehicle.updated_at)} />
              <DetailRow label="Asset Owner" value={vehicle.asset_owner_name || vehicle.ownership_summary?.asset_owner_name} />
              <DetailRow label="Ownership Type" value={vehicle.asset_owner_type || vehicle.ownership_summary?.asset_owner_type} />
              <DetailRow label="Operating Fleet" value={vehicle.operating_fleet_name || vehicle.ownership_summary?.operating_fleet_name} />
              <DetailRow label="Created By" value="Fleet record" />
            </div>
          </div>
          <div className="rounded-xl border border-gray-200 bg-white p-5">
            <h2 className="text-lg font-semibold text-[#0F172A]">Targets & Ownership History</h2>
            <div className="mt-4 grid grid-cols-1 gap-3">
              <DetailRow label="Default Weekly Target" value={formatCurrency(vehicle.default_weekly_target)} />
              <DetailRow label="Default Daily Target" value={formatCurrency(vehicle.default_daily_target)} />
              <DetailRow label="Trips Today" value={vehiclePerformance?.trips_today ?? 0} />
              <DetailRow label="Trips This Month" value={vehiclePerformance?.trips_this_month ?? 0} />
            </div>
            <div className="mt-5">
              <div className="text-sm font-semibold text-[#0F172A]">Ownership Timeline</div>
              {ownershipHistory.length > 0 ? (
                <div className="mt-3 space-y-3">
                  {ownershipHistory.slice(0, 4).map((entry) => (
                    <div key={entry.transfer_id || `${entry.new_owner}-${entry.effective_date}`} className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3">
                      <div className="text-sm font-medium text-[#0F172A]">{entry.new_owner || 'Asset owner record'}</div>
                      <div className="mt-1 text-xs text-gray-500">
                        {formatLabel(entry.ownership_type)} • Effective {formatDate(entry.effective_date)}
                      </div>
                      <div className="mt-2 text-xs text-gray-600">
                        Capital Basis {formatCurrency(entry.new_capital_basis)} • Previous Balance {formatCurrency(entry.previous_recovery_balance)}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyPanel label="Ownership history will appear here once transfers are recorded." />
              )}
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
                <DetailRow label="Historical Purchase Price" value={formatCurrency(vehicle.economics?.investment?.original_purchase_price ?? vehicle.original_purchase_price)} />
                <DetailRow label="Historical Purchase Date" value={formatDate(vehicle.economics?.investment?.original_purchase_date ?? vehicle.original_purchase_date)} />
                <DetailRow label="Current Estimated Value" value={formatCurrency(vehicle.economics?.investment?.current_estimated_value ?? vehicle.current_estimated_value)} />
                <DetailRow label="Custom Recovery Value" value={formatCurrency(vehicle.economics?.investment?.custom_recovery_value ?? vehicle.custom_recovery_value)} />
                <DetailRow label="Recovery Basis" value={vehicle.economics?.investment?.recovery_basis_type ?? vehicle.recovery_basis_type} />
                <DetailRow label="Capital Basis For Recovery" value={formatCurrency(vehicle.economics?.investment?.capital_basis_for_recovery ?? vehicle.capital_basis_for_recovery)} />
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
              <DetailRow label="Recovery Basis" value={recovery.recovery_basis_type || vehicle.recovery_basis_type} />
              <DetailRow label="Capital Basis For Recovery" value={formatCurrency(recovery.capital_basis_for_recovery ?? vehicle.capital_basis_for_recovery)} />
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
                <DetailRow label="Operating Fleet" value={vehicle.operating_fleet_name || vehicle.ownership_summary?.operating_fleet_name} />
                <DetailRow label="Asset Owner" value={vehicle.asset_owner_name || vehicle.ownership_summary?.asset_owner_name} />
                <DetailRow label="Ownership Type" value={vehicle.asset_owner_type || vehicle.ownership_summary?.asset_owner_type} />
                <DetailRow label="Capital Basis For ROI" value={formatCurrency(profitability?.capital_basis_for_recovery ?? vehicle.capital_basis_for_recovery)} />
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

      {isTransferModalOpen && canTransferOwnership && (
        <div className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-slate-900/50 p-3 sm:p-4">
          <div className="flex max-h-[85vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-2xl">
            <div className="sticky top-0 z-10 flex items-start justify-between gap-4 border-b border-gray-200 bg-white px-4 py-4 sm:px-6">
              <div>
                <h2 className="text-xl font-semibold text-[#0F172A]">Transfer Ownership</h2>
                <p className="mt-1 text-sm text-gray-500">
                  Preserve historical reporting while updating the current legal asset owner.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setIsTransferModalOpen(false)}
                className="rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-600 hover:bg-gray-50"
              >
                Close
              </button>
            </div>
            <form onSubmit={handleSubmitTransfer} className="flex min-h-0 flex-1 flex-col">
              <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-6">
                {transferError && (
                  <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                    {transferError}
                  </div>
                )}
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                  <div>
                    <label className="mb-1.5 block text-sm font-medium text-gray-700">New Asset Owner</label>
                    <input
                      value={transferForm.asset_owner_name}
                      onChange={(event) => handleTransferFieldChange('asset_owner_name', event.target.value)}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm"
                    />
                  </div>
                  <div>
                    <label className="mb-1.5 block text-sm font-medium text-gray-700">Ownership Type</label>
                    <select
                      value={transferForm.asset_owner_type}
                      onChange={(event) => handleTransferFieldChange('asset_owner_type', event.target.value)}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm"
                    >
                      {TRANSFER_OWNER_TYPES.map((option) => (
                        <option key={option} value={option}>{option}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="mb-1.5 block text-sm font-medium text-gray-700">Transfer Date</label>
                    <input
                      type="date"
                      value={transferForm.transfer_date}
                      onChange={(event) => handleTransferFieldChange('transfer_date', event.target.value)}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm"
                    />
                  </div>
                  <div>
                    <label className="mb-1.5 block text-sm font-medium text-gray-700">Effective Date</label>
                    <input
                      type="date"
                      value={transferForm.effective_date}
                      onChange={(event) => handleTransferFieldChange('effective_date', event.target.value)}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm"
                    />
                  </div>
                  <div>
                    <label className="mb-1.5 block text-sm font-medium text-gray-700">Transfer Value</label>
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      value={transferForm.transfer_value}
                      onChange={(event) => handleTransferFieldChange('transfer_value', event.target.value)}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm"
                    />
                  </div>
                  <div>
                    <label className="mb-1.5 block text-sm font-medium text-gray-700">Recovery Basis</label>
                    <select
                      value={transferForm.recovery_basis_type}
                      onChange={(event) => handleTransferFieldChange('recovery_basis_type', event.target.value)}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm"
                    >
                      {TRANSFER_RECOVERY_BASIS_TYPES.map((option) => (
                        <option key={option} value={option}>{option}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="mb-1.5 block text-sm font-medium text-gray-700">Current Estimated Value</label>
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      value={transferForm.current_estimated_value}
                      onChange={(event) => handleTransferFieldChange('current_estimated_value', event.target.value)}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm"
                    />
                  </div>
                  <div>
                    <label className="mb-1.5 block text-sm font-medium text-gray-700">Custom Recovery Value</label>
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      value={transferForm.custom_recovery_value}
                      onChange={(event) => handleTransferFieldChange('custom_recovery_value', event.target.value)}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm"
                    />
                  </div>
                  <div>
                    <label className="mb-1.5 block text-sm font-medium text-gray-700">Owner Phone</label>
                    <input
                      value={transferForm.asset_owner_phone}
                      onChange={(event) => handleTransferFieldChange('asset_owner_phone', event.target.value)}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm"
                    />
                  </div>
                  <div>
                    <label className="mb-1.5 block text-sm font-medium text-gray-700">Owner Email</label>
                    <input
                      type="email"
                      value={transferForm.asset_owner_email}
                      onChange={(event) => handleTransferFieldChange('asset_owner_email', event.target.value)}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm"
                    />
                  </div>
                  <div className="md:col-span-2">
                    <label className="mb-1.5 block text-sm font-medium text-gray-700">Owner Address</label>
                    <input
                      value={transferForm.asset_owner_address}
                      onChange={(event) => handleTransferFieldChange('asset_owner_address', event.target.value)}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm"
                    />
                  </div>
                  <div>
                    <label className="mb-1.5 block text-sm font-medium text-gray-700">Capital Recovery Tracking</label>
                    <select
                      value={transferForm.capital_recovery_tracking_enabled}
                      onChange={(event) => handleTransferFieldChange('capital_recovery_tracking_enabled', event.target.value)}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm"
                    >
                      <option value="true">Enabled</option>
                      <option value="false">Disabled</option>
                    </select>
                  </div>
                  <div className="rounded-lg border border-blue-100 bg-blue-50 px-4 py-3">
                    <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Capital Basis Preview</div>
                    <div className="mt-1 text-lg font-semibold text-[#0F172A]">{formatCurrency(transferCapitalBasisPreview)}</div>
                    <div className="mt-1 text-xs text-gray-600">This will be used for recovery and ROI going forward.</div>
                  </div>
                  <div className="md:col-span-2">
                    <label className="mb-1.5 block text-sm font-medium text-gray-700">Reason for Transfer</label>
                    <input
                      value={transferForm.reason}
                      onChange={(event) => handleTransferFieldChange('reason', event.target.value)}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm"
                    />
                  </div>
                  <div className="md:col-span-2">
                    <label className="mb-1.5 block text-sm font-medium text-gray-700">Notes</label>
                    <textarea
                      rows={3}
                      value={transferForm.notes}
                      onChange={(event) => handleTransferFieldChange('notes', event.target.value)}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm"
                    />
                  </div>
                </div>
              </div>
              <div className="sticky bottom-0 z-10 flex flex-col-reverse gap-3 border-t border-gray-200 bg-white px-4 py-4 sm:flex-row sm:justify-end sm:px-6">
                <button
                  type="button"
                  onClick={() => setIsTransferModalOpen(false)}
                  className="rounded-lg border border-gray-300 px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmittingTransfer}
                  className="rounded-lg bg-[#2563EB] px-4 py-2.5 text-sm font-medium text-white hover:bg-[#1d4ed8] disabled:cursor-not-allowed disabled:opacity-70"
                >
                  {isSubmittingTransfer ? 'Transferring...' : 'Confirm Transfer'}
                </button>
              </div>
            </form>
          </div>
        </div>
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
