import { useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  Ban,
  Calendar,
  CheckCircle,
  DollarSign,
  Eye,
  Filter,
  Loader2,
  MoreVertical,
  Plus,
  Search,
  Truck,
  Wrench,
  X,
} from 'lucide-react';
import { apiRequest, ApiRequestError } from '../../lib/api';
import { fetchSystemSettings, type SystemSettingsRecord } from '../../lib/system-settings-api';

interface VehiclesProps {
  onOpenVehicleDetails: (vehicleId: string) => void;
}

type VehicleStatus =
  | 'available'
  | 'assigned'
  | 'maintenance'
  | 'accident'
  | 'out_of_service'
  | 'suspended'
  | 'retired';

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
    insurance_type?: 'Third Party' | 'Comprehensive' | string | null;
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
  purchase_cost: number | null;
  shipping_cost?: number | null;
  clearing_cost?: number | null;
  insurance_cost: number | null;
  roadworthy_cost: number | null;
  ama_permit_cost?: number | null;
  vehicle_license_cost?: number | null;
  tracker_cost?: number | null;
  branding_cost?: number | null;
  initial_repairs_cost?: number | null;
  registration_cost?: number | null;
  other_setup_cost?: number | null;
  vehicle_cost_items?: Array<{ id: string; item_name: string; amount: number; date: string; notes?: string | null }>;
  economics?: {
    investment?: { total_vehicle_investment?: number; custom_cost_total?: number };
    recovery?: { amount_recovered?: number; remaining_balance?: number; recovery_percentage?: number; status?: string };
    operating_costs?: { monthly?: number; quarterly?: number; annual?: number; lifetime?: number; fuel_cost?: number; maintenance_cost?: number; repair_cost?: number; expense_cost?: number; compliance_renewal_cost?: number };
    profitability?: { gross_revenue?: number; net_profit?: number; profit_margin?: number; roi?: number };
    performance?: { trips_today?: number; trips_this_month?: number; utilization_percentage?: number; active_days?: number; idle_days?: number; downtime_days?: number };
    health?: { score?: number; category?: string };
  };
  status: VehicleStatus;
  assigned_driver_id: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
}

interface VehiclesResponse {
  success: boolean;
  message: string;
  data: {
    vehicles: Vehicle[];
  };
}

interface CreateVehicleResponse {
  success: boolean;
  message: string;
  data: {
    vehicle: Vehicle;
  };
}

interface VehicleFormState {
  registration_number: string;
  vehicle_type: string;
  make: string;
  model: string;
  year: string;
  color: string;
  transmission: string;
  fuel_type: string;
  chassis_number: string;
  engine_number: string;
  insurance_expiry: string;
  insurance_company: string;
  policy_number: string;
  insurance_type: 'Third Party' | 'Comprehensive';
  insurance_start_date: string;
  insurance_expiry_date: string;
  coverage_duration_months: string;
  claims_officer_name: string;
  claims_officer_phone: string;
  claims_officer_email: string;
  emergency_contact: string;
  excess_amount: string;
  covered_risks: string;
  excluded_risks: string;
  roadworthy_expiry: string;
  default_weekly_target: string;
  default_daily_target: string;
  purchase_cost: string;
  shipping_cost: string;
  clearing_cost: string;
  insurance_cost: string;
  roadworthy_cost: string;
  ama_permit_cost: string;
  vehicle_license_cost: string;
  tracker_cost: string;
  branding_cost: string;
  initial_repairs_cost: string;
  registration_cost: string;
  other_setup_cost: string;
}

const initialVehicleForm: VehicleFormState = {
  registration_number: '',
  vehicle_type: 'saloon',
  make: '',
  model: '',
  year: '',
  color: '',
  transmission: 'automatic',
  fuel_type: 'petrol',
  chassis_number: '',
  engine_number: '',
  insurance_expiry: '',
  insurance_company: '',
  policy_number: '',
  insurance_type: 'Third Party',
  insurance_start_date: '',
  insurance_expiry_date: '',
  coverage_duration_months: '',
  claims_officer_name: '',
  claims_officer_phone: '',
  claims_officer_email: '',
  emergency_contact: '',
  excess_amount: '',
  covered_risks: '',
  excluded_risks: '',
  roadworthy_expiry: '',
  default_weekly_target: '',
  default_daily_target: '',
  purchase_cost: '',
  shipping_cost: '',
  clearing_cost: '',
  insurance_cost: '',
  roadworthy_cost: '',
  ama_permit_cost: '',
  vehicle_license_cost: '',
  tracker_cost: '',
  branding_cost: '',
  initial_repairs_cost: '',
  registration_cost: '',
  other_setup_cost: '',
};

interface EconomicsDashboardResponse {
  success: boolean;
  data: {
    dashboard: {
      total_fleet_investment?: number;
      total_recovered?: number;
      remaining_recovery_balance?: number;
      net_fleet_profit?: number;
      vehicles_recovering?: number;
      vehicles_fully_recovered?: number;
      vehicles_profit_generating?: number;
    };
  };
}

interface VehicleCostItemFormState {
  item_name: string;
  amount: string;
  date: string;
  notes: string;
}

const statusConfig: Record<
  VehicleStatus,
  {
    label: string;
    color: string;
    icon: typeof CheckCircle;
  }
> = {
  available: { label: 'Available', color: 'bg-green-100 text-green-800', icon: CheckCircle },
  assigned: { label: 'Assigned', color: 'bg-blue-100 text-blue-800', icon: Truck },
  maintenance: { label: 'Maintenance', color: 'bg-yellow-100 text-yellow-800', icon: Wrench },
  accident: { label: 'Accident', color: 'bg-red-100 text-red-800', icon: AlertTriangle },
  out_of_service: { label: 'Out of Service', color: 'bg-red-100 text-red-800', icon: AlertTriangle },
  suspended: { label: 'Suspended', color: 'bg-gray-100 text-gray-800', icon: Ban },
  retired: { label: 'Retired', color: 'bg-slate-100 text-slate-700', icon: Ban },
};

function formatVehicleType(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function formatCurrency(value: number | null) {
  if (value === null || Number.isNaN(value)) {
    return '-';
  }

  return `GH₵ ${value.toLocaleString()}`;
}

function formatDriverLabel(assignedDriverId: string | null) {
  if (!assignedDriverId) {
    return null;
  }

  return `Driver ID: ${assignedDriverId.slice(0, 8)}...`;
}

function getDaysUntilExpiry(expiryDate: string | null) {
  if (!expiryDate) {
    return null;
  }

  const today = new Date();
  const expiry = new Date(expiryDate);
  const diffTime = expiry.getTime() - today.getTime();
  return Math.ceil(diffTime / (1000 * 60 * 60 * 24));
}

function getExpiryStatus(days: number | null) {
  if (days === null) {
    return { label: 'N/A', color: 'text-gray-400' };
  }
  if (days < 0) {
    return { label: 'Expired', color: 'text-red-600 font-semibold' };
  }
  if (days <= 7) {
    return { label: `${days}d`, color: 'text-red-600 font-semibold' };
  }
  if (days <= 30) {
    return { label: `${days}d`, color: 'text-amber-600 font-medium' };
  }
  return { label: `${days}d`, color: 'text-gray-600' };
}

function buildVehiclePayload(form: VehicleFormState) {
  const parseOptionalNumber = (value: string) =>
    value.trim() === '' ? undefined : Number(value);

  const parseOptionalString = (value: string) =>
    value.trim() === '' ? undefined : value.trim();

  const parseOptionalInteger = (value: string) =>
    value.trim() === '' ? undefined : Number.parseInt(value, 10);

  const parseList = (value: string) =>
    value
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean);

  return {
    registration_number: form.registration_number.trim(),
    vehicle_type: form.vehicle_type,
    make: form.make.trim(),
    model: form.model.trim(),
    year: Number(form.year),
    color: parseOptionalString(form.color),
    transmission: form.transmission,
    fuel_type: form.fuel_type,
    chassis_number: parseOptionalString(form.chassis_number),
    engine_number: parseOptionalString(form.engine_number),
    insurance_expiry: parseOptionalString(form.insurance_expiry_date || form.insurance_expiry),
    insurance_company: parseOptionalString(form.insurance_company),
    policy_number: parseOptionalString(form.policy_number),
    insurance_type: parseOptionalString(form.insurance_type),
    start_date: parseOptionalString(form.insurance_start_date),
    expiry_date: parseOptionalString(form.insurance_expiry_date || form.insurance_expiry),
    coverage_duration_months: parseOptionalInteger(form.coverage_duration_months),
    claims_officer_name: parseOptionalString(form.claims_officer_name),
    claims_officer_phone: parseOptionalString(form.claims_officer_phone),
    claims_officer_email: parseOptionalString(form.claims_officer_email),
    emergency_contact: parseOptionalString(form.emergency_contact),
    excess_amount: parseOptionalNumber(form.excess_amount),
    covered_risks: parseList(form.covered_risks),
    excluded_risks: parseList(form.excluded_risks),
    roadworthy_expiry: parseOptionalString(form.roadworthy_expiry),
    default_weekly_target: Number(form.default_weekly_target),
    default_daily_target: Number(form.default_daily_target),
    purchase_cost: parseOptionalNumber(form.purchase_cost),
    shipping_cost: parseOptionalNumber(form.shipping_cost),
    clearing_cost: parseOptionalNumber(form.clearing_cost),
    insurance_cost: parseOptionalNumber(form.insurance_cost),
    roadworthy_cost: parseOptionalNumber(form.roadworthy_cost),
    ama_permit_cost: parseOptionalNumber(form.ama_permit_cost),
    vehicle_license_cost: parseOptionalNumber(form.vehicle_license_cost),
    tracker_cost: parseOptionalNumber(form.tracker_cost),
    branding_cost: parseOptionalNumber(form.branding_cost),
    initial_repairs_cost: parseOptionalNumber(form.initial_repairs_cost),
    registration_cost: parseOptionalNumber(form.registration_cost),
    other_setup_cost: parseOptionalNumber(form.other_setup_cost),
  };
}

const VEHICLES_PAGE_SIZE = 10;

export default function Vehicles({ onOpenVehicleDetails }: VehiclesProps) {
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedStatus, setSelectedStatus] = useState('all');
  const [currentPage, setCurrentPage] = useState(1);
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [pageError, setPageError] = useState('');
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingVehicle, setEditingVehicle] = useState<Vehicle | null>(null);
  const [formState, setFormState] = useState<VehicleFormState>(initialVehicleForm);
  const [formError, setFormError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [scheduleActionVehicleId, setScheduleActionVehicleId] = useState<string | null>(null);
  const [scheduleActionMessage, setScheduleActionMessage] = useState('');
  const [economicsDashboard, setEconomicsDashboard] = useState<EconomicsDashboardResponse['data']['dashboard'] | null>(null);
  const [systemSettings, setSystemSettings] = useState<SystemSettingsRecord | null>(null);
  const [costItemVehicle, setCostItemVehicle] = useState<Vehicle | null>(null);
  const [costItemForm, setCostItemForm] = useState<VehicleCostItemFormState>({
    item_name: '',
    amount: '',
    date: new Date().toISOString().slice(0, 10),
    notes: '',
  });

  const storedUser = localStorage.getItem('flux_user');
  const currentRole = storedUser ? JSON.parse(storedUser).role : null;

  const loadVehicleSupplementalData = async () => {
    try {
      const [dashboardResponse, settingsResponse] = await Promise.all([
        apiRequest<EconomicsDashboardResponse>('/vehicles/economics/dashboard', {
          cacheTtlMs: 15000,
        }),
        fetchSystemSettings(),
      ]);
      setEconomicsDashboard(dashboardResponse.data.dashboard);
      setSystemSettings(settingsResponse);
    } catch {
      setEconomicsDashboard(null);
    }
  };

  const loadVehicles = async () => {
    const pageLoadStartedAt = performance.now();
    setIsLoading(true);
    setPageError('');

    try {
      const response = await apiRequest<VehiclesResponse>('/vehicles', {
        cacheTtlMs: 10000,
      });
      setVehicles(Array.isArray(response.data?.vehicles) ? response.data.vehicles : []);
      console.info('[Flux Performance] Vehicles list loaded', {
        durationMs: Number((performance.now() - pageLoadStartedAt).toFixed(2)),
        records: Array.isArray(response.data?.vehicles) ? response.data.vehicles.length : 0,
      });
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setPageError(error.message);
      } else {
        setPageError('Unable to load vehicles right now.');
      }
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void loadVehicles();
  }, []);

  useEffect(() => {
    void loadVehicleSupplementalData();
  }, []);

  const handleGenerateDefaultSchedule = async (vehicleId: string) => {
    setScheduleActionVehicleId(vehicleId);
    setScheduleActionMessage('');

    try {
      await apiRequest(`/vehicles/${vehicleId}/generate-default-maintenance`, {
        method: 'POST',
      });
      setScheduleActionMessage('Default maintenance schedules generated successfully.');
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setScheduleActionMessage(error.message);
      } else {
        setScheduleActionMessage('Unable to generate default maintenance schedules right now.');
      }
    } finally {
      setScheduleActionVehicleId(null);
    }
  };

  const stats = useMemo(
    () => [
      { label: 'Total Vehicles', value: vehicles.length, color: 'bg-blue-500', icon: Truck },
      {
        label: 'Available',
        value: vehicles.filter((vehicle) => vehicle.status === 'available').length,
        color: 'bg-green-500',
        icon: CheckCircle,
      },
      {
        label: 'Assigned',
        value: vehicles.filter((vehicle) => vehicle.status === 'assigned').length,
        color: 'bg-blue-500',
        icon: Truck,
      },
      {
        label: 'In Maintenance',
        value: vehicles.filter((vehicle) => vehicle.status === 'maintenance').length,
        color: 'bg-yellow-500',
        icon: Wrench,
      },
      {
        label: 'Suspended/Accident',
        value: vehicles.filter((vehicle) =>
          ['suspended', 'accident', 'out_of_service'].includes(vehicle.status),
        ).length,
        color: 'bg-red-500',
        icon: AlertTriangle,
      },
      ...(economicsDashboard
        ? [
            {
              label: 'Fleet Investment',
              value: formatCurrency(economicsDashboard.total_fleet_investment ?? 0),
              color: 'bg-slate-700',
              icon: DollarSign,
            },
          ]
        : []),
    ],
    [economicsDashboard, vehicles],
  );

  const filteredVehicles = useMemo(
    () =>
      vehicles.filter((vehicle) => {
        const searchValue = searchQuery.trim().toLowerCase();
        const statusValue = selectedStatus.trim().toLowerCase();
        const assignedDriverLabel = formatDriverLabel(vehicle.assigned_driver_id)?.toLowerCase() || '';
        const searchTargets = [
          vehicle.registration_number,
          vehicle.vehicle_type,
          vehicle.make,
          vehicle.model,
          `${vehicle.make} ${vehicle.model}`,
          assignedDriverLabel,
        ].map((value) => (value || '').toLowerCase());
        const matchesSearch =
          searchValue === '' || searchTargets.some((value) => value.includes(searchValue));
        const matchesStatus =
          statusValue === '' ||
          statusValue === 'all' ||
          (vehicle.status || '').toLowerCase() === statusValue;
        return matchesSearch && matchesStatus;
      }),
    [searchQuery, selectedStatus, vehicles],
  );

  const totalPages = Math.max(1, Math.ceil(filteredVehicles.length / VEHICLES_PAGE_SIZE));
  const paginatedVehicles = useMemo(() => {
    const startIndex = (currentPage - 1) * VEHICLES_PAGE_SIZE;
    return filteredVehicles.slice(startIndex, startIndex + VEHICLES_PAGE_SIZE);
  }, [currentPage, filteredVehicles]);

  useEffect(() => {
    setCurrentPage(1);
  }, [searchQuery, selectedStatus]);

  useEffect(() => {
    setCurrentPage((page) => Math.min(page, totalPages));
  }, [totalPages]);

  const canManageCostItems =
    currentRole === 'owner' || Boolean(systemSettings?.role_permissions?.admin?.manage_vehicle_cost_items);
  const canViewInvestmentFields =
    currentRole === 'owner' || Boolean(systemSettings?.role_permissions?.admin?.view_vehicle_investment);
  const canViewRecoveryFields =
    currentRole === 'owner' || Boolean(systemSettings?.role_permissions?.admin?.view_vehicle_recovery);
  const canViewProfitabilityFields =
    currentRole === 'owner' || Boolean(systemSettings?.role_permissions?.admin?.view_profitability);

  const handleFieldChange = (
    field: keyof VehicleFormState,
    value: string,
  ) => {
    setFormState((current) => ({
      ...current,
      [field]: value,
    }));
  };

  const closeModal = () => {
    setIsModalOpen(false);
    setEditingVehicle(null);
    setFormError('');
    setFormState(initialVehicleForm);
  };

  const openCreateModal = () => {
    setEditingVehicle(null);
    setFormError('');
    setFormState(initialVehicleForm);
    setIsModalOpen(true);
  };

  const openEditModal = (vehicle: Vehicle) => {
    setEditingVehicle(vehicle);
    setFormError('');
    setFormState({
      registration_number: vehicle.registration_number || '',
      vehicle_type: vehicle.vehicle_type || 'saloon',
      make: vehicle.make || '',
      model: vehicle.model || '',
      year: vehicle.year ? String(vehicle.year) : '',
      color: vehicle.color || '',
      transmission: vehicle.transmission || 'automatic',
      fuel_type: vehicle.fuel_type || 'petrol',
      chassis_number: vehicle.chassis_number || '',
      engine_number: vehicle.engine_number || '',
      insurance_expiry: vehicle.insurance_expiry || '',
      insurance_company: vehicle.insurance_profile?.insurance_company || '',
      policy_number: vehicle.insurance_profile?.policy_number || '',
      insurance_type: (vehicle.insurance_profile?.insurance_type as 'Third Party' | 'Comprehensive') || 'Third Party',
      insurance_start_date: vehicle.insurance_profile?.start_date || '',
      insurance_expiry_date: vehicle.insurance_profile?.expiry_date || vehicle.insurance_expiry || '',
      coverage_duration_months: vehicle.insurance_profile?.coverage_duration_months != null ? String(vehicle.insurance_profile.coverage_duration_months) : '',
      claims_officer_name: vehicle.insurance_profile?.claims_officer_name || '',
      claims_officer_phone: vehicle.insurance_profile?.claims_officer_phone || '',
      claims_officer_email: vehicle.insurance_profile?.claims_officer_email || '',
      emergency_contact: vehicle.insurance_profile?.emergency_contact || '',
      excess_amount: vehicle.insurance_profile?.excess_amount != null ? String(vehicle.insurance_profile.excess_amount) : '',
      covered_risks: (vehicle.insurance_profile?.covered_risks || []).join(', '),
      excluded_risks: (vehicle.insurance_profile?.excluded_risks || []).join(', '),
      roadworthy_expiry: vehicle.roadworthy_expiry || '',
      default_weekly_target: String(vehicle.default_weekly_target ?? ''),
      default_daily_target: String(vehicle.default_daily_target ?? ''),
      purchase_cost: vehicle.purchase_cost != null ? String(vehicle.purchase_cost) : '',
      shipping_cost: vehicle.shipping_cost != null ? String(vehicle.shipping_cost) : '',
      clearing_cost: vehicle.clearing_cost != null ? String(vehicle.clearing_cost) : '',
      insurance_cost: vehicle.insurance_cost != null ? String(vehicle.insurance_cost) : '',
      roadworthy_cost: vehicle.roadworthy_cost != null ? String(vehicle.roadworthy_cost) : '',
      ama_permit_cost: vehicle.ama_permit_cost != null ? String(vehicle.ama_permit_cost) : '',
      vehicle_license_cost: vehicle.vehicle_license_cost != null ? String(vehicle.vehicle_license_cost) : '',
      tracker_cost: vehicle.tracker_cost != null ? String(vehicle.tracker_cost) : '',
      branding_cost: vehicle.branding_cost != null ? String(vehicle.branding_cost) : '',
      initial_repairs_cost: vehicle.initial_repairs_cost != null ? String(vehicle.initial_repairs_cost) : '',
      registration_cost: vehicle.registration_cost != null ? String(vehicle.registration_cost) : '',
      other_setup_cost: vehicle.other_setup_cost != null ? String(vehicle.other_setup_cost) : '',
    });
    setIsModalOpen(true);
  };

  const closeCostItemModal = () => {
    setCostItemVehicle(null);
    setFormError('');
    setCostItemForm({
      item_name: '',
      amount: '',
      date: new Date().toISOString().slice(0, 10),
      notes: '',
    });
  };

  const handleSaveVehicle = async (event: React.FormEvent) => {
    event.preventDefault();
    setFormError('');
    setIsSubmitting(true);

    try {
      await apiRequest<CreateVehicleResponse>(editingVehicle ? `/vehicles/${editingVehicle.id}` : '/vehicles', {
        method: editingVehicle ? 'PATCH' : 'POST',
        body: JSON.stringify(buildVehiclePayload(formState)),
      });

      closeModal();
      await loadVehicles();
      await loadVehicleSupplementalData();
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setFormError(error.message);
      } else {
        setFormError(editingVehicle ? 'Unable to update vehicle right now.' : 'Unable to create vehicle right now.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleCreateCostItem = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!costItemVehicle) return;
    setFormError('');
    setIsSubmitting(true);
    try {
      await apiRequest(`/vehicles/${costItemVehicle.id}/cost-items`, {
        method: 'POST',
        body: JSON.stringify({
          item_name: costItemForm.item_name.trim(),
          amount: Number(costItemForm.amount),
          date: costItemForm.date,
          notes: costItemForm.notes.trim() || undefined,
        }),
      });
      closeCostItemModal();
      await loadVehicles();
      await loadVehicleSupplementalData();
    } catch (error) {
      setFormError(error instanceof ApiRequestError ? error.message : 'Unable to add vehicle cost item right now.');
    } finally {
      setIsSubmitting(false);
    }
  };

  if (currentRole === 'driver') {
    return (
      <div className="p-6">
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Drivers do not have access to the Vehicles page.
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Vehicle Management</h1>
          <p className="text-gray-500 mt-1">Manage your fleet vehicles and assignments</p>
        </div>
        <button
          onClick={openCreateModal}
          className="px-4 py-2.5 bg-[#2563EB] text-white rounded-lg hover:bg-[#1d4ed8] flex items-center gap-2 font-medium"
        >
          <Plus className="w-5 h-5" />
          Add Vehicle
        </button>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3 xl:grid-cols-6">
        {stats.map((stat, index) => {
          const Icon = stat.icon;
          return (
            <div key={index} className="bg-white rounded-lg border border-gray-200 p-5">
              <div className="flex items-start justify-between mb-3">
                <div className={`w-10 h-10 ${stat.color} rounded-lg flex items-center justify-center`}>
                  <Icon className="w-5 h-5 text-white" />
                </div>
              </div>
              <div className="text-2xl font-semibold text-gray-900 mb-1">{stat.value}</div>
              <div className="text-sm text-gray-600">{stat.label}</div>
            </div>
          );
        })}
      </div>

      <div className="bg-white rounded-lg border border-gray-200 p-4">
        <div className="flex flex-col lg:flex-row gap-4">
          <div className="flex-1">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" />
              <input
                type="text"
                placeholder="Search by vehicle number, type, or driver..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-10 pr-4 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent"
              />
            </div>
          </div>

          <div className="flex gap-2">
            <select
              value={selectedStatus}
              onChange={(e) => setSelectedStatus(e.target.value)}
              className="px-4 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent bg-white"
            >
              <option value="all">All Status</option>
              <option value="available">Available</option>
              <option value="assigned">Assigned</option>
              <option value="maintenance">Maintenance</option>
              <option value="accident">Accident</option>
              <option value="suspended">Suspended</option>
              <option value="retired">Retired</option>
            </select>

            <button className="px-4 py-2.5 border border-gray-300 rounded-lg hover:bg-gray-50 flex items-center gap-2">
              <Filter className="w-4 h-4" />
              More Filters
            </button>
          </div>
        </div>
      </div>

      {pageError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {pageError}
        </div>
      )}

      {scheduleActionMessage && (
        <div className="rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-700">
          {scheduleActionMessage}
        </div>
      )}

      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        {isLoading ? (
          <div className="px-6 py-16 flex items-center justify-center gap-3 text-gray-500">
            <Loader2 className="w-5 h-5 animate-spin" />
            <span>Loading vehicles...</span>
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-gray-50 border-b border-gray-200">
                  <tr>
                    <th className="px-6 py-4 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">
                      Vehicle Number
                    </th>
                    <th className="px-6 py-4 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">
                      Type
                    </th>
                    <th className="px-6 py-4 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">
                      Assigned Driver
                    </th>
                    <th className="px-6 py-4 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">
                      Weekly Target
                    </th>
                    <th className="px-6 py-4 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">
                      Economics
                    </th>
                    <th className="px-6 py-4 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">
                      Fuel Type
                    </th>
                    <th className="px-6 py-4 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">
                      Insurance Expiry
                    </th>
                    <th className="px-6 py-4 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">
                      Roadworthy Expiry
                    </th>
                    <th className="px-6 py-4 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">
                      Status
                    </th>
                    <th className="px-6 py-4 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {paginatedVehicles.map((vehicle) => {
                    const StatusIcon = statusConfig[vehicle.status].icon;
                    const insuranceDays = getDaysUntilExpiry(vehicle.insurance_expiry);
                    const roadworthyDays = getDaysUntilExpiry(vehicle.roadworthy_expiry);
                    const insuranceStatus = getExpiryStatus(insuranceDays);
                    const roadworthyStatus = getExpiryStatus(roadworthyDays);
                    const assignedDriverLabel = formatDriverLabel(vehicle.assigned_driver_id);

                    return (
                      <tr
                        key={vehicle.id}
                        className="cursor-pointer hover:bg-gray-50 transition-colors"
                        onClick={() => {
                          console.info('[Flux Performance] Vehicle row clicked', {
                            vehicle,
                          });
                          onOpenVehicleDetails(vehicle.id);
                        }}
                      >
                        <td className="px-6 py-4">
                          <div className="flex items-center gap-3">
                            <div className="w-10 h-10 bg-blue-100 rounded-lg flex items-center justify-center">
                              <Truck className="w-5 h-5 text-blue-600" />
                            </div>
                            <div>
                              <div className="font-semibold text-gray-900">
                                {vehicle.registration_number}
                              </div>
                              <div className="text-sm text-gray-500">
                                {vehicle.make} {vehicle.model} • {vehicle.year}
                              </div>
                            </div>
                          </div>
                        </td>
                        <td className="px-6 py-4">
                          <span className="text-sm text-gray-900">
                            {formatVehicleType(vehicle.vehicle_type)}
                          </span>
                        </td>
                        <td className="px-6 py-4">
                          {assignedDriverLabel ? (
                            <div>
                              <div className="text-sm font-medium text-gray-900">{assignedDriverLabel}</div>
                              <div className="text-xs text-gray-500">Assigned</div>
                            </div>
                          ) : (
                            <span className="text-sm text-gray-400 italic">Unassigned</span>
                          )}
                        </td>
                        <td className="px-6 py-4">
                          <div className="text-sm font-medium text-gray-900">
                            {formatCurrency(vehicle.default_weekly_target)}
                          </div>
                          <div className="text-xs text-gray-500">per week</div>
                        </td>
                        <td className="px-6 py-4">
                          <div className="text-sm font-medium text-gray-900">
                            {canViewInvestmentFields && vehicle.economics?.investment?.total_vehicle_investment != null
                              ? formatCurrency(vehicle.economics.investment.total_vehicle_investment)
                              : 'Restricted'}
                          </div>
                          <div className="text-xs text-gray-500">
                            Recovery {canViewRecoveryFields && vehicle.economics?.recovery?.recovery_percentage != null ? `${vehicle.economics.recovery.recovery_percentage}%` : 'Restricted'}
                          </div>
                          <div className="text-xs text-gray-500">
                            Costs {vehicle.economics?.operating_costs?.company_vehicle_costs != null ? formatCurrency(vehicle.economics.operating_costs.company_vehicle_costs) : '-'}
                          </div>
                          <div className="text-xs text-gray-500">
                            Profit {canViewProfitabilityFields && vehicle.economics?.profitability?.net_profit != null ? formatCurrency(vehicle.economics.profitability.net_profit) : 'Restricted'}
                          </div>
                          <div className="text-xs text-gray-500">
                            Health {vehicle.economics?.health?.score != null ? `${vehicle.economics.health.score}/100` : '-'}
                          </div>
                        </td>
                        <td className="px-6 py-4">
                          <span
                            className={`px-2.5 py-1 rounded-full text-xs font-medium ${
                              vehicle.fuel_type === 'petrol'
                                ? 'bg-purple-100 text-purple-800'
                                : vehicle.fuel_type === 'diesel'
                                  ? 'bg-orange-100 text-orange-800'
                                  : 'bg-emerald-100 text-emerald-800'
                            }`}
                          >
                            {formatVehicleType(vehicle.fuel_type)}
                          </span>
                        </td>
                        <td className="px-6 py-4">
                          <div className="flex items-center gap-2">
                            <Calendar
                              className={`w-4 h-4 ${insuranceDays !== null && insuranceDays <= 30 ? 'text-red-500' : 'text-gray-400'}`}
                            />
                            <div>
                              <div className="text-sm text-gray-900">
                                {vehicle.insurance_expiry || 'Not set'}
                              </div>
                              <div className={`text-xs ${insuranceStatus.color}`}>
                                {insuranceStatus.label}
                              </div>
                            </div>
                          </div>
                        </td>
                        <td className="px-6 py-4">
                          <div className="flex items-center gap-2">
                            <Calendar
                              className={`w-4 h-4 ${roadworthyDays !== null && roadworthyDays <= 30 ? 'text-red-500' : 'text-gray-400'}`}
                            />
                            <div>
                              <div className="text-sm text-gray-900">
                                {vehicle.roadworthy_expiry || 'Not set'}
                              </div>
                              <div className={`text-xs ${roadworthyStatus.color}`}>
                                {roadworthyStatus.label}
                              </div>
                            </div>
                          </div>
                        </td>
                        <td className="px-6 py-4">
                          <span
                            className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${statusConfig[vehicle.status].color}`}
                          >
                            <StatusIcon className="w-3.5 h-3.5" />
                            {statusConfig[vehicle.status].label}
                          </span>
                        </td>
                        <td className="px-6 py-4">
                          <div className="flex flex-wrap items-center gap-2">
                            {canManageCostItems && (
                              <button
                                onClick={(event) => {
                                  event.stopPropagation();
                                  setCostItemVehicle(vehicle);
                                }}
                                className="inline-flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs font-medium text-emerald-700 transition-colors hover:bg-emerald-100"
                                title="Add Vehicle Cost Item"
                              >
                                <DollarSign className="w-4 h-4" />
                                Add Cost Item
                              </button>
                            )}
                            <button
                              onClick={(event) => {
                                event.stopPropagation();
                                void handleGenerateDefaultSchedule(vehicle.id);
                              }}
                              disabled={scheduleActionVehicleId === vehicle.id}
                              className="inline-flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-xs font-medium text-blue-700 transition-colors hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-70"
                              title="Generate Default Maintenance Schedule"
                            >
                              {scheduleActionVehicleId === vehicle.id ? (
                                <Loader2 className="w-4 h-4 animate-spin" />
                              ) : (
                                <Calendar className="w-4 h-4" />
                              )}
                              Generate Default Maintenance Schedule
                            </button>
                            <button
                              onClick={(event) => {
                                event.stopPropagation();
                                openEditModal(vehicle);
                              }}
                              className="inline-flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-700 transition-colors hover:bg-amber-100"
                              title="Edit Vehicle"
                            >
                              Edit
                            </button>
                            <button
                              onClick={(event) => {
                                event.stopPropagation();
                                console.info('[Flux Performance] Vehicle details button clicked', {
                                  vehicle,
                                });
                                onOpenVehicleDetails(vehicle.id);
                              }}
                              className="inline-flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-2 text-xs font-medium text-gray-700 transition-colors hover:bg-gray-100"
                              title="View Details"
                            >
                              <Eye className="w-4 h-4 text-gray-600" />
                              View Details
                            </button>
                            <button
                              onClick={(event) => event.stopPropagation()}
                              className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
                              title="More"
                            >
                              <MoreVertical className="w-4 h-4 text-gray-600" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                  {paginatedVehicles.length === 0 && (
                    <tr>
                      <td colSpan={10} className="px-6 py-12 text-center text-sm text-gray-500">
                        {vehicles.length === 0
                          ? 'No vehicles have been added yet.'
                          : 'No vehicles match the current filters.'}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            <div className="px-6 py-4 border-t border-gray-200 flex items-center justify-between bg-gray-50">
              <div className="text-sm text-gray-600">
                Showing <span className="font-medium">{paginatedVehicles.length}</span> of{' '}
                <span className="font-medium">{vehicles.length}</span> vehicles
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setCurrentPage((page) => Math.max(page - 1, 1))}
                  disabled={currentPage === 1}
                  className="px-3 py-1.5 border border-gray-300 rounded-lg hover:bg-white text-sm font-medium text-gray-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Previous
                </button>
                <button className="px-3 py-1.5 bg-[#2563EB] text-white rounded-lg text-sm font-medium">
                  {currentPage} / {totalPages}
                </button>
                <button
                  type="button"
                  onClick={() => setCurrentPage((page) => Math.min(page + 1, totalPages))}
                  disabled={currentPage === totalPages}
                  className="px-3 py-1.5 border border-gray-300 rounded-lg hover:bg-white text-sm font-medium text-gray-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Next
                </button>
              </div>
            </div>
          </>
        )}
      </div>

      {isModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 px-4">
          <div className="w-full max-w-5xl h-[90vh] rounded-2xl bg-white shadow-2xl border border-gray-200 overflow-hidden flex flex-col">
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
              <div>
                <h2 className="text-xl font-semibold text-gray-900">{editingVehicle ? 'Edit Vehicle' : 'Add Vehicle'}</h2>
                <p className="text-sm text-gray-500 mt-1">
                  {editingVehicle ? 'Update the vehicle record, insurance cover, and claim contact details.' : 'Create a new vehicle record for the fleet.'}
                </p>
              </div>
              <button
                onClick={closeModal}
                className="p-2 rounded-lg hover:bg-gray-100 transition-colors"
                aria-label="Close add vehicle modal"
              >
                <X className="w-5 h-5 text-gray-500" />
              </button>
            </div>

            <form onSubmit={handleSaveVehicle} className="flex flex-1 min-h-0 flex-col">
              <div className="flex-1 min-h-0 overflow-y-auto px-6 py-5">
                {formError && (
                  <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                    {formError}
                  </div>
                )}

                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">Registration Number</label>
                    <input
                      value={formState.registration_number}
                      onChange={(e) => handleFieldChange('registration_number', e.target.value)}
                      className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent"
                      required
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">Vehicle Type</label>
                    <select
                      value={formState.vehicle_type}
                      onChange={(e) => handleFieldChange('vehicle_type', e.target.value)}
                      className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent bg-white"
                    >
                      <option value="saloon">Saloon</option>
                      <option value="suv">SUV</option>
                      <option value="pickup">Pickup</option>
                      <option value="van">Van</option>
                      <option value="truck">Truck</option>
                      <option value="motorcycle">Motorcycle</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">Make</label>
                    <input
                      value={formState.make}
                      onChange={(e) => handleFieldChange('make', e.target.value)}
                      className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent"
                      required
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">Model</label>
                    <input
                      value={formState.model}
                      onChange={(e) => handleFieldChange('model', e.target.value)}
                      className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent"
                      required
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">Year</label>
                    <input
                      type="number"
                      value={formState.year}
                      onChange={(e) => handleFieldChange('year', e.target.value)}
                      className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent"
                      required
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">Color</label>
                    <input
                      value={formState.color}
                      onChange={(e) => handleFieldChange('color', e.target.value)}
                      className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">Transmission</label>
                    <select
                      value={formState.transmission}
                      onChange={(e) => handleFieldChange('transmission', e.target.value)}
                      className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent bg-white"
                    >
                      <option value="automatic">Automatic</option>
                      <option value="manual">Manual</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">Fuel Type</label>
                    <select
                      value={formState.fuel_type}
                      onChange={(e) => handleFieldChange('fuel_type', e.target.value)}
                      className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent bg-white"
                    >
                      <option value="petrol">Petrol</option>
                      <option value="diesel">Diesel</option>
                      <option value="hybrid">Hybrid</option>
                      <option value="electric">Electric</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">Chassis Number</label>
                    <input
                      value={formState.chassis_number}
                      onChange={(e) => handleFieldChange('chassis_number', e.target.value)}
                      className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">Engine Number</label>
                    <input
                      value={formState.engine_number}
                      onChange={(e) => handleFieldChange('engine_number', e.target.value)}
                      className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">Insurance Expiry</label>
                    <input
                      type="date"
                      value={formState.insurance_expiry_date || formState.insurance_expiry}
                      onChange={(e) => {
                        handleFieldChange('insurance_expiry', e.target.value);
                        handleFieldChange('insurance_expiry_date', e.target.value);
                      }}
                      className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">Roadworthy Expiry</label>
                    <input
                      type="date"
                      value={formState.roadworthy_expiry}
                      onChange={(e) => handleFieldChange('roadworthy_expiry', e.target.value)}
                      className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">Default Weekly Target</label>
                    <input
                      type="number"
                      step="0.01"
                      value={formState.default_weekly_target}
                      onChange={(e) => handleFieldChange('default_weekly_target', e.target.value)}
                      className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent"
                      required
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">Default Daily Target</label>
                    <input
                      type="number"
                      step="0.01"
                      value={formState.default_daily_target}
                      onChange={(e) => handleFieldChange('default_daily_target', e.target.value)}
                      className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent"
                      required
                    />
                  </div>
                  <div className="md:col-span-2 xl:col-span-3 rounded-xl border border-blue-100 bg-blue-50/60 p-4">
                    <div className="text-sm font-semibold text-[#0F172A]">Insurance Profile</div>
                    <div className="mt-3 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">Insurance Company</label>
                        <input value={formState.insurance_company} onChange={(e) => handleFieldChange('insurance_company', e.target.value)} className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent" />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">Policy Number</label>
                        <input value={formState.policy_number} onChange={(e) => handleFieldChange('policy_number', e.target.value)} className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent" />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">Insurance Type</label>
                        <select value={formState.insurance_type} onChange={(e) => handleFieldChange('insurance_type', e.target.value)} className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent bg-white">
                          <option value="Third Party">Third Party</option>
                          <option value="Comprehensive">Comprehensive</option>
                        </select>
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">Insurance Start Date</label>
                        <input type="date" value={formState.insurance_start_date} onChange={(e) => handleFieldChange('insurance_start_date', e.target.value)} className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent" />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">Coverage Expiry Date</label>
                        <input type="date" value={formState.insurance_expiry_date} onChange={(e) => {
                          handleFieldChange('insurance_expiry_date', e.target.value);
                          handleFieldChange('insurance_expiry', e.target.value);
                        }} className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent" />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">Coverage Duration (Months)</label>
                        <input type="number" value={formState.coverage_duration_months} onChange={(e) => handleFieldChange('coverage_duration_months', e.target.value)} className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent" />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">Claims Officer Name</label>
                        <input value={formState.claims_officer_name} onChange={(e) => handleFieldChange('claims_officer_name', e.target.value)} className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent" />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">Claims Officer Phone</label>
                        <input value={formState.claims_officer_phone} onChange={(e) => handleFieldChange('claims_officer_phone', e.target.value)} className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent" />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">Claims Officer Email</label>
                        <input type="email" value={formState.claims_officer_email} onChange={(e) => handleFieldChange('claims_officer_email', e.target.value)} className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent" />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">Emergency Contact</label>
                        <input value={formState.emergency_contact} onChange={(e) => handleFieldChange('emergency_contact', e.target.value)} className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent" />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">Excess / Deductible</label>
                        <input type="number" step="0.01" value={formState.excess_amount} onChange={(e) => handleFieldChange('excess_amount', e.target.value)} disabled={formState.insurance_type !== 'Comprehensive'} className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent disabled:bg-gray-100 disabled:text-gray-500" />
                      </div>
                      <div className="md:col-span-2 xl:col-span-3">
                        <label className="block text-sm font-medium text-gray-700 mb-2">Covered Risks</label>
                        <input value={formState.covered_risks} onChange={(e) => handleFieldChange('covered_risks', e.target.value)} placeholder="accident, fire, theft, third_party_damage" className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent" />
                      </div>
                      <div className="md:col-span-2 xl:col-span-3">
                        <label className="block text-sm font-medium text-gray-700 mb-2">Excluded Risks</label>
                        <input value={formState.excluded_risks} onChange={(e) => handleFieldChange('excluded_risks', e.target.value)} placeholder="other, breakdown" className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent" />
                      </div>
                    </div>
                    <div className="mt-3 text-xs text-gray-600">
                      Third Party policies are tracked for validity and liability-only claims. Comprehensive policies can include own-damage, excess, covered risks, and exclusions.
                    </div>
                  </div>
                  {canViewInvestmentFields && (
                    <>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">Purchase Cost</label>
                        <input
                          type="number"
                          step="0.01"
                          value={formState.purchase_cost}
                          onChange={(e) => handleFieldChange('purchase_cost', e.target.value)}
                          className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">Shipping Cost</label>
                        <input
                          type="number"
                          step="0.01"
                          value={formState.shipping_cost}
                          onChange={(e) => handleFieldChange('shipping_cost', e.target.value)}
                          className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">Clearing Cost</label>
                        <input
                          type="number"
                          step="0.01"
                          value={formState.clearing_cost}
                          onChange={(e) => handleFieldChange('clearing_cost', e.target.value)}
                          className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">Insurance Cost</label>
                        <input
                          type="number"
                          step="0.01"
                          value={formState.insurance_cost}
                          onChange={(e) => handleFieldChange('insurance_cost', e.target.value)}
                          className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">Roadworthy Cost</label>
                        <input
                          type="number"
                          step="0.01"
                          value={formState.roadworthy_cost}
                          onChange={(e) => handleFieldChange('roadworthy_cost', e.target.value)}
                          className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">AMA Permit Cost</label>
                        <input type="number" step="0.01" value={formState.ama_permit_cost} onChange={(e) => handleFieldChange('ama_permit_cost', e.target.value)} className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent" />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">Vehicle License Cost</label>
                        <input type="number" step="0.01" value={formState.vehicle_license_cost} onChange={(e) => handleFieldChange('vehicle_license_cost', e.target.value)} className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent" />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">Tracker Cost</label>
                        <input type="number" step="0.01" value={formState.tracker_cost} onChange={(e) => handleFieldChange('tracker_cost', e.target.value)} className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent" />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">Branding Cost</label>
                        <input type="number" step="0.01" value={formState.branding_cost} onChange={(e) => handleFieldChange('branding_cost', e.target.value)} className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent" />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">Initial Repairs Cost</label>
                        <input type="number" step="0.01" value={formState.initial_repairs_cost} onChange={(e) => handleFieldChange('initial_repairs_cost', e.target.value)} className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent" />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">Registration Cost</label>
                        <input type="number" step="0.01" value={formState.registration_cost} onChange={(e) => handleFieldChange('registration_cost', e.target.value)} className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent" />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">Other Setup Cost</label>
                        <input type="number" step="0.01" value={formState.other_setup_cost} onChange={(e) => handleFieldChange('other_setup_cost', e.target.value)} className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent" />
                      </div>
                    </>
                  )}
                </div>
              </div>

              <div className="shrink-0 border-t border-gray-200 bg-gray-50 px-6 py-4">
                <div className="flex items-center justify-end gap-3">
                <button
                  type="button"
                  onClick={closeModal}
                  className="px-4 py-2.5 border border-gray-300 rounded-lg hover:bg-white text-sm font-medium text-gray-700"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="px-4 py-2.5 bg-[#2563EB] text-white rounded-lg hover:bg-[#1d4ed8] disabled:opacity-70 disabled:cursor-not-allowed flex items-center gap-2 font-medium"
                >
                  {isSubmitting && <Loader2 className="w-4 h-4 animate-spin" />}
                  {isSubmitting ? 'Saving Vehicle...' : editingVehicle ? 'Save Changes' : 'Add Vehicle'}
                </button>
                </div>
              </div>
            </form>
          </div>
        </div>
      )}

      {costItemVehicle && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 px-4">
          <div className="w-full max-w-2xl rounded-2xl bg-white shadow-2xl border border-gray-200 overflow-hidden flex flex-col">
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
              <div>
                <h2 className="text-xl font-semibold text-gray-900">Add Custom Vehicle Cost</h2>
                <p className="text-sm text-gray-500 mt-1">{costItemVehicle.registration_number}</p>
              </div>
              <button onClick={closeCostItemModal} className="p-2 rounded-lg hover:bg-gray-100 transition-colors" aria-label="Close vehicle cost item modal">
                <X className="w-5 h-5 text-gray-500" />
              </button>
            </div>
            <form onSubmit={handleCreateCostItem} className="space-y-4 px-6 py-5">
              {formError && (
                <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                  {formError}
                </div>
              )}
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Item Name</label>
                  <input value={costItemForm.item_name} onChange={(e) => setCostItemForm((current) => ({ ...current, item_name: e.target.value }))} className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent" required />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Amount</label>
                  <input type="number" step="0.01" value={costItemForm.amount} onChange={(e) => setCostItemForm((current) => ({ ...current, amount: e.target.value }))} className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent" required />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Date</label>
                  <input type="date" value={costItemForm.date} onChange={(e) => setCostItemForm((current) => ({ ...current, date: e.target.value }))} className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent" required />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Notes</label>
                <textarea value={costItemForm.notes} onChange={(e) => setCostItemForm((current) => ({ ...current, notes: e.target.value }))} className="w-full min-h-[110px] px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent" />
              </div>
              <div className="flex items-center justify-end gap-3 border-t border-gray-200 pt-4">
                <button type="button" onClick={closeCostItemModal} className="px-4 py-2.5 border border-gray-300 rounded-lg hover:bg-white text-sm font-medium text-gray-700">
                  Cancel
                </button>
                <button type="submit" disabled={isSubmitting} className="px-4 py-2.5 bg-[#2563EB] text-white rounded-lg hover:bg-[#1d4ed8] disabled:opacity-70 disabled:cursor-not-allowed flex items-center gap-2 font-medium">
                  {isSubmitting && <Loader2 className="w-4 h-4 animate-spin" />}
                  Add Cost Item
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
