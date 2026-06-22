import { useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Loader2,
  Plus,
  RefreshCw,
  Settings2,
  ShieldAlert,
  TimerReset,
  Truck,
  UserCog,
  Wrench,
  XCircle,
} from 'lucide-react';
import { apiRequest, ApiRequestError } from '../../lib/api';
import { getStoredSessionUser } from '../../lib/auth-session';

type MaintenanceType =
  | 'repair'
  | 'servicing'
  | 'inspection'
  | 'oil_change'
  | 'tyre_change'
  | 'battery_replacement'
  | 'brake_service'
  | 'engine_service'
  | 'electrical_repair'
  | 'body_repair'
  | 'accident_repair'
  | 'roadworthy_inspection'
  | 'insurance_inspection'
  | 'other';
type MaintenancePriority = 'low' | 'medium' | 'high' | 'critical';
type MaintenanceStatus = 'pending' | 'approved' | 'in_progress' | 'waiting_parts' | 'completed' | 'cancelled';
type MaintenanceStage =
  | 'assigned_to_mechanic'
  | 'diagnosing'
  | 'waiting_parts'
  | 'parts_received'
  | 'repair_in_progress'
  | 'testing'
  | 'ready_for_driver_test'
  | 'driver_confirmed'
  | 'completed'
  | 'delayed';
type ProgressUpdateType =
  | 'follow_up'
  | 'mechanic_update'
  | 'parts_update'
  | 'cost_update'
  | 'delay'
  | 'ready_for_test'
  | 'general';
type ExpenseCategory =
  | 'fuel'
  | 'repairs'
  | 'servicing'
  | 'insurance'
  | 'roadworthy'
  | 'tyres'
  | 'battery'
  | 'car_wash'
  | 'driver_advance'
  | 'office'
  | 'other';
type PaymentMethod = 'cash' | 'momo_transfer' | 'bank_transfer' | 'card' | 'other';

interface UserSummary {
  id: string;
  full_name: string;
  role: 'owner' | 'admin' | 'driver';
  status?: string;
}

interface VehicleSummary {
  id: string;
  registration_number: string;
  make?: string | null;
  model?: string | null;
  status?: string | null;
}

interface FaultRecord {
  id: string;
  severity: MaintenancePriority;
  status: string;
  description: string;
  maintenance_job_id?: string | null;
  vehicle?: VehicleSummary | null;
  driver?: UserSummary | null;
  category?: { name: string } | null;
  component?: { name: string } | null;
}

interface ExpenseRecord {
  id: string;
  expense_title: string;
  amount: number;
  status: string;
}

interface FinanceAccount {
  id: string;
  account_name: string;
  account_type: 'bank' | 'momo' | 'cash' | 'reserve';
  status: 'active' | 'inactive';
}

interface MaintenanceProgressLog {
  id: string;
  maintenance_job_id: string;
  update_type: ProgressUpdateType;
  progress_note: string;
  current_stage: MaintenanceStage | null;
  next_action: string | null;
  next_follow_up_date: string | null;
  updated_at: string | null;
  updated_by_user?: UserSummary | null;
}

interface MaintenanceJob {
  id: string;
  vehicle_id: string;
  driver_id: string | null;
  fault_report_id: string | null;
  maintenance_type: MaintenanceType;
  title: string;
  description: string;
  priority: MaintenancePriority;
  vendor_name: string | null;
  vendor_contact: string | null;
  estimated_cost: number | null;
  actual_cost: number | null;
  expense_id: string | null;
  odometer_reading: number | null;
  start_date: string | null;
  target_completion_date: string | null;
  completion_date: string | null;
  status: MaintenanceStatus;
  notes: string | null;
  maintenance_coordinator_id: string | null;
  assigned_admin_name: string | null;
  assigned_at: string | null;
  current_stage: MaintenanceStage | null;
  next_action: string | null;
  next_follow_up_date: string | null;
  follow_up_overdue: boolean;
  is_overdue: boolean;
  last_progress_updated_at: string | null;
  vehicle?: VehicleSummary | null;
  driver?: UserSummary | null;
  fault_report?: FaultRecord | null;
  expense?: ExpenseRecord | null;
  maintenance_coordinator?: UserSummary | null;
}

interface MaintenanceJobsResponse {
  success: boolean;
  data: {
    jobs: MaintenanceJob[];
  };
}

interface MaintenanceJobMutationResponse {
  success: boolean;
  data: {
    job: MaintenanceJob;
  };
}

interface MaintenanceProgressResponse {
  success: boolean;
  data: {
    progress_logs: MaintenanceProgressLog[];
  };
}

interface MaintenanceProgressMutationResponse {
  success: boolean;
  data: {
    progress_log: MaintenanceProgressLog;
  };
}

interface FaultsResponse {
  success: boolean;
  data: {
    faults: FaultRecord[];
  };
}

interface VehiclesResponse {
  success: boolean;
  data: {
    vehicles: VehicleSummary[];
  };
}

interface DriversResponse {
  success: boolean;
  data: {
    drivers: UserSummary[];
  };
}

interface ExpensesResponse {
  success: boolean;
  data: {
    expenses: ExpenseRecord[];
  };
}

interface FinanceAccountsResponse {
  success: boolean;
  data: {
    accounts: FinanceAccount[];
  };
}

interface AccountabilityResponse {
  success: boolean;
  data: {
    admins: {
      admin: UserSummary;
    }[];
  };
}

interface MaintenanceFormState {
  vehicle_id: string;
  driver_id: string;
  maintenance_type: MaintenanceType;
  title: string;
  description: string;
  priority: MaintenancePriority;
  vendor_name: string;
  vendor_contact: string;
  estimated_cost: string;
  actual_cost: string;
  expense_id: string;
  odometer_reading: string;
  start_date: string;
  target_completion_date: string;
  completion_date: string;
  notes: string;
  maintenance_coordinator_id: string;
  current_stage: MaintenanceStage;
  next_action: string;
  next_follow_up_date: string;
  create_linked_expense: boolean;
  linked_expense_category: ExpenseCategory;
  linked_expense_amount: string;
  linked_expense_finance_account_id: string;
  linked_expense_payment_method: PaymentMethod;
  linked_expense_date: string;
}

interface ProgressFormState {
  update_type: ProgressUpdateType;
  progress_note: string;
  current_stage: MaintenanceStage;
  next_action: string;
  next_follow_up_date: string;
  estimated_cost: string;
  actual_cost: string;
}

const initialFormState: MaintenanceFormState = {
  vehicle_id: '',
  driver_id: '',
  maintenance_type: 'repair',
  title: '',
  description: '',
  priority: 'medium',
  vendor_name: '',
  vendor_contact: '',
  estimated_cost: '',
  actual_cost: '',
  expense_id: '',
  odometer_reading: '',
  start_date: new Date().toISOString().slice(0, 10),
  target_completion_date: '',
  completion_date: '',
  notes: '',
  maintenance_coordinator_id: '',
  current_stage: 'assigned_to_mechanic',
  next_action: '',
  next_follow_up_date: '',
  create_linked_expense: false,
  linked_expense_category: 'repairs',
  linked_expense_amount: '',
  linked_expense_finance_account_id: '',
  linked_expense_payment_method: 'cash',
  linked_expense_date: new Date().toISOString().slice(0, 10),
};

const initialProgressForm: ProgressFormState = {
  update_type: 'follow_up',
  progress_note: '',
  current_stage: 'diagnosing',
  next_action: '',
  next_follow_up_date: '',
  estimated_cost: '',
  actual_cost: '',
};

function formatCurrency(value: number | null | undefined) {
  return `GHS ${(value || 0).toLocaleString()}`;
}

function formatDate(value: string | null | undefined) {
  if (!value) {
    return 'Not available';
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleDateString();
}

function formatDateTime(value: string | null | undefined) {
  if (!value) {
    return 'Not available';
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString();
}

function formatLabel(value: string) {
  return value
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function statusClassName(status: MaintenanceStatus | string) {
  switch (status) {
    case 'completed':
      return 'border-green-200 bg-green-100 text-green-800';
    case 'in_progress':
      return 'border-blue-200 bg-blue-100 text-blue-800';
    case 'approved':
      return 'border-indigo-200 bg-indigo-100 text-indigo-800';
    case 'waiting_parts':
      return 'border-amber-200 bg-amber-100 text-amber-800';
    case 'cancelled':
      return 'border-rose-200 bg-rose-100 text-rose-800';
    default:
      return 'border-slate-200 bg-slate-100 text-slate-800';
  }
}

function priorityClassName(priority: MaintenancePriority | string) {
  switch (priority) {
    case 'critical':
      return 'border-red-200 bg-red-100 text-red-800';
    case 'high':
      return 'border-orange-200 bg-orange-100 text-orange-800';
    case 'medium':
      return 'border-amber-200 bg-amber-100 text-amber-800';
    default:
      return 'border-slate-200 bg-slate-100 text-slate-800';
  }
}

function stageClassName(stage: MaintenanceStage | string | null | undefined) {
  switch (stage) {
    case 'ready_for_driver_test':
      return 'border-cyan-200 bg-cyan-100 text-cyan-800';
    case 'delayed':
      return 'border-rose-200 bg-rose-100 text-rose-800';
    case 'driver_confirmed':
      return 'border-green-200 bg-green-100 text-green-800';
    case 'waiting_parts':
      return 'border-amber-200 bg-amber-100 text-amber-800';
    case 'repair_in_progress':
    case 'testing':
    case 'diagnosing':
      return 'border-blue-200 bg-blue-100 text-blue-800';
    default:
      return 'border-slate-200 bg-slate-100 text-slate-800';
  }
}

export default function Maintenance() {
  const currentUser = getStoredSessionUser();
  const currentRole = currentUser?.role || null;
  const isOwner = currentRole === 'owner';

  const [jobs, setJobs] = useState<MaintenanceJob[]>([]);
  const [faults, setFaults] = useState<FaultRecord[]>([]);
  const [vehicles, setVehicles] = useState<VehicleSummary[]>([]);
  const [drivers, setDrivers] = useState<UserSummary[]>([]);
  const [expenses, setExpenses] = useState<ExpenseRecord[]>([]);
  const [financeAccounts, setFinanceAccounts] = useState<FinanceAccount[]>([]);
  const [coordinators, setCoordinators] = useState<UserSummary[]>([]);
  const [dueFollowUps, setDueFollowUps] = useState<MaintenanceJob[]>([]);
  const [overdueFollowUps, setOverdueFollowUps] = useState<MaintenanceJob[]>([]);
  const [selectedTimelineJob, setSelectedTimelineJob] = useState<MaintenanceJob | null>(null);
  const [selectedProgressJob, setSelectedProgressJob] = useState<MaintenanceJob | null>(null);
  const [progressLogs, setProgressLogs] = useState<MaintenanceProgressLog[]>([]);
  const [timelineLoading, setTimelineLoading] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isActionSubmitting, setIsActionSubmitting] = useState(false);
  const [pageError, setPageError] = useState('');
  const [formError, setFormError] = useState('');
  const [actionError, setActionError] = useState('');
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [editingJob, setEditingJob] = useState<MaintenanceJob | null>(null);
  const [statusTarget, setStatusTarget] = useState<MaintenanceJob | null>(null);
  const [formState, setFormState] = useState<MaintenanceFormState>(initialFormState);
  const [progressForm, setProgressForm] = useState<ProgressFormState>(initialProgressForm);
  const [statusForm, setStatusForm] = useState({
    status: 'approved' as MaintenanceStatus,
    notes: '',
    actual_cost: '',
    completion_date: '',
    vendor_name: '',
    vendor_contact: '',
  });

  const getSettledData = <T,>(result: PromiseSettledResult<T>, fallback: T): T =>
    result.status === 'fulfilled' ? result.value : fallback;

  const getSettledError = (result: PromiseSettledResult<unknown>) =>
    result.status === 'rejected'
      ? result.reason instanceof ApiRequestError
        ? result.reason.message
        : 'Unable to load some maintenance data right now.'
      : null;

  const loadMaintenance = async () => {
    setIsLoading(true);
    setPageError('');
    try {
      const [
        jobsResult,
        faultsResult,
        vehiclesResult,
        driversResult,
        expensesResult,
        financeAccountsResult,
        coordinatorsResult,
        dueResult,
        overdueResult,
      ] = await Promise.allSettled([
        apiRequest<MaintenanceJobsResponse>('/maintenance', { cacheTtlMs: 10000, timeoutMs: 15000 }),
        apiRequest<FaultsResponse>('/faults', { cacheTtlMs: 10000, timeoutMs: 15000 }),
        apiRequest<VehiclesResponse>('/vehicles', { cacheTtlMs: 10000, timeoutMs: 15000 }),
        apiRequest<DriversResponse>('/drivers', { cacheTtlMs: 10000, timeoutMs: 15000 }),
        apiRequest<ExpensesResponse>('/expenses', { cacheTtlMs: 10000, timeoutMs: 15000 }),
        apiRequest<FinanceAccountsResponse>('/finance/accounts', { cacheTtlMs: 10000, timeoutMs: 15000 }),
        apiRequest<AccountabilityResponse>('/admins/accountability', { cacheTtlMs: 10000, timeoutMs: 15000 }),
        apiRequest<MaintenanceJobsResponse>('/maintenance/follow-ups/due', { cacheTtlMs: 10000, timeoutMs: 15000 }),
        apiRequest<MaintenanceJobsResponse>('/maintenance/follow-ups/overdue', { cacheTtlMs: 10000, timeoutMs: 15000 }),
      ]);

      const jobsResponse = getSettledData<MaintenanceJobsResponse | null>(jobsResult, null);
      const faultsResponse = getSettledData<FaultsResponse | null>(faultsResult, null);
      const vehiclesResponse = getSettledData<VehiclesResponse | null>(vehiclesResult, null);
      const driversResponse = getSettledData<DriversResponse | null>(driversResult, null);
      const expensesResponse = getSettledData<ExpensesResponse | null>(expensesResult, null);
      const financeAccountsResponse = getSettledData<FinanceAccountsResponse | null>(financeAccountsResult, null);
      const coordinatorsResponse = getSettledData<AccountabilityResponse | null>(coordinatorsResult, null);
      const dueResponse = getSettledData<MaintenanceJobsResponse | null>(dueResult, null);
      const overdueResponse = getSettledData<MaintenanceJobsResponse | null>(overdueResult, null);
      const errors = [
        getSettledError(jobsResult),
        getSettledError(faultsResult),
        getSettledError(vehiclesResult),
        getSettledError(driversResult),
        getSettledError(expensesResult),
        getSettledError(financeAccountsResult),
        getSettledError(coordinatorsResult),
        getSettledError(dueResult),
        getSettledError(overdueResult),
      ];

      const nextCoordinators = (coordinatorsResponse?.data?.admins || [])
        .map((entry) => entry.admin)
        .filter(Boolean);

      setJobs(Array.isArray(jobsResponse?.data?.jobs) ? jobsResponse.data.jobs : []);
      setFaults(Array.isArray(faultsResponse?.data?.faults) ? faultsResponse.data.faults : []);
      setVehicles(Array.isArray(vehiclesResponse?.data?.vehicles) ? vehiclesResponse.data.vehicles : []);
      setDrivers(Array.isArray(driversResponse?.data?.drivers) ? driversResponse.data.drivers : []);
      setExpenses(Array.isArray(expensesResponse?.data?.expenses) ? expensesResponse.data.expenses : []);
      setFinanceAccounts(Array.isArray(financeAccountsResponse?.data?.accounts) ? financeAccountsResponse.data.accounts : []);
      setCoordinators(nextCoordinators);
      setDueFollowUps(Array.isArray(dueResponse?.data?.jobs) ? dueResponse.data.jobs : []);
      setOverdueFollowUps(Array.isArray(overdueResponse?.data?.jobs) ? overdueResponse.data.jobs : []);

      setFormState((current) => ({
        ...current,
        vehicle_id: current.vehicle_id || vehiclesResponse?.data?.vehicles?.[0]?.id || '',
        driver_id: current.driver_id || driversResponse?.data?.drivers?.find((driver) => driver.role === 'driver')?.id || '',
        maintenance_coordinator_id:
          current.maintenance_coordinator_id || nextCoordinators.find((coordinator) => coordinator.id === currentUser?.id)?.id || nextCoordinators[0]?.id || '',
        linked_expense_finance_account_id:
          current.linked_expense_finance_account_id || financeAccountsResponse?.data?.accounts?.find((account) => account.status === 'active')?.id || '',
      }));

      const primaryError = getSettledError(jobsResult);
      if (primaryError) {
        setPageError(primaryError);
      }
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void loadMaintenance();
  }, []);

  const dashboardTotals = useMemo(() => {
    return jobs.reduce(
      (summary, job) => {
        if (['pending', 'approved', 'in_progress', 'waiting_parts'].includes(job.status)) {
          summary.open += 1;
        }
        if (job.status === 'in_progress') {
          summary.inProgress += 1;
        }
        if (job.status === 'waiting_parts') {
          summary.waitingParts += 1;
        }
        if (job.priority === 'critical' && job.status !== 'completed' && job.status !== 'cancelled') {
          summary.critical += 1;
        }
        if (job.status === 'completed') {
          summary.completed += 1;
        }
        if (job.is_overdue) {
          summary.overdue += 1;
        }
        return summary;
      },
      {
        open: 0,
        inProgress: 0,
        waitingParts: 0,
        critical: 0,
        completed: 0,
        overdue: 0,
      },
    );
  }, [jobs]);

  const approvedFaultsReady = useMemo(
    () => faults.filter((fault) => fault.status === 'approved' && !fault.maintenance_job_id),
    [faults],
  );

  const ownerPerformance = useMemo(() => {
    const performance = jobs.reduce<Record<string, { name: string; total: number; overdue: number; critical: number }>>(
      (accumulator, job) => {
        const name = job.assigned_admin_name || 'Unassigned';
        if (!accumulator[name]) {
          accumulator[name] = { name, total: 0, overdue: 0, critical: 0 };
        }
        accumulator[name].total += 1;
        if (job.follow_up_overdue || job.is_overdue) {
          accumulator[name].overdue += 1;
        }
        if (job.priority === 'critical' && (job.follow_up_overdue || job.is_overdue)) {
          accumulator[name].critical += 1;
        }
        return accumulator;
      },
      {},
    );
    return Object.values(performance).sort((left, right) => right.overdue - left.overdue || right.total - left.total);
  }, [jobs]);

  const closeCreateModal = () => {
    setShowCreateModal(false);
    setEditingJob(null);
    setFormError('');
    setFormState({
      ...initialFormState,
      vehicle_id: vehicles[0]?.id || '',
      driver_id: drivers.find((driver) => driver.role === 'driver')?.id || '',
      maintenance_coordinator_id: coordinators.find((coordinator) => coordinator.id === currentUser?.id)?.id || coordinators[0]?.id || '',
      linked_expense_finance_account_id: financeAccounts.find((account) => account.status === 'active')?.id || '',
    });
  };

  const openEditModal = (job: MaintenanceJob) => {
    setEditingJob(job);
    setFormError('');
    setFormState({
      vehicle_id: job.vehicle_id || '',
      driver_id: job.driver_id || '',
      maintenance_type: job.maintenance_type,
      title: job.title,
      description: job.description,
      priority: job.priority,
      vendor_name: job.vendor_name || '',
      vendor_contact: job.vendor_contact || '',
      estimated_cost: job.estimated_cost != null ? String(job.estimated_cost) : '',
      actual_cost: job.actual_cost != null ? String(job.actual_cost) : '',
      expense_id: job.expense_id || '',
      odometer_reading: job.odometer_reading != null ? String(job.odometer_reading) : '',
      start_date: job.start_date || '',
      target_completion_date: job.target_completion_date || '',
      completion_date: job.completion_date || '',
      notes: job.notes || '',
      maintenance_coordinator_id: job.maintenance_coordinator_id || '',
      current_stage: job.current_stage || 'assigned_to_mechanic',
      next_action: job.next_action || '',
      next_follow_up_date: job.next_follow_up_date || '',
      create_linked_expense: false,
      linked_expense_category: 'repairs',
      linked_expense_amount: job.estimated_cost != null ? String(job.estimated_cost) : '',
      linked_expense_finance_account_id: financeAccounts.find((account) => account.status === 'active')?.id || '',
      linked_expense_payment_method: 'cash',
      linked_expense_date: job.start_date || new Date().toISOString().slice(0, 10),
    });
    setShowCreateModal(true);
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setIsSubmitting(true);
    setFormError('');

    const payload: Record<string, unknown> = {
      vehicle_id: formState.vehicle_id,
      driver_id: formState.driver_id || null,
      maintenance_type: formState.maintenance_type,
      title: formState.title,
      description: formState.description,
      priority: formState.priority,
      vendor_name: formState.vendor_name,
      vendor_contact: formState.vendor_contact,
      estimated_cost: formState.estimated_cost ? Number(formState.estimated_cost) : null,
      actual_cost: formState.actual_cost ? Number(formState.actual_cost) : null,
      expense_id: formState.expense_id || null,
      odometer_reading: formState.odometer_reading ? Number(formState.odometer_reading) : null,
      start_date: formState.start_date || null,
      target_completion_date: formState.target_completion_date || null,
      completion_date: formState.completion_date || null,
      notes: formState.notes,
      maintenance_coordinator_id: formState.maintenance_coordinator_id || null,
      current_stage: formState.current_stage,
      next_action: formState.next_action || null,
      next_follow_up_date: formState.next_follow_up_date || null,
    };

    if (formState.create_linked_expense) {
      payload.create_linked_expense = {
        expense_category: formState.linked_expense_category,
        amount: formState.linked_expense_amount ? Number(formState.linked_expense_amount) : null,
        finance_account_id: formState.linked_expense_finance_account_id,
        payment_method: formState.linked_expense_payment_method,
        expense_date: formState.linked_expense_date,
        notes: `Linked from maintenance job: ${formState.title}`,
      };
    }

    try {
      if (editingJob) {
        await apiRequest<MaintenanceJobMutationResponse>(`/maintenance/${editingJob.id}`, {
          method: 'PATCH',
          body: JSON.stringify(payload),
        });
      } else {
        await apiRequest<MaintenanceJobMutationResponse>('/maintenance', {
          method: 'POST',
          body: JSON.stringify(payload),
        });
      }
      closeCreateModal();
      await loadMaintenance();
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setFormError(error.message);
      } else {
        setFormError('Unable to save maintenance job right now.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleConvertFault = async (faultId: string) => {
    setActionError('');
    setIsActionSubmitting(true);
    try {
      await apiRequest<MaintenanceJobMutationResponse>(`/faults/${faultId}/convert-to-maintenance`, {
        method: 'POST',
      });
      await loadMaintenance();
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setActionError(error.message);
      } else {
        setActionError('Unable to convert fault to maintenance right now.');
      }
    } finally {
      setIsActionSubmitting(false);
    }
  };

  const openProgressModal = (job: MaintenanceJob) => {
    setSelectedProgressJob(job);
    setActionError('');
    setProgressForm({
      update_type: 'follow_up',
      progress_note: '',
      current_stage: job.current_stage || 'diagnosing',
      next_action: job.next_action || '',
      next_follow_up_date: job.next_follow_up_date || '',
      estimated_cost: job.estimated_cost != null ? String(job.estimated_cost) : '',
      actual_cost: job.actual_cost != null ? String(job.actual_cost) : '',
    });
  };

  const closeProgressModal = () => {
    setSelectedProgressJob(null);
    setActionError('');
  };

  const handleProgressSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!selectedProgressJob) {
      return;
    }
    setActionError('');
    setIsActionSubmitting(true);
    try {
      await apiRequest<MaintenanceProgressMutationResponse>(`/maintenance/${selectedProgressJob.id}/progress`, {
        method: 'POST',
        body: JSON.stringify({
          update_type: progressForm.update_type,
          progress_note: progressForm.progress_note,
          current_stage: progressForm.current_stage,
          next_action: progressForm.next_action || null,
          next_follow_up_date: progressForm.next_follow_up_date || null,
          estimated_cost: progressForm.estimated_cost ? Number(progressForm.estimated_cost) : null,
          actual_cost: progressForm.actual_cost ? Number(progressForm.actual_cost) : null,
        }),
      });
      closeProgressModal();
      await loadMaintenance();
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setActionError(error.message);
      } else {
        setActionError('Unable to add maintenance progress right now.');
      }
    } finally {
      setIsActionSubmitting(false);
    }
  };

  const openStatusModal = (job: MaintenanceJob) => {
    setStatusTarget(job);
    setActionError('');
    setStatusForm({
      status:
        job.status === 'pending'
          ? 'approved'
          : job.status === 'approved'
            ? 'in_progress'
            : job.status === 'in_progress'
              ? 'waiting_parts'
              : 'completed',
      notes: job.notes || '',
      actual_cost: job.actual_cost != null ? String(job.actual_cost) : '',
      completion_date: job.completion_date || '',
      vendor_name: job.vendor_name || '',
      vendor_contact: job.vendor_contact || '',
    });
  };

  const closeStatusModal = () => {
    setStatusTarget(null);
    setActionError('');
  };

  const handleStatusSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!statusTarget) {
      return;
    }
    setActionError('');
    setIsActionSubmitting(true);
    try {
      await apiRequest<MaintenanceJobMutationResponse>(`/maintenance/${statusTarget.id}/status`, {
        method: 'PATCH',
        body: JSON.stringify({
          status: statusForm.status,
          notes: statusForm.notes,
          actual_cost: statusForm.actual_cost ? Number(statusForm.actual_cost) : null,
          completion_date: statusForm.completion_date || null,
          vendor_name: statusForm.vendor_name,
          vendor_contact: statusForm.vendor_contact,
        }),
      });
      closeStatusModal();
      await loadMaintenance();
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setActionError(error.message);
      } else {
        setActionError('Unable to update maintenance status right now.');
      }
    } finally {
      setIsActionSubmitting(false);
    }
  };

  const handleAssignCoordinator = async (job: MaintenanceJob, coordinatorId: string) => {
    setActionError('');
    setIsActionSubmitting(true);
    try {
      await apiRequest<MaintenanceJobMutationResponse>(`/maintenance/${job.id}/assign-coordinator`, {
        method: 'PATCH',
        body: JSON.stringify({
          maintenance_coordinator_id: coordinatorId,
        }),
      });
      await loadMaintenance();
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setActionError(error.message);
      } else {
        setActionError('Unable to assign maintenance coordinator right now.');
      }
    } finally {
      setIsActionSubmitting(false);
    }
  };

  const openTimelineModal = async (job: MaintenanceJob) => {
    setSelectedTimelineJob(job);
    setTimelineLoading(true);
    setActionError('');
    try {
      const response = await apiRequest<MaintenanceProgressResponse>(`/maintenance/${job.id}/progress`);
      setProgressLogs(Array.isArray(response.data?.progress_logs) ? response.data.progress_logs : []);
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setActionError(error.message);
      } else {
        setActionError('Unable to load the maintenance timeline right now.');
      }
    } finally {
      setTimelineLoading(false);
    }
  };

  const closeTimelineModal = () => {
    setSelectedTimelineJob(null);
    setProgressLogs([]);
    setActionError('');
  };

  return (
    <div className="space-y-6 p-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-[#0F172A]">Maintenance Jobs</h1>
          <p className="mt-1 text-gray-600">
            Track job ownership, progress updates, follow-ups, driver testing, and overdue maintenance without leaving the maintenance workflow.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={() => void loadMaintenance()}
            className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2.5 font-medium text-gray-700 transition-all hover:bg-gray-50"
          >
            <RefreshCw className="h-4 w-4" />
            Refresh
          </button>
          <button
            onClick={() => {
              setEditingJob(null);
              setFormError('');
              setShowCreateModal(true);
            }}
            className="inline-flex items-center gap-2 rounded-lg bg-[#2563EB] px-4 py-2.5 font-medium text-white transition-all hover:bg-[#1d4ed8]"
          >
            <Plus className="h-4 w-4" />
            Create Maintenance Job
          </button>
        </div>
      </div>

      {pageError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {pageError}
        </div>
      )}

      {actionError && !selectedProgressJob && !statusTarget && !selectedTimelineJob && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          {actionError}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3 xl:grid-cols-6">
        <SummaryCard label="Open Jobs" value={dashboardTotals.open} icon={Wrench} tone="slate" />
        <SummaryCard label="In Progress" value={dashboardTotals.inProgress} icon={Truck} tone="blue" />
        <SummaryCard label="Waiting Parts" value={dashboardTotals.waitingParts} icon={Clock3} tone="amber" />
        <SummaryCard label="Critical Jobs" value={dashboardTotals.critical} icon={ShieldAlert} tone="rose" />
        <SummaryCard label="Completed Jobs" value={dashboardTotals.completed} icon={CheckCircle2} tone="green" />
        <SummaryCard label="Overdue Jobs" value={dashboardTotals.overdue} icon={TimerReset} tone="rose" />
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <FollowUpPanel
          title={isOwner ? 'Due Today Follow-ups' : 'My Maintenance Follow-ups Due Today'}
          subtitle="Jobs that need attention today based on the next follow-up date."
          jobs={dueFollowUps}
          emptyMessage="No maintenance follow-ups due today."
          onProgress={openProgressModal}
          onTimeline={(job) => void openTimelineModal(job)}
        />
        <FollowUpPanel
          title={isOwner ? 'Overdue Follow-ups' : 'My Overdue Follow-ups'}
          subtitle="Jobs where the next follow-up or expected completion has already passed."
          jobs={overdueFollowUps}
          emptyMessage="No overdue maintenance follow-ups."
          onProgress={openProgressModal}
          onTimeline={(job) => void openTimelineModal(job)}
        />
      </div>

      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
        <div className="border-b border-gray-200 px-6 py-4">
          <h2 className="text-lg font-semibold text-[#0F172A]">Approved Faults Ready For Conversion</h2>
          <p className="mt-1 text-sm text-gray-600">Convert approved faults into maintenance jobs and immediately assign ownership.</p>
        </div>
        {isLoading ? (
          <div className="flex items-center justify-center gap-3 px-6 py-12 text-gray-500">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span>Loading approved faults...</span>
          </div>
        ) : approvedFaultsReady.length === 0 ? (
          <div className="px-6 py-12 text-center text-gray-500">No approved faults waiting for maintenance conversion.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  {['Vehicle', 'Driver', 'Category', 'Component', 'Severity', 'Action'].map((header) => (
                    <th key={header} className="px-6 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">
                      {header}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {approvedFaultsReady.map((fault) => (
                  <tr key={fault.id} className={fault.severity === 'critical' ? 'bg-red-50/50' : 'hover:bg-gray-50'}>
                    <td className="px-6 py-4 text-sm font-medium text-[#0F172A]">{fault.vehicle?.registration_number || 'Vehicle'}</td>
                    <td className="px-6 py-4 text-sm text-gray-700">{fault.driver?.full_name || 'Driver'}</td>
                    <td className="px-6 py-4 text-sm text-gray-700">{fault.category?.name || 'Category'}</td>
                    <td className="px-6 py-4 text-sm text-gray-700">{fault.component?.name || 'Component'}</td>
                    <td className="px-6 py-4 text-sm">
                      <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${priorityClassName(fault.severity)}`}>
                        {formatLabel(fault.severity)}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-sm">
                      <button
                        onClick={() => void handleConvertFault(fault.id)}
                        disabled={isActionSubmitting}
                        className="inline-flex items-center gap-2 rounded-lg bg-[#2563EB] px-3 py-2 text-xs font-medium text-white transition-all hover:bg-[#1d4ed8] disabled:cursor-not-allowed disabled:opacity-70"
                      >
                        {isActionSubmitting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Wrench className="h-3.5 w-3.5" />}
                        Convert To Maintenance
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
        <div className="border-b border-gray-200 px-6 py-4">
          <h2 className="text-lg font-semibold text-[#0F172A]">Maintenance Jobs</h2>
          <p className="mt-1 text-sm text-gray-600">Track current stage, coordinator ownership, next action, and follow-up health for every job.</p>
        </div>
        {isLoading ? (
          <div className="flex items-center justify-center gap-3 px-6 py-16 text-gray-500">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span>Loading maintenance jobs...</span>
          </div>
        ) : jobs.length === 0 ? (
          <div className="px-6 py-14 text-center text-gray-500">No maintenance jobs recorded yet.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  {['Job', 'Vehicle', 'Coordinator', 'Stage', 'Next Action', 'Follow-up', 'Status', 'Actions'].map((header) => (
                    <th key={header} className="px-6 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">
                      {header}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {jobs.map((job) => (
                  <tr key={job.id} className={job.priority === 'critical' ? 'bg-red-50/40' : 'hover:bg-gray-50'}>
                    <td className="px-6 py-4">
                      <div className="text-sm font-semibold text-[#0F172A]">{job.title}</div>
                      <div className="mt-1 flex flex-wrap gap-2">
                        <span className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-medium ${statusClassName(job.status)}`}>
                          {formatLabel(job.status)}
                        </span>
                        <span className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-medium ${stageClassName(job.current_stage)}`}>
                          {formatLabel(job.current_stage || 'assigned_to_mechanic')}
                        </span>
                      </div>
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-700">
                      <div>{job.vehicle?.registration_number || 'Vehicle'}</div>
                      <div className="text-xs text-gray-500">{job.driver?.full_name || 'No driver linked'}</div>
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-700">
                      <div>{job.assigned_admin_name || 'Unassigned'}</div>
                      <select
                        value={job.maintenance_coordinator_id || ''}
                        onChange={(event) => void handleAssignCoordinator(job, event.target.value)}
                        className="mt-2 w-full rounded-lg border border-gray-300 px-2 py-1.5 text-xs focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                      >
                        <option value="">Choose coordinator...</option>
                        {coordinators.map((coordinator) => (
                          <option key={coordinator.id} value={coordinator.id}>
                            {coordinator.full_name}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-700">
                      <div>{formatLabel(job.current_stage || 'assigned_to_mechanic')}</div>
                      <div className="text-xs text-gray-500">Updated {formatDateTime(job.last_progress_updated_at)}</div>
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-700">
                      <div>{job.next_action || 'No next action set'}</div>
                      <div className="text-xs text-gray-500">{job.notes || 'No coordinator note'}</div>
                    </td>
                    <td className="px-6 py-4 text-sm">
                      <div className={job.follow_up_overdue || job.is_overdue ? 'text-red-700' : 'text-gray-700'}>
                        {formatDate(job.next_follow_up_date)}
                      </div>
                      <div className="mt-1 flex flex-wrap gap-2">
                        {job.follow_up_overdue && (
                          <span className="inline-flex rounded-full border border-red-200 bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">
                            Follow-up overdue
                          </span>
                        )}
                        {job.is_overdue && (
                          <span className="inline-flex rounded-full border border-rose-200 bg-rose-100 px-2 py-0.5 text-xs font-medium text-rose-700">
                            Completion overdue
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-700">
                      <div>{formatLabel(job.status)}</div>
                      <div className="text-xs text-gray-500">Target {formatDate(job.target_completion_date)}</div>
                    </td>
                    <td className="px-6 py-4 text-sm">
                      <div className="flex flex-wrap gap-2">
                        <button
                          onClick={() => openProgressModal(job)}
                          className="inline-flex items-center gap-1 rounded-lg border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-100"
                        >
                          <Plus className="h-3.5 w-3.5" />
                          Add Progress
                        </button>
                        <button
                          onClick={() => void openTimelineModal(job)}
                          className="inline-flex items-center gap-1 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
                        >
                          <Clock3 className="h-3.5 w-3.5" />
                          Timeline
                        </button>
                        <button
                          onClick={() => openStatusModal(job)}
                          className="inline-flex items-center gap-1 rounded-lg border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-800 hover:bg-amber-100"
                        >
                          Update Status
                        </button>
                        <button
                          onClick={() => openEditModal(job)}
                          className="inline-flex items-center gap-1 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
                        >
                          Edit
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {isOwner && (
        <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
          <div className="rounded-xl border border-gray-200 bg-white p-5">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-red-100 text-red-600">
                <AlertTriangle className="h-5 w-5" />
              </div>
              <div>
                <h3 className="text-base font-semibold text-[#0F172A]">Critical Delayed Jobs</h3>
                <p className="text-sm text-gray-500">Owner oversight on high-risk overdue maintenance.</p>
              </div>
            </div>
            <div className="mt-4 space-y-3">
              {jobs.filter((job) => job.priority === 'critical' && (job.follow_up_overdue || job.is_overdue)).length === 0 ? (
                <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 px-4 py-4 text-sm text-gray-500">
                  No critical delayed maintenance jobs right now.
                </div>
              ) : (
                jobs
                  .filter((job) => job.priority === 'critical' && (job.follow_up_overdue || job.is_overdue))
                  .map((job) => (
                    <div key={job.id} className="rounded-lg border border-red-200 bg-red-50 px-4 py-4">
                      <div className="font-medium text-red-900">{job.title}</div>
                      <div className="mt-1 text-sm text-red-700">
                        Responsible: {job.assigned_admin_name || 'Unassigned'} • Follow-up {formatDate(job.next_follow_up_date)}
                      </div>
                    </div>
                  ))
              )}
            </div>
          </div>
          <div className="rounded-xl border border-gray-200 bg-white p-5">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-100 text-blue-600">
                <UserCog className="h-5 w-5" />
              </div>
              <div>
                <h3 className="text-base font-semibold text-[#0F172A]">Admin Follow-up Performance</h3>
                <p className="text-sm text-gray-500">See who owns maintenance follow-up and where delays are building.</p>
              </div>
            </div>
            <div className="mt-4 space-y-3">
              {ownerPerformance.length === 0 ? (
                <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 px-4 py-4 text-sm text-gray-500">
                  No coordinator performance data available yet.
                </div>
              ) : (
                ownerPerformance.map((entry) => (
                  <div key={entry.name} className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-4">
                    <div className="flex items-center justify-between">
                      <div className="font-medium text-[#0F172A]">{entry.name}</div>
                      <div className="text-sm text-gray-600">{entry.total} jobs</div>
                    </div>
                    <div className="mt-2 flex flex-wrap gap-2 text-xs">
                      <span className="rounded-full border border-amber-200 bg-amber-100 px-2 py-0.5 font-medium text-amber-800">
                        {entry.overdue} overdue
                      </span>
                      <span className="rounded-full border border-red-200 bg-red-100 px-2 py-0.5 font-medium text-red-700">
                        {entry.critical} critical delayed
                      </span>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}

      {showCreateModal && (
        <ModalShell title={editingJob ? 'Edit Maintenance Job' : 'Create Maintenance Job'} onClose={closeCreateModal} maxWidth="max-w-5xl">
          <form onSubmit={handleSubmit} className="flex h-full flex-col">
            <div className="flex-1 space-y-5 overflow-y-auto px-6 py-5">
              {formError && (
                <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                  {formError}
                </div>
              )}

              <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
                <SelectField label="Vehicle" value={formState.vehicle_id} onChange={(value) => setFormState((current) => ({ ...current, vehicle_id: value }))}>
                  <option value="">Choose vehicle...</option>
                  {vehicles.map((vehicle) => (
                    <option key={vehicle.id} value={vehicle.id}>
                      {vehicle.registration_number} - {[vehicle.make, vehicle.model].filter(Boolean).join(' ')}
                    </option>
                  ))}
                </SelectField>
                <SelectField label="Driver" value={formState.driver_id} onChange={(value) => setFormState((current) => ({ ...current, driver_id: value }))}>
                  <option value="">No driver linked</option>
                  {drivers.map((driver) => (
                    <option key={driver.id} value={driver.id}>
                      {driver.full_name}
                    </option>
                  ))}
                </SelectField>
                <SelectField label="Maintenance Type" value={formState.maintenance_type} onChange={(value) => setFormState((current) => ({ ...current, maintenance_type: value as MaintenanceType }))}>
                  {[
                    'repair',
                    'servicing',
                    'inspection',
                    'oil_change',
                    'tyre_change',
                    'battery_replacement',
                    'brake_service',
                    'engine_service',
                    'electrical_repair',
                    'body_repair',
                    'accident_repair',
                    'roadworthy_inspection',
                    'insurance_inspection',
                    'other',
                  ].map((type) => (
                    <option key={type} value={type}>
                      {formatLabel(type)}
                    </option>
                  ))}
                </SelectField>
                <SelectField label="Priority" value={formState.priority} onChange={(value) => setFormState((current) => ({ ...current, priority: value as MaintenancePriority }))}>
                  {['low', 'medium', 'high', 'critical'].map((priority) => (
                    <option key={priority} value={priority}>
                      {formatLabel(priority)}
                    </option>
                  ))}
                </SelectField>
              </div>

              <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                <InputField label="Title" value={formState.title} onChange={(value) => setFormState((current) => ({ ...current, title: value }))} />
                <SelectField label="Maintenance Coordinator" value={formState.maintenance_coordinator_id} onChange={(value) => setFormState((current) => ({ ...current, maintenance_coordinator_id: value }))}>
                  <option value="">Choose coordinator...</option>
                  {coordinators.map((coordinator) => (
                    <option key={coordinator.id} value={coordinator.id}>
                      {coordinator.full_name}
                    </option>
                  ))}
                </SelectField>
                <SelectField label="Current Stage" value={formState.current_stage} onChange={(value) => setFormState((current) => ({ ...current, current_stage: value as MaintenanceStage }))}>
                  {[
                    'assigned_to_mechanic',
                    'diagnosing',
                    'waiting_parts',
                    'parts_received',
                    'repair_in_progress',
                    'testing',
                    'ready_for_driver_test',
                    'driver_confirmed',
                    'completed',
                    'delayed',
                  ].map((stage) => (
                    <option key={stage} value={stage}>
                      {formatLabel(stage)}
                    </option>
                  ))}
                </SelectField>
              </div>

              <TextAreaField label="Description" value={formState.description} onChange={(value) => setFormState((current) => ({ ...current, description: value }))} minHeight="min-h-[110px]" />

              <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
                <InputField label="Vendor Name" value={formState.vendor_name} onChange={(value) => setFormState((current) => ({ ...current, vendor_name: value }))} />
                <InputField label="Vendor Contact" value={formState.vendor_contact} onChange={(value) => setFormState((current) => ({ ...current, vendor_contact: value }))} />
                <InputField label="Estimated Cost" type="number" value={formState.estimated_cost} onChange={(value) => setFormState((current) => ({ ...current, estimated_cost: value }))} />
                <InputField label="Actual Cost" type="number" value={formState.actual_cost} onChange={(value) => setFormState((current) => ({ ...current, actual_cost: value }))} />
                <InputField label="Odometer Reading" type="number" value={formState.odometer_reading} onChange={(value) => setFormState((current) => ({ ...current, odometer_reading: value }))} />
                <InputField label="Start Date" type="date" value={formState.start_date} onChange={(value) => setFormState((current) => ({ ...current, start_date: value }))} />
                <InputField label="Target Completion" type="date" value={formState.target_completion_date} onChange={(value) => setFormState((current) => ({ ...current, target_completion_date: value }))} />
                <InputField label="Next Follow-up Date" type="date" value={formState.next_follow_up_date} onChange={(value) => setFormState((current) => ({ ...current, next_follow_up_date: value }))} />
              </div>

              <InputField label="Next Action" value={formState.next_action} onChange={(value) => setFormState((current) => ({ ...current, next_action: value }))} />

              <SelectField label="Linked Expense" value={formState.expense_id} onChange={(value) => setFormState((current) => ({ ...current, expense_id: value }))}>
                <option value="">No linked expense</option>
                {expenses.map((expense) => (
                  <option key={expense.id} value={expense.id}>
                    {expense.expense_title} - {formatCurrency(expense.amount)} ({formatLabel(expense.status)})
                  </option>
                ))}
              </SelectField>

              <div className="rounded-lg border border-blue-100 bg-blue-50 px-4 py-3">
                <label className="flex items-start gap-3">
                  <input
                    type="checkbox"
                    checked={formState.create_linked_expense}
                    onChange={(event) =>
                      setFormState((current) => ({
                        ...current,
                        create_linked_expense: event.target.checked,
                        expense_id: event.target.checked ? '' : current.expense_id,
                      }))
                    }
                    className="mt-1 h-4 w-4 rounded border-gray-300 text-[#2563EB] focus:ring-[#2563EB]"
                  />
                  <div>
                    <div className="font-medium text-blue-900">Create linked expense from this maintenance job</div>
                    <div className="mt-1 text-sm text-blue-700">Use this when you need an expense record created immediately instead of linking an existing one.</div>
                  </div>
                </label>
              </div>

              {formState.create_linked_expense && (
                <div className="grid grid-cols-1 gap-4 rounded-xl border border-gray-200 bg-gray-50 p-4 md:grid-cols-2 xl:grid-cols-5">
                  <SelectField label="Expense Category" value={formState.linked_expense_category} onChange={(value) => setFormState((current) => ({ ...current, linked_expense_category: value as ExpenseCategory }))}>
                    {['repairs', 'servicing', 'tyres', 'battery', 'insurance', 'roadworthy', 'other'].map((category) => (
                      <option key={category} value={category}>
                        {formatLabel(category)}
                      </option>
                    ))}
                  </SelectField>
                  <InputField label="Expense Amount" type="number" value={formState.linked_expense_amount} onChange={(value) => setFormState((current) => ({ ...current, linked_expense_amount: value }))} />
                  <SelectField label="Finance Account" value={formState.linked_expense_finance_account_id} onChange={(value) => setFormState((current) => ({ ...current, linked_expense_finance_account_id: value }))}>
                    <option value="">Choose finance account...</option>
                    {financeAccounts.filter((account) => account.status === 'active').map((account) => (
                      <option key={account.id} value={account.id}>
                        {account.account_name} - {formatLabel(account.account_type)}
                      </option>
                    ))}
                  </SelectField>
                  <SelectField label="Payment Method" value={formState.linked_expense_payment_method} onChange={(value) => setFormState((current) => ({ ...current, linked_expense_payment_method: value as PaymentMethod }))}>
                    {['cash', 'momo_transfer', 'bank_transfer', 'card', 'other'].map((method) => (
                      <option key={method} value={method}>
                        {formatLabel(method)}
                      </option>
                    ))}
                  </SelectField>
                  <InputField label="Expense Date" type="date" value={formState.linked_expense_date} onChange={(value) => setFormState((current) => ({ ...current, linked_expense_date: value }))} />
                </div>
              )}

              <TextAreaField label="Notes" value={formState.notes} onChange={(value) => setFormState((current) => ({ ...current, notes: value }))} />
            </div>
            <ModalFooter
              onCancel={closeCreateModal}
              submitLabel={isSubmitting ? 'Saving...' : editingJob ? 'Save Changes' : 'Create Maintenance Job'}
              isSubmitting={isSubmitting}
            />
          </form>
        </ModalShell>
      )}

      {selectedProgressJob && (
        <ModalShell title="Add Progress Update" subtitle={selectedProgressJob.title} onClose={closeProgressModal} maxWidth="max-w-3xl">
          <form onSubmit={handleProgressSubmit} className="flex h-full flex-col">
            <div className="flex-1 space-y-5 overflow-y-auto px-6 py-5">
              {actionError && (
                <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                  {actionError}
                </div>
              )}
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <SelectField label="Update Type" value={progressForm.update_type} onChange={(value) => setProgressForm((current) => ({ ...current, update_type: value as ProgressUpdateType }))}>
                  {['follow_up', 'mechanic_update', 'parts_update', 'cost_update', 'delay', 'ready_for_test', 'general'].map((type) => (
                    <option key={type} value={type}>
                      {formatLabel(type)}
                    </option>
                  ))}
                </SelectField>
                <SelectField label="Current Stage" value={progressForm.current_stage} onChange={(value) => setProgressForm((current) => ({ ...current, current_stage: value as MaintenanceStage }))}>
                  {['assigned_to_mechanic', 'diagnosing', 'waiting_parts', 'parts_received', 'repair_in_progress', 'testing', 'ready_for_driver_test', 'driver_confirmed', 'completed', 'delayed'].map((stage) => (
                    <option key={stage} value={stage}>
                      {formatLabel(stage)}
                    </option>
                  ))}
                </SelectField>
              </div>
              <TextAreaField label="Progress Note" value={progressForm.progress_note} onChange={(value) => setProgressForm((current) => ({ ...current, progress_note: value }))} minHeight="min-h-[120px]" />
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <InputField label="Next Action" value={progressForm.next_action} onChange={(value) => setProgressForm((current) => ({ ...current, next_action: value }))} />
                <InputField label="Next Follow-up Date" type="date" value={progressForm.next_follow_up_date} onChange={(value) => setProgressForm((current) => ({ ...current, next_follow_up_date: value }))} />
                <InputField label="Estimated Cost" type="number" value={progressForm.estimated_cost} onChange={(value) => setProgressForm((current) => ({ ...current, estimated_cost: value }))} />
                <InputField label="Actual Cost" type="number" value={progressForm.actual_cost} onChange={(value) => setProgressForm((current) => ({ ...current, actual_cost: value }))} />
              </div>
            </div>
            <ModalFooter onCancel={closeProgressModal} submitLabel={isActionSubmitting ? 'Saving Update...' : 'Save Progress Update'} isSubmitting={isActionSubmitting} />
          </form>
        </ModalShell>
      )}

      {statusTarget && (
        <ModalShell title="Update Maintenance Status" subtitle={statusTarget.title} onClose={closeStatusModal} maxWidth="max-w-2xl">
          <form onSubmit={handleStatusSubmit} className="flex h-full flex-col">
            <div className="flex-1 space-y-5 overflow-y-auto px-6 py-5">
              {actionError && (
                <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                  {actionError}
                </div>
              )}
              <SelectField label="Next Status" value={statusForm.status} onChange={(value) => setStatusForm((current) => ({ ...current, status: value as MaintenanceStatus }))}>
                {['approved', 'in_progress', 'waiting_parts', 'completed', 'cancelled'].map((status) => (
                  <option key={status} value={status}>
                    {formatLabel(status)}
                  </option>
                ))}
              </SelectField>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <InputField label="Vendor Name" value={statusForm.vendor_name} onChange={(value) => setStatusForm((current) => ({ ...current, vendor_name: value }))} />
                <InputField label="Vendor Contact" value={statusForm.vendor_contact} onChange={(value) => setStatusForm((current) => ({ ...current, vendor_contact: value }))} />
                <InputField label="Actual Cost" type="number" value={statusForm.actual_cost} onChange={(value) => setStatusForm((current) => ({ ...current, actual_cost: value }))} />
                <InputField label="Completion Date" type="date" value={statusForm.completion_date} onChange={(value) => setStatusForm((current) => ({ ...current, completion_date: value }))} />
              </div>
              <TextAreaField label="Notes" value={statusForm.notes} onChange={(value) => setStatusForm((current) => ({ ...current, notes: value }))} minHeight="min-h-[120px]" />
            </div>
            <ModalFooter onCancel={closeStatusModal} submitLabel={isActionSubmitting ? 'Updating...' : 'Update Status'} isSubmitting={isActionSubmitting} />
          </form>
        </ModalShell>
      )}

      {selectedTimelineJob && (
        <ModalShell title="Maintenance Timeline" subtitle={selectedTimelineJob.title} onClose={closeTimelineModal} maxWidth="max-w-4xl">
          <div className="flex-1 overflow-y-auto px-6 py-5">
            {timelineLoading ? (
              <div className="flex items-center justify-center gap-3 px-6 py-16 text-gray-500">
                <Loader2 className="h-5 w-5 animate-spin" />
                <span>Loading maintenance timeline...</span>
              </div>
            ) : progressLogs.length === 0 ? (
              <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 px-4 py-10 text-center text-sm text-gray-500">
                No progress logs recorded yet.
              </div>
            ) : (
              <div className="space-y-4">
                {progressLogs.map((log) => (
                  <div key={log.id} className="rounded-xl border border-gray-200 bg-gray-50 p-4">
                    <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                      <div>
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-sm font-semibold text-[#0F172A]">{formatLabel(log.update_type)}</span>
                          <span className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-medium ${stageClassName(log.current_stage)}`}>
                            {formatLabel(log.current_stage || 'assigned_to_mechanic')}
                          </span>
                        </div>
                        <div className="mt-1 text-xs text-gray-500">
                          {formatDateTime(log.updated_at)} • {log.updated_by_user?.full_name || 'System'}
                        </div>
                      </div>
                      {log.next_follow_up_date && (
                        <span className="inline-flex rounded-full border border-amber-200 bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
                          Follow-up {formatDate(log.next_follow_up_date)}
                        </span>
                      )}
                    </div>
                    <div className="mt-3 text-sm text-gray-700">{log.progress_note}</div>
                    {(log.next_action || log.next_follow_up_date) && (
                      <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
                        <div>
                          <div className="text-xs font-semibold uppercase tracking-wide text-gray-500">Next Action</div>
                          <div className="mt-1 text-sm text-[#0F172A]">{log.next_action || 'Not set'}</div>
                        </div>
                        <div>
                          <div className="text-xs font-semibold uppercase tracking-wide text-gray-500">Next Follow-up Date</div>
                          <div className="mt-1 text-sm text-[#0F172A]">{formatDate(log.next_follow_up_date)}</div>
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </ModalShell>
      )}

      {isOwner && (
        <div className="rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-800">
          <div className="flex items-start gap-3">
            <Settings2 className="mt-0.5 h-5 w-5 flex-shrink-0" />
            <div>
              Maintenance reminders are generated from follow-up dates, waiting parts delays, critical overdue jobs, and ready-for-driver-test handoffs using the existing notification system.
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function SummaryCard({
  label,
  value,
  icon: Icon,
  tone,
}: {
  label: string;
  value: number;
  icon: typeof Wrench;
  tone: 'slate' | 'blue' | 'amber' | 'rose' | 'green';
}) {
  const toneClasses = {
    slate: 'bg-slate-100 text-slate-600',
    blue: 'bg-blue-100 text-blue-600',
    amber: 'bg-amber-100 text-amber-600',
    rose: 'bg-rose-100 text-rose-600',
    green: 'bg-green-100 text-green-600',
  }[tone];

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5">
      <div className={`mb-2 flex h-10 w-10 items-center justify-center rounded-lg ${toneClasses}`}>
        <Icon className="h-5 w-5" />
      </div>
      <div className="text-2xl font-semibold text-[#0F172A]">{value}</div>
      <div className="text-sm text-gray-600">{label}</div>
    </div>
  );
}

function FollowUpPanel({
  title,
  subtitle,
  jobs,
  emptyMessage,
  onProgress,
  onTimeline,
}: {
  title: string;
  subtitle: string;
  jobs: MaintenanceJob[];
  emptyMessage: string;
  onProgress: (job: MaintenanceJob) => void;
  onTimeline: (job: MaintenanceJob) => void;
}) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white">
      <div className="border-b border-gray-200 px-6 py-4">
        <h2 className="text-lg font-semibold text-[#0F172A]">{title}</h2>
        <p className="mt-1 text-sm text-gray-600">{subtitle}</p>
      </div>
      <div className="space-y-3 px-6 py-5">
        {jobs.length === 0 ? (
          <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 px-4 py-8 text-center text-sm text-gray-500">
            {emptyMessage}
          </div>
        ) : (
          jobs.map((job) => (
            <div key={job.id} className={`rounded-xl border p-4 ${job.follow_up_overdue || job.is_overdue ? 'border-red-200 bg-red-50' : 'border-gray-200 bg-gray-50'}`}>
              <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                <div>
                  <div className="text-sm font-semibold text-[#0F172A]">{job.title}</div>
                  <div className="mt-1 text-sm text-gray-600">
                    {job.vehicle?.registration_number || 'Vehicle'} • {job.assigned_admin_name || 'No coordinator'}
                  </div>
                  <div className="mt-1 text-xs text-gray-500">
                    Stage {formatLabel(job.current_stage || 'assigned_to_mechanic')} • Follow-up {formatDate(job.next_follow_up_date)}
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    onClick={() => onProgress(job)}
                    className="inline-flex items-center gap-1 rounded-lg border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-100"
                  >
                    Add Progress
                  </button>
                  <button
                    onClick={() => onTimeline(job)}
                    className="inline-flex items-center gap-1 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
                  >
                    Timeline
                  </button>
                </div>
              </div>
              {job.next_action && <div className="mt-3 text-sm text-gray-700">Next action: {job.next_action}</div>}
            </div>
          ))
        )}
      </div>
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
          <button onClick={onClose} className="rounded-lg p-2 transition-all hover:bg-gray-100">
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
          className="rounded-lg border border-gray-300 px-4 py-2.5 font-medium text-gray-700 transition-all hover:bg-white"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={isSubmitting}
          className="flex items-center gap-2 rounded-lg bg-[#2563EB] px-4 py-2.5 font-medium text-white transition-all hover:bg-[#1d4ed8] disabled:cursor-not-allowed disabled:opacity-70"
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
        className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
      />
    </div>
  );
}

function SelectField({
  label,
  value,
  onChange,
  children,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-gray-700">{label}</label>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
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
  minHeight = 'min-h-[100px]',
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  minHeight?: string;
}) {
  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-gray-700">{label}</label>
      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className={`${minHeight} w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]`}
      />
    </div>
  );
}
