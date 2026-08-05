import { useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  CheckCircle,
  ChevronLeft,
  ChevronRight,
  Eye,
  Filter,
  Loader2,
  MapPinned,
  Plus,
  RefreshCcw,
  Search,
  TimerReset,
  Truck,
  XCircle,
  Play,
  LogOut,
  ShieldCheck,
} from 'lucide-react';
import { toast } from 'sonner';
import { ApiRequestError } from '../../lib/api';
import {
  approveVehicleMovement,
  cancelVehicleMovement,
  checkOutVehicleMovement,
  closeVehicleMovement,
  createVehicleMovement,
  fetchVehicleMovementById,
  fetchVehicleMovementOptions,
  fetchVehicleMovements,
  returnVehicleMovement,
  startVehicleMovement,
  reviewMaintenanceMovementCompletion,
  type AssignmentSummary,
  type UserSummary,
  type VehicleMovementOptionsResponse,
  type VehicleMovementRecord,
  type VehicleMovementStatus,
  type VehicleMovementType,
  type VehicleSummary,
} from '../../lib/vehicle-movement-api';
import { useDebouncedValue } from '../../lib/use-debounced-value';
import { usePageToastFeedback } from '../../lib/use-page-toast-feedback';
import { normalizeFuelLevelEighths } from '../../lib/fuel-gauge';
import { FuelGaugeSelector } from '../shared/FuelGaugeSelector';
import { Drawer, DrawerContent, DrawerDescription, DrawerHeader, DrawerTitle } from '../ui/drawer';
import { Skeleton } from '../ui/skeleton';

type LifecycleAction = 'approve' | 'check_out' | 'start' | 'return' | 'close' | 'cancel';

interface CreateFormState {
  vehicle_id: string;
  driver_id: string;
  maintenance_job_id: string;
  movement_type: VehicleMovementType;
  origin: string;
  destination: string;
  purpose: string;
  requested_departure_time: string;
  expected_return_time: string;
  opening_odometer: string;
  opening_fuel_level: string;
  notes: string;
  instructions: string;
}

interface ReturnFormState {
  actual_return_time: string;
  closing_odometer: string;
  closing_fuel_level: string;
  notes: string;
}

interface CancelFormState {
  cancellation_reason: string;
}

interface CheckOutFormState {
  departure_time: string;
  opening_odometer: string;
  opening_fuel_level: string;
}

const MOVEMENT_TYPE_LABELS: Record<VehicleMovementType, string> = {
  customer_dispatch: 'Customer Dispatch',
  personal_use: 'Personal Use',
  fuel_purchase: 'Fuel Purchase',
  maintenance: 'Maintenance',
  workshop: 'Workshop',
  maintenance_transport: 'Maintenance Return Transport',
  workshop_transport: 'Workshop Outbound Transport',
  assignment_handover: 'Assignment Handover',
  internal_company_delivery: 'Internal Company Delivery',
  stock_transfer: 'Stock Transfer',
  fuel_station_visit: 'Fuel-station Visit',
  compliance_inspection_visit: 'Compliance / Inspection Visit',
  administrative_errand: 'Administrative Errand',
  vehicle_repositioning: 'Vehicle Repositioning',
  vehicle_transfer: 'Vehicle Transfer',
  internal_company_movement: 'Internal Company Movement',
  emergency: 'Emergency',
  other: 'Other',
};

const STATUS_LABELS: Record<VehicleMovementStatus, string> = {
  draft: 'Draft',
  pending_approval: 'Pending Approval',
  approved: 'Approved',
  checked_out: 'Checked Out',
  in_progress: 'In Progress',
  returned: 'Returned',
  closed: 'Closed',
  cancelled: 'Cancelled',
};

const STATUS_BADGES: Record<VehicleMovementStatus, string> = {
  draft: 'border-slate-200 bg-slate-100 text-slate-700',
  pending_approval: 'border-amber-200 bg-amber-100 text-amber-800',
  approved: 'border-blue-200 bg-blue-100 text-blue-800',
  checked_out: 'border-indigo-200 bg-indigo-100 text-indigo-800',
  in_progress: 'border-cyan-200 bg-cyan-100 text-cyan-800',
  returned: 'border-emerald-200 bg-emerald-100 text-emerald-800',
  closed: 'border-green-200 bg-green-100 text-green-800',
  cancelled: 'border-rose-200 bg-rose-100 text-rose-800',
};

const initialCreateFormState = (): CreateFormState => ({
  vehicle_id: '',
  driver_id: '',
  maintenance_job_id: '',
  movement_type: 'personal_use',
  origin: '',
  destination: '',
  purpose: '',
  requested_departure_time: new Date().toISOString().slice(0, 16),
  expected_return_time: '',
  opening_odometer: '',
  opening_fuel_level: '',
  notes: '',
  instructions: '',
});

const initialReturnFormState = (): ReturnFormState => ({
  actual_return_time: new Date().toISOString().slice(0, 16),
  closing_odometer: '',
  closing_fuel_level: '',
  notes: '',
});

const initialCancelFormState = (): CancelFormState => ({
  cancellation_reason: '',
});

const initialCheckOutFormState = (): CheckOutFormState => ({
  departure_time: new Date().toISOString().slice(0, 16),
  opening_odometer: '',
  opening_fuel_level: '',
});

function formatDateTime(value?: string | null) {
  if (!value) {
    return 'Not recorded';
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString();
}

function formatOptionalNumber(value?: number | null) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return 'Not recorded';
  }
  return value.toLocaleString();
}

function buildCreatePayload(form: CreateFormState) {
  return {
    vehicle_id: form.vehicle_id,
    driver_id: form.driver_id || undefined,
    maintenance_job_id: form.maintenance_job_id || undefined,
    movement_type: form.movement_type,
    status: 'pending_approval',
    origin: form.origin || undefined,
    destination: form.destination || undefined,
    purpose: form.purpose || undefined,
    requested_departure_time: form.requested_departure_time || undefined,
    expected_return_time: form.expected_return_time || undefined,
    opening_odometer: form.opening_odometer ? Number(form.opening_odometer) : undefined,
    opening_fuel_level: form.opening_fuel_level ? normalizeFuelLevelEighths(form.opening_fuel_level) ?? undefined : undefined,
    notes: form.notes || undefined,
    instructions: form.instructions || undefined,
  };
}

function getFuelFormValue(value: string) {
  return normalizeFuelLevelEighths(value);
}

function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof ApiRequestError ? error.message : fallback;
}

function getAllowedActions(status: VehicleMovementStatus): LifecycleAction[] {
  switch (status) {
    case 'draft':
    case 'pending_approval':
      return ['approve', 'cancel'];
    case 'approved':
      return ['check_out', 'start', 'cancel'];
    case 'checked_out':
      return ['start', 'return'];
    case 'in_progress':
      return ['return'];
    case 'returned':
      return ['close'];
    default:
      return [];
  }
}

export default function VehicleMovements() {
  const [movements, setMovements] = useState<VehicleMovementRecord[]>([]);
  const [pagination, setPagination] = useState({ page: 1, page_size: 25, total: 0, total_pages: 1 });
  const [options, setOptions] = useState<VehicleMovementOptionsResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingOptions, setIsLoadingOptions] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [pageError, setPageError] = useState('');
  const [pageNotice, setPageNotice] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [movementTypeFilter, setMovementTypeFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [vehicleFilter, setVehicleFilter] = useState('');
  const [driverFilter, setDriverFilter] = useState('');
  const [branchFilter, setBranchFilter] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [formError, setFormError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [createForm, setCreateForm] = useState<CreateFormState>(initialCreateFormState);
  const [selectedMovementId, setSelectedMovementId] = useState<string | null>(null);
  const [detailMovement, setDetailMovement] = useState<VehicleMovementRecord | null>(null);
  const [isLoadingDetail, setIsLoadingDetail] = useState(false);
  const [detailError, setDetailError] = useState('');
  const [detailCache, setDetailCache] = useState<Record<string, VehicleMovementRecord>>({});
  const [actionTarget, setActionTarget] = useState<VehicleMovementRecord | null>(null);
  const [actionType, setActionType] = useState<LifecycleAction | null>(null);
  const [actionError, setActionError] = useState('');
  const [isActionSubmitting, setIsActionSubmitting] = useState(false);
  const [returnForm, setReturnForm] = useState<ReturnFormState>(initialReturnFormState);
  const [cancelForm, setCancelForm] = useState<CancelFormState>(initialCancelFormState);
  const [checkOutForm, setCheckOutForm] = useState<CheckOutFormState>(initialCheckOutFormState);
  const debouncedSearchQuery = useDebouncedValue(searchQuery, 300);

  usePageToastFeedback(pageError, pageNotice);

  const loadOptions = async () => {
    if (options || isLoadingOptions) {
      return;
    }
    setIsLoadingOptions(true);
    try {
      const nextOptions = await fetchVehicleMovementOptions();
      setOptions(nextOptions);
    } catch (error) {
      setPageNotice(getErrorMessage(error, 'Vehicle movement options are temporarily unavailable.'));
    } finally {
      setIsLoadingOptions(false);
    }
  };

  const loadMovements = async ({ refresh = false }: { refresh?: boolean } = {}) => {
    if (refresh) {
      setIsRefreshing(true);
    } else {
      setIsLoading(true);
    }
    setPageError('');
    try {
      const response = await fetchVehicleMovements({
        page: currentPage,
        page_size: 25,
        q: debouncedSearchQuery || undefined,
        vehicle_id: vehicleFilter || undefined,
        driver_id: driverFilter || undefined,
        branch_id: branchFilter || undefined,
        status: statusFilter || undefined,
        movement_type: movementTypeFilter || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
      });
      setMovements(response.movements || []);
      setPagination(response.pagination || { page: 1, page_size: 25, total: 0, total_pages: 1 });
    } catch (error) {
      setMovements([]);
      setPagination({ page: 1, page_size: 25, total: 0, total_pages: 1 });
      setPageError(getErrorMessage(error, 'Unable to load vehicle movements right now.'));
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  };

  useEffect(() => {
    void loadOptions();
  }, []);

  useEffect(() => {
    void loadMovements();
  }, [currentPage, debouncedSearchQuery, movementTypeFilter, statusFilter, vehicleFilter, driverFilter, dateFrom, dateTo]);

  const openCreateModal = async () => {
    setFormError('');
    const assignment = options?.assignments?.[0];
    setCreateForm({
      ...initialCreateFormState(),
      vehicle_id: assignment?.vehicle_id || options?.vehicles?.[0]?.id || '',
      driver_id: assignment?.driver_id || '',
    });
    setShowCreateModal(true);
    void loadOptions();
  };

  const closeCreateModal = () => {
    setShowCreateModal(false);
    setFormError('');
    setCreateForm(initialCreateFormState());
  };

  const openDetailsDrawer = async (movement: VehicleMovementRecord) => {
    setSelectedMovementId(movement.id);
    setDetailMovement(detailCache[movement.id] || movement);
    setDetailError('');
    if (detailCache[movement.id]) {
      return;
    }
    setIsLoadingDetail(true);
    try {
      const detail = await fetchVehicleMovementById(movement.id);
      setDetailCache((current) => ({ ...current, [movement.id]: detail }));
      setDetailMovement(detail);
    } catch (error) {
      setDetailError(getErrorMessage(error, 'Unable to load movement details right now.'));
    } finally {
      setIsLoadingDetail(false);
    }
  };

  const closeDetailsDrawer = () => {
    setSelectedMovementId(null);
    setDetailMovement(null);
    setDetailError('');
    setIsLoadingDetail(false);
  };

  const openActionModal = (movement: VehicleMovementRecord, action: LifecycleAction) => {
    setActionTarget(movement);
    setActionType(action);
    setActionError('');
    setReturnForm({
      ...initialReturnFormState(),
      closing_odometer: movement.opening_odometer !== null && movement.opening_odometer !== undefined ? String(movement.opening_odometer) : '',
      closing_fuel_level: movement.opening_fuel_level !== null && movement.opening_fuel_level !== undefined ? String(movement.opening_fuel_level) : '',
      notes: movement.notes || '',
    });
    setCancelForm(initialCancelFormState());
    setCheckOutForm({
      ...initialCheckOutFormState(),
      opening_odometer: movement.opening_odometer !== null && movement.opening_odometer !== undefined ? String(movement.opening_odometer) : '',
      opening_fuel_level: movement.opening_fuel_level !== null && movement.opening_fuel_level !== undefined ? String(movement.opening_fuel_level) : '',
    });
  };

  const closeActionModal = () => {
    setActionTarget(null);
    setActionType(null);
    setActionError('');
    setIsActionSubmitting(false);
  };

  const replaceMovementInState = (movement: VehicleMovementRecord) => {
    setMovements((current) => current.map((item) => (item.id === movement.id ? movement : item)));
    setDetailCache((current) => ({ ...current, [movement.id]: movement }));
    if (detailMovement?.id === movement.id) {
      setDetailMovement(movement);
    }
    if (actionTarget?.id === movement.id) {
      setActionTarget(movement);
    }
  };

  const handleCreateMovement = async (event: React.FormEvent) => {
    event.preventDefault();
    setIsSubmitting(true);
    setFormError('');
    try {
      const createdMovement = await createVehicleMovement(buildCreatePayload(createForm));
      setMovements((current) => [createdMovement, ...current].slice(0, pageSize));
      closeCreateModal();
      setPageNotice('Vehicle movement created successfully.');
      setCurrentPage(1);
    } catch (error) {
      setFormError(getErrorMessage(error, 'Unable to create vehicle movement right now.'));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleMaintenanceReview = async (movement: VehicleMovementRecord, decision: 'approved' | 'returned_for_correction' | 'rejected') => {
    if (isActionSubmitting) return;
    const reason = decision === 'approved' ? undefined : window.prompt('Enter the review reason:')?.trim();
    if (decision !== 'approved' && !reason) return;
    setIsActionSubmitting(true);
    setDetailError('');
    try {
      const updated = await reviewMaintenanceMovementCompletion(movement.id, decision, reason);
      replaceMovementInState(updated);
      setPageNotice(`Maintenance completion ${decision.replaceAll('_', ' ')}.`);
    } catch (error) {
      setDetailError(getErrorMessage(error, 'Unable to review maintenance completion.'));
    } finally {
      setIsActionSubmitting(false);
    }
  };

  const handleLifecycleAction = async (event?: React.FormEvent) => {
    event?.preventDefault();
    if (!actionTarget || !actionType) {
      return;
    }
    setActionError('');
    setIsActionSubmitting(true);
    try {
      let updatedMovement: VehicleMovementRecord;
      switch (actionType) {
        case 'approve':
          updatedMovement = await approveVehicleMovement(actionTarget.id);
          break;
        case 'check_out':
          updatedMovement = await checkOutVehicleMovement(actionTarget.id, {
            departure_time: checkOutForm.departure_time || undefined,
            opening_odometer: checkOutForm.opening_odometer ? Number(checkOutForm.opening_odometer) : undefined,
            opening_fuel_level: checkOutForm.opening_fuel_level ? normalizeFuelLevelEighths(checkOutForm.opening_fuel_level) ?? undefined : undefined,
          });
          break;
        case 'start':
          updatedMovement = await startVehicleMovement(actionTarget.id, {});
          break;
        case 'return':
          updatedMovement = await returnVehicleMovement(actionTarget.id, {
            actual_return_time: returnForm.actual_return_time || undefined,
            closing_odometer: returnForm.closing_odometer ? Number(returnForm.closing_odometer) : undefined,
            closing_fuel_level: returnForm.closing_fuel_level ? normalizeFuelLevelEighths(returnForm.closing_fuel_level) ?? undefined : undefined,
            notes: returnForm.notes || undefined,
          });
          break;
        case 'close':
          updatedMovement = await closeVehicleMovement(actionTarget.id);
          break;
        case 'cancel':
          updatedMovement = await cancelVehicleMovement(actionTarget.id, {
            cancellation_reason: cancelForm.cancellation_reason,
          });
          break;
      }
      replaceMovementInState(updatedMovement!);
      toast.success(`Vehicle movement ${STATUS_LABELS[updatedMovement!.status].toLowerCase()} successfully.`);
      closeActionModal();
    } catch (error) {
      setActionError(getErrorMessage(error, 'Unable to update vehicle movement right now.'));
    } finally {
      setIsActionSubmitting(false);
    }
  };

  const totalOpen = useMemo(
    () => movements.filter((item) => ['draft', 'pending_approval', 'approved', 'checked_out', 'in_progress'].includes(item.status)).length,
    [movements],
  );
  const totalReturned = useMemo(() => movements.filter((item) => item.status === 'returned').length, [movements]);
  const totalClosed = useMemo(() => movements.filter((item) => item.status === 'closed').length, [movements]);

  const vehicleOptions = options?.vehicles || [];
  const driverOptions = options?.drivers || [];
  const movementTypeOptions = options?.movement_types || [];
  const creatableMovementTypeOptions = options?.creatable_movement_types || movementTypeOptions;
  const statusOptions = options?.statuses || [];
  const assignmentOptions = options?.assignments || [];

  return (
    <div className="space-y-6 p-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-[#0F172A]">Vehicle Movements</h1>
          <p className="mt-1 text-gray-600">
            Track every time a vehicle leaves the yard, manage lifecycle actions, and keep movement records clean.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => void loadMovements({ refresh: true })}
            className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 transition-all hover:bg-gray-50"
          >
            {isRefreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCcw className="h-4 w-4" />}
            Refresh
          </button>
          <button
            type="button"
            onClick={() => void openCreateModal()}
            className="inline-flex items-center gap-2 rounded-lg bg-[#2563EB] px-4 py-2.5 text-sm font-medium text-white transition-all hover:bg-[#1d4ed8]"
          >
            <Plus className="h-4 w-4" />
            Create Movement
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <StatCard icon={Truck} label="This Page" value={movements.length} tint="bg-blue-100 text-blue-700" />
        <StatCard icon={TimerReset} label="Open Statuses" value={totalOpen} tint="bg-amber-100 text-amber-700" />
        <StatCard icon={ShieldCheck} label="Returned / Closed" value={totalReturned + totalClosed} tint="bg-green-100 text-green-700" />
      </div>

      <div className="rounded-xl border border-gray-200 bg-white p-4">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-center">
          <div className="relative min-w-0 flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
            <input
              value={searchQuery}
              onChange={(event) => {
                setSearchQuery(event.target.value);
                setCurrentPage(1);
              }}
              placeholder="Search movement ID, purpose, origin, destination..."
              className="w-full rounded-lg border border-gray-300 py-2.5 pl-10 pr-4 text-sm focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
            />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Filter className="h-4 w-4 text-gray-500" />
            <select
              value={movementTypeFilter}
              onChange={(event) => {
                setMovementTypeFilter(event.target.value);
                setCurrentPage(1);
              }}
              className="rounded-lg border border-gray-300 px-3 py-2.5 text-sm focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
            >
              <option value="">All Types</option>
              {movementTypeOptions.map((movementType) => (
                <option key={movementType} value={movementType}>
                  {MOVEMENT_TYPE_LABELS[movementType]}
                </option>
              ))}
            </select>
            <select
              value={statusFilter}
              onChange={(event) => {
                setStatusFilter(event.target.value);
                setCurrentPage(1);
              }}
              className="rounded-lg border border-gray-300 px-3 py-2.5 text-sm focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
            >
              <option value="">All Statuses</option>
              {statusOptions.map((status) => (
                <option key={status} value={status}>
                  {STATUS_LABELS[status]}
                </option>
              ))}
            </select>
            <select
              value={vehicleFilter}
              onChange={(event) => {
                setVehicleFilter(event.target.value);
                setCurrentPage(1);
              }}
              className="rounded-lg border border-gray-300 px-3 py-2.5 text-sm focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
            >
              <option value="">All Vehicles</option>
              {vehicleOptions.map((vehicle) => (
                <option key={vehicle.id} value={vehicle.id}>
                  {vehicle.registration_number}
                </option>
              ))}
            </select>
            <select
              value={branchFilter}
              onChange={(event) => { setBranchFilter(event.target.value); setCurrentPage(1); }}
              className="rounded-lg border border-gray-300 px-3 py-2.5 text-sm focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
            >
              <option value="">All Branches</option>
              {(options?.branches || []).map((branch) => <option key={branch.id} value={branch.id}>{branch.name}</option>)}
            </select>
            <select
              value={driverFilter}
              onChange={(event) => {
                setDriverFilter(event.target.value);
                setCurrentPage(1);
              }}
              className="rounded-lg border border-gray-300 px-3 py-2.5 text-sm focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
            >
              <option value="">All Drivers</option>
              {driverOptions.map((driver) => (
                <option key={driver.id} value={driver.id}>
                  {driver.full_name}
                </option>
              ))}
            </select>
            <input
              type="date"
              value={dateFrom}
              onChange={(event) => {
                setDateFrom(event.target.value);
                setCurrentPage(1);
              }}
              className="rounded-lg border border-gray-300 px-3 py-2.5 text-sm focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
            />
            <input
              type="date"
              value={dateTo}
              onChange={(event) => {
                setDateTo(event.target.value);
                setCurrentPage(1);
              }}
              className="rounded-lg border border-gray-300 px-3 py-2.5 text-sm focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
            />
          </div>
        </div>
      </div>

      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
        <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
          <div>
            <h2 className="text-lg font-semibold text-[#0F172A]">Movement Log</h2>
            <p className="mt-1 text-sm text-gray-600">
              Page {pagination.page} of {pagination.total_pages} • {pagination.total.toLocaleString()} total movements
            </p>
          </div>
        </div>

        {isLoading ? (
          <MovementTableSkeleton />
        ) : pageError ? (
          <div className="px-6 py-12">
            <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-4 text-sm text-red-700">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <span>{pageError}</span>
                <button
                  type="button"
                  onClick={() => void loadMovements({ refresh: true })}
                  className="rounded-lg border border-red-200 bg-white px-3 py-2 text-xs font-medium text-red-700 hover:bg-red-100"
                >
                  Retry
                </button>
              </div>
            </div>
          </div>
        ) : movements.length === 0 ? (
          <div className="px-6 py-16 text-center">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-blue-50">
              <MapPinned className="h-7 w-7 text-blue-600" />
            </div>
            <h3 className="mt-4 text-lg font-semibold text-[#0F172A]">No vehicle movements found</h3>
            <p className="mt-2 text-sm text-gray-500">
              Try adjusting your filters or create the first movement for a vehicle leaving the yard.
            </p>
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="border-b border-gray-200 bg-gray-50">
                  <tr>
                    {['Movement', 'Vehicle', 'Driver', 'Type', 'Status', 'Departure', 'Expected Return', 'Actions'].map((header) => (
                      <th key={header} className="px-6 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">
                        {header}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {movements.map((movement) => (
                    <tr key={movement.id} className="transition-colors hover:bg-gray-50">
                      <td className="px-6 py-4">
                        <div className="font-medium text-[#0F172A]">{movement.movement_id}</div>
                        <div className="text-xs text-gray-500">{formatDateTime(movement.created_at)}</div>
                      </td>
                      <td className="px-6 py-4">
                        <div className="font-medium text-[#0F172A]">{movement.vehicle?.registration_number || 'Unknown vehicle'}</div>
                        <div className="text-xs capitalize text-gray-500">{movement.vehicle?.vehicle_type || 'n/a'}</div>
                      </td>
                      <td className="px-6 py-4">
                        <div className="font-medium text-[#0F172A]">{movement.driver?.full_name || 'Unassigned'}</div>
                        <div className="text-xs text-gray-500">{movement.driver?.phone || 'No phone'}</div>
                      </td>
                      <td className="px-6 py-4 text-sm text-gray-700">{movement.movement_category?.replaceAll('_', ' ') || MOVEMENT_TYPE_LABELS[movement.movement_type]}</td>
                      <td className="px-6 py-4">
                        <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${STATUS_BADGES[movement.status]}`}>
                          {STATUS_LABELS[movement.status]}
                        </span>
                      </td>
                      <td className="px-6 py-4 text-sm text-gray-700">{formatDateTime(movement.departure_time || movement.requested_departure_time)}</td>
                      <td className="px-6 py-4 text-sm text-gray-700">{formatDateTime(movement.expected_return_time)}</td>
                      <td className="px-6 py-4">
                        <div className="flex flex-wrap items-center gap-2">
                          <button
                            type="button"
                            onClick={() => void openDetailsDrawer(movement)}
                            className="rounded-lg border border-gray-200 bg-white p-2 text-gray-700 transition-all hover:bg-gray-50"
                            title="View details"
                          >
                            <Eye className="h-4 w-4" />
                          </button>
                          {getAllowedActions(movement.status).map((action) => (
                            <ActionBadge key={action} action={action} onClick={() => openActionModal(movement, action)} />
                          ))}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex flex-col gap-3 border-t border-gray-200 px-6 py-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="text-sm text-gray-500">
                Showing {movements.length} of {pagination.total.toLocaleString()} movements
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  disabled={pagination.page <= 1}
                  onClick={() => setCurrentPage((current) => Math.max(1, current - 1))}
                  className="inline-flex items-center gap-2 rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 transition-all hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <ChevronLeft className="h-4 w-4" />
                  Previous
                </button>
                <span className="text-sm font-medium text-[#0F172A]">
                  {pagination.page} / {pagination.total_pages}
                </span>
                <button
                  type="button"
                  disabled={pagination.page >= pagination.total_pages}
                  onClick={() => setCurrentPage((current) => Math.min(pagination.total_pages, current + 1))}
                  className="inline-flex items-center gap-2 rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 transition-all hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Next
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            </div>
          </>
        )}
      </div>

      {showCreateModal && (
        <ModalShell title="Create Vehicle Movement" subtitle="Log the next time a vehicle leaves the yard." onClose={closeCreateModal} maxWidth="max-w-4xl">
          <form onSubmit={handleCreateMovement} className="flex min-h-0 flex-1 flex-col overflow-hidden">
            <div className="grid flex-1 grid-cols-1 gap-4 overflow-y-auto px-6 py-5 md:grid-cols-2">
              <SelectField label="Vehicle" value={createForm.vehicle_id} onChange={(value) => setCreateForm((current) => ({ ...current, vehicle_id: value }))}>
                <option value="">Select vehicle</option>
                {vehicleOptions.map((vehicle) => (
                  <option key={vehicle.id} value={vehicle.id}>
                    {vehicle.registration_number}
                  </option>
                ))}
              </SelectField>
              <SelectField label={['maintenance', 'workshop'].includes(createForm.movement_type) ? 'Movement Custodian (Optional)' : 'Driver (Optional)'} value={createForm.driver_id} onChange={(value) => setCreateForm((current) => ({ ...current, driver_id: value }))}>
                <option value="">Unassigned</option>
                {driverOptions.map((driver) => (
                  <option key={driver.id} value={driver.id}>
                    {driver.full_name}
                  </option>
                ))}
              </SelectField>
              {['maintenance', 'workshop'].includes(createForm.movement_type) ? (
                <InputField label="Maintenance Job ID" value={createForm.maintenance_job_id} onChange={(value) => setCreateForm((current) => ({ ...current, maintenance_job_id: value }))} />
              ) : null}
              <SelectField label="Movement Type" value={createForm.movement_type} onChange={(value) => setCreateForm((current) => ({ ...current, movement_type: value as VehicleMovementType }))}>
                {creatableMovementTypeOptions.map((movementType) => (
                  <option key={movementType} value={movementType}>
                    {MOVEMENT_TYPE_LABELS[movementType]}
                  </option>
                ))}
              </SelectField>
              <SelectField
                label="Linked Assignment (Auto via driver/vehicle if available)"
                value={
                  assignmentOptions.find(
                    (assignment) =>
                      assignment.vehicle_id === createForm.vehicle_id
                      && (!createForm.driver_id || assignment.driver_id === createForm.driver_id),
                  )?.id || ''
                }
                onChange={() => undefined}
                disabled
              >
                <option value="">
                  {assignmentOptions.find(
                    (assignment) =>
                      assignment.vehicle_id === createForm.vehicle_id
                      && (!createForm.driver_id || assignment.driver_id === createForm.driver_id),
                  )
                    ? 'Assignment matched automatically'
                    : 'No active assignment matched'}
                </option>
              </SelectField>
              <InputField label="Origin" value={createForm.origin} onChange={(value) => setCreateForm((current) => ({ ...current, origin: value }))} />
              <InputField label="Destination" value={createForm.destination} onChange={(value) => setCreateForm((current) => ({ ...current, destination: value }))} />
              <InputField label="Purpose" value={createForm.purpose} onChange={(value) => setCreateForm((current) => ({ ...current, purpose: value }))} />
              {['maintenance', 'workshop'].includes(createForm.movement_type) ? (
                <InputField label="Custodian Instructions" value={createForm.instructions} onChange={(value) => setCreateForm((current) => ({ ...current, instructions: value }))} />
              ) : null}
              <InputField
                label="Requested Departure Time"
                type="datetime-local"
                value={createForm.requested_departure_time}
                onChange={(value) => setCreateForm((current) => ({ ...current, requested_departure_time: value }))}
              />
              <InputField
                label="Expected Return Time"
                type="datetime-local"
                value={createForm.expected_return_time}
                onChange={(value) => setCreateForm((current) => ({ ...current, expected_return_time: value }))}
              />
              <InputField label="Opening Odometer (Optional)" type="number" value={createForm.opening_odometer} onChange={(value) => setCreateForm((current) => ({ ...current, opening_odometer: value }))} />
              <div className="md:col-span-2">
                <FuelGaugeSelector
                  label="Opening Fuel Level (Optional)"
                  value={getFuelFormValue(createForm.opening_fuel_level)}
                  onChange={(value) => setCreateForm((current) => ({ ...current, opening_fuel_level: String(value) }))}
                  compact
                  showEstimatedLitres
                  tankCapacityLitres={vehicleOptions.find((vehicle) => vehicle.id === createForm.vehicle_id)?.tank_capacity_litres}
                />
              </div>
              <div className="md:col-span-2">
                <TextAreaField label="Notes" value={createForm.notes} onChange={(value) => setCreateForm((current) => ({ ...current, notes: value }))} placeholder="Add context, handover notes, or operational remarks." />
              </div>
              {formError && (
                <div className="md:col-span-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                  {formError}
                </div>
              )}
            </div>
            <ModalFooter onCancel={closeCreateModal} submitLabel={isSubmitting ? 'Creating...' : 'Create Movement'} isSubmitting={isSubmitting} />
          </form>
        </ModalShell>
      )}

      <Drawer open={Boolean(selectedMovementId)} direction="right" onOpenChange={(open) => !open && closeDetailsDrawer()}>
        <DrawerContent className="w-full max-w-2xl border-l border-gray-200 bg-white">
          <DrawerHeader className="border-b border-gray-200 px-6 py-4 text-left">
            <DrawerTitle className="text-xl font-semibold text-[#0F172A]">
              {detailMovement?.movement_id || 'Vehicle Movement'}
            </DrawerTitle>
            <DrawerDescription className="text-sm text-gray-500">
              View the full movement lifecycle, handoff timestamps, and audit-facing details.
            </DrawerDescription>
          </DrawerHeader>
          <div className="flex-1 overflow-y-auto px-6 py-5">
            {isLoadingDetail ? (
              <div className="space-y-4">
                <Skeleton className="h-6 w-48" />
                <Skeleton className="h-24 w-full" />
                <Skeleton className="h-24 w-full" />
                <Skeleton className="h-24 w-full" />
              </div>
            ) : detailError ? (
              <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                {detailError}
              </div>
            ) : detailMovement ? (
              <div className="space-y-6">
                <DetailSection title="Overview">
                  <DetailGrid>
                    <DetailRow label="Movement ID" value={detailMovement.movement_id} />
                    <DetailRow label="Vehicle" value={detailMovement.vehicle?.registration_number || 'Unknown vehicle'} />
                    <DetailRow label="Driver" value={detailMovement.driver?.full_name || 'Unassigned'} />
                    <DetailRow label="Movement Type" value={detailMovement.movement_category?.replaceAll('_', ' ') || MOVEMENT_TYPE_LABELS[detailMovement.movement_type]} />
                    <DetailRow label="Status" value={STATUS_LABELS[detailMovement.status]} />
                    <DetailRow label="Purpose" value={detailMovement.purpose || 'Not provided'} />
                    <DetailRow label="Origin" value={detailMovement.origin || 'Not provided'} />
                    <DetailRow label="Destination" value={detailMovement.destination || 'Not provided'} />
                  </DetailGrid>
                </DetailSection>
                <DetailSection title="Timing">
                  <DetailGrid>
                    <DetailRow label="Requested Departure" value={formatDateTime(detailMovement.requested_departure_time)} />
                    <DetailRow label="Departure Time" value={formatDateTime(detailMovement.departure_time)} />
                    <DetailRow label="Expected Return" value={formatDateTime(detailMovement.expected_return_time)} />
                    <DetailRow label="Actual Return" value={formatDateTime(detailMovement.actual_return_time)} />
                  </DetailGrid>
                </DetailSection>
                <DetailSection title="Mileage & Fuel">
                  <DetailGrid>
                    <DetailRow label="Odometer Out" value={formatOptionalNumber(detailMovement.opening_odometer)} />
                    <DetailRow label="Odometer In" value={formatOptionalNumber(detailMovement.closing_odometer)} />
                    <div className="md:col-span-2">
                      <FuelGaugeSelector
                        label="Fuel Out"
                        value={detailMovement.opening_fuel_level ?? null}
                        readOnly
                        compact
                        showEstimatedLitres
                        tankCapacityLitres={detailMovement.vehicle?.tank_capacity_litres}
                      />
                    </div>
                    <div className="md:col-span-2">
                      <FuelGaugeSelector
                        label="Fuel In"
                        value={detailMovement.closing_fuel_level ?? null}
                        compareToValue={detailMovement.opening_fuel_level ?? null}
                        readOnly
                        compact
                        showEstimatedLitres
                        tankCapacityLitres={detailMovement.vehicle?.tank_capacity_litres}
                      />
                    </div>
                  </DetailGrid>
                </DetailSection>
                <DetailSection title="Workflow">
                  <DetailGrid>
                    <DetailRow label="Created By" value={detailMovement.created_by_user?.full_name || 'Unknown'} />
                    <DetailRow label="Approved By" value={detailMovement.approved_by_user?.full_name || 'Not recorded'} />
                    <DetailRow label="Checked Out By" value={detailMovement.checked_out_by_user?.full_name || 'Not recorded'} />
                    <DetailRow label="Returned By" value={detailMovement.returned_by_user?.full_name || 'Not recorded'} />
                    <DetailRow label="Closed By" value={detailMovement.closed_by_user?.full_name || 'Not recorded'} />
                    <DetailRow label="Cancelled Reason" value={detailMovement.cancellation_reason || 'Not cancelled'} />
                  </DetailGrid>
                </DetailSection>
                {['maintenance', 'workshop'].includes(detailMovement.movement_type) ? (
                  <DetailSection title="Maintenance Completion">
                    <DetailGrid>
                      <DetailRow label="Permanent Driver" value={detailMovement.permanent_driver?.full_name || 'Unassigned'} />
                      <DetailRow label="Movement Custodian" value={detailMovement.movement_custodian?.full_name || 'Unassigned'} />
                      <DetailRow label="Maintenance Assignee" value={detailMovement.maintenance_assignee?.full_name || 'Unassigned'} />
                      <DetailRow label="Review Status" value={detailMovement.completion_status?.replaceAll('_', ' ') || 'Not submitted'} />
                      <DetailRow label="Work Performed" value={detailMovement.work_performed || 'Not submitted'} />
                      <DetailRow label="Parts Changed" value={detailMovement.parts_changed?.join(', ') || 'None recorded'} />
                      <DetailRow label="Test Result" value={detailMovement.test_result || 'Not submitted'} />
                    </DetailGrid>
                    {detailMovement.completion_status === 'awaiting_admin_verification' ? (
                      <div className="mt-4 flex flex-wrap gap-2">
                        <button disabled={isActionSubmitting} onClick={() => void handleMaintenanceReview(detailMovement, 'approved')} className="rounded-lg bg-emerald-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-60">{isActionSubmitting ? 'Saving...' : 'Approve Completion'}</button>
                        <button disabled={isActionSubmitting} onClick={() => void handleMaintenanceReview(detailMovement, 'returned_for_correction')} className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm font-medium text-amber-800 disabled:opacity-60">Return for Correction</button>
                        <button disabled={isActionSubmitting} onClick={() => void handleMaintenanceReview(detailMovement, 'rejected')} className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm font-medium text-red-700 disabled:opacity-60">Reject</button>
                      </div>
                    ) : null}
                  </DetailSection>
                ) : null}
                <DetailSection title="Timestamps">
                  <DetailGrid>
                    <DetailRow label="Created At" value={formatDateTime(detailMovement.created_at)} />
                    <DetailRow label="Updated At" value={formatDateTime(detailMovement.updated_at)} />
                    <DetailRow label="Approved At" value={formatDateTime(detailMovement.approved_at)} />
                    <DetailRow label="Checked Out At" value={formatDateTime(detailMovement.checked_out_at)} />
                    <DetailRow label="Returned At" value={formatDateTime(detailMovement.returned_at)} />
                    <DetailRow label="Closed At" value={formatDateTime(detailMovement.closed_at)} />
                  </DetailGrid>
                </DetailSection>
                <DetailSection title="Notes">
                  <div className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-4 text-sm text-gray-700">
                    {detailMovement.notes || 'No notes recorded.'}
                  </div>
                </DetailSection>
              </div>
            ) : null}
          </div>
        </DrawerContent>
      </Drawer>

      {actionTarget && actionType && (
        <ModalShell title={getActionTitle(actionType)} subtitle={actionTarget.movement_id} onClose={closeActionModal} maxWidth="max-w-2xl">
          <form onSubmit={handleLifecycleAction} className="flex min-h-0 flex-1 flex-col overflow-hidden">
            <div className="space-y-4 overflow-y-auto px-6 py-5">
              {actionType === 'approve' && (
                <p className="text-sm text-gray-600">
                  Approving this movement confirms it is ready to leave the yard when operations checks are complete.
                </p>
              )}
              {actionType === 'check_out' && (
                <>
                  <InputField label="Departure Time" type="datetime-local" value={checkOutForm.departure_time} onChange={(value) => setCheckOutForm((current) => ({ ...current, departure_time: value }))} />
                  <InputField label="Opening Odometer" type="number" value={checkOutForm.opening_odometer} onChange={(value) => setCheckOutForm((current) => ({ ...current, opening_odometer: value }))} />
                  <FuelGaugeSelector
                    label="Opening Fuel Level"
                    value={getFuelFormValue(checkOutForm.opening_fuel_level)}
                    onChange={(value) => setCheckOutForm((current) => ({ ...current, opening_fuel_level: String(value) }))}
                    showEstimatedLitres
                    tankCapacityLitres={actionTarget?.vehicle?.tank_capacity_litres}
                  />
                </>
              )}
              {actionType === 'start' && (
                <p className="text-sm text-gray-600">
                  Starting this movement marks the vehicle as actively in motion. Use this when the trip has actually begun.
                </p>
              )}
              {actionType === 'return' && (
                <>
                  <InputField label="Actual Return Time" type="datetime-local" value={returnForm.actual_return_time} onChange={(value) => setReturnForm((current) => ({ ...current, actual_return_time: value }))} />
                  <InputField label="Closing Odometer" type="number" value={returnForm.closing_odometer} onChange={(value) => setReturnForm((current) => ({ ...current, closing_odometer: value }))} />
                  <FuelGaugeSelector
                    label="Closing Fuel Level"
                    value={getFuelFormValue(returnForm.closing_fuel_level)}
                    onChange={(value) => setReturnForm((current) => ({ ...current, closing_fuel_level: String(value) }))}
                    compareToValue={actionTarget?.opening_fuel_level ?? null}
                    showEstimatedLitres
                    tankCapacityLitres={actionTarget?.vehicle?.tank_capacity_litres}
                  />
                  <TextAreaField label="Return Notes" value={returnForm.notes} onChange={(value) => setReturnForm((current) => ({ ...current, notes: value }))} placeholder="Describe return condition, route notes, or exceptions." />
                </>
              )}
              {actionType === 'close' && (
                <p className="text-sm text-gray-600">
                  Closing this movement finishes the record so it no longer counts as an active operational item.
                </p>
              )}
              {actionType === 'cancel' && (
                <TextAreaField label="Cancellation Reason" value={cancelForm.cancellation_reason} onChange={(value) => setCancelForm({ cancellation_reason: value })} placeholder="Explain why this movement was cancelled." />
              )}
              {actionError && (
                <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                  {actionError}
                </div>
              )}
            </div>
            <ModalFooter onCancel={closeActionModal} submitLabel={isActionSubmitting ? 'Saving...' : getActionSubmitLabel(actionType)} isSubmitting={isActionSubmitting} />
          </form>
        </ModalShell>
      )}
    </div>
  );
}

function StatCard({
  icon: Icon,
  label,
  value,
  tint,
}: {
  icon: typeof Truck;
  label: string;
  value: number;
  tint: string;
}) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5">
      <div className={`mb-3 flex h-10 w-10 items-center justify-center rounded-lg ${tint}`}>
        <Icon className="h-5 w-5" />
      </div>
      <div className="text-2xl font-semibold text-[#0F172A]">{value.toLocaleString()}</div>
      <div className="text-sm text-gray-600">{label}</div>
    </div>
  );
}

function ActionBadge({ action, onClick }: { action: LifecycleAction; onClick: () => void }) {
  const config: Record<LifecycleAction, { label: string; className: string; icon: typeof CheckCircle }> = {
    approve: { label: 'Approve', className: 'border-green-200 bg-green-50 text-green-700 hover:bg-green-100', icon: CheckCircle },
    check_out: { label: 'Check Out', className: 'border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100', icon: LogOut },
    start: { label: 'Start', className: 'border-cyan-200 bg-cyan-50 text-cyan-700 hover:bg-cyan-100', icon: Play },
    return: { label: 'Return', className: 'border-amber-200 bg-amber-50 text-amber-700 hover:bg-amber-100', icon: TimerReset },
    close: { label: 'Close', className: 'border-indigo-200 bg-indigo-50 text-indigo-700 hover:bg-indigo-100', icon: ShieldCheck },
    cancel: { label: 'Cancel', className: 'border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100', icon: XCircle },
  };
  const Icon = config[action].icon;
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex items-center gap-1 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-all ${config[action].className}`}
      title={config[action].label}
    >
      <Icon className="h-3.5 w-3.5" />
      {config[action].label}
    </button>
  );
}

function MovementTableSkeleton() {
  return (
    <div className="space-y-3 px-6 py-5">
      {Array.from({ length: 6 }).map((_, index) => (
        <div key={index} className="grid grid-cols-1 gap-3 rounded-xl border border-gray-200 p-4 md:grid-cols-8">
          {Array.from({ length: 8 }).map((__, innerIndex) => (
            <Skeleton key={innerIndex} className="h-5 w-full" />
          ))}
        </div>
      ))}
    </div>
  );
}

function ModalShell({
  title,
  subtitle,
  onClose,
  children,
  maxWidth,
}: {
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: ReactNode;
  maxWidth?: string;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4 py-6">
      <div className={`flex max-h-[92vh] w-full flex-col overflow-hidden rounded-xl border border-gray-200 bg-white shadow-2xl ${maxWidth || 'max-w-3xl'}`}>
        <div className="flex items-start justify-between border-b border-gray-200 px-6 py-4">
          <div>
            <h2 className="text-xl font-semibold text-[#0F172A]">{title}</h2>
            {subtitle && <p className="mt-1 text-sm text-gray-500">{subtitle}</p>}
          </div>
          <button type="button" onClick={onClose} className="rounded-lg p-2 transition-all hover:bg-gray-100">
            <XCircle className="h-5 w-5 text-gray-500" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

function ModalFooter({
  onCancel,
  submitLabel,
  isSubmitting,
}: {
  onCancel: () => void;
  submitLabel: string;
  isSubmitting: boolean;
}) {
  return (
    <div className="shrink-0 border-t border-gray-200 bg-gray-50 px-6 py-4">
      <div className="flex items-center justify-end gap-3">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-lg border border-gray-300 px-4 py-2.5 text-sm font-medium text-gray-700 transition-all hover:bg-white"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={isSubmitting}
          className="inline-flex items-center gap-2 rounded-lg bg-[#2563EB] px-4 py-2.5 text-sm font-medium text-white transition-all hover:bg-[#1d4ed8] disabled:cursor-not-allowed disabled:opacity-70"
        >
          {isSubmitting && <Loader2 className="h-4 w-4 animate-spin" />}
          {submitLabel}
        </button>
      </div>
    </div>
  );
}

function InputField({
  label,
  value,
  onChange,
  type = 'text',
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
}) {
  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-gray-700">{label}</label>
      <input
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
      />
    </div>
  );
}

function SelectField({
  label,
  value,
  onChange,
  children,
  disabled = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  children: ReactNode;
  disabled?: boolean;
}) {
  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-gray-700">{label}</label>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm focus:border-transparent focus:ring-2 focus:ring-[#2563EB] disabled:cursor-not-allowed disabled:bg-gray-50"
      >
        {children}
      </select>
    </div>
  );
}

function TextAreaField({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}) {
  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-gray-700">{label}</label>
      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="min-h-[120px] w-full rounded-lg border border-gray-300 px-4 py-3 text-sm focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
      />
    </div>
  );
}

function DetailSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h3 className="mb-3 text-sm font-semibold uppercase tracking-[0.18em] text-gray-500">{title}</h3>
      {children}
    </section>
  );
}

function DetailGrid({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-1 gap-3 md:grid-cols-2">{children}</div>;
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3">
      <div className="text-xs font-semibold uppercase tracking-[0.14em] text-gray-500">{label}</div>
      <div className="mt-1 text-sm font-medium text-[#0F172A]">{value}</div>
    </div>
  );
}

function getActionTitle(action: LifecycleAction) {
  switch (action) {
    case 'approve':
      return 'Approve Vehicle Movement';
    case 'check_out':
      return 'Check Out Vehicle Movement';
    case 'start':
      return 'Start Vehicle Movement';
    case 'return':
      return 'Return Vehicle Movement';
    case 'close':
      return 'Close Vehicle Movement';
    case 'cancel':
      return 'Cancel Vehicle Movement';
  }
}

function getActionSubmitLabel(action: LifecycleAction) {
  switch (action) {
    case 'approve':
      return 'Approve Movement';
    case 'check_out':
      return 'Check Out Movement';
    case 'start':
      return 'Start Movement';
    case 'return':
      return 'Save Return';
    case 'close':
      return 'Close Movement';
    case 'cancel':
      return 'Cancel Movement';
  }
}
