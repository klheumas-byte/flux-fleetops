import { useEffect, useMemo, useState, type ChangeEvent, type ReactNode } from 'react';
import {
  AlertTriangle,
  CalendarClock,
  CheckCircle2,
  Clock3,
  FileText,
  Loader2,
  Plus,
  RefreshCw,
  ShieldAlert,
  Upload,
  Wrench,
  XCircle,
} from 'lucide-react';
import { apiRequest, ApiRequestError } from '../../lib/api';

type TabKey = 'mechanical' | 'compliance';
type ScheduleType = 'date_based' | 'mileage_based' | 'both';
type RecurrenceType =
  | 'weekly'
  | 'every_2_weeks'
  | 'monthly'
  | 'every_2_months'
  | 'quarterly'
  | 'custom_days'
  | 'mileage_based'
  | 'both_time_and_mileage';
type ScheduleStatus = 'active' | 'due_soon' | 'due' | 'overdue' | 'completed' | 'paused';
type PreventiveType =
  | 'oil_change'
  | 'general_servicing'
  | 'brake_inspection'
  | 'tyre_check'
  | 'battery_check'
  | 'belt_check'
  | 'coolant_check'
  | 'suspension_check'
  | 'wheel_alignment'
  | 'air_filter_check'
  | 'vehicle_inspection'
  | 'engine_service'
  | 'other'
  | 'tyre_rotation';
type ComplianceStatus = 'active' | 'due_soon' | 'expired' | 'renewed' | 'inactive';
type RenewalFrequency = 'yearly' | 'every_6_months' | 'quarterly' | 'monthly' | 'custom';

interface UserSummary {
  id: string;
  full_name: string;
  role: 'owner' | 'admin' | 'driver';
}

interface VehicleSummary {
  id: string;
  registration_number: string;
  make?: string | null;
  model?: string | null;
}

interface PreventiveSchedule {
  id: string;
  vehicle_id: string;
  maintenance_type: PreventiveType;
  maintenance_item?: PreventiveType;
  title: string;
  description: string | null;
  notes?: string | null;
  recurrence_type?: RecurrenceType | null;
  schedule_type: ScheduleType;
  interval_days: number | null;
  interval_months?: number | null;
  interval_km: number | null;
  last_done_date: string | null;
  last_done_odometer: number | null;
  next_due_date: string | null;
  next_due_odometer: number | null;
  warning_days_before: number | null;
  warning_km_before: number | null;
  assigned_admin_id: string | null;
  status: ScheduleStatus;
  generated_maintenance_job_id: string | null;
  current_odometer?: number | null;
  mechanic_name?: string | null;
  parts_changed?: string[] | null;
  vehicle?: VehicleSummary | null;
  assigned_admin?: UserSummary | null;
}

interface ComplianceType {
  id: string;
  item_name: string;
  category: string;
  status: 'active' | 'inactive';
}

interface ComplianceHistoryEntry {
  previous_issue_date?: string | null;
  previous_expiry_date?: string | null;
  previous_status?: string | null;
  renewed_at?: string | null;
}

interface ComplianceRecord {
  id: string;
  vehicle_id: string;
  compliance_type_id: string | null;
  compliance_item_name: string;
  provider_or_authority_name: string | null;
  policy_or_reference_number: string | null;
  issue_date: string | null;
  expiry_date: string | null;
  renewal_frequency: RenewalFrequency;
  custom_interval_days?: number | null;
  warning_days_before: number | null;
  document_upload?: {
    file_name?: string;
    content_type?: string;
    data_url?: string;
  } | null;
  status: ComplianceStatus;
  notes: string | null;
  history: ComplianceHistoryEntry[];
  vehicle?: VehicleSummary | null;
  compliance_type?: ComplianceType | null;
}

interface ScheduleListResponse {
  success: boolean;
  data: {
    schedules: PreventiveSchedule[];
  };
}

interface ComplianceRecordsResponse {
  success: boolean;
  data: {
    records: ComplianceRecord[];
    summary: {
      expiring_soon: number;
      expired: number;
      renewed_this_month: number;
      vehicles_with_missing_compliance: Array<{
        vehicle_id: string;
        vehicle_registration_number: string;
        missing_items: string[];
      }>;
      compliance_by_vehicle: Array<{
        vehicle_id: string;
        vehicle_registration_number: string;
        total_records: number;
        missing_count: number;
      }>;
    };
  };
}

interface ComplianceTypesResponse {
  success: boolean;
  data: {
    types: ComplianceType[];
  };
}

interface ScheduleMutationResponse {
  success: boolean;
}

interface ComplianceMutationResponse {
  success: boolean;
}

interface VehiclesResponse {
  success: boolean;
  data: {
    vehicles: VehicleSummary[];
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

interface ScheduleFormState {
  vehicle_id: string;
  maintenance_type: PreventiveType;
  title: string;
  description: string;
  recurrence_type: RecurrenceType;
  interval_days: string;
  interval_months: string;
  interval_km: string;
  last_done_date: string;
  last_done_odometer: string;
  next_due_date: string;
  next_due_odometer: string;
  warning_days_before: string;
  warning_km_before: string;
  assigned_admin_id: string;
  status: ScheduleStatus;
  notes: string;
}

interface ComplianceFormState {
  vehicle_id: string;
  compliance_type_id: string;
  compliance_item_name: string;
  provider_or_authority_name: string;
  policy_or_reference_number: string;
  issue_date: string;
  expiry_date: string;
  renewal_frequency: RenewalFrequency;
  custom_interval_days: string;
  warning_days_before: string;
  notes: string;
  document_upload: { file_name?: string; content_type?: string; data_url?: string } | null;
}

function getSettledData<T>(result: PromiseSettledResult<T>) {
  return result.status === 'fulfilled' ? result.value : null;
}

function getSettledError(result: PromiseSettledResult<unknown>) {
  if (result.status !== 'rejected') {
    return null;
  }
  return result.reason instanceof ApiRequestError
    ? result.reason.message
    : 'Unable to load preventive maintenance data right now.';
}

const initialScheduleForm: ScheduleFormState = {
  vehicle_id: '',
  maintenance_type: 'oil_change',
  title: '',
  description: '',
  recurrence_type: 'monthly',
  interval_days: '',
  interval_months: '1',
  interval_km: '',
  last_done_date: '',
  last_done_odometer: '',
  next_due_date: '',
  next_due_odometer: '',
  warning_days_before: '7',
  warning_km_before: '500',
  assigned_admin_id: '',
  status: 'active',
  notes: '',
};

const initialComplianceForm: ComplianceFormState = {
  vehicle_id: '',
  compliance_type_id: '',
  compliance_item_name: '',
  provider_or_authority_name: '',
  policy_or_reference_number: '',
  issue_date: '',
  expiry_date: '',
  renewal_frequency: 'yearly',
  custom_interval_days: '',
  warning_days_before: '30',
  notes: '',
  document_upload: null,
};

function formatDate(value: string | null | undefined) {
  if (!value) return 'Not set';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString();
}

function formatLabel(value: string) {
  return value
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function recurrenceSummary(schedule: PreventiveSchedule) {
  const parts = [formatLabel(schedule.recurrence_type || schedule.schedule_type)];
  if (schedule.interval_months) parts.push(`${schedule.interval_months} month${schedule.interval_months === 1 ? '' : 's'}`);
  if (schedule.interval_days) parts.push(`${schedule.interval_days} day${schedule.interval_days === 1 ? '' : 's'}`);
  if (schedule.interval_km) parts.push(`${schedule.interval_km.toLocaleString()} km`);
  return parts.join(' • ');
}

function statusClassName(status: string) {
  switch (status) {
    case 'overdue':
    case 'expired':
      return 'border-red-200 bg-red-100 text-red-800';
    case 'due':
      return 'border-orange-200 bg-orange-100 text-orange-800';
    case 'due_soon':
      return 'border-amber-200 bg-amber-100 text-amber-800';
    case 'completed':
    case 'renewed':
      return 'border-green-200 bg-green-100 text-green-800';
    case 'paused':
    case 'inactive':
      return 'border-slate-200 bg-slate-100 text-slate-800';
    default:
      return 'border-blue-200 bg-blue-100 text-blue-800';
  }
}

export default function PreventiveMaintenance() {
  const [activeTab, setActiveTab] = useState<TabKey>('mechanical');
  const [schedules, setSchedules] = useState<PreventiveSchedule[]>([]);
  const [dueSoon, setDueSoon] = useState<PreventiveSchedule[]>([]);
  const [overdue, setOverdue] = useState<PreventiveSchedule[]>([]);
  const [complianceRecords, setComplianceRecords] = useState<ComplianceRecord[]>([]);
  const [complianceTypes, setComplianceTypes] = useState<ComplianceType[]>([]);
  const [vehicles, setVehicles] = useState<VehicleSummary[]>([]);
  const [admins, setAdmins] = useState<UserSummary[]>([]);
  const [complianceSummary, setComplianceSummary] = useState<ComplianceRecordsResponse['data']['summary']>({
    expiring_soon: 0,
    expired: 0,
    renewed_this_month: 0,
    vehicles_with_missing_compliance: [],
    compliance_by_vehicle: [],
  });
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [pageError, setPageError] = useState('');
  const [formError, setFormError] = useState('');
  const [actionError, setActionError] = useState('');
  const [showMechanicalModal, setShowMechanicalModal] = useState(false);
  const [showComplianceModal, setShowComplianceModal] = useState(false);
  const [showTypeModal, setShowTypeModal] = useState(false);
  const [editingSchedule, setEditingSchedule] = useState<PreventiveSchedule | null>(null);
  const [completingSchedule, setCompletingSchedule] = useState<PreventiveSchedule | null>(null);
  const [editingCompliance, setEditingCompliance] = useState<ComplianceRecord | null>(null);
  const [renewingCompliance, setRenewingCompliance] = useState<ComplianceRecord | null>(null);
  const [editingType, setEditingType] = useState<ComplianceType | null>(null);
  const [viewingHistory, setViewingHistory] = useState<ComplianceRecord | null>(null);
  const [scheduleForm, setScheduleForm] = useState<ScheduleFormState>(initialScheduleForm);
  const [complianceForm, setComplianceForm] = useState<ComplianceFormState>(initialComplianceForm);
  const [typeForm, setTypeForm] = useState({ item_name: '', category: 'other', status: 'active' as 'active' | 'inactive' });
  const [completionForm, setCompletionForm] = useState({
    completed_date: new Date().toISOString().slice(0, 10),
    completed_odometer: '',
    mechanic_name: '',
    work_done: '',
    parts_changed: '',
    condition_notes: '',
    next_due_date: '',
    next_due_odometer: '',
  });

  const loadData = async () => {
    setIsLoading(true);
    setPageError('');
    try {
      const [
        schedulesResult,
        dueSoonResult,
        overdueResult,
        vehiclesResult,
        adminsResult,
        complianceResult,
        typesResult,
      ] = await Promise.allSettled([
        apiRequest<ScheduleListResponse>('/preventive-maintenance', { cacheTtlMs: 10000, timeoutMs: 15000 }),
        apiRequest<ScheduleListResponse>('/preventive-maintenance/due-soon', { cacheTtlMs: 10000, timeoutMs: 15000 }),
        apiRequest<ScheduleListResponse>('/preventive-maintenance/overdue', { cacheTtlMs: 10000, timeoutMs: 15000 }),
        apiRequest<VehiclesResponse>('/vehicles', { cacheTtlMs: 10000, timeoutMs: 15000 }),
        apiRequest<AccountabilityResponse>('/admins/accountability', { cacheTtlMs: 10000, timeoutMs: 15000 }),
        apiRequest<ComplianceRecordsResponse>('/preventive-maintenance/compliance/records', { cacheTtlMs: 10000, timeoutMs: 15000 }),
        apiRequest<ComplianceTypesResponse>('/preventive-maintenance/compliance/types', { cacheTtlMs: 10000, timeoutMs: 15000 }),
      ]);

      const schedulesResponse = getSettledData(schedulesResult);
      const dueSoonResponse = getSettledData(dueSoonResult);
      const overdueResponse = getSettledData(overdueResult);
      const vehiclesResponse = getSettledData(vehiclesResult);
      const adminsResponse = getSettledData(adminsResult);
      const complianceResponse = getSettledData(complianceResult);
      const typesResponse = getSettledData(typesResult);

      const nextAdmins = (adminsResponse?.data?.admins || []).map((entry) => entry.admin).filter(Boolean);
      const nextVehicles = Array.isArray(vehiclesResponse?.data?.vehicles) ? vehiclesResponse.data.vehicles : [];
      const nextTypes = Array.isArray(typesResponse?.data?.types) ? typesResponse.data.types : [];

      setSchedules(Array.isArray(schedulesResponse?.data?.schedules) ? schedulesResponse.data.schedules : []);
      setDueSoon(Array.isArray(dueSoonResponse?.data?.schedules) ? dueSoonResponse.data.schedules : []);
      setOverdue(Array.isArray(overdueResponse?.data?.schedules) ? overdueResponse.data.schedules : []);
      setVehicles(nextVehicles);
      setAdmins(nextAdmins);
      setComplianceRecords(Array.isArray(complianceResponse?.data?.records) ? complianceResponse.data.records : []);
      setComplianceSummary(complianceResponse?.data?.summary || {
        expiring_soon: 0,
        expired: 0,
        renewed_this_month: 0,
        vehicles_with_missing_compliance: [],
        compliance_by_vehicle: [],
      });
      setComplianceTypes(nextTypes);
      setScheduleForm((current) => ({
        ...current,
        vehicle_id: current.vehicle_id || nextVehicles[0]?.id || '',
        assigned_admin_id: current.assigned_admin_id || nextAdmins[0]?.id || '',
      }));
      setComplianceForm((current) => ({
        ...current,
        vehicle_id: current.vehicle_id || nextVehicles[0]?.id || '',
        compliance_type_id: current.compliance_type_id || nextTypes.find((item) => item.status === 'active')?.id || '',
      }));

      const primaryError = getSettledError(schedulesResult) || getSettledError(complianceResult);
      if (primaryError) {
        setPageError(primaryError);
      }
    } catch (error) {
      setPageError(error instanceof ApiRequestError ? error.message : 'Unable to load preventive maintenance data right now.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void loadData();
  }, []);

  const mechanicalStats = useMemo(
    () => ({
      total: schedules.length,
      dueSoon: dueSoon.length,
      overdue: overdue.length,
      activeVehicles: new Set(schedules.map((schedule) => schedule.vehicle_id)).size,
    }),
    [dueSoon.length, overdue.length, schedules],
  );

  const openMechanicalEdit = (schedule: PreventiveSchedule | null) => {
    setEditingSchedule(schedule);
    setFormError('');
    setScheduleForm(
      schedule
        ? {
            vehicle_id: schedule.vehicle_id,
            maintenance_type: schedule.maintenance_type,
            title: schedule.title,
            description: schedule.description || '',
            recurrence_type: schedule.recurrence_type || 'custom_days',
            interval_days: schedule.interval_days != null ? String(schedule.interval_days) : '',
            interval_months: schedule.interval_months != null ? String(schedule.interval_months) : '',
            interval_km: schedule.interval_km != null ? String(schedule.interval_km) : '',
            last_done_date: schedule.last_done_date || '',
            last_done_odometer: schedule.last_done_odometer != null ? String(schedule.last_done_odometer) : '',
            next_due_date: schedule.next_due_date || '',
            next_due_odometer: schedule.next_due_odometer != null ? String(schedule.next_due_odometer) : '',
            warning_days_before: schedule.warning_days_before != null ? String(schedule.warning_days_before) : '7',
            warning_km_before: schedule.warning_km_before != null ? String(schedule.warning_km_before) : '500',
            assigned_admin_id: schedule.assigned_admin_id || '',
            status: schedule.status,
            notes: schedule.notes || '',
          }
        : {
            ...initialScheduleForm,
            vehicle_id: vehicles[0]?.id || '',
            assigned_admin_id: admins[0]?.id || '',
          },
    );
    setShowMechanicalModal(true);
  };

  const closeMechanicalModal = () => {
    setShowMechanicalModal(false);
    setEditingSchedule(null);
    setFormError('');
  };

  const handleMechanicalSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setIsSubmitting(true);
    setFormError('');
    const payload = {
      vehicle_id: scheduleForm.vehicle_id,
      maintenance_type: scheduleForm.maintenance_type,
      title: scheduleForm.title,
      description: scheduleForm.description || null,
      recurrence_type: scheduleForm.recurrence_type,
      interval_days: scheduleForm.interval_days ? Number(scheduleForm.interval_days) : null,
      interval_months: scheduleForm.interval_months ? Number(scheduleForm.interval_months) : null,
      interval_km: scheduleForm.interval_km ? Number(scheduleForm.interval_km) : null,
      last_done_date: scheduleForm.last_done_date || null,
      last_done_odometer: scheduleForm.last_done_odometer ? Number(scheduleForm.last_done_odometer) : null,
      next_due_date: scheduleForm.next_due_date || null,
      next_due_odometer: scheduleForm.next_due_odometer ? Number(scheduleForm.next_due_odometer) : null,
      warning_days_before: scheduleForm.warning_days_before ? Number(scheduleForm.warning_days_before) : 0,
      warning_km_before: scheduleForm.warning_km_before ? Number(scheduleForm.warning_km_before) : 0,
      assigned_admin_id: scheduleForm.assigned_admin_id || null,
      status: scheduleForm.status,
      notes: scheduleForm.notes || null,
    };
    try {
      await apiRequest<ScheduleMutationResponse>(editingSchedule ? `/preventive-maintenance/${editingSchedule.id}` : '/preventive-maintenance', {
        method: editingSchedule ? 'PATCH' : 'POST',
        body: JSON.stringify(payload),
      });
      closeMechanicalModal();
      await loadData();
    } catch (error) {
      setFormError(error instanceof ApiRequestError ? error.message : 'Unable to save mechanical maintenance right now.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleCompleteSchedule = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!completingSchedule) return;
    setIsSubmitting(true);
    setActionError('');
    try {
      await apiRequest<ScheduleMutationResponse>(`/preventive-maintenance/${completingSchedule.id}/complete`, {
        method: 'PATCH',
        body: JSON.stringify({
          completed_date: completionForm.completed_date,
          completed_odometer: completionForm.completed_odometer ? Number(completionForm.completed_odometer) : null,
          mechanic_name: completionForm.mechanic_name || null,
          work_done: completionForm.work_done || null,
          parts_changed: completionForm.parts_changed || null,
          condition_notes: completionForm.condition_notes || null,
          next_due_date: completionForm.next_due_date || null,
          next_due_odometer: completionForm.next_due_odometer ? Number(completionForm.next_due_odometer) : null,
        }),
      });
      setCompletingSchedule(null);
      await loadData();
    } catch (error) {
      setActionError(error instanceof ApiRequestError ? error.message : 'Unable to complete that maintenance item right now.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleGenerateJob = async (scheduleId: string) => {
    setIsSubmitting(true);
    setActionError('');
    try {
      await apiRequest<ScheduleMutationResponse>(`/preventive-maintenance/${scheduleId}/generate-maintenance-job`, { method: 'POST' });
      await loadData();
    } catch (error) {
      setActionError(error instanceof ApiRequestError ? error.message : 'Unable to generate a maintenance job right now.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const openComplianceModal = (record: ComplianceRecord | null, isRenewal = false) => {
    setEditingCompliance(isRenewal ? null : record);
    setRenewingCompliance(isRenewal ? record : null);
    setFormError('');
    const base = record
      ? {
          vehicle_id: record.vehicle_id,
          compliance_type_id: record.compliance_type_id || '',
          compliance_item_name: record.compliance_item_name,
          provider_or_authority_name: record.provider_or_authority_name || '',
          policy_or_reference_number: record.policy_or_reference_number || '',
          issue_date: record.issue_date || '',
          expiry_date: record.expiry_date || '',
          renewal_frequency: record.renewal_frequency || 'yearly',
          custom_interval_days: record.custom_interval_days != null ? String(record.custom_interval_days) : '',
          warning_days_before: record.warning_days_before != null ? String(record.warning_days_before) : '30',
          notes: record.notes || '',
          document_upload: record.document_upload || null,
        }
      : {
          ...initialComplianceForm,
          vehicle_id: vehicles[0]?.id || '',
          compliance_type_id: complianceTypes.find((item) => item.status === 'active')?.id || '',
        };
    setComplianceForm(base);
    setShowComplianceModal(true);
  };

  const closeComplianceModal = () => {
    setShowComplianceModal(false);
    setEditingCompliance(null);
    setRenewingCompliance(null);
    setFormError('');
  };

  const handleComplianceFileChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const dataUrl = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ''));
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
    setComplianceForm((current) => ({
      ...current,
      document_upload: {
        file_name: file.name,
        content_type: file.type,
        data_url: dataUrl,
      },
    }));
  };

  const handleComplianceSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setIsSubmitting(true);
    setFormError('');
    const payload = {
      vehicle_id: complianceForm.vehicle_id,
      compliance_type_id: complianceForm.compliance_type_id || null,
      compliance_item_name: complianceForm.compliance_item_name || null,
      provider_or_authority_name: complianceForm.provider_or_authority_name || null,
      policy_or_reference_number: complianceForm.policy_or_reference_number || null,
      issue_date: complianceForm.issue_date,
      expiry_date: complianceForm.expiry_date,
      renewal_frequency: complianceForm.renewal_frequency,
      custom_interval_days: complianceForm.custom_interval_days ? Number(complianceForm.custom_interval_days) : null,
      warning_days_before: complianceForm.warning_days_before ? Number(complianceForm.warning_days_before) : 30,
      notes: complianceForm.notes || null,
      document_upload: complianceForm.document_upload,
    };
    try {
      const endpoint = renewingCompliance
        ? `/preventive-maintenance/compliance/records/${renewingCompliance.id}/renew`
        : editingCompliance
          ? `/preventive-maintenance/compliance/records/${editingCompliance.id}`
          : '/preventive-maintenance/compliance/records';
      await apiRequest<ComplianceMutationResponse>(endpoint, {
        method: renewingCompliance ? 'PATCH' : editingCompliance ? 'PATCH' : 'POST',
        body: JSON.stringify(payload),
      });
      closeComplianceModal();
      await loadData();
    } catch (error) {
      setFormError(error instanceof ApiRequestError ? error.message : 'Unable to save compliance data right now.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const openTypeModal = (type: ComplianceType | null) => {
    setEditingType(type);
    setTypeForm(type ? { item_name: type.item_name, category: type.category || 'other', status: type.status } : { item_name: '', category: 'other', status: 'active' });
    setShowTypeModal(true);
    setFormError('');
  };

  const handleTypeSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setIsSubmitting(true);
    setFormError('');
    try {
      await apiRequest<ComplianceMutationResponse>(editingType ? `/preventive-maintenance/compliance/types/${editingType.id}` : '/preventive-maintenance/compliance/types', {
        method: editingType ? 'PATCH' : 'POST',
        body: JSON.stringify(typeForm),
      });
      setShowTypeModal(false);
      setEditingType(null);
      await loadData();
    } catch (error) {
      setFormError(error instanceof ApiRequestError ? error.message : 'Unable to save compliance type right now.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="space-y-6 overflow-x-hidden p-4 sm:p-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-[#0F172A]">Preventive Maintenance</h1>
          <p className="mt-1 max-w-3xl text-gray-600">
            Separate recurring mechanical maintenance from compliance renewals while keeping the same fleet workflow.
          </p>
        </div>
        <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap">
          <button
            onClick={() => void loadData()}
            className="inline-flex w-full items-center justify-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2.5 font-medium text-gray-700 transition-all hover:bg-gray-50 sm:w-auto"
          >
            <RefreshCw className="h-4 w-4" />
            Refresh
          </button>
          {activeTab === 'mechanical' ? (
            <button
              onClick={() => openMechanicalEdit(null)}
              className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-[#2563EB] px-4 py-2.5 font-medium text-white transition-all hover:bg-[#1d4ed8] sm:w-auto"
            >
              <Plus className="h-4 w-4" />
              Add Mechanical Schedule
            </button>
          ) : (
            <button
              onClick={() => openComplianceModal(null)}
              className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-[#2563EB] px-4 py-2.5 font-medium text-white transition-all hover:bg-[#1d4ed8] sm:w-auto"
            >
              <Plus className="h-4 w-4" />
              Add Compliance Record
            </button>
          )}
        </div>
      </div>

      <div className="flex flex-wrap gap-2 rounded-xl border border-gray-200 bg-white p-2">
        {[
          { id: 'mechanical', label: 'Mechanical Maintenance' },
          { id: 'compliance', label: 'Compliance & Renewals' },
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id as TabKey)}
            className={`rounded-lg px-4 py-2 text-sm font-medium transition-all ${
              activeTab === tab.id ? 'bg-[#2563EB] text-white' : 'text-gray-600 hover:bg-gray-100'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {pageError && <Banner tone="error">{pageError}</Banner>}
      {actionError && <Banner tone="warning">{actionError}</Banner>}

      {activeTab === 'mechanical' ? (
        <>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
            <SummaryCard label="Total Schedules" value={mechanicalStats.total} icon={CalendarClock} tone="blue" />
            <SummaryCard label="Due Soon" value={mechanicalStats.dueSoon} icon={Clock3} tone="amber" />
            <SummaryCard label="Overdue" value={mechanicalStats.overdue} icon={AlertTriangle} tone="rose" />
            <SummaryCard label="Vehicles Covered" value={mechanicalStats.activeVehicles} icon={Wrench} tone="blue" />
          </div>

          <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
            <SchedulePanel title="Due Soon" subtitle="Mechanical checks approaching warning threshold." schedules={dueSoon} />
            <SchedulePanel title="Overdue" subtitle="Mechanical items already past date or mileage thresholds." schedules={overdue} />
          </div>

          <Panel title="Mechanical Maintenance" subtitle="Recurring servicing, inspections, and usage-based upkeep per vehicle.">
            {isLoading ? (
              <LoadingState label="Loading mechanical schedules..." />
            ) : schedules.length === 0 ? (
              <EmptyState label="No mechanical maintenance schedules recorded yet." />
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50">
                    <tr>
                      {['Vehicle', 'Item', 'Next Due', 'Recurrence', 'Status', 'Actions'].map((header) => (
                        <th key={header} className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">
                          {header}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200 bg-white">
                    {schedules.map((schedule) => (
                      <tr key={schedule.id} className={schedule.status === 'overdue' ? 'bg-red-50/50' : schedule.status === 'due_soon' ? 'bg-amber-50/40' : 'hover:bg-gray-50'}>
                        <td className="px-4 py-4 text-sm text-[#0F172A]">
                          <div className="font-medium">{schedule.vehicle?.registration_number || 'Vehicle'}</div>
                          <div className="text-xs text-gray-500">{[schedule.vehicle?.make, schedule.vehicle?.model].filter(Boolean).join(' ') || 'Fleet vehicle'}</div>
                        </td>
                        <td className="px-4 py-4 text-sm text-gray-700">
                          <div className="font-medium text-[#0F172A]">{schedule.title}</div>
                          <div className="text-xs text-gray-500">{formatLabel(schedule.maintenance_type)}</div>
                          {schedule.notes && <div className="mt-1 line-clamp-2 text-xs text-gray-500">{schedule.notes}</div>}
                        </td>
                        <td className="px-4 py-4 text-sm text-gray-700">
                          <div>Date: {formatDate(schedule.next_due_date)}</div>
                          <div className="text-xs text-gray-500">Threshold: {schedule.next_due_odometer != null ? `${schedule.next_due_odometer.toLocaleString()} km` : 'Not set'}</div>
                          <div className="text-xs text-gray-500">Current: {schedule.current_odometer != null ? `${schedule.current_odometer.toLocaleString()} km` : 'Unavailable'}</div>
                        </td>
                        <td className="px-4 py-4 text-sm text-gray-700">
                          <div>{recurrenceSummary(schedule)}</div>
                          <div className="text-xs text-gray-500">Warning: {schedule.warning_days_before ?? 0} days / {schedule.warning_km_before ?? 0} km</div>
                        </td>
                        <td className="px-4 py-4 text-sm">
                          <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${statusClassName(schedule.status)}`}>
                            {formatLabel(schedule.status)}
                          </span>
                        </td>
                        <td className="px-4 py-4 text-sm">
                          <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
                            <button onClick={() => openMechanicalEdit(schedule)} className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50">
                              Edit
                            </button>
                            <button
                              onClick={() => {
                                setCompletingSchedule(schedule);
                                setCompletionForm({
                                  completed_date: new Date().toISOString().slice(0, 10),
                                  completed_odometer: schedule.current_odometer != null ? String(schedule.current_odometer) : '',
                                  mechanic_name: schedule.mechanic_name || '',
                                  work_done: '',
                                  parts_changed: Array.isArray(schedule.parts_changed) ? schedule.parts_changed.join(', ') : '',
                                  condition_notes: '',
                                  next_due_date: '',
                                  next_due_odometer: '',
                                });
                              }}
                              className="rounded-lg border border-green-200 bg-green-50 px-3 py-1.5 text-xs font-medium text-green-700 hover:bg-green-100"
                            >
                              Mark Completed
                            </button>
                            <button
                              onClick={() => void handleGenerateJob(schedule.id)}
                              disabled={isSubmitting}
                              className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-70"
                            >
                              Generate Job
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
        </>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
            <SummaryCard label="Expiring Soon" value={complianceSummary.expiring_soon} icon={Clock3} tone="amber" />
            <SummaryCard label="Expired" value={complianceSummary.expired} icon={ShieldAlert} tone="rose" />
            <SummaryCard label="Renewed This Month" value={complianceSummary.renewed_this_month} icon={CheckCircle2} tone="blue" />
            <SummaryCard label="Vehicles Missing Compliance" value={complianceSummary.vehicles_with_missing_compliance.length} icon={AlertTriangle} tone="rose" />
          </div>

          <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
            <Panel title="Compliance Type Management" subtitle="Create, edit, and deactivate reusable compliance items.">
              <div className="mb-4 flex justify-end">
                <button onClick={() => openTypeModal(null)} className="inline-flex items-center gap-2 rounded-lg bg-[#2563EB] px-4 py-2 text-sm font-medium text-white hover:bg-[#1d4ed8]">
                  <Plus className="h-4 w-4" />
                  Add Type
                </button>
              </div>
              <div className="space-y-3">
                {complianceTypes.map((type) => (
                  <div key={type.id} className="flex flex-col gap-3 rounded-xl border border-gray-200 p-4 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                      <div className="font-medium text-[#0F172A]">{type.item_name}</div>
                      <div className="text-sm text-gray-500">{formatLabel(type.category || 'other')}</div>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${statusClassName(type.status)}`}>{formatLabel(type.status)}</span>
                      <button onClick={() => openTypeModal(type)} className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50">
                        Edit
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </Panel>

            <Panel title="Missing Compliance" subtitle="Vehicles missing one or more active compliance requirements.">
              {complianceSummary.vehicles_with_missing_compliance.length === 0 ? (
                <EmptyState label="All vehicles have records for the currently active compliance types." />
              ) : (
                <div className="space-y-3">
                  {complianceSummary.vehicles_with_missing_compliance.map((entry) => (
                    <div key={entry.vehicle_id} className="rounded-xl border border-amber-200 bg-amber-50 p-4">
                      <div className="font-medium text-[#0F172A]">{entry.vehicle_registration_number}</div>
                      <div className="mt-1 text-sm text-gray-700">{entry.missing_items.join(', ')}</div>
                    </div>
                  ))}
                </div>
              )}
            </Panel>
          </div>

          <Panel title="Compliance & Renewals" subtitle="Track insurance, roadworthy, permits, kits, and other expiry-based legal requirements.">
            {isLoading ? (
              <LoadingState label="Loading compliance records..." />
            ) : complianceRecords.length === 0 ? (
              <EmptyState label="No compliance records recorded yet." />
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50">
                    <tr>
                      {['Vehicle', 'Compliance Item', 'Authority', 'Expiry', 'Document', 'Status', 'Actions'].map((header) => (
                        <th key={header} className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">
                          {header}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200 bg-white">
                    {complianceRecords.map((record) => (
                      <tr key={record.id} className={record.status === 'expired' ? 'bg-red-50/50' : record.status === 'due_soon' ? 'bg-amber-50/40' : 'hover:bg-gray-50'}>
                        <td className="px-4 py-4 text-sm text-[#0F172A]">
                          <div className="font-medium">{record.vehicle?.registration_number || 'Vehicle'}</div>
                          <div className="text-xs text-gray-500">{[record.vehicle?.make, record.vehicle?.model].filter(Boolean).join(' ') || 'Fleet vehicle'}</div>
                        </td>
                        <td className="px-4 py-4 text-sm text-gray-700">
                          <div className="font-medium text-[#0F172A]">{record.compliance_item_name}</div>
                          <div className="text-xs text-gray-500">{formatLabel(record.renewal_frequency)}</div>
                          {record.notes && <div className="mt-1 line-clamp-2 text-xs text-gray-500">{record.notes}</div>}
                        </td>
                        <td className="px-4 py-4 text-sm text-gray-700">
                          <div>{record.provider_or_authority_name || 'Not set'}</div>
                          <div className="text-xs text-gray-500">{record.policy_or_reference_number || 'No reference'}</div>
                        </td>
                        <td className="px-4 py-4 text-sm text-gray-700">
                          <div>Issue: {formatDate(record.issue_date)}</div>
                          <div className="text-xs text-gray-500">Expiry: {formatDate(record.expiry_date)}</div>
                        </td>
                        <td className="px-4 py-4 text-sm text-gray-700">
                          {record.document_upload?.file_name ? (
                            <div className="inline-flex items-center gap-2 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-xs">
                              <FileText className="h-4 w-4 text-gray-500" />
                              <span className="max-w-[180px] truncate">{record.document_upload.file_name}</span>
                            </div>
                          ) : (
                            'No document'
                          )}
                        </td>
                        <td className="px-4 py-4 text-sm">
                          <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${statusClassName(record.status)}`}>
                            {formatLabel(record.status)}
                          </span>
                        </td>
                        <td className="px-4 py-4 text-sm">
                          <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
                            <button onClick={() => openComplianceModal(record)} className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50">
                              Edit
                            </button>
                            <button onClick={() => openComplianceModal(record, true)} className="rounded-lg border border-green-200 bg-green-50 px-3 py-1.5 text-xs font-medium text-green-700 hover:bg-green-100">
                              Renew
                            </button>
                            <button onClick={() => setViewingHistory(record)} className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-100">
                              History
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
        </>
      )}

      {showMechanicalModal && (
        <ModalShell title={editingSchedule ? 'Edit Mechanical Schedule' : 'Add Mechanical Schedule'} onClose={closeMechanicalModal}>
          <form onSubmit={handleMechanicalSubmit} className="flex h-full flex-col">
            <div className="flex-1 space-y-5 overflow-y-auto px-5 py-5">
              {formError && <Banner tone="error">{formError}</Banner>}
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                <SelectField label="Vehicle" value={scheduleForm.vehicle_id} onChange={(value) => setScheduleForm((current) => ({ ...current, vehicle_id: value }))}>
                  <option value="">Choose vehicle...</option>
                  {vehicles.map((vehicle) => (
                    <option key={vehicle.id} value={vehicle.id}>
                      {vehicle.registration_number} - {[vehicle.make, vehicle.model].filter(Boolean).join(' ')}
                    </option>
                  ))}
                </SelectField>
                <SelectField label="Item Name" value={scheduleForm.maintenance_type} onChange={(value) => setScheduleForm((current) => ({ ...current, maintenance_type: value as PreventiveType, title: current.title || formatLabel(value) }))}>
                  {['oil_change', 'general_servicing', 'brake_inspection', 'tyre_check', 'battery_check', 'coolant_check', 'suspension_check', 'air_filter_check', 'wheel_alignment', 'belt_check', 'vehicle_inspection', 'engine_service', 'other'].map((type) => (
                    <option key={type} value={type}>
                      {formatLabel(type)}
                    </option>
                  ))}
                </SelectField>
                <InputField label="Title" value={scheduleForm.title} onChange={(value) => setScheduleForm((current) => ({ ...current, title: value }))} />
                <SelectField label="Trigger Type" value={scheduleForm.recurrence_type} onChange={(value) => setScheduleForm((current) => ({ ...current, recurrence_type: value as RecurrenceType }))}>
                  {['weekly', 'every_2_weeks', 'monthly', 'every_2_months', 'quarterly', 'custom_days', 'mileage_based', 'both_time_and_mileage'].map((type) => (
                    <option key={type} value={type}>
                      {formatLabel(type)}
                    </option>
                  ))}
                </SelectField>
                <InputField label="Interval Days" type="number" value={scheduleForm.interval_days} onChange={(value) => setScheduleForm((current) => ({ ...current, interval_days: value }))} />
                <InputField label="Interval Months" type="number" value={scheduleForm.interval_months} onChange={(value) => setScheduleForm((current) => ({ ...current, interval_months: value }))} />
                <InputField label="Interval KM" type="number" value={scheduleForm.interval_km} onChange={(value) => setScheduleForm((current) => ({ ...current, interval_km: value }))} />
                <InputField label="Last Done Date" type="date" value={scheduleForm.last_done_date} onChange={(value) => setScheduleForm((current) => ({ ...current, last_done_date: value }))} />
                <InputField label="Last Done Odometer" type="number" value={scheduleForm.last_done_odometer} onChange={(value) => setScheduleForm((current) => ({ ...current, last_done_odometer: value }))} />
                <InputField label="Next Due Date" type="date" value={scheduleForm.next_due_date} onChange={(value) => setScheduleForm((current) => ({ ...current, next_due_date: value }))} />
                <InputField label="Next Due Odometer" type="number" value={scheduleForm.next_due_odometer} onChange={(value) => setScheduleForm((current) => ({ ...current, next_due_odometer: value }))} />
                <InputField label="Warning Days Before" type="number" value={scheduleForm.warning_days_before} onChange={(value) => setScheduleForm((current) => ({ ...current, warning_days_before: value }))} />
                <InputField label="Warning KM Before" type="number" value={scheduleForm.warning_km_before} onChange={(value) => setScheduleForm((current) => ({ ...current, warning_km_before: value }))} />
                <SelectField label="Assigned Admin" value={scheduleForm.assigned_admin_id} onChange={(value) => setScheduleForm((current) => ({ ...current, assigned_admin_id: value }))}>
                  <option value="">Choose admin...</option>
                  {admins.map((admin) => (
                    <option key={admin.id} value={admin.id}>
                      {admin.full_name}
                    </option>
                  ))}
                </SelectField>
                <SelectField label="Status" value={scheduleForm.status} onChange={(value) => setScheduleForm((current) => ({ ...current, status: value as ScheduleStatus }))}>
                  {['active', 'due_soon', 'due', 'overdue', 'completed', 'paused'].map((status) => (
                    <option key={status} value={status}>
                      {formatLabel(status)}
                    </option>
                  ))}
                </SelectField>
              </div>
              <TextAreaField label="Description" value={scheduleForm.description} onChange={(value) => setScheduleForm((current) => ({ ...current, description: value }))} />
              <TextAreaField label="Notes" value={scheduleForm.notes} onChange={(value) => setScheduleForm((current) => ({ ...current, notes: value }))} />
            </div>
            <ModalFooter onCancel={closeMechanicalModal} submitLabel={isSubmitting ? 'Saving...' : editingSchedule ? 'Save Changes' : 'Create Schedule'} isSubmitting={isSubmitting} />
          </form>
        </ModalShell>
      )}

      {completingSchedule && (
        <ModalShell title="Mark Mechanical Maintenance Completed" subtitle={completingSchedule.title} onClose={() => setCompletingSchedule(null)} maxWidth="max-w-2xl">
          <form onSubmit={handleCompleteSchedule} className="space-y-5 px-5 py-5">
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <InputField label="Completed Date" type="date" value={completionForm.completed_date} onChange={(value) => setCompletionForm((current) => ({ ...current, completed_date: value }))} />
              <InputField label="Completed Odometer" type="number" value={completionForm.completed_odometer} onChange={(value) => setCompletionForm((current) => ({ ...current, completed_odometer: value }))} />
              <InputField label="Mechanic Name" value={completionForm.mechanic_name} onChange={(value) => setCompletionForm((current) => ({ ...current, mechanic_name: value }))} />
              <InputField label="Next Due Odometer Override" type="number" value={completionForm.next_due_odometer} onChange={(value) => setCompletionForm((current) => ({ ...current, next_due_odometer: value }))} />
              <InputField label="Next Due Date Override" type="date" value={completionForm.next_due_date} onChange={(value) => setCompletionForm((current) => ({ ...current, next_due_date: value }))} />
            </div>
            <TextAreaField label="Work Done" value={completionForm.work_done} onChange={(value) => setCompletionForm((current) => ({ ...current, work_done: value }))} />
            <TextAreaField label="Parts Changed" value={completionForm.parts_changed} onChange={(value) => setCompletionForm((current) => ({ ...current, parts_changed: value }))} />
            <TextAreaField label="Condition Notes" value={completionForm.condition_notes} onChange={(value) => setCompletionForm((current) => ({ ...current, condition_notes: value }))} />
            <ModalFooter onCancel={() => setCompletingSchedule(null)} submitLabel={isSubmitting ? 'Saving...' : 'Mark Completed'} isSubmitting={isSubmitting} />
          </form>
        </ModalShell>
      )}

      {showComplianceModal && (
        <ModalShell title={renewingCompliance ? 'Renew Compliance Record' : editingCompliance ? 'Edit Compliance Record' : 'Add Compliance Record'} onClose={closeComplianceModal}>
          <form onSubmit={handleComplianceSubmit} className="flex h-full flex-col">
            <div className="flex-1 space-y-5 overflow-y-auto px-5 py-5">
              {formError && <Banner tone="error">{formError}</Banner>}
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                <SelectField label="Vehicle" value={complianceForm.vehicle_id} onChange={(value) => setComplianceForm((current) => ({ ...current, vehicle_id: value }))}>
                  <option value="">Choose vehicle...</option>
                  {vehicles.map((vehicle) => (
                    <option key={vehicle.id} value={vehicle.id}>
                      {vehicle.registration_number} - {[vehicle.make, vehicle.model].filter(Boolean).join(' ')}
                    </option>
                  ))}
                </SelectField>
                <SelectField label="Compliance Item Type" value={complianceForm.compliance_type_id} onChange={(value) => {
                  const selected = complianceTypes.find((item) => item.id === value);
                  setComplianceForm((current) => ({
                    ...current,
                    compliance_type_id: value,
                    compliance_item_name: selected ? selected.item_name : current.compliance_item_name,
                  }));
                }}>
                  <option value="">Custom item / historical item</option>
                  {complianceTypes.filter((item) => item.status === 'active').map((type) => (
                    <option key={type.id} value={type.id}>
                      {type.item_name}
                    </option>
                  ))}
                </SelectField>
                <InputField label="Compliance Item Name" value={complianceForm.compliance_item_name} onChange={(value) => setComplianceForm((current) => ({ ...current, compliance_item_name: value }))} />
                <InputField label="Provider or Authority" value={complianceForm.provider_or_authority_name} onChange={(value) => setComplianceForm((current) => ({ ...current, provider_or_authority_name: value }))} />
                <InputField label="Policy / Reference Number" value={complianceForm.policy_or_reference_number} onChange={(value) => setComplianceForm((current) => ({ ...current, policy_or_reference_number: value }))} />
                <SelectField label="Renewal Frequency" value={complianceForm.renewal_frequency} onChange={(value) => setComplianceForm((current) => ({ ...current, renewal_frequency: value as RenewalFrequency }))}>
                  {['yearly', 'every_6_months', 'quarterly', 'monthly', 'custom'].map((type) => (
                    <option key={type} value={type}>
                      {formatLabel(type)}
                    </option>
                  ))}
                </SelectField>
                <InputField label="Issue Date" type="date" value={complianceForm.issue_date} onChange={(value) => setComplianceForm((current) => ({ ...current, issue_date: value }))} />
                <InputField label="Expiry Date" type="date" value={complianceForm.expiry_date} onChange={(value) => setComplianceForm((current) => ({ ...current, expiry_date: value }))} />
                <InputField label="Warning Days Before" type="number" value={complianceForm.warning_days_before} onChange={(value) => setComplianceForm((current) => ({ ...current, warning_days_before: value }))} />
                {complianceForm.renewal_frequency === 'custom' && (
                  <InputField label="Custom Interval Days" type="number" value={complianceForm.custom_interval_days} onChange={(value) => setComplianceForm((current) => ({ ...current, custom_interval_days: value }))} />
                )}
              </div>
              <TextAreaField label="Notes" value={complianceForm.notes} onChange={(value) => setComplianceForm((current) => ({ ...current, notes: value }))} />
              <label className="block">
                <span className="mb-2 block text-sm font-medium text-gray-700">Upload Document</span>
                <label className="flex cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed border-gray-300 bg-gray-50 px-4 py-6 text-sm text-gray-600">
                  <Upload className="mb-2 h-5 w-5 text-gray-500" />
                  <span>{complianceForm.document_upload?.file_name || 'Choose a document to attach'}</span>
                  <input type="file" className="hidden" onChange={(event) => void handleComplianceFileChange(event)} />
                </label>
              </label>
            </div>
            <ModalFooter onCancel={closeComplianceModal} submitLabel={isSubmitting ? 'Saving...' : renewingCompliance ? 'Renew Record' : editingCompliance ? 'Save Changes' : 'Create Record'} isSubmitting={isSubmitting} />
          </form>
        </ModalShell>
      )}

      {showTypeModal && (
        <ModalShell title={editingType ? 'Edit Compliance Type' : 'Add Compliance Type'} onClose={() => setShowTypeModal(false)} maxWidth="max-w-xl">
          <form onSubmit={handleTypeSubmit} className="space-y-5 px-5 py-5">
            {formError && <Banner tone="error">{formError}</Banner>}
            <InputField label="Item Name" value={typeForm.item_name} onChange={(value) => setTypeForm((current) => ({ ...current, item_name: value }))} />
            <SelectField label="Category" value={typeForm.category} onChange={(value) => setTypeForm((current) => ({ ...current, category: value }))}>
              {['renewal', 'permit', 'compliance', 'other'].map((category) => (
                <option key={category} value={category}>
                  {formatLabel(category)}
                </option>
              ))}
            </SelectField>
            <SelectField label="Status" value={typeForm.status} onChange={(value) => setTypeForm((current) => ({ ...current, status: value as 'active' | 'inactive' }))}>
              {['active', 'inactive'].map((status) => (
                <option key={status} value={status}>
                  {formatLabel(status)}
                </option>
              ))}
            </SelectField>
            <ModalFooter onCancel={() => setShowTypeModal(false)} submitLabel={isSubmitting ? 'Saving...' : editingType ? 'Save Changes' : 'Create Type'} isSubmitting={isSubmitting} />
          </form>
        </ModalShell>
      )}

      {viewingHistory && (
        <ModalShell title="Compliance History" subtitle={viewingHistory.compliance_item_name} onClose={() => setViewingHistory(null)} maxWidth="max-w-2xl">
          <div className="space-y-4 px-5 py-5">
            {viewingHistory.history.length === 0 ? (
              <EmptyState label="No renewal history recorded yet." />
            ) : (
              viewingHistory.history.map((entry, index) => (
                <div key={`${viewingHistory.id}-${index}`} className="rounded-xl border border-gray-200 bg-gray-50 p-4">
                  <div className="font-medium text-[#0F172A]">Renewal {viewingHistory.history.length - index}</div>
                  <div className="mt-2 space-y-1 text-sm text-gray-600">
                    <div>Previous Issue Date: {formatDate(entry.previous_issue_date)}</div>
                    <div>Previous Expiry Date: {formatDate(entry.previous_expiry_date)}</div>
                    <div>Previous Status: {entry.previous_status ? formatLabel(entry.previous_status) : 'Not set'}</div>
                    <div>Renewed At: {formatDate(entry.renewed_at)}</div>
                  </div>
                </div>
              ))
            )}
            <div className="sticky bottom-0 flex justify-end border-t border-gray-200 bg-white pt-4">
              <button onClick={() => setViewingHistory(null)} className="rounded-lg border border-gray-300 px-4 py-2.5 font-medium text-gray-700 hover:bg-gray-50">
                Close
              </button>
            </div>
          </div>
        </ModalShell>
      )}
    </div>
  );
}

function Banner({ tone, children }: { tone: 'error' | 'warning'; children: ReactNode }) {
  const className = tone === 'error' ? 'border-red-200 bg-red-50 text-red-700' : 'border-amber-200 bg-amber-50 text-amber-800';
  return <div className={`rounded-lg border px-4 py-3 text-sm ${className}`}>{children}</div>;
}

function SummaryCard({ label, value, icon: Icon, tone }: { label: string; value: number; icon: typeof CalendarClock; tone: 'blue' | 'amber' | 'rose' }) {
  const toneClasses = { blue: 'bg-blue-100 text-blue-600', amber: 'bg-amber-100 text-amber-600', rose: 'bg-rose-100 text-rose-600' }[tone];
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

function Panel({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  return (
    <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
      <div className="border-b border-gray-200 px-5 py-4">
        <h2 className="text-lg font-semibold text-[#0F172A]">{title}</h2>
        <p className="mt-1 text-sm text-gray-600">{subtitle}</p>
      </div>
      <div className="px-5 py-5">{children}</div>
    </div>
  );
}

function SchedulePanel({ title, subtitle, schedules }: { title: string; subtitle: string; schedules: PreventiveSchedule[] }) {
  return (
    <Panel title={title} subtitle={subtitle}>
      <div className="space-y-3">
        {schedules.length === 0 ? (
          <EmptyState label="No schedules in this state right now." />
        ) : (
          schedules.map((schedule) => (
            <div key={schedule.id} className={`rounded-xl border p-4 ${schedule.status === 'overdue' ? 'border-red-200 bg-red-50' : 'border-amber-200 bg-amber-50'}`}>
              <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <div className="text-sm font-semibold text-[#0F172A]">
                    {schedule.vehicle?.registration_number || 'Vehicle'} • {schedule.title}
                  </div>
                  <div className="mt-1 text-sm text-gray-700">
                    Due {formatDate(schedule.next_due_date)} • {schedule.next_due_odometer != null ? `${schedule.next_due_odometer.toLocaleString()} km` : 'No odometer threshold'}
                  </div>
                </div>
                <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${statusClassName(schedule.status)}`}>
                  {formatLabel(schedule.status)}
                </span>
              </div>
            </div>
          ))
        )}
      </div>
    </Panel>
  );
}

function EmptyState({ label }: { label: string }) {
  return <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 px-4 py-8 text-center text-sm text-gray-500">{label}</div>;
}

function LoadingState({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-center gap-3 px-4 py-12 text-gray-500">
      <Loader2 className="h-5 w-5 animate-spin" />
      <span>{label}</span>
    </div>
  );
}

function ModalShell({
  title,
  subtitle,
  onClose,
  children,
  maxWidth = 'max-w-4xl',
}: {
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: ReactNode;
  maxWidth?: string;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-3 py-4 sm:px-4 sm:py-6">
      <div className={`flex max-h-[90vh] w-[95%] ${maxWidth} flex-col overflow-hidden rounded-xl border border-gray-200 bg-white shadow-2xl`}>
        <div className="flex items-start justify-between border-b border-gray-200 px-5 py-4">
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

function InputField({ label, value, onChange, type = 'text' }: { label: string; value: string; onChange: (value: string) => void; type?: string }) {
  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-gray-700">{label}</label>
      <input type={type} value={value} onChange={(event) => onChange(event.target.value)} className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]" />
    </div>
  );
}

function SelectField({ label, value, onChange, children }: { label: string; value: string; onChange: (value: string) => void; children: ReactNode }) {
  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-gray-700">{label}</label>
      <select value={value} onChange={(event) => onChange(event.target.value)} className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]">
        {children}
      </select>
    </div>
  );
}

function TextAreaField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-gray-700">{label}</label>
      <textarea value={value} onChange={(event) => onChange(event.target.value)} className="min-h-[110px] w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]" />
    </div>
  );
}

function ModalFooter({ onCancel, submitLabel, isSubmitting }: { onCancel: () => void; submitLabel: string; isSubmitting: boolean }) {
  return (
    <div className="sticky bottom-0 flex flex-col gap-3 border-t border-gray-200 bg-white px-5 py-4 sm:flex-row sm:justify-end">
      <button type="button" onClick={onCancel} className="w-full rounded-lg border border-gray-300 px-4 py-2.5 font-medium text-gray-700 transition-all hover:bg-gray-50 sm:w-auto">
        Cancel
      </button>
      <button type="submit" disabled={isSubmitting} className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-[#2563EB] px-4 py-2.5 font-medium text-white transition-all hover:bg-[#1d4ed8] disabled:cursor-not-allowed disabled:opacity-70 sm:w-auto">
        {isSubmitting && <Loader2 className="h-4 w-4 animate-spin" />}
        {submitLabel}
      </button>
    </div>
  );
}
