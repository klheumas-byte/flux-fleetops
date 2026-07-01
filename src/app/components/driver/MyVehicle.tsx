import { useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, Calendar, Car, Gauge, Loader2, Shield, Truck, Wrench } from 'lucide-react';
import { apiRequest, ApiRequestError } from '../../lib/api';
import { getAssignedVehicleLabel, type SessionUser } from '../../lib/auth-session';
import type { DriverActiveAssignment } from '../../lib/driver-api';

interface MyVehicleProps {
  currentUser: SessionUser | null;
  activeAssignment: DriverActiveAssignment | null;
}

interface DetailRowProps {
  label: string;
  value: string;
}

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

interface MaintenanceJob {
  id: string;
  title: string;
  maintenance_type: string;
  status: MaintenanceStatus;
  start_date: string | null;
  target_completion_date: string | null;
  completion_date: string | null;
  service_note: string | null;
  current_stage: MaintenanceStage | null;
  next_action: string | null;
  next_follow_up_date: string | null;
  driver_confirmation_status: 'pending' | 'confirmed' | 'rejected' | null;
  vehicle: {
    id: string;
    registration_number: string;
  } | null;
}

interface MaintenanceJobsResponse {
  success: boolean;
  data: {
    jobs: MaintenanceJob[];
  };
}

interface MaintenanceProgressMutationResponse {
  success: boolean;
}

type PreventiveScheduleStatus = 'active' | 'due_soon' | 'due' | 'overdue' | 'completed' | 'paused';

interface PreventiveSchedule {
  id: string;
  maintenance_type: string;
  title: string;
  status: PreventiveScheduleStatus;
  next_due_date: string | null;
  next_due_odometer: number | null;
  description: string | null;
}

interface PreventiveSchedulesResponse {
  success: boolean;
  data: {
    schedules: PreventiveSchedule[];
    compliance_records?: ComplianceRecord[];
  };
}

type ComplianceStatus = 'active' | 'due_soon' | 'expired' | 'renewed' | 'inactive';

interface ComplianceRecord {
  id: string;
  compliance_item_name: string;
  status: ComplianceStatus;
  expiry_date: string | null;
  provider_or_authority_name: string | null;
}

function DetailRow({ label, value }: DetailRowProps) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-gray-100 py-3 last:border-b-0">
      <span className="text-sm text-gray-500">{label}</span>
      <span className="text-right text-sm font-medium text-[#0F172A]">{value}</span>
    </div>
  );
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

function formatLabel(value: string) {
  return value
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function statusBadgeClass(status: MaintenanceStatus) {
  switch (status) {
    case 'completed':
      return 'border-green-200 bg-green-100 text-green-700';
    case 'in_progress':
      return 'border-blue-200 bg-blue-100 text-blue-700';
    case 'waiting_parts':
      return 'border-amber-200 bg-amber-100 text-amber-700';
    case 'cancelled':
      return 'border-rose-200 bg-rose-100 text-rose-700';
    case 'approved':
      return 'border-indigo-200 bg-indigo-100 text-indigo-700';
    default:
      return 'border-slate-200 bg-slate-100 text-slate-700';
  }
}

function preventiveStatusBadgeClass(status: PreventiveScheduleStatus) {
  switch (status) {
    case 'overdue':
      return 'border-rose-200 bg-rose-100 text-rose-700';
    case 'due':
      return 'border-orange-200 bg-orange-100 text-orange-700';
    case 'due_soon':
      return 'border-amber-200 bg-amber-100 text-amber-700';
    case 'completed':
      return 'border-green-200 bg-green-100 text-green-700';
    case 'paused':
      return 'border-slate-200 bg-slate-100 text-slate-700';
    default:
      return 'border-blue-200 bg-blue-100 text-blue-700';
  }
}

function useVisibilityOnce<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    if (isVisible) {
      return;
    }
    if (typeof IntersectionObserver === 'undefined') {
      setIsVisible(true);
      return;
    }
    if (!ref.current) {
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setIsVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin: '160px 0px' },
    );

    observer.observe(ref.current);
    return () => observer.disconnect();
  }, [isVisible]);

  return [ref, isVisible] as const;
}

export default function MyVehicle({ currentUser, activeAssignment }: MyVehicleProps) {
  const vehicle = activeAssignment?.vehicle || null;
  const hasAssignedVehicle = Boolean(activeAssignment && vehicle);
  const [preventiveSectionRef, shouldLoadPreventive] = useVisibilityOnce<HTMLDivElement>();
  const [maintenanceSectionRef, shouldLoadMaintenance] = useVisibilityOnce<HTMLDivElement>();
  const [maintenanceJobs, setMaintenanceJobs] = useState<MaintenanceJob[]>([]);
  const [isLoadingMaintenance, setIsLoadingMaintenance] = useState(false);
  const [maintenanceError, setMaintenanceError] = useState('');
  const [preventiveSchedules, setPreventiveSchedules] = useState<PreventiveSchedule[]>([]);
  const [complianceRecords, setComplianceRecords] = useState<ComplianceRecord[]>([]);
  const [isLoadingPreventive, setIsLoadingPreventive] = useState(false);
  const [preventiveError, setPreventiveError] = useState('');
  const [driverUpdateJobId, setDriverUpdateJobId] = useState<string | null>(null);
  const [driverUpdateNote, setDriverUpdateNote] = useState('');
  const [driverActionError, setDriverActionError] = useState('');

  const formatValue = (value: string | number | null | undefined) =>
    value === null || value === undefined || value === '' ? 'Not provided' : String(value);

  useEffect(() => {
    if (!hasAssignedVehicle) {
      setMaintenanceJobs([]);
      setMaintenanceError('');
      setIsLoadingMaintenance(false);
      setPreventiveSchedules([]);
      setComplianceRecords([]);
      setPreventiveError('');
      setIsLoadingPreventive(false);
    }
  }, [hasAssignedVehicle]);

  const loadMaintenanceJobs = async () => {
    setIsLoadingMaintenance(true);
    setMaintenanceError('');
    try {
      const maintenanceResponse = await apiRequest<MaintenanceJobsResponse>('/driver/maintenance');
      setMaintenanceJobs(Array.isArray(maintenanceResponse.data?.jobs) ? maintenanceResponse.data.jobs : []);
    } catch (error) {
      setMaintenanceJobs([]);
      if (error instanceof ApiRequestError) {
        setMaintenanceError(error.message);
      } else {
        setMaintenanceError('Unable to load maintenance status right now.');
      }
    } finally {
      setIsLoadingMaintenance(false);
    }
  };

  const loadPreventiveData = async () => {
    setIsLoadingPreventive(true);
    setPreventiveError('');
    try {
      const preventiveResponse = await apiRequest<PreventiveSchedulesResponse>('/driver/preventive-maintenance');
      setPreventiveSchedules(Array.isArray(preventiveResponse.data?.schedules) ? preventiveResponse.data.schedules : []);
      setComplianceRecords(Array.isArray(preventiveResponse.data?.compliance_records) ? preventiveResponse.data.compliance_records : []);
    } catch (error) {
      setPreventiveSchedules([]);
      setComplianceRecords([]);
      if (error instanceof ApiRequestError) {
        setPreventiveError(error.message);
      } else {
        setPreventiveError('Unable to load preventive maintenance reminders right now.');
      }
    } finally {
      setIsLoadingPreventive(false);
    }
  };

  useEffect(() => {
    if (!hasAssignedVehicle || !shouldLoadPreventive || isLoadingPreventive || preventiveSchedules.length || complianceRecords.length || preventiveError) {
      return;
    }
    void loadPreventiveData();
  }, [complianceRecords.length, hasAssignedVehicle, isLoadingPreventive, preventiveError, preventiveSchedules.length, shouldLoadPreventive]);

  useEffect(() => {
    if (!hasAssignedVehicle || !shouldLoadMaintenance || isLoadingMaintenance || maintenanceJobs.length || maintenanceError) {
      return;
    }
    void loadMaintenanceJobs();
  }, [hasAssignedVehicle]);

  const activeMaintenanceJobs = useMemo(
    () => maintenanceJobs.filter((job) => job.status !== 'completed' && job.status !== 'cancelled'),
    [maintenanceJobs],
  );

  const maintenanceHistory = useMemo(
    () => maintenanceJobs.filter((job) => job.status === 'completed' || job.status === 'cancelled'),
    [maintenanceJobs],
  );

  const preventiveAlerts = useMemo(
    () =>
      preventiveSchedules.filter((schedule) =>
        ['due_soon', 'due', 'overdue'].includes(schedule.status),
      ),
    [preventiveSchedules],
  );

  const complianceAlerts = useMemo(
    () => complianceRecords.filter((record) => ['due_soon', 'expired'].includes(record.status)),
    [complianceRecords],
  );

  const submitDriverMaintenanceUpdate = async (jobId: string, driverConfirmation: 'confirmed' | 'rejected') => {
    setDriverActionError('');
    setDriverUpdateJobId(jobId);
    try {
      await apiRequest<MaintenanceProgressMutationResponse>(`/driver/maintenance/${jobId}/progress`, {
        method: 'POST',
        body: JSON.stringify({
          driver_confirmation: driverConfirmation,
          driver_note: driverUpdateNote || undefined,
        }),
      });
      setDriverUpdateNote('');
      const response = await apiRequest<MaintenanceJobsResponse>('/driver/maintenance');
      setMaintenanceJobs(Array.isArray(response.data?.jobs) ? response.data.jobs : []);
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setDriverActionError(error.message);
      } else {
        setDriverActionError('Unable to send your maintenance confirmation right now.');
      }
    } finally {
      setDriverUpdateJobId(null);
    }
  };

  return (
    <div className="min-h-screen bg-[#F8FAFC] pb-6">
      <div className="mb-6 bg-gradient-to-r from-[#0F172A] to-[#1e293b] p-6">
        <div className="mx-auto max-w-4xl text-white">
          <div className="mb-6 flex items-center gap-3">
            <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-white/20">
              <Car className="h-6 w-6 text-white" />
            </div>
            <div>
              <h1 className="text-2xl font-bold">My Vehicle</h1>
              <p className="text-gray-300">
                {hasAssignedVehicle ? 'Your current assigned vehicle details' : 'No vehicle assigned yet'}
              </p>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            <div className="rounded-lg bg-white/10 p-4">
              <div className="mb-1 text-sm text-gray-300">Driver</div>
              <div className="font-semibold">{currentUser?.full_name || 'Driver'}</div>
            </div>
            <div className="rounded-lg bg-white/10 p-4">
              <div className="mb-1 text-sm text-gray-300">Assignment Status</div>
              <div className="font-semibold capitalize">{activeAssignment?.status || 'not assigned'}</div>
            </div>
            <div className="rounded-lg bg-white/10 p-4">
              <div className="mb-1 text-sm text-gray-300">Assigned Vehicle</div>
              <div className="font-semibold">{getAssignedVehicleLabel(currentUser, activeAssignment)}</div>
            </div>
          </div>
        </div>
      </div>

      <div className="mx-auto max-w-4xl space-y-6 px-4">
        {!hasAssignedVehicle ? (
          <>
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-5">
              <div className="flex items-start gap-3">
                <AlertCircle className="mt-0.5 h-5 w-5 text-amber-600" />
                <div>
                  <h3 className="text-sm font-semibold text-amber-900">No vehicle assigned yet</h3>
                  <p className="mt-1 text-sm text-amber-700">
                    Your driver account does not have an active assignment at the moment. Once an admin
                    assigns a vehicle, it will appear here automatically.
                  </p>
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
              <div className="rounded-xl border border-gray-200 bg-white p-5">
                <div className="mb-4 flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-purple-100">
                    <Gauge className="h-5 w-5 text-purple-600" />
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold text-[#0F172A]">Targets</h3>
                    <p className="text-xs text-gray-500">Defaults when there is no active assignment</p>
                  </div>
                </div>
                <DetailRow label="Weekly Target" value="GHS 0" />
                <DetailRow label="Daily Target" value="GHS 0" />
              </div>

              <div className="rounded-xl border border-gray-200 bg-white p-5">
                <div className="mb-4 flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-green-100">
                    <Shield className="h-5 w-5 text-green-600" />
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold text-[#0F172A]">Vehicle Status</h3>
                    <p className="text-xs text-gray-500">Assignment feed is connected</p>
                  </div>
                </div>
                <p className="text-sm text-gray-600">
                  Vehicle details will populate here automatically when your active assignment is created.
                </p>
              </div>
            </div>
          </>
        ) : (
          <>
            <div className="rounded-xl border border-gray-200 bg-white p-6">
              <div className="mb-6 flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-100">
                  <Truck className="h-5 w-5 text-blue-600" />
                </div>
                <div>
                  <h3 className="text-lg font-semibold text-[#0F172A]">Assigned Vehicle</h3>
                  <p className="text-sm text-gray-500">
                    Live assignment and vehicle details from your driver account.
                  </p>
                </div>
              </div>

              <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
                <div className="rounded-xl border border-gray-100 bg-gray-50 p-5">
                  <h4 className="mb-2 text-base font-semibold text-[#0F172A]">
                    {formatValue(vehicle?.registration_number)}
                  </h4>
                  <p className="text-sm text-gray-500">
                    {formatValue(vehicle?.make)} {formatValue(vehicle?.model)}
                  </p>
                  <div className="mt-4 space-y-1 text-sm text-gray-600">
                    <div>
                      Assignment Status:{' '}
                      <span className="font-medium capitalize text-[#0F172A]">
                        {formatValue(activeAssignment?.status)}
                      </span>
                    </div>
                    <div>
                      Start Date:{' '}
                      <span className="font-medium text-[#0F172A]">
                        {formatValue(activeAssignment?.start_date)}
                      </span>
                    </div>
                  </div>
                </div>

                <div className="rounded-xl border border-gray-100 bg-gray-50 p-5">
                  <div className="mb-4 flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-purple-100">
                      <Gauge className="h-5 w-5 text-purple-600" />
                    </div>
                    <div>
                      <h4 className="text-base font-semibold text-[#0F172A]">Assignment Targets</h4>
                      <p className="text-sm text-gray-500">Current active assignment values</p>
                    </div>
                  </div>
                  <DetailRow label="Weekly Target" value={`GHS ${activeAssignment?.weekly_target || 0}`} />
                  <DetailRow label="Daily Target" value={`GHS ${activeAssignment?.daily_target || 0}`} />
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
              <div className="rounded-xl border border-gray-200 bg-white p-5">
                <div className="mb-4 flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-green-100">
                    <Car className="h-5 w-5 text-green-600" />
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold text-[#0F172A]">Vehicle Details</h3>
                    <p className="text-xs text-gray-500">Core vehicle information from the backend</p>
                  </div>
                </div>
                <DetailRow label="Registration Number" value={formatValue(vehicle?.registration_number)} />
                <DetailRow label="Make" value={formatValue(vehicle?.make)} />
                <DetailRow label="Model" value={formatValue(vehicle?.model)} />
                <DetailRow label="Year" value={formatValue(vehicle?.year)} />
                <DetailRow label="Color" value={formatValue(vehicle?.color)} />
                <DetailRow label="Transmission" value={formatValue(vehicle?.transmission)} />
                <DetailRow label="Fuel Type" value={formatValue(vehicle?.fuel_type)} />
              </div>

              <div className="rounded-xl border border-gray-200 bg-white p-5">
                <div className="mb-4 flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-amber-100">
                    <Calendar className="h-5 w-5 text-amber-600" />
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold text-[#0F172A]">Compliance & Targets</h3>
                    <p className="text-xs text-gray-500">Expiry dates and active target values</p>
                  </div>
                </div>
                <DetailRow label="Insurance Expiry" value={formatValue(vehicle?.insurance_expiry)} />
                <DetailRow label="Roadworthy Expiry" value={formatValue(vehicle?.roadworthy_expiry)} />
                <DetailRow label="Active Compliance Alerts" value={String(complianceAlerts.length)} />
                <DetailRow label="Weekly Target" value={`GHS ${activeAssignment?.weekly_target || 0}`} />
                <DetailRow label="Daily Target" value={`GHS ${activeAssignment?.daily_target || 0}`} />
              </div>
            </div>

            <div ref={preventiveSectionRef} className="rounded-xl border border-gray-200 bg-white p-5">
              <div className="mb-4 flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-amber-100">
                  <AlertCircle className="h-5 w-5 text-amber-600" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-[#0F172A]">Preventive Maintenance Reminders</h3>
                  <p className="text-xs text-gray-500">Upcoming service and compliance reminders for your assigned vehicle</p>
                </div>
              </div>

              {isLoadingPreventive ? (
                <div className="flex items-center gap-3 rounded-xl border border-gray-200 bg-gray-50 px-4 py-5 text-sm text-gray-600">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Loading preventive reminders...
                </div>
              ) : preventiveError ? (
                <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-4 text-sm text-red-700">
                  {preventiveError}
                </div>
              ) : preventiveAlerts.length === 0 ? (
                <div className="rounded-xl border border-dashed border-gray-200 bg-gray-50 px-4 py-5 text-sm text-gray-600">
                  No preventive maintenance alerts for your vehicle right now.
                </div>
              ) : (
                <div className="space-y-3">
                  {preventiveAlerts.map((schedule) => (
                    <div
                      key={schedule.id}
                      className={`rounded-xl border px-4 py-4 ${
                        schedule.status === 'overdue'
                          ? 'border-rose-200 bg-rose-50'
                          : schedule.status === 'due'
                            ? 'border-orange-200 bg-orange-50'
                            : 'border-amber-200 bg-amber-50'
                      }`}
                    >
                      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                        <div>
                          <h4 className="text-sm font-semibold text-[#0F172A]">{schedule.title}</h4>
                          <p className="mt-1 text-sm text-gray-600">
                            {schedule.description || 'Scheduled preventive maintenance reminder.'}
                          </p>
                        </div>
                        <span
                          className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${preventiveStatusBadgeClass(schedule.status)}`}
                        >
                          {formatLabel(schedule.status)}
                        </span>
                      </div>

                      <div className="mt-3 grid grid-cols-1 gap-3 text-sm text-gray-600 md:grid-cols-2">
                        <div>
                          <span className="font-medium text-[#0F172A]">Type:</span> {formatLabel(schedule.maintenance_type)}
                        </div>
                        <div>
                          <span className="font-medium text-[#0F172A]">Next Due Date:</span> {formatDate(schedule.next_due_date)}
                        </div>
                        <div>
                          <span className="font-medium text-[#0F172A]">Next Due Odometer:</span>{' '}
                          {schedule.next_due_odometer != null ? `${schedule.next_due_odometer.toLocaleString()} km` : 'Not set'}
                        </div>
                      </div>
                    </div>
                  ))}
                  {complianceAlerts.map((record) => (
                    <div
                      key={record.id}
                      className={`rounded-xl border px-4 py-4 ${
                        record.status === 'expired' ? 'border-rose-200 bg-rose-50' : 'border-amber-200 bg-amber-50'
                      }`}
                    >
                      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                        <div>
                          <h4 className="text-sm font-semibold text-[#0F172A]">{record.compliance_item_name}</h4>
                          <p className="mt-1 text-sm text-gray-600">
                            {record.provider_or_authority_name || 'Compliance renewal reminder for your assigned vehicle.'}
                          </p>
                        </div>
                        <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${preventiveStatusBadgeClass(record.status === 'expired' ? 'overdue' : 'due_soon')}`}>
                          {formatLabel(record.status)}
                        </span>
                      </div>
                      <div className="mt-3 text-sm text-gray-600">
                        <span className="font-medium text-[#0F172A]">Expiry Date:</span> {formatDate(record.expiry_date)}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div ref={maintenanceSectionRef} className="rounded-xl border border-gray-200 bg-white p-5">
              <div className="mb-4 flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-100">
                  <Wrench className="h-5 w-5 text-blue-600" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-[#0F172A]">Maintenance Status</h3>
                  <p className="text-xs text-gray-500">Live maintenance jobs for your assigned vehicle</p>
                </div>
              </div>

              {isLoadingMaintenance ? (
                <div className="flex items-center gap-3 rounded-xl border border-gray-200 bg-gray-50 px-4 py-5 text-sm text-gray-600">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Loading maintenance status...
                </div>
              ) : maintenanceError ? (
                <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-4 text-sm text-red-700">
                  {maintenanceError}
                </div>
              ) : activeMaintenanceJobs.length === 0 ? (
                <div className="rounded-xl border border-dashed border-gray-200 bg-gray-50 px-4 py-5 text-sm text-gray-600">
                  No active maintenance jobs for this vehicle right now.
                </div>
              ) : (
                <div className="space-y-4">
                  {driverActionError && (
                    <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-4 text-sm text-red-700">
                      {driverActionError}
                    </div>
                  )}
                  {activeMaintenanceJobs.map((job) => (
                    <div
                      key={job.id}
                      className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-4"
                    >
                      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                        <div className="min-w-0">
                          <h4 className="text-sm font-semibold text-[#0F172A]">{job.title}</h4>
                          <p className="mt-1 text-sm text-gray-600">{job.service_note || 'No service note shared yet.'}</p>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          <span
                            className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${statusBadgeClass(job.status)}`}
                          >
                            {formatLabel(job.status)}
                          </span>
                          {job.driver_confirmation_status ? (
                            <span className="inline-flex rounded-full border border-cyan-200 bg-cyan-100 px-2.5 py-1 text-xs font-medium text-cyan-800">
                              Driver {formatLabel(job.driver_confirmation_status)}
                            </span>
                          ) : null}
                        </div>
                      </div>

                      <div className="mt-4 grid grid-cols-1 gap-3 text-sm text-gray-600 md:grid-cols-2 xl:grid-cols-4">
                        <div>
                          <span className="font-medium text-[#0F172A]">Type:</span> {formatLabel(job.maintenance_type)}
                        </div>
                        <div>
                          <span className="font-medium text-[#0F172A]">Vehicle:</span> {job.vehicle?.registration_number || 'Assigned vehicle'}
                        </div>
                        <div>
                          <span className="font-medium text-[#0F172A]">Start Date:</span> {formatDate(job.start_date)}
                        </div>
                        <div>
                          <span className="font-medium text-[#0F172A]">Target Completion:</span>{' '}
                          {formatDate(job.target_completion_date)}
                        </div>
                        <div>
                          <span className="font-medium text-[#0F172A]">Current Stage:</span>{' '}
                          {formatLabel(job.current_stage || 'assigned_to_mechanic')}
                        </div>
                        <div className="md:col-span-2 xl:col-span-4">
                          <span className="font-medium text-[#0F172A]">Next Action:</span>{' '}
                          {job.next_action || 'No next action shared yet.'}
                        </div>
                        <div>
                          <span className="font-medium text-[#0F172A]">Next Follow-up:</span>{' '}
                          {formatDate(job.next_follow_up_date)}
                        </div>
                      </div>

                      {job.current_stage === 'ready_for_driver_test' && (
                        <div className="mt-4 rounded-xl border border-cyan-200 bg-cyan-50 p-4">
                          <div className="text-sm font-semibold text-cyan-900">Vehicle Ready For Driver Test</div>
                          <p className="mt-1 text-sm text-cyan-800">
                            Test the vehicle and confirm whether the issue has been fixed. If it still has issues, report that here so the coordinator can continue follow-up.
                          </p>
                          <textarea
                            value={driverUpdateNote}
                            onChange={(event) => setDriverUpdateNote(event.target.value)}
                            className="mt-3 min-h-[96px] w-full rounded-lg border border-cyan-200 bg-white px-4 py-2.5 text-sm text-gray-700 focus:border-transparent focus:ring-2 focus:ring-cyan-500"
                            placeholder="Add your test feedback or note what still needs attention."
                          />
                          <div className="mt-3 flex flex-col gap-3 sm:flex-row">
                            <button
                              type="button"
                              disabled={driverUpdateJobId === job.id}
                              onClick={() => void submitDriverMaintenanceUpdate(job.id, 'confirmed')}
                              className="inline-flex items-center justify-center gap-2 rounded-lg bg-green-600 px-4 py-2.5 text-sm font-medium text-white transition-all hover:bg-green-700 disabled:cursor-not-allowed disabled:opacity-70"
                            >
                              {driverUpdateJobId === job.id ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                              Confirm Fixed
                            </button>
                            <button
                              type="button"
                              disabled={driverUpdateJobId === job.id}
                              onClick={() => void submitDriverMaintenanceUpdate(job.id, 'rejected')}
                              className="inline-flex items-center justify-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm font-medium text-red-700 transition-all hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-70"
                            >
                              {driverUpdateJobId === job.id ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                              Report Not Fixed
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="rounded-xl border border-gray-200 bg-white p-5">
              <div className="mb-4 flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-slate-100">
                  <Calendar className="h-5 w-5 text-slate-600" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-[#0F172A]">Maintenance History</h3>
                  <p className="text-xs text-gray-500">Completed and closed maintenance work for this vehicle</p>
                </div>
              </div>

              {isLoadingMaintenance ? (
                <div className="flex items-center gap-3 rounded-xl border border-gray-200 bg-gray-50 px-4 py-5 text-sm text-gray-600">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Loading maintenance history...
                </div>
              ) : maintenanceError ? (
                <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-4 text-sm text-red-700">
                  {maintenanceError}
                </div>
              ) : maintenanceHistory.length === 0 ? (
                <div className="rounded-xl border border-dashed border-gray-200 bg-gray-50 px-4 py-5 text-sm text-gray-600">
                  No maintenance history recorded yet.
                </div>
              ) : (
                <div className="space-y-3">
                  {maintenanceHistory.map((job) => (
                    <div key={job.id} className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-4">
                      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                        <div>
                          <h4 className="text-sm font-semibold text-[#0F172A]">{job.title}</h4>
                          <p className="mt-1 text-sm text-gray-600">
                            {job.service_note || 'No service note shared yet.'}
                          </p>
                        </div>
                        <span
                          className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${statusBadgeClass(job.status)}`}
                        >
                          {formatLabel(job.status)}
                        </span>
                      </div>

                      <div className="mt-3 grid grid-cols-1 gap-3 text-sm text-gray-600 md:grid-cols-2 xl:grid-cols-4">
                        <div>
                          <span className="font-medium text-[#0F172A]">Completed:</span>{' '}
                          {formatDate(job.completion_date)}
                        </div>
                        <div>
                          <span className="font-medium text-[#0F172A]">Type:</span> {formatLabel(job.maintenance_type)}
                        </div>
                        <div>
                          <span className="font-medium text-[#0F172A]">Vehicle:</span> {job.vehicle?.registration_number || 'Assigned vehicle'}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
