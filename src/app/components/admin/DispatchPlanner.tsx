import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  AlertTriangle,
  CalendarDays,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  ClipboardList,
  Clock3,
  Eye,
  Loader2,
  RefreshCcw,
  Search,
  ShieldAlert,
  Truck,
  UserRound,
} from 'lucide-react';
import { toast } from 'sonner';

import { ApiRequestError, isRequestAborted } from '../../lib/api';
import { getStoredSessionUser } from '../../lib/auth-session';
import {
  combineLocalDateAndTime,
  formatDateTimeSafe,
  toDateInputValue,
  toDateTimeLocalInputValue,
  toIsoDateTime,
  toTimeInputValue,
} from '../../lib/date-time';
import { fetchDispatchRequestById, type DispatchRequestRecord } from '../../lib/dispatch-request-api';
import {
  assignDispatchPlannerJob,
  cancelPlannerOperation,
  correctDispatchPlannerJobSchedule,
  detectPlannerConflicts,
  fetchDispatchPlannerJob,
  fetchDispatchPlannerJobs,
  fetchPlannerAvailability,
  fetchPlannerOptions,
  fetchPlannerRequests,
  planPlannerOperation,
  reassignDispatchPlannerJob,
  reassignPlannerOperation,
  reserveDispatchPlannerJob,
  saveDispatchPlannerDraft,
  type DispatchPlannerAvailabilityResponse,
  type DispatchPlannerJobRecord,
  type DispatchPlannerOptionsResponse,
  type PlannerRequestRecord,
} from '../../lib/dispatch-planner-api';
import { useDebouncedValue } from '../../lib/use-debounced-value';
import { Drawer, DrawerContent, DrawerDescription, DrawerHeader, DrawerTitle } from '../ui/drawer';
import { SearchableSelect, type SearchableSelectOption } from '../ui/searchable-select';
import { Skeleton } from '../ui/skeleton';

interface PlannerFormState {
  vehicle_id: string;
  driver_id: string;
  assistant_id: string;
  dispatcher_id: string;
  pickup: string;
  destination: string;
  dispatch_date: string;
  dispatch_time: string;
  expected_arrival_time: string;
  expected_return_time: string;
  distance_estimate_km: string;
  goods_description: string;
  quantity: string;
  weight_category: string;
  fragile: boolean;
  refrigerated: boolean;
  hazardous: boolean;
  restriction_acknowledged: boolean;
  loading_notes: string;
  customer_contact: string;
  receiver_contact: string;
  dispatch_instructions: string;
  internal_notes: string;
}

const sessionUser = getStoredSessionUser();

function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof ApiRequestError ? error.message : fallback;
}

function formatDateTime(value?: string | null) {
  if (!value) {
    return 'Not scheduled';
  }
  return formatDateTimeSafe(value);
}

function buildPlannerForm(requestRecord?: Partial<PlannerRequestRecord & DispatchRequestRecord> | null): PlannerFormState {
  return {
    vehicle_id: requestRecord?.vehicle_id || '',
    driver_id: requestRecord?.driver_id || '',
    assistant_id: '',
    dispatcher_id: sessionUser?.id || '',
    pickup: requestRecord?.pickup_location || '',
    destination: requestRecord?.destination || '',
    dispatch_date: requestRecord?.scheduled_start_time ? toDateInputValue(requestRecord.scheduled_start_time) : toDateInputValue(requestRecord?.preferred_pickup_date),
    dispatch_time: requestRecord?.scheduled_start_time ? toTimeInputValue(requestRecord.scheduled_start_time) : toTimeInputValue(requestRecord?.preferred_pickup_time),
    expected_arrival_time: toDateTimeLocalInputValue(requestRecord?.expected_delivery_time),
    expected_return_time: toDateTimeLocalInputValue(requestRecord?.expected_return_time),
    distance_estimate_km: '',
    goods_description: requestRecord?.load_description || '',
    quantity: '',
    weight_category: requestRecord?.load_weight_category || '',
    fragile: false,
    refrigerated: false,
    hazardous: false,
    restriction_acknowledged: false,
    loading_notes: '',
    customer_contact: requestRecord?.customer_phone || '',
    receiver_contact: '',
    dispatch_instructions: '',
    internal_notes: '',
  };
}

function buildPlannerFormFromJob(job: DispatchPlannerJobRecord): PlannerFormState {
  return {
    vehicle_id: job.vehicle_id || '',
    driver_id: job.driver_id || '',
    assistant_id: job.assistant_id || '',
    dispatcher_id: job.dispatcher_id || sessionUser?.id || '',
    pickup: job.pickup || '',
    destination: job.destination || '',
    dispatch_date: toDateInputValue(job.dispatch_date) || toDateInputValue(job.scheduled_start_time),
    dispatch_time: toTimeInputValue(job.dispatch_time) || toTimeInputValue(job.scheduled_start_time),
    expected_arrival_time: toDateTimeLocalInputValue(job.expected_arrival_time),
    expected_return_time: toDateTimeLocalInputValue(job.expected_return_time),
    distance_estimate_km:
      job.distance_estimate_km === null || job.distance_estimate_km === undefined
        ? ''
        : String(job.distance_estimate_km),
    goods_description: job.goods_description || '',
    quantity: job.quantity || '',
    weight_category: job.weight_category || '',
    fragile: Boolean(job.fragile),
    refrigerated: Boolean(job.refrigerated),
    hazardous: Boolean(job.hazardous),
    restriction_acknowledged: Boolean(job.restriction_acknowledged),
    loading_notes: job.loading_notes || '',
    customer_contact: job.customer_contact || '',
    receiver_contact: job.receiver_contact || '',
    dispatch_instructions: job.dispatch_instructions || '',
    internal_notes: job.internal_notes || '',
  };
}

function buildSearchableUserOptions(
  users: Array<{ id: string; full_name: string; phone?: string | null; email?: string | null; role?: string | null }>,
): SearchableSelectOption[] {
  return users.map((user) => ({
    value: user.id,
    label: user.full_name,
    description: [user.role, user.phone || user.email].filter(Boolean).join(' • '),
    keywords: [user.full_name, user.phone || '', user.email || '', user.role || ''],
  }));
}

function buildSearchableVehicleOptions(
  vehicles: Array<{ id: string; registration_number: string; vehicle_type?: string | null; make?: string | null; model?: string | null }>,
): SearchableSelectOption[] {
  return vehicles.map((vehicle) => ({
    value: vehicle.id,
    label: vehicle.registration_number,
    description: [vehicle.vehicle_type, [vehicle.make, vehicle.model].filter(Boolean).join(' ')].filter(Boolean).join(' • '),
    keywords: [vehicle.registration_number, vehicle.vehicle_type || '', vehicle.make || '', vehicle.model || ''],
  }));
}

function buildDraftPayload(form: PlannerFormState, requestDetail: DispatchRequestRecord | null, currentJobId: string | null) {
  return {
    job_id: currentJobId || undefined,
    vehicle_id: form.vehicle_id || undefined,
    driver_id: form.driver_id || undefined,
    assistant_id: form.assistant_id || undefined,
    dispatcher_id: form.dispatcher_id || undefined,
    pickup: form.pickup || undefined,
    destination: form.destination || undefined,
    dispatch_date: form.dispatch_date || undefined,
    dispatch_time: form.dispatch_time || undefined,
    expected_arrival_time: toIsoDateTime(form.expected_arrival_time) || undefined,
    expected_return_time: toIsoDateTime(form.expected_return_time) || undefined,
    distance_estimate_km: form.distance_estimate_km ? Number(form.distance_estimate_km) : undefined,
    goods_description: form.goods_description || undefined,
    quantity: form.quantity || undefined,
    weight_category: form.weight_category || undefined,
    fragile: form.fragile,
    refrigerated: form.refrigerated,
    hazardous: form.hazardous,
    restriction_acknowledged: form.restriction_acknowledged,
    loading_notes: form.loading_notes || undefined,
    customer_contact: form.customer_contact || undefined,
    receiver_contact: form.receiver_contact || undefined,
    dispatch_instructions: form.dispatch_instructions || undefined,
    internal_notes: form.internal_notes || undefined,
    stops: requestDetail?.stops || [],
  };
}

function AvailabilityMetric({
  label,
  value,
  accent,
}: {
  label: string;
  value: number | undefined;
  accent: string;
}) {
  return (
    <div className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
      <div className={`text-xs font-semibold uppercase tracking-[0.18em] ${accent}`}>{label}</div>
      <div className="mt-3 text-3xl font-semibold text-slate-900">{value ?? 0}</div>
    </div>
  );
}

export default function DispatchPlanner() {
  const [requests, setRequests] = useState<PlannerRequestRecord[]>([]);
  const [requestPagination, setRequestPagination] = useState({ page: 1, page_size: 10, total: 0, total_pages: 1 });
  const [jobs, setJobs] = useState<DispatchPlannerJobRecord[]>([]);
  const [jobsPagination, setJobsPagination] = useState({ page: 1, page_size: 10, total: 0, total_pages: 1 });
  const [options, setOptions] = useState<DispatchPlannerOptionsResponse | null>(null);
  const [availability, setAvailability] = useState<DispatchPlannerAvailabilityResponse | null>(null);
  const [selectedRequest, setSelectedRequest] = useState<PlannerRequestRecord | null>(null);
  const [selectedRequestDetail, setSelectedRequestDetail] = useState<DispatchRequestRecord | null>(null);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [currentJob, setCurrentJob] = useState<DispatchPlannerJobRecord | null>(null);
  const [plannerForm, setPlannerForm] = useState<PlannerFormState>(buildPlannerForm());
  const [conflicts, setConflicts] = useState<{ vehicle_conflicts: string[]; driver_conflicts: string[]; has_conflicts: boolean; vehicle_restrictions: Array<{ override_id: string; operational_restriction: string; repair_deadline?: string | null }>; restriction_acknowledgement_required: boolean }>({
    vehicle_conflicts: [],
    driver_conflicts: [],
    has_conflicts: false,
    vehicle_restrictions: [],
    restriction_acknowledgement_required: false,
  });
  const [isDirty, setIsDirty] = useState(false);
  const [isLoadingRequests, setIsLoadingRequests] = useState(true);
  const [isLoadingJobs, setIsLoadingJobs] = useState(true);
  const [isLoadingOptions, setIsLoadingOptions] = useState(true);
  const [isLoadingAvailability, setIsLoadingAvailability] = useState(true);
  const [isLoadingRequestDetail, setIsLoadingRequestDetail] = useState(false);
  const [isCheckingConflicts, setIsCheckingConflicts] = useState(false);
  const [conflictError, setConflictError] = useState('');
  const [isSavingDraft, setIsSavingDraft] = useState(false);
  const [isReserving, setIsReserving] = useState(false);
  const [isAssigning, setIsAssigning] = useState(false);
  const [isReassigning, setIsReassigning] = useState(false);
  const [isCorrectingSchedule, setIsCorrectingSchedule] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [loadingJobId, setLoadingJobId] = useState<string | null>(null);
  const [loadingDetailJobId, setLoadingDetailJobId] = useState<string | null>(null);
  const [isDetailOpen, setIsDetailOpen] = useState(false);
  const [detailJob, setDetailJob] = useState<DispatchPlannerJobRecord | null>(null);
  const [isLoadingDetail, setIsLoadingDetail] = useState(false);
  const [pageError, setPageError] = useState('');
  const [formError, setFormError] = useState('');
  const [detailError, setDetailError] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [planningStatusFilter, setPlanningStatusFilter] = useState('');
  const [jobStatusFilter, setJobStatusFilter] = useState('');
  const [requestPage, setRequestPage] = useState(1);
  const [jobPage, setJobPage] = useState(1);
  const debouncedSearchQuery = useDebouncedValue(searchQuery, 300);
  const actionLocks = useRef(new Set<string>());
  const conflictCheckSequence = useRef(0);
  const requestDetailSequence = useRef(0);
  const requestLoadSequence = useRef(0);
  const jobLoadSequence = useRef(0);
  const availabilityLoadSequence = useRef(0);

  const vehicleOptions = useMemo(() => buildSearchableVehicleOptions(options?.vehicles || []), [options?.vehicles]);
  const driverOptions = useMemo(() => buildSearchableUserOptions(options?.drivers || []), [options?.drivers]);
  const assistantOptions = useMemo(() => buildSearchableUserOptions(options?.assistants || []), [options?.assistants]);
  const dispatcherOptions = useMemo(() => buildSearchableUserOptions(options?.dispatchers || []), [options?.dispatchers]);
  const selectedDateWarnings = useMemo(() => {
    const warnings = [...(selectedRequest?.date_warnings || [])];
    if (selectedRequest?.scheduled_start_time && (
      !toDateInputValue(selectedRequest.scheduled_start_time) || !toTimeInputValue(selectedRequest.scheduled_start_time)
    )) warnings.push('The stored schedule date or time is invalid. Set a valid schedule before confirming.');
    if (selectedRequest?.expected_return_time && !toDateTimeLocalInputValue(selectedRequest.expected_return_time)) {
      warnings.push('The stored expected return time is invalid. Set a valid return time before confirming.');
    }
    return [...new Set(warnings)];
  }, [selectedRequest]);

  const loadRequests = async (force = false) => {
    const sequence = ++requestLoadSequence.current;
    setIsLoadingRequests(true);
    setPageError('');
    try {
      const response = await fetchPlannerRequests({
        page: requestPage,
        page_size: 10,
        q: debouncedSearchQuery || undefined,
        planning_status: planningStatusFilter || undefined,
        operation_type: 'all',
        force,
      });
      if (sequence !== requestLoadSequence.current) return false;
      setRequests(response.requests || []);
      setRequestPagination(response.pagination || { page: 1, page_size: 10, total: 0, total_pages: 1 });
      return true;
    } catch (error) {
      if (sequence !== requestLoadSequence.current || isRequestAborted(error)) return false;
      setRequests([]);
      setPageError(getErrorMessage(error, 'Unable to load dispatch requests for planning right now.'));
      return false;
    } finally {
      if (sequence === requestLoadSequence.current) setIsLoadingRequests(false);
    }
  };

  const loadJobs = async (force = false) => {
    const sequence = ++jobLoadSequence.current;
    setIsLoadingJobs(true);
    try {
      const response = await fetchDispatchPlannerJobs({
        page: jobPage,
        page_size: 10,
        status: jobStatusFilter || undefined,
        force,
      });
      if (sequence !== jobLoadSequence.current) return false;
      setJobs(response.jobs || []);
      setJobsPagination(response.pagination || { page: 1, page_size: 10, total: 0, total_pages: 1 });
      return true;
    } catch (error) {
      if (sequence !== jobLoadSequence.current || isRequestAborted(error)) return false;
      setJobs([]);
      setPageError(getErrorMessage(error, 'Unable to load dispatch jobs right now.'));
      return false;
    } finally {
      if (sequence === jobLoadSequence.current) setIsLoadingJobs(false);
    }
  };

  const loadOptions = async () => {
    setIsLoadingOptions(true);
    try {
      const response = await fetchPlannerOptions();
      setOptions(response);
    } catch (error) {
      setPageError(getErrorMessage(error, 'Dispatch planner options are unavailable right now.'));
    } finally {
      setIsLoadingOptions(false);
    }
  };

  const loadAvailability = async (force = false) => {
    const sequence = ++availabilityLoadSequence.current;
    setIsLoadingAvailability(true);
    try {
      const response = await fetchPlannerAvailability(force);
      if (sequence !== availabilityLoadSequence.current) return false;
      setAvailability(response);
      return true;
    } catch (error) {
      if (sequence !== availabilityLoadSequence.current || isRequestAborted(error)) return false;
      setPageError(getErrorMessage(error, 'Fleet availability is temporarily unavailable.'));
      return false;
    } finally {
      if (sequence === availabilityLoadSequence.current) setIsLoadingAvailability(false);
    }
  };

  useEffect(() => {
    void loadOptions();
    void loadAvailability();
  }, []);

  useEffect(() => {
    void loadRequests();
  }, [requestPage, debouncedSearchQuery, planningStatusFilter]);

  useEffect(() => {
    void loadJobs();
  }, [jobPage, jobStatusFilter]);

  useEffect(() => {
    const sequence = ++requestDetailSequence.current;
    if (!selectedRequest?.id) {
      setIsLoadingRequestDetail(false);
      setSelectedRequestDetail(null);
      return;
    }
    if ((selectedRequest.planner_operation_type || 'dispatch') !== 'dispatch') {
      setIsLoadingRequestDetail(false);
      setSelectedRequestDetail(null);
      setPlannerForm(buildPlannerForm(selectedRequest));
      setCurrentJob(null);
      setSelectedJobId(null);
      return;
    }
    setIsLoadingRequestDetail(true);
    setFormError('');
    void fetchDispatchRequestById(selectedRequest.id)
      .then((requestDetail) => {
        if (sequence !== requestDetailSequence.current) return;
        setSelectedRequestDetail(requestDetail);
        if (!currentJob || currentJob.dispatch_request_id !== selectedRequest.id) {
          setPlannerForm(buildPlannerForm(requestDetail));
          setCurrentJob(null);
          setSelectedJobId(null);
          setIsDirty(false);
        }
      })
      .catch((error) => {
        if (sequence !== requestDetailSequence.current) return;
        setSelectedRequestDetail(null);
        setFormError(getErrorMessage(error, 'Unable to load this dispatch request for planning.'));
      })
      .finally(() => {
        if (sequence === requestDetailSequence.current) setIsLoadingRequestDetail(false);
      });
  }, [selectedRequest?.id]);

  useEffect(() => {
    const scheduledStart = combineLocalDateAndTime(plannerForm.dispatch_date, plannerForm.dispatch_time);
    if (!plannerForm.vehicle_id && !plannerForm.driver_id) {
      conflictCheckSequence.current += 1;
      setIsCheckingConflicts(false);
      setConflictError('');
      setConflicts({ vehicle_conflicts: [], driver_conflicts: [], has_conflicts: false, vehicle_restrictions: [], restriction_acknowledgement_required: false });
      return;
    }
    const expectedReturn = toIsoDateTime(plannerForm.expected_return_time);
    if (!scheduledStart || !expectedReturn) {
      conflictCheckSequence.current += 1;
      setIsCheckingConflicts(false);
      setConflictError('');
      return;
    }
    const sequence = ++conflictCheckSequence.current;
    setIsCheckingConflicts(true);
    setConflictError('');
    const timeout = window.setTimeout(() => {
      void detectPlannerConflicts({
        vehicle_id: plannerForm.vehicle_id || undefined,
        driver_id: plannerForm.driver_id || undefined,
        scheduled_start_time: scheduledStart,
        expected_return_time: expectedReturn,
        exclude_job_id: currentJob?.id || undefined,
        exclude_movement_id: selectedRequest?.linked_vehicle_movement_id || undefined,
      })
        .then((response) => {
          if (sequence === conflictCheckSequence.current) setConflicts(response);
        })
        .catch((error) => {
          if (sequence === conflictCheckSequence.current) {
            setConflictError(getErrorMessage(error, 'Unable to check resource availability. Try again before confirming.'));
          }
        })
        .finally(() => {
          if (sequence === conflictCheckSequence.current) setIsCheckingConflicts(false);
        });
    }, 250);
    return () => {
      window.clearTimeout(timeout);
      if (sequence === conflictCheckSequence.current) setIsCheckingConflicts(false);
    };
  }, [
    plannerForm.vehicle_id,
    plannerForm.driver_id,
    plannerForm.dispatch_date,
    plannerForm.dispatch_time,
    plannerForm.expected_return_time,
    currentJob?.id,
    selectedRequest?.linked_vehicle_movement_id,
  ]);

  const handleSelectRequest = (requestRecord: PlannerRequestRecord) => {
    setSelectedRequest(requestRecord);
    setSelectedRequestDetail(null);
    setPlannerForm(buildPlannerForm(requestRecord));
    setCurrentJob(null);
    setSelectedJobId(null);
    setConflicts({ vehicle_conflicts: [], driver_conflicts: [], has_conflicts: false, vehicle_restrictions: [], restriction_acknowledgement_required: false });
    setFormError('');
    setIsDirty(false);
  };

  const handleLoadJobIntoPlanner = async (job: DispatchPlannerJobRecord) => {
    if (actionLocks.current.has(`load-job:${job.id}`)) return;
    setLoadingJobId(job.id);
    setSelectedJobId(job.id);
    setCurrentJob(job);
    setPlannerForm(buildPlannerFormFromJob(job));
    setIsDirty(false);
    setFormError('');
    actionLocks.current.add(`load-job:${job.id}`);
    try {
      const requestDetail = await fetchDispatchRequestById(job.dispatch_request_id);
      setSelectedRequest({
        id: requestDetail.id,
        request_id: requestDetail.request_id,
        customer_name: requestDetail.customer_name,
        customer_phone: requestDetail.customer_phone,
        pickup_location: requestDetail.pickup_location,
        destination: requestDetail.destination,
        vehicle_type_needed: requestDetail.vehicle_type_needed,
        urgency: requestDetail.urgency,
        status: requestDetail.status,
        planning_status: job.status,
        scheduled_start_time: requestDetail.scheduled_start_time,
        pricing_status: requestDetail.pricing_status,
        load_description: requestDetail.load_description,
        stops_count: requestDetail.stops_count,
        created_at: requestDetail.created_at,
        updated_at: requestDetail.updated_at,
      });
      setSelectedRequestDetail(requestDetail);
    } catch (error) {
      const message = getErrorMessage(error, 'Unable to load the linked dispatch request.');
      setFormError(message);
      toast.error(message, { id: `planner:load-job:${job.id}` });
    } finally {
      actionLocks.current.delete(`load-job:${job.id}`);
      setLoadingJobId(null);
    }
  };

  const handleFormChange = <K extends keyof PlannerFormState>(field: K, value: PlannerFormState[K]) => {
    setPlannerForm((current) => ({ ...current, [field]: value }));
    setIsDirty(true);
    setFormError('');
  };

  const ensureDraft = async () => {
    if (!selectedRequest?.id) {
      throw new ApiRequestError('Select an approved dispatch request before planning.', 400);
    }
    const payload = buildDraftPayload(plannerForm, selectedRequestDetail, currentJob?.id || null);
    const job = await saveDispatchPlannerDraft(selectedRequest.id, payload);
    setCurrentJob(job);
    setSelectedJobId(job.id);
    setPlannerForm(buildPlannerFormFromJob(job));
    setIsDirty(false);
    return job;
  };

  const handleSaveDraft = async () => {
    if (actionLocks.current.has('mutation') || actionLocks.current.has('save')) return;
    actionLocks.current.add('mutation');
    actionLocks.current.add('save');
    toast.dismiss('planner:save');
    setIsSavingDraft(true);
    setFormError('');
    try {
      const job = await ensureDraft();
      toast.success('Changes saved', { id: 'planner:save' });
      await Promise.all([loadRequests(true), loadJobs(true), loadAvailability(true)]);
    } catch (error) {
      const message = getErrorMessage(error, 'Unable to save this dispatch draft.');
      setFormError(message);
      toast.error(message, { id: 'planner:save' });
    } finally {
      actionLocks.current.delete('save');
      actionLocks.current.delete('mutation');
      setIsSavingDraft(false);
    }
  };

  const handleReserve = async () => {
    if (actionLocks.current.has('mutation') || actionLocks.current.has('reserve')) return;
    actionLocks.current.add('mutation');
    actionLocks.current.add('reserve');
    toast.dismiss('planner:reserve');
    setIsReserving(true);
    setFormError('');
    try {
      const draftJob = isDirty || !currentJob ? await ensureDraft() : currentJob;
      const reservedJob = await reserveDispatchPlannerJob(draftJob.id);
      setCurrentJob(reservedJob);
      setSelectedJobId(reservedJob.id);
      setPlannerForm(buildPlannerFormFromJob(reservedJob));
      setIsDirty(false);
      toast.success(`Resources reserved for ${reservedJob.dispatch_job_id}.`, { id: 'planner:reserve' });
      await Promise.all([loadRequests(true), loadJobs(true), loadAvailability(true)]);
    } catch (error) {
      const message = getErrorMessage(error, 'Unable to reserve these resources.');
      setFormError(message);
      toast.error(message, { id: 'planner:reserve' });
    } finally {
      actionLocks.current.delete('reserve');
      actionLocks.current.delete('mutation');
      setIsReserving(false);
    }
  };

  const handleAssign = async () => {
    if (actionLocks.current.has('mutation') || actionLocks.current.has('assign')) return;
    actionLocks.current.add('mutation');
    actionLocks.current.add('assign');
    toast.dismiss('planner:assign');
    setIsAssigning(true);
    setFormError('');
    try {
      if (selectedDateWarnings.length) throw new ApiRequestError(selectedDateWarnings[0], 400);
      if (isCheckingConflicts) throw new ApiRequestError('Availability is still being checked. Please wait a moment.', 409);
      if (conflictError) throw new ApiRequestError(conflictError, 409);
      if (conflicts.has_conflicts) {
        throw new ApiRequestError(
          [...conflicts.vehicle_conflicts, ...conflicts.driver_conflicts][0] || 'Resolve resource conflicts before confirming.',
          409,
        );
      }
      const operationType = selectedRequest?.planner_operation_type || 'dispatch';
      if (selectedRequest && operationType !== 'dispatch') {
        const scheduledStart = combineLocalDateAndTime(plannerForm.dispatch_date, plannerForm.dispatch_time);
        if (!scheduledStart) {
          throw new ApiRequestError('A schedule date and time are required.', 400);
        }
        const operationPayload = {
          vehicle_id: plannerForm.vehicle_id,
          driver_id: plannerForm.driver_id,
          scheduled_start_time: scheduledStart,
          expected_return_time: toIsoDateTime(plannerForm.expected_return_time) || undefined,
        };
        if (selectedRequest.status === 'scheduled') {
          await reassignPlannerOperation(operationType, selectedRequest.id, operationPayload);
          toast.success(`${selectedRequest.request_id} reassigned successfully.`, { id: 'planner:assign' });
        } else {
          await planPlannerOperation(operationType, selectedRequest.id, operationPayload);
          toast.success('Dispatch scheduled', { id: 'planner:assign' });
        }
        setSelectedRequest(null);
        setIsDirty(false);
        await Promise.all([loadRequests(true), loadAvailability(true)]);
        return;
      }
      const draftJob = isDirty || !currentJob ? await ensureDraft() : currentJob;
      const assignedJob = currentJob?.status && currentJob.status !== 'draft'
        ? await assignDispatchPlannerJob(draftJob.id)
        : await assignDispatchPlannerJob(draftJob.id);
      setCurrentJob(assignedJob);
      setSelectedJobId(assignedJob.id);
      setPlannerForm(buildPlannerFormFromJob(assignedJob));
      setIsDirty(false);
      toast.success(`Assignment published to ${assignedJob.driver?.full_name || 'driver'}`, { id: 'planner:assign' });
      await Promise.all([loadRequests(true), loadJobs(true), loadAvailability(true)]);
    } catch (error) {
      const message = getErrorMessage(error, 'Unable to assign this dispatch.');
      setFormError(message);
      toast.error(message, { id: 'planner:assign' });
    } finally {
      actionLocks.current.delete('assign');
      actionLocks.current.delete('mutation');
      setIsAssigning(false);
    }
  };

  const handleReassign = async () => {
    if (!currentJob?.id) {
      return;
    }
    if (actionLocks.current.has('mutation') || actionLocks.current.has('reassign')) return;
    actionLocks.current.add('mutation');
    actionLocks.current.add('reassign');
    toast.dismiss('planner:reassign');
    setIsReassigning(true);
    setFormError('');
    try {
      const payload = buildDraftPayload(plannerForm, selectedRequestDetail, currentJob.id);
      const job = await reassignDispatchPlannerJob(currentJob.id, payload);
      setCurrentJob(job);
      setSelectedJobId(job.id);
      setPlannerForm(buildPlannerFormFromJob(job));
      setIsDirty(false);
      toast.success(`Dispatch ${job.dispatch_job_id} is ready for reassignment.`, { id: 'planner:reassign' });
      await Promise.all([loadRequests(true), loadJobs(true), loadAvailability(true)]);
    } catch (error) {
      const message = getErrorMessage(error, 'Unable to reassign this dispatch.');
      setFormError(message);
      toast.error(message, { id: 'planner:reassign' });
    } finally {
      actionLocks.current.delete('reassign');
      actionLocks.current.delete('mutation');
      setIsReassigning(false);
    }
  };

  const handleCorrectSchedule = async () => {
    if (!currentJob?.id || actionLocks.current.has('mutation') || actionLocks.current.has('correct-schedule')) return;
    actionLocks.current.add('mutation');
    actionLocks.current.add('correct-schedule');
    toast.dismiss('planner:correct-schedule');
    setIsCorrectingSchedule(true);
    setFormError('');
    try {
      if (selectedDateWarnings.length) throw new ApiRequestError(selectedDateWarnings[0], 400);
      const payload = buildDraftPayload(plannerForm, selectedRequestDetail, currentJob.id);
      const job = await correctDispatchPlannerJobSchedule(currentJob.id, payload);
      setCurrentJob(job);
      setSelectedJobId(job.id);
      setPlannerForm(buildPlannerFormFromJob(job));
      setIsDirty(false);
      toast.success(`Schedule updated and assigned to ${job.driver?.full_name || 'driver'}.`, { id: 'planner:correct-schedule' });
      await Promise.all([loadRequests(true), loadJobs(true), loadAvailability(true)]);
    } catch (error) {
      const message = getErrorMessage(error, 'Unable to correct this dispatch schedule.');
      setFormError(message);
      toast.error(message, { id: 'planner:correct-schedule' });
    } finally {
      actionLocks.current.delete('correct-schedule');
      actionLocks.current.delete('mutation');
      setIsCorrectingSchedule(false);
    }
  };

  const handleCancelOperation = async () => {
    if (!selectedRequest) return;
    const operationType = selectedRequest.planner_operation_type || 'dispatch';
    if (operationType === 'dispatch') return;
    const reason = window.prompt(`Why is ${selectedRequest.request_id} being cancelled?`)?.trim();
    if (!reason) return;
    if (actionLocks.current.has('mutation') || actionLocks.current.has('cancel')) return;
    actionLocks.current.add('mutation');
    actionLocks.current.add('cancel');
    toast.dismiss('planner:cancel');
    setIsCancelling(true);
    setFormError('');
    try {
      await cancelPlannerOperation(operationType, selectedRequest.id, reason);
      toast.success(`${selectedRequest.request_id} cancelled.`, { id: 'planner:cancel' });
      setSelectedRequest(null);
      await Promise.all([loadRequests(true), loadAvailability(true)]);
    } catch (error) {
      const message = getErrorMessage(error, 'Unable to cancel this operation.');
      setFormError(message);
      toast.error(message, { id: 'planner:cancel' });
    } finally {
      actionLocks.current.delete('cancel');
      actionLocks.current.delete('mutation');
      setIsCancelling(false);
    }
  };

  const openJobDetail = async (jobId: string) => {
    if (actionLocks.current.has(`detail:${jobId}`)) return;
    actionLocks.current.add(`detail:${jobId}`);
    setLoadingDetailJobId(jobId);
    setIsDetailOpen(true);
    setIsLoadingDetail(true);
    setDetailError('');
    try {
      const job = await fetchDispatchPlannerJob(jobId, true);
      setDetailJob(job);
    } catch (error) {
      setDetailJob(null);
      setDetailError(getErrorMessage(error, 'Unable to load dispatch job details.'));
    } finally {
      actionLocks.current.delete(`detail:${jobId}`);
      setLoadingDetailJobId(null);
      setIsLoadingDetail(false);
    }
  };

  const handleRefresh = async () => {
    if (actionLocks.current.has('refresh')) return;
    actionLocks.current.add('refresh');
    toast.dismiss('planner:refresh');
    setIsRefreshing(true);
    setPageError('');
    try {
      const results = await Promise.all([loadRequests(true), loadJobs(true), loadAvailability(true)]);
      if (results.every(Boolean)) {
        toast.success('Planner refreshed', { id: 'planner:refresh' });
      } else {
        toast.error('Some Planner data could not be refreshed. Review the message above and try again.', { id: 'planner:refresh' });
      }
    } finally {
      actionLocks.current.delete('refresh');
      setIsRefreshing(false);
    }
  };

  const handleAvailabilityRefresh = async () => {
    if (actionLocks.current.has('availability-refresh')) return;
    actionLocks.current.add('availability-refresh');
    toast.dismiss('planner:availability-refresh');
    try {
      const refreshed = await loadAvailability(true);
      if (refreshed) toast.success('Availability refreshed', { id: 'planner:availability-refresh' });
      else toast.error('Unable to refresh fleet availability.', { id: 'planner:availability-refresh' });
    } finally {
      actionLocks.current.delete('availability-refresh');
    }
  };

  const isMutationPending = isSavingDraft || isReserving || isAssigning || isReassigning || isCorrectingSchedule || isCancelling;
  const isAssignedPreStart = Boolean(currentJob && ['assigned', 'accepted', 'clarification_requested'].includes(currentJob.status));
  const canCorrectSchedule = isAssignedPreStart && ['owner', 'admin'].includes(sessionUser?.role || '');

  return (
    <div className="space-y-6 pb-10">
      <section className="rounded-[28px] border border-slate-200 bg-gradient-to-r from-slate-50 via-white to-blue-50 p-6 shadow-sm">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.2em] text-blue-600">Shared Resource Planning</p>
            <h1 className="mt-2 text-3xl font-semibold text-slate-900">Operations Planner</h1>
            <p className="mt-2 max-w-3xl text-sm text-slate-600">
              Plan dispatches, supplier pickups, stock transfers, and operational requests with shared vehicle and driver availability.
            </p>
          </div>
          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => void handleRefresh()}
              disabled={isRefreshing}
              className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 shadow-sm transition hover:border-slate-300 hover:text-slate-900 disabled:opacity-60"
            >
              <RefreshCcw className={`h-4 w-4 ${isRefreshing ? 'animate-spin' : ''}`} />
              {isRefreshing ? 'Refreshing...' : 'Refresh Planner'}
            </button>
          </div>
        </div>
      </section>

      {pageError ? (
        <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{pageError}</div>
      ) : null}

      <section className="grid gap-6 xl:grid-cols-[320px_minmax(0,1fr)_320px]">
        <div className="rounded-[24px] border border-slate-200 bg-white shadow-sm">
          <div className="border-b border-slate-100 p-5">
            <div className="flex items-center gap-3">
              <div className="rounded-2xl bg-blue-50 p-3 text-blue-600">
                <ClipboardList className="h-5 w-5" />
              </div>
              <div>
                <h2 className="text-lg font-semibold text-slate-900">Pending Requests</h2>
                <p className="text-sm text-slate-500">Approved requests ready for planning.</p>
              </div>
            </div>
            <div className="mt-4 grid gap-3">
              <label className="relative block">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <input
                  value={searchQuery}
                  onChange={(event) => {
                    setSearchQuery(event.target.value);
                    setRequestPage(1);
                  }}
                  placeholder="Search customer, route, request ID"
                  className="w-full rounded-2xl border border-slate-200 py-2.5 pl-10 pr-10 text-sm outline-none transition focus:border-blue-300"
                />
                {(searchQuery !== debouncedSearchQuery || isLoadingRequests) && searchQuery ? (
                  <Loader2 className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 animate-spin text-blue-500" />
                ) : null}
              </label>
              <select
                value={planningStatusFilter}
                onChange={(event) => {
                  setPlanningStatusFilter(event.target.value);
                  setRequestPage(1);
                }}
                disabled={isLoadingRequests}
                className="rounded-2xl border border-slate-200 px-4 py-2.5 text-sm outline-none transition focus:border-blue-300"
              >
                <option value="">All Planning States</option>
                <option value="unplanned">Unplanned</option>
                <option value="draft">Draft</option>
                <option value="reserved">Reserved</option>
                <option value="assigned">Assigned</option>
                <option value="rejected">Rejected</option>
                <option value="clarification_requested">Clarification Requested</option>
              </select>
            </div>
          </div>

          <div className="max-h-[720px] overflow-y-auto p-4">
            {isLoadingRequests ? (
              <div className="space-y-3">
                {Array.from({ length: 5 }).map((_, index) => (
                  <Skeleton key={index} className="h-28 rounded-2xl" />
                ))}
              </div>
            ) : requests.length ? (
              <div className="space-y-3">
                {requests.map((requestRecord) => {
                  const isActive = selectedRequest?.id === requestRecord.id;
                  return (
                    <button
                      key={requestRecord.id}
                      type="button"
                      onClick={() => handleSelectRequest(requestRecord)}
                      disabled={isLoadingRequestDetail && isActive}
                      className={`w-full rounded-2xl border px-4 py-4 text-left transition ${
                        isActive
                          ? 'border-blue-300 bg-blue-50 shadow-sm'
                          : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50'
                      }`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">{requestRecord.request_id}</div>
                          <div className="mt-1 text-sm font-semibold text-slate-900">{requestRecord.customer_name}</div>
                        </div>
                        <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600">
                          {requestRecord.planning_status || 'unplanned'}
                        </span>
                      </div>
                      <div className="mt-3 space-y-1 text-sm text-slate-600">
                        <div>{requestRecord.pickup_location}</div>
                        <div>{requestRecord.destination}</div>
                      </div>
                      <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500">
                        <span className="rounded-full bg-white px-2.5 py-1 ring-1 ring-slate-200">
                          {(requestRecord.planner_operation_type || 'dispatch').replaceAll('_', ' ')}
                        </span>
                        <span className="rounded-full bg-white px-2.5 py-1 ring-1 ring-slate-200">{requestRecord.urgency || 'normal'}</span>
                        <span className="rounded-full bg-white px-2.5 py-1 ring-1 ring-slate-200">
                          {requestRecord.scheduled_start_time ? formatDateTime(requestRecord.scheduled_start_time) : 'Schedule pending'}
                        </span>
                      </div>
                      {isLoadingRequestDetail && isActive ? (
                        <div className="mt-3 inline-flex items-center gap-2 text-xs font-medium text-blue-700">
                          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading request...
                        </div>
                      ) : (
                        <div className="mt-3 text-xs font-semibold text-blue-700">Plan</div>
                      )}
                    </button>
                  );
                })}
              </div>
            ) : (
              <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 p-6 text-sm text-slate-500">
                No approved requests are waiting for planning right now.
              </div>
            )}
          </div>

          <div className="flex items-center justify-between border-t border-slate-100 px-4 py-3 text-sm text-slate-600">
            <button
              type="button"
              disabled={requestPagination.page <= 1}
              onClick={() => setRequestPage((current) => Math.max(1, current - 1))}
              className="inline-flex items-center gap-2 rounded-xl border border-slate-200 px-3 py-2 disabled:opacity-50"
            >
              <ChevronLeft className="h-4 w-4" />
              Prev
            </button>
            <span>Page {requestPagination.page} of {requestPagination.total_pages}</span>
            <button
              type="button"
              disabled={requestPagination.page >= requestPagination.total_pages}
              onClick={() => setRequestPage((current) => Math.min(requestPagination.total_pages, current + 1))}
              className="inline-flex items-center gap-2 rounded-xl border border-slate-200 px-3 py-2 disabled:opacity-50"
            >
              Next
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>

        <div className="space-y-6">
          <div className="rounded-[24px] border border-slate-200 bg-white shadow-sm">
            <div className="border-b border-slate-100 p-5">
              <div className="flex items-center gap-3">
                <div className="rounded-2xl bg-emerald-50 p-3 text-emerald-600">
                  <Truck className="h-5 w-5" />
                </div>
                <div>
                  <h2 className="text-lg font-semibold text-slate-900">Dispatch Planning</h2>
                  <p className="text-sm text-slate-500">
                    {selectedRequest ? `${selectedRequest.request_id} • ${selectedRequest.customer_name}` : 'Select a request to start planning.'}
                  </p>
                </div>
              </div>
            </div>

            <div className="p-5">
              {!selectedRequest ? (
                <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 p-8 text-center text-sm text-slate-500">
                  Pick an approved dispatch request from the left column to load its planning form.
                </div>
              ) : (
                <div className="space-y-5">
                  {isLoadingRequestDetail ? <Skeleton className="h-20 rounded-2xl" /> : null}
                  {formError ? (
                    <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">{formError}</div>
                  ) : null}
                  {selectedDateWarnings.length ? (
                    <div className="rounded-2xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900" role="alert">
                      <div className="flex items-center gap-2 font-medium"><AlertTriangle className="h-4 w-4" /> Schedule data needs attention</div>
                      {selectedDateWarnings.map((warning) => <div key={warning} className="mt-1">{warning}</div>)}
                    </div>
                  ) : null}
                  {isCheckingConflicts ? (
                    <div className="inline-flex items-center gap-2 rounded-xl bg-blue-50 px-3 py-2 text-sm font-medium text-blue-700" role="status" aria-live="polite">
                      <Loader2 className="h-4 w-4 animate-spin" /> Checking availability...
                    </div>
                  ) : null}
                  {conflictError ? (
                    <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">{conflictError}</div>
                  ) : null}
                  {conflicts.has_conflicts ? (
                    <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                      <div className="flex items-center gap-2 font-medium">
                        <ShieldAlert className="h-4 w-4" />
                        Conflict detected
                      </div>
                      {[...conflicts.vehicle_conflicts, ...conflicts.driver_conflicts].map((item) => (
                        <div key={item} className="mt-1">{item}</div>
                      ))}
                    </div>
                  ) : null}
                  {conflicts.vehicle_restrictions.length ? (
                    <div className="rounded-2xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900">
                      <div className="flex items-center gap-2 font-semibold"><AlertTriangle className="h-4 w-4" /> Vehicle available with restriction</div>
                      {conflicts.vehicle_restrictions.map((item) => <div key={item.override_id} className="mt-2"><div>{item.operational_restriction}</div>{item.repair_deadline ? <div className="text-xs">Repair deadline: {formatDateTime(item.repair_deadline)}</div> : null}</div>)}
                      <label className="mt-3 flex items-start gap-2"><input type="checkbox" checked={plannerForm.restriction_acknowledged} onChange={(event) => handleFormChange('restriction_acknowledged', event.target.checked)} /><span>I reviewed and explicitly acknowledge these restrictions for this assignment.</span></label>
                    </div>
                  ) : null}

                  <div className="grid gap-4 md:grid-cols-2">
                    <div>
                      <label className="mb-2 block text-sm font-medium text-slate-700">Vehicle</label>
                      <SearchableSelect
                        value={plannerForm.vehicle_id}
                        onChange={(value) => handleFormChange('vehicle_id', value)}
                        disabled={isLoadingOptions || isMutationPending}
                        options={vehicleOptions}
                        placeholder="Select vehicle"
                        searchPlaceholder="Search vehicles..."
                        emptyLabel={isLoadingOptions ? 'Loading vehicles...' : 'No available vehicles found.'}
                      />
                    </div>
                    <div>
                      <label className="mb-2 block text-sm font-medium text-slate-700">Driver</label>
                      <SearchableSelect
                        value={plannerForm.driver_id}
                        onChange={(value) => handleFormChange('driver_id', value)}
                        disabled={isLoadingOptions || isMutationPending}
                        options={driverOptions}
                        placeholder="Select driver"
                        searchPlaceholder="Search drivers..."
                        emptyLabel={isLoadingOptions ? 'Loading drivers...' : 'No available drivers found.'}
                      />
                    </div>
                    <div>
                      <label className="mb-2 block text-sm font-medium text-slate-700">Assistant</label>
                      <SearchableSelect
                        value={plannerForm.assistant_id}
                        onChange={(value) => handleFormChange('assistant_id', value)}
                        disabled={isLoadingOptions || isMutationPending}
                        options={assistantOptions}
                        placeholder="Select assistant"
                        searchPlaceholder="Search assistants..."
                        emptyLabel={isLoadingOptions ? 'Loading assistants...' : 'No assistants found.'}
                        allowClear
                        clearLabel="No assistant"
                      />
                    </div>
                    <div>
                      <label className="mb-2 block text-sm font-medium text-slate-700">Dispatcher</label>
                      <SearchableSelect
                        value={plannerForm.dispatcher_id}
                        onChange={(value) => handleFormChange('dispatcher_id', value)}
                        disabled={isLoadingOptions || isMutationPending}
                        options={dispatcherOptions}
                        placeholder="Select dispatcher"
                        searchPlaceholder="Search dispatchers..."
                        emptyLabel={isLoadingOptions ? 'Loading dispatchers...' : 'No dispatchers found.'}
                      />
                    </div>
                    <FormInput label="Pickup" value={plannerForm.pickup} onChange={(value) => handleFormChange('pickup', value)} />
                    <FormInput label="Destination" value={plannerForm.destination} onChange={(value) => handleFormChange('destination', value)} />
                    <FormInput label="Dispatch Date" type="date" value={plannerForm.dispatch_date} onChange={(value) => handleFormChange('dispatch_date', value)} />
                    <FormInput label="Dispatch Time" type="time" value={plannerForm.dispatch_time} onChange={(value) => handleFormChange('dispatch_time', value)} />
                    <FormInput label="Expected Arrival" type="datetime-local" value={plannerForm.expected_arrival_time} onChange={(value) => handleFormChange('expected_arrival_time', value)} />
                    <FormInput label="Expected Return" type="datetime-local" value={plannerForm.expected_return_time} onChange={(value) => handleFormChange('expected_return_time', value)} />
                    <FormInput label="Distance Estimate (km)" type="number" value={plannerForm.distance_estimate_km} onChange={(value) => handleFormChange('distance_estimate_km', value)} />
                    <FormInput label="Quantity" value={plannerForm.quantity} onChange={(value) => handleFormChange('quantity', value)} />
                    <FormInput label="Goods Description" value={plannerForm.goods_description} onChange={(value) => handleFormChange('goods_description', value)} />
                    <FormInput label="Weight Category" value={plannerForm.weight_category} onChange={(value) => handleFormChange('weight_category', value)} />
                    <FormInput label="Customer Contact" value={plannerForm.customer_contact} onChange={(value) => handleFormChange('customer_contact', value)} />
                    <FormInput label="Receiver Contact" value={plannerForm.receiver_contact} onChange={(value) => handleFormChange('receiver_contact', value)} />
                  </div>

                  <div className="grid gap-4 md:grid-cols-3">
                    <ToggleCard label="Fragile" checked={plannerForm.fragile} onChange={(checked) => handleFormChange('fragile', checked)} />
                    <ToggleCard label="Refrigerated" checked={plannerForm.refrigerated} onChange={(checked) => handleFormChange('refrigerated', checked)} />
                    <ToggleCard label="Hazardous" checked={plannerForm.hazardous} onChange={(checked) => handleFormChange('hazardous', checked)} />
                  </div>

                  <TextAreaField label="Loading Notes" value={plannerForm.loading_notes} onChange={(value) => handleFormChange('loading_notes', value)} />
                  <TextAreaField label="Dispatch Instructions" value={plannerForm.dispatch_instructions} onChange={(value) => handleFormChange('dispatch_instructions', value)} />
                  <TextAreaField label="Internal Notes" value={plannerForm.internal_notes} onChange={(value) => handleFormChange('internal_notes', value)} />

                  <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600">
                    <div className="font-medium text-slate-900">Intermediate Stops</div>
                    {selectedRequestDetail?.stops?.length ? (
                      <div className="mt-2 space-y-2">
                        {selectedRequestDetail.stops.map((stop) => (
                          <div key={stop.stop_id} className="rounded-xl bg-white px-3 py-2 ring-1 ring-slate-200">
                            Stop {stop.stop_sequence}: {stop.location}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="mt-2">No intermediate stops on this request.</div>
                    )}
                  </div>

                  <div className="flex flex-wrap gap-3">
                    {(selectedRequest?.planner_operation_type || 'dispatch') === 'dispatch' && !isAssignedPreStart ? (
                      <>
                        <button
                          type="button"
                          onClick={() => void handleSaveDraft()}
                          disabled={isMutationPending || !selectedRequest}
                          className="inline-flex items-center gap-2 rounded-2xl bg-slate-900 px-4 py-2.5 text-sm font-medium text-white disabled:opacity-60"
                        >
                          {isSavingDraft ? <Loader2 className="h-4 w-4 animate-spin" /> : <ClipboardList className="h-4 w-4" />}
                          {isSavingDraft ? 'Saving...' : 'Save Changes'}
                        </button>
                        <button
                          type="button"
                          onClick={() => void handleReserve()}
                          disabled={isMutationPending || isCheckingConflicts || !selectedRequest}
                          className="inline-flex items-center gap-2 rounded-2xl border border-amber-300 bg-amber-50 px-4 py-2.5 text-sm font-medium text-amber-800 disabled:opacity-60"
                        >
                          {isReserving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Clock3 className="h-4 w-4" />}
                          {isReserving ? 'Checking availability...' : 'Reserve Resources'}
                        </button>
                      </>
                    ) : null}
                    {!isAssignedPreStart ? (
                      <button
                        type="button"
                        onClick={() => void handleAssign()}
                        disabled={isMutationPending || isCheckingConflicts || Boolean(conflictError) || conflicts.has_conflicts || selectedDateWarnings.length > 0 || !selectedRequest}
                        className="inline-flex items-center gap-2 rounded-2xl bg-blue-600 px-4 py-2.5 text-sm font-medium text-white disabled:opacity-60"
                      >
                        {isAssigning ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                        {isAssigning
                          ? ((selectedRequest?.planner_operation_type || 'dispatch') === 'dispatch' ? 'Publishing...' : 'Assigning...')
                          : (selectedRequest?.planner_operation_type || 'dispatch') === 'dispatch'
                          ? 'Confirm Assignment'
                          : selectedRequest?.status === 'scheduled'
                            ? 'Update Assignment'
                            : 'Assign Operation'}
                      </button>
                    ) : null}
                    {canCorrectSchedule ? (
                      <button
                        type="button"
                        onClick={() => void handleCorrectSchedule()}
                        disabled={isMutationPending || isCheckingConflicts || Boolean(conflictError) || conflicts.has_conflicts || selectedDateWarnings.length > 0}
                        className="inline-flex items-center gap-2 rounded-2xl bg-blue-600 px-4 py-2.5 text-sm font-medium text-white disabled:opacity-60"
                      >
                        {isCorrectingSchedule ? <Loader2 className="h-4 w-4 animate-spin" /> : <CalendarDays className="h-4 w-4" />}
                        {isCorrectingSchedule ? 'Updating schedule...' : 'Edit Schedule'}
                      </button>
                    ) : null}
                    {currentJob && !['in_progress', 'completed', 'cancelled'].includes(currentJob.status) ? (
                      <button
                        type="button"
                        onClick={() => void handleReassign()}
                        disabled={isMutationPending}
                        className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 disabled:opacity-60"
                      >
                        {isReassigning ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCcw className="h-4 w-4" />}
                        {isReassigning ? 'Returning to planning...' : isAssignedPreStart ? 'Return to Planning' : 'Reassign'}
                      </button>
                    ) : null}
                    {selectedRequest && (selectedRequest.planner_operation_type || 'dispatch') !== 'dispatch' ? (
                      <button
                        type="button"
                        onClick={() => void handleCancelOperation()}
                        disabled={isMutationPending}
                        className="inline-flex items-center gap-2 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-2.5 text-sm font-medium text-rose-700 disabled:opacity-60"
                      >
                        {isCancelling ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                        {isCancelling ? 'Cancelling...' : 'Cancel Operation'}
                      </button>
                    ) : null}
                  </div>
                </div>
              )}
            </div>
          </div>

          <div className="rounded-[24px] border border-slate-200 bg-white shadow-sm">
            <div className="flex items-center justify-between border-b border-slate-100 p-5">
              <div>
                <h2 className="text-lg font-semibold text-slate-900">Dispatch Jobs</h2>
                <p className="text-sm text-slate-500">Reopen, inspect, and reassign before a dispatch starts.</p>
              </div>
              <select
                value={jobStatusFilter}
                onChange={(event) => {
                  setJobStatusFilter(event.target.value);
                  setJobPage(1);
                }}
                disabled={isLoadingJobs}
                className="rounded-2xl border border-slate-200 px-4 py-2.5 text-sm outline-none transition focus:border-blue-300"
              >
                <option value="">All Job Statuses</option>
                {(options?.job_statuses || []).map((status) => (
                  <option key={status} value={status}>{status}</option>
                ))}
              </select>
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-100 text-sm">
                <thead className="bg-slate-50">
                  <tr className="text-left text-slate-500">
                    <th className="px-4 py-3 font-medium">Dispatch</th>
                    <th className="px-4 py-3 font-medium">Route</th>
                    <th className="px-4 py-3 font-medium">Vehicle / Driver</th>
                    <th className="px-4 py-3 font-medium">Status</th>
                    <th className="px-4 py-3 font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {isLoadingJobs ? (
                    Array.from({ length: 4 }).map((_, index) => (
                      <tr key={index}>
                        <td colSpan={5} className="px-4 py-3"><Skeleton className="h-14 rounded-2xl" /></td>
                      </tr>
                    ))
                  ) : jobs.length ? (
                    jobs.map((job) => (
                      <tr key={job.id} className={selectedJobId === job.id ? 'bg-blue-50/50' : ''}>
                        <td className="px-4 py-3">
                          <div className="font-medium text-slate-900">{job.dispatch_job_id}</div>
                          <div className="text-xs text-slate-500">Departure: {formatDateTime(job.scheduled_start_time)}</div>
                          <div className="text-xs text-slate-500">Return: {formatDateTime(job.expected_return_time)}</div>
                          {job.schedule_valid === false ? <div className="mt-1 text-xs font-medium text-amber-700">Schedule needs correction</div> : null}
                        </td>
                        <td className="px-4 py-3 text-slate-600">
                          <div>{job.pickup || 'Pickup pending'}</div>
                          <div>{job.destination || 'Destination pending'}</div>
                        </td>
                        <td className="px-4 py-3 text-slate-600">
                          <div>{job.vehicle?.registration_number || 'Vehicle pending'}</div>
                          <div>{job.driver?.full_name || 'Driver pending'}</div>
                        </td>
                        <td className="px-4 py-3">
                          <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700">{job.status}</span>
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex flex-wrap gap-2">
                            <button
                              type="button"
                              onClick={() => void openJobDetail(job.id)}
                              disabled={loadingDetailJobId === job.id}
                              className="inline-flex items-center gap-2 rounded-xl border border-slate-200 px-3 py-2 text-xs font-medium text-slate-700"
                            >
                              {loadingDetailJobId === job.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Eye className="h-3.5 w-3.5" />}
                              {loadingDetailJobId === job.id ? 'Loading...' : 'View'}
                            </button>
                            <button
                              type="button"
                              onClick={() => void handleLoadJobIntoPlanner(job)}
                              disabled={loadingJobId === job.id}
                              className="inline-flex items-center gap-2 rounded-xl border border-blue-200 bg-blue-50 px-3 py-2 text-xs font-medium text-blue-700"
                            >
                              {loadingJobId === job.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCcw className="h-3.5 w-3.5" />}
                              {loadingJobId === job.id ? 'Loading...' : 'Load'}
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={5} className="px-4 py-8 text-center text-slate-500">No dispatch jobs created yet.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <div className="flex items-center justify-between border-t border-slate-100 px-4 py-3 text-sm text-slate-600">
              <button
                type="button"
                disabled={jobsPagination.page <= 1}
                onClick={() => setJobPage((current) => Math.max(1, current - 1))}
                className="inline-flex items-center gap-2 rounded-xl border border-slate-200 px-3 py-2 disabled:opacity-50"
              >
                <ChevronLeft className="h-4 w-4" />
                Prev
              </button>
              <span>Page {jobsPagination.page} of {jobsPagination.total_pages}</span>
              <button
                type="button"
                disabled={jobsPagination.page >= jobsPagination.total_pages}
                onClick={() => setJobPage((current) => Math.min(jobsPagination.total_pages, current + 1))}
                className="inline-flex items-center gap-2 rounded-xl border border-slate-200 px-3 py-2 disabled:opacity-50"
              >
                Next
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>

        <div className="space-y-6">
          <div className="rounded-[24px] border border-slate-200 bg-white shadow-sm">
            <div className="flex items-center justify-between border-b border-slate-100 p-5">
              <div>
                <h2 className="text-lg font-semibold text-slate-900">Fleet Availability</h2>
                <p className="text-sm text-slate-500">Live operational snapshot.</p>
              </div>
              <button
                type="button"
                onClick={() => void handleAvailabilityRefresh()}
                disabled={isLoadingAvailability}
                aria-label={isLoadingAvailability ? 'Refreshing fleet availability' : 'Refresh fleet availability'}
                className="rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-700 disabled:opacity-60"
              >
                {isLoadingAvailability ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCcw className="h-4 w-4" />}
              </button>
            </div>
            <div className="grid gap-3 p-5">
              {isLoadingAvailability ? (
                Array.from({ length: 9 }).map((_, index) => <Skeleton key={index} className="h-24 rounded-2xl" />)
              ) : (
                <>
                  <AvailabilityMetric label="Vehicles Available" value={availability?.vehicles.available} accent="text-emerald-600" />
                  <AvailabilityMetric label="Vehicles Reserved" value={availability?.vehicles.reserved} accent="text-amber-600" />
                  <AvailabilityMetric label="On Dispatch" value={availability?.vehicles.on_dispatch} accent="text-blue-600" />
                  <AvailabilityMetric label="Drivers Available" value={availability?.drivers.available} accent="text-emerald-600" />
                  <AvailabilityMetric label="Drivers Reserved" value={availability?.drivers.reserved} accent="text-amber-600" />
                  <AvailabilityMetric label="Drivers On Dispatch" value={availability?.drivers.on_dispatch} accent="text-blue-600" />
                  <AvailabilityMetric label="Pending Requests" value={availability?.dispatch.pending_requests} accent="text-slate-700" />
                  <AvailabilityMetric label="Waiting Assignment" value={availability?.dispatch.waiting_assignment} accent="text-violet-600" />
                  <AvailabilityMetric label="Overdue Dispatches" value={availability?.dispatch.overdue_dispatches} accent="text-rose-600" />
                </>
              )}
            </div>
          </div>

          <div className="rounded-[24px] border border-slate-200 bg-slate-900 p-5 text-white shadow-sm">
            <div className="flex items-center gap-3">
              <div className="rounded-2xl bg-white/10 p-3">
                <AlertTriangle className="h-5 w-5" />
              </div>
              <div>
                <h3 className="text-lg font-semibold">Planning Safety</h3>
                <p className="text-sm text-slate-300">Primary driver assignments stay untouched. Dispatch planning uses separate reservations and job records.</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      <Drawer open={isDetailOpen} onOpenChange={setIsDetailOpen}>
        <DrawerContent className="max-h-[92vh] overflow-y-auto">
          <DrawerHeader>
            <DrawerTitle>{detailJob?.dispatch_job_id || 'Dispatch Job Details'}</DrawerTitle>
            <DrawerDescription>Review reservation state, assignment, route, and driver visibility details.</DrawerDescription>
          </DrawerHeader>
          <div className="px-4 pb-8">
            {isLoadingDetail ? (
              <div className="space-y-3">
                <Skeleton className="h-20 rounded-2xl" />
                <Skeleton className="h-20 rounded-2xl" />
                <Skeleton className="h-40 rounded-2xl" />
              </div>
            ) : detailError ? (
              <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{detailError}</div>
            ) : detailJob ? (
              <div className="grid gap-4 md:grid-cols-2">
                <DetailCard icon={<CalendarDays className="h-4 w-4" />} label="Scheduled Start" value={formatDateTime(detailJob.scheduled_start_time)} />
                <DetailCard icon={<Clock3 className="h-4 w-4" />} label="Expected Return" value={formatDateTime(detailJob.expected_return_time)} />
                <DetailCard icon={<Truck className="h-4 w-4" />} label="Vehicle" value={detailJob.vehicle?.registration_number || 'Not assigned'} />
                <DetailCard icon={<UserRound className="h-4 w-4" />} label="Driver" value={detailJob.driver?.full_name || 'Not assigned'} />
                <DetailCard icon={<ClipboardList className="h-4 w-4" />} label="Status" value={detailJob.status} />
                <DetailCard icon={<CheckCircle2 className="h-4 w-4" />} label="Driver Response" value={detailJob.driver_response_status} />
                <div className="md:col-span-2 rounded-2xl border border-slate-200 bg-white p-4">
                  <div className="text-sm font-semibold text-slate-900">Route & Instructions</div>
                  <div className="mt-3 grid gap-3 text-sm text-slate-600 md:grid-cols-2">
                    <div>
                      <div className="font-medium text-slate-800">Pickup</div>
                      <div>{detailJob.pickup || 'Not recorded'}</div>
                    </div>
                    <div>
                      <div className="font-medium text-slate-800">Destination</div>
                      <div>{detailJob.destination || 'Not recorded'}</div>
                    </div>
                    <div>
                      <div className="font-medium text-slate-800">Goods</div>
                      <div>{detailJob.goods_description || 'Not recorded'}</div>
                    </div>
                    <div>
                      <div className="font-medium text-slate-800">Instructions</div>
                      <div>{detailJob.dispatch_instructions || 'Not recorded'}</div>
                    </div>
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        </DrawerContent>
      </Drawer>
    </div>
  );
}

function FormInput({
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
      <label className="mb-2 block text-sm font-medium text-slate-700">{label}</label>
      <input
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-2xl border border-slate-200 px-4 py-2.5 text-sm outline-none transition focus:border-blue-300"
      />
    </div>
  );
}

function TextAreaField({
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
      <label className="mb-2 block text-sm font-medium text-slate-700">{label}</label>
      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        rows={3}
        className="w-full rounded-2xl border border-slate-200 px-4 py-3 text-sm outline-none transition focus:border-blue-300"
      />
    </div>
  );
}

function ToggleCard({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      className={`rounded-2xl border px-4 py-4 text-left transition ${
        checked ? 'border-blue-300 bg-blue-50 text-blue-700' : 'border-slate-200 bg-white text-slate-600'
      }`}
    >
      <div className="font-medium">{label}</div>
      <div className="mt-1 text-sm">{checked ? 'Yes' : 'No'}</div>
    </button>
  );
}

function DetailCard({
  icon,
  label,
  value,
}: {
  icon: ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4">
      <div className="flex items-center gap-2 text-sm font-medium text-slate-700">
        {icon}
        {label}
      </div>
      <div className="mt-2 text-sm text-slate-600">{value}</div>
    </div>
  );
}
