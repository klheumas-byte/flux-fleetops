import { useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  CalendarDays,
  CheckCircle,
  ChevronLeft,
  ChevronRight,
  CircleDollarSign,
  Eye,
  Filter,
  Loader2,
  PackageCheck,
  Pencil,
  Plus,
  RefreshCcw,
  Route,
  Search,
  Tag,
  Trash2,
  XCircle,
} from 'lucide-react';
import { toast } from 'sonner';

import { ApiRequestError } from '../../lib/api';
import { getStoredSessionUser } from '../../lib/auth-session';
import {
  addDispatchStop,
  approveDispatchPricing,
  approveDispatchRequest,
  cancelDispatchRequest,
  createDispatchRequest,
  deleteDispatchStop,
  fetchDispatchRequestById,
  fetchDispatchRequestOptions,
  fetchDispatchRequests,
  fetchDispatchSchedule,
  rejectDispatchPricing,
  rejectDispatchRequest,
  reviseDispatchPricing,
  updateDispatchRequest,
  updateDispatchSchedule,
  updateDispatchStop,
  type DispatchLoadSizeCategory,
  type DispatchFinancialType,
  type DriverCompensationType,
  type PartnerBillingMethod,
  type DispatchLoadType,
  type DispatchLoadWeightCategory,
  type DispatchPaymentStatus,
  type DispatchPricingStatus,
  type DispatchRecurrencePattern,
  type DispatchRequestOptionsResponse,
  type DispatchRequestRecord,
  type DispatchRequestStatus,
  type DispatchRequestStopRecord,
  type DispatchRequestType,
  type DispatchScheduleType,
  type DispatchStopType,
  type DispatchUrgency,
  type DispatchVehicleTypeNeeded,
} from '../../lib/dispatch-request-api';
import { useDebouncedValue } from '../../lib/use-debounced-value';
import { usePageToastFeedback } from '../../lib/use-page-toast-feedback';
import { Drawer, DrawerContent, DrawerDescription, DrawerHeader, DrawerTitle } from '../ui/drawer';
import { Skeleton } from '../ui/skeleton';

type PageView = 'queue' | 'scheduled';
type RequestAction = 'approve' | 'reject' | 'cancel';
type PricingAction = 'approve' | 'reject' | 'revise';

interface DispatchRequestFormState {
  request_type: DispatchRequestType;
  customer_name: string;
  customer_phone: string;
  customer_company: string;
  pickup_location: string;
  destination: string;
  vehicle_type_needed: DispatchVehicleTypeNeeded | '';
  load_type: DispatchLoadType;
  load_weight_category: DispatchLoadWeightCategory | '';
  load_size_category: DispatchLoadSizeCategory | '';
  load_description: string;
  preferred_pickup_date: string;
  preferred_pickup_time: string;
  expected_delivery_time: string;
  urgency: DispatchUrgency;
  proposed_charge: string;
  payment_status: DispatchPaymentStatus;
  dispatch_financial_type: DispatchFinancialType;
  partner_organization_reference: string;
  partner_billing_method: PartnerBillingMethod | '';
  payment_method: string;
  amount_paid: string;
  driver_compensation_type: DriverCompensationType;
  driver_compensation_value: string;
  notes: string;
  status: '' | 'new' | 'reviewing' | 'pricing_pending';
}

interface ApprovalFormState {
  approved_charge: string;
}

interface RejectFormState {
  rejection_reason: string;
}

interface CancelFormState {
  cancellation_reason: string;
}

interface PricingFormState {
  proposed_charge: string;
  approved_charge: string;
  pricing_notes: string;
  distance_estimate_km: string;
  fuel_estimate_amount: string;
  fuel_estimate_cost: string;
  other_expected_costs: string;
}

interface ScheduleFormState {
  schedule_type: DispatchScheduleType;
  scheduled_start_time: string;
  scheduled_end_time: string;
  expected_return_time: string;
  recurrence_pattern: DispatchRecurrencePattern | '';
  recurrence_end_date: string;
  schedule_notes: string;
}

interface StopFormState {
  stop_sequence: string;
  stop_type: DispatchStopType;
  location: string;
  contact_name: string;
  contact_phone: string;
  load_note: string;
  planned_arrival_time: string;
  planned_departure_time: string;
  stop_charge: string;
}

const STATUS_LABELS: Record<DispatchRequestStatus, string> = {
  new: 'New',
  reviewing: 'Reviewing',
  pricing_pending: 'Pricing Pending',
  approved: 'Approved',
  rejected: 'Rejected',
  converted: 'Converted',
  cancelled: 'Cancelled',
};

const STATUS_BADGES: Record<DispatchRequestStatus, string> = {
  new: 'border-slate-200 bg-slate-100 text-slate-700',
  reviewing: 'border-blue-200 bg-blue-100 text-blue-700',
  pricing_pending: 'border-amber-200 bg-amber-100 text-amber-800',
  approved: 'border-green-200 bg-green-100 text-green-800',
  rejected: 'border-rose-200 bg-rose-100 text-rose-800',
  converted: 'border-indigo-200 bg-indigo-100 text-indigo-800',
  cancelled: 'border-gray-200 bg-gray-100 text-gray-700',
};

const PRICING_STATUS_LABELS: Record<DispatchPricingStatus, string> = {
  pricing_pending: 'Pricing Pending',
  pricing_approved: 'Pricing Approved',
  pricing_rejected: 'Pricing Rejected',
  pricing_revised: 'Pricing Revised',
};

const PRICING_STATUS_BADGES: Record<DispatchPricingStatus, string> = {
  pricing_pending: 'border-amber-200 bg-amber-100 text-amber-800',
  pricing_approved: 'border-green-200 bg-green-100 text-green-800',
  pricing_rejected: 'border-rose-200 bg-rose-100 text-rose-800',
  pricing_revised: 'border-blue-200 bg-blue-100 text-blue-700',
};
const DEFAULT_PRICING_STATUS_OPTIONS: DispatchPricingStatus[] = [
  'pricing_pending',
  'pricing_approved',
  'pricing_rejected',
  'pricing_revised',
];

const REQUEST_TYPE_LABELS: Record<string, string> = {
  delivery: 'Delivery',
  pickup: 'Pickup',
  relocation: 'Relocation',
  bulk_delivery: 'Bulk Delivery',
  special_request: 'Special Request',
  other: 'Other',
};

const sessionUser = getStoredSessionUser();
const currentRole = String(sessionUser?.role || '').trim().toLowerCase();
const canApprovePricing = currentRole === 'owner' || currentRole === 'admin';
const canManagePricing = canApprovePricing || currentRole === 'dispatcher' || currentRole === 'customer_service';

const initialFormState = (): DispatchRequestFormState => ({
  request_type: 'Delivery',
  customer_name: '',
  customer_phone: '',
  customer_company: '',
  pickup_location: '',
  destination: '',
  vehicle_type_needed: '',
  load_type: 'Goods',
  load_weight_category: '',
  load_size_category: '',
  load_description: '',
  preferred_pickup_date: new Date().toISOString().slice(0, 10),
  preferred_pickup_time: new Date().toTimeString().slice(0, 5),
  expected_delivery_time: '',
  urgency: 'Normal',
  proposed_charge: '0',
  payment_status: 'Unpaid',
  dispatch_financial_type: 'external_paid',
  partner_organization_reference: '',
  partner_billing_method: '',
  payment_method: '',
  amount_paid: '0',
  driver_compensation_type: 'none',
  driver_compensation_value: '0',
  notes: '',
  status: 'new',
});

const initialApprovalFormState = (): ApprovalFormState => ({ approved_charge: '' });
const initialRejectFormState = (): RejectFormState => ({ rejection_reason: '' });
const initialCancelFormState = (): CancelFormState => ({ cancellation_reason: '' });
const initialPricingFormState = (): PricingFormState => ({
  proposed_charge: '0',
  approved_charge: '',
  pricing_notes: '',
  distance_estimate_km: '',
  fuel_estimate_amount: '',
  fuel_estimate_cost: '',
  other_expected_costs: '',
});
const initialScheduleFormState = (): ScheduleFormState => ({
  schedule_type: 'immediate',
  scheduled_start_time: '',
  scheduled_end_time: '',
  expected_return_time: '',
  recurrence_pattern: '',
  recurrence_end_date: '',
  schedule_notes: '',
});
const initialStopFormState = (): StopFormState => ({
  stop_sequence: '1',
  stop_type: 'pickup',
  location: '',
  contact_name: '',
  contact_phone: '',
  load_note: '',
  planned_arrival_time: '',
  planned_departure_time: '',
  stop_charge: '',
});

function formatLabel(value?: string | null) {
  if (!value) {
    return 'Not provided';
  }
  return value
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function formatRequestTypeLabel(value?: string | null) {
  if (!value) {
    return 'Not provided';
  }
  return REQUEST_TYPE_LABELS[String(value).trim().toLowerCase()] || formatLabel(value);
}

function formatCurrency(value?: number | null) {
  if (value === null || value === undefined) {
    return 'Pending';
  }
  return `GHS ${Number(value).toLocaleString()}`;
}

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

function toDateTimeLocalValue(value?: string | null) {
  if (!value) {
    return '';
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value.slice(0, 16);
  }
  const local = new Date(parsed.getTime() - parsed.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
}

function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof ApiRequestError ? error.message : fallback;
}

function buildRequestPayload(form: DispatchRequestFormState) {
  return {
    request_type: form.request_type,
    customer_name: form.customer_name,
    customer_phone: form.customer_phone,
    customer_company: form.customer_company || undefined,
    pickup_location: form.pickup_location,
    destination: form.destination,
    vehicle_type_needed: form.vehicle_type_needed,
    load_type: form.load_type || undefined,
    load_weight_category: form.load_weight_category || undefined,
    load_size_category: form.load_size_category || undefined,
    load_description: form.load_description || undefined,
    preferred_pickup_date: form.preferred_pickup_date,
    preferred_pickup_time: form.preferred_pickup_time,
    expected_delivery_time: form.expected_delivery_time || undefined,
    urgency: form.urgency || undefined,
    proposed_charge: ['internal_company', 'complimentary'].includes(form.dispatch_financial_type) ? 0 : Number(form.proposed_charge || 0),
    payment_status: form.payment_status,
    dispatch_financial_type: form.dispatch_financial_type,
    partner_organization_reference: form.dispatch_financial_type === 'partner_contract' ? form.partner_organization_reference : undefined,
    partner_billing_method: form.dispatch_financial_type === 'partner_contract' ? form.partner_billing_method : undefined,
    payment_method: ['external_paid', 'partner_contract'].includes(form.dispatch_financial_type) ? form.payment_method || undefined : undefined,
    amount_paid: ['external_paid', 'partner_contract'].includes(form.dispatch_financial_type) ? Number(form.amount_paid || 0) : 0,
    driver_compensation_type: form.driver_compensation_type,
    driver_compensation_value: Number(form.driver_compensation_value || 0),
    notes: form.notes || undefined,
    status: form.status || undefined,
  };
}

function toEditableStatus(value: DispatchRequestRecord['status']): DispatchRequestFormState['status'] {
  if (value === 'reviewing' || value === 'pricing_pending' || value === 'new') {
    return value;
  }
  return '';
}

function getActionableActions(status: DispatchRequestStatus): RequestAction[] {
  switch (status) {
    case 'new':
    case 'reviewing':
    case 'pricing_pending':
      return ['approve', 'reject', 'cancel'];
    case 'approved':
      return ['cancel'];
    default:
      return [];
  }
}

function computeExpectedNetRevenue(form: PricingFormState, requestItem?: DispatchRequestRecord | null) {
  const baseCharge = Number(form.approved_charge || form.proposed_charge || requestItem?.approved_charge || requestItem?.proposed_charge || 0);
  const fuelCost = Number(form.fuel_estimate_cost || requestItem?.fuel_estimate_cost || 0);
  const otherCosts = Number(form.other_expected_costs || requestItem?.other_expected_costs || 0);
  return baseCharge - fuelCost - otherCosts;
}

export default function DispatchRequests() {
  const [currentView, setCurrentView] = useState<PageView>('queue');
  const [requests, setRequests] = useState<DispatchRequestRecord[]>([]);
  const [pagination, setPagination] = useState({ page: 1, page_size: 25, total: 0, total_pages: 1 });
  const [options, setOptions] = useState<DispatchRequestOptionsResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingOptions, setIsLoadingOptions] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [pageError, setPageError] = useState('');
  const [pageNotice, setPageNotice] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [vehicleTypeFilter, setVehicleTypeFilter] = useState('');
  const [pricingStatusFilter, setPricingStatusFilter] = useState('');
  const [scheduleTypeFilter, setScheduleTypeFilter] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [editingRequest, setEditingRequest] = useState<DispatchRequestRecord | null>(null);
  const [formState, setFormState] = useState<DispatchRequestFormState>(initialFormState);
  const [formError, setFormError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [selectedRequestId, setSelectedRequestId] = useState<string | null>(null);
  const [detailRequest, setDetailRequest] = useState<DispatchRequestRecord | null>(null);
  const [detailCache, setDetailCache] = useState<Record<string, DispatchRequestRecord>>({});
  const [isLoadingDetail, setIsLoadingDetail] = useState(false);
  const [detailError, setDetailError] = useState('');
  const [actionTarget, setActionTarget] = useState<DispatchRequestRecord | null>(null);
  const [actionType, setActionType] = useState<RequestAction | null>(null);
  const [actionError, setActionError] = useState('');
  const [isActionSubmitting, setIsActionSubmitting] = useState(false);
  const [approvalForm, setApprovalForm] = useState<ApprovalFormState>(initialApprovalFormState);
  const [rejectForm, setRejectForm] = useState<RejectFormState>(initialRejectFormState);
  const [cancelForm, setCancelForm] = useState<CancelFormState>(initialCancelFormState);
  const [pricingTarget, setPricingTarget] = useState<DispatchRequestRecord | null>(null);
  const [pricingAction, setPricingAction] = useState<PricingAction | null>(null);
  const [pricingForm, setPricingForm] = useState<PricingFormState>(initialPricingFormState);
  const [pricingError, setPricingError] = useState('');
  const [isPricingSubmitting, setIsPricingSubmitting] = useState(false);
  const [scheduleTarget, setScheduleTarget] = useState<DispatchRequestRecord | null>(null);
  const [scheduleForm, setScheduleForm] = useState<ScheduleFormState>(initialScheduleFormState);
  const [scheduleError, setScheduleError] = useState('');
  const [isScheduleSubmitting, setIsScheduleSubmitting] = useState(false);
  const [stopTarget, setStopTarget] = useState<DispatchRequestRecord | null>(null);
  const [editingStop, setEditingStop] = useState<DispatchRequestStopRecord | null>(null);
  const [stopForm, setStopForm] = useState<StopFormState>(initialStopFormState);
  const [stopError, setStopError] = useState('');
  const [isStopSubmitting, setIsStopSubmitting] = useState(false);
  const debouncedSearchQuery = useDebouncedValue(searchQuery, 300);

  usePageToastFeedback(pageError, pageNotice);

  const requestTypeOptions = options?.request_types || [];
  const pickupLocationOptions = options?.pickup_locations || [];
  const vehicleTypeOptions = options?.vehicle_types || [];
  const loadTypeOptions = options?.load_types || [];
  const loadWeightCategoryOptions = options?.load_weight_categories || [];
  const loadSizeCategoryOptions = options?.load_size_categories || [];
  const urgencyOptions = options?.urgencies || [];
  const paymentStatusOptions = options?.payment_statuses || [];
  const statusOptions = options?.statuses || [];
  const pricingStatusOptions = options?.pricing_statuses?.length ? options.pricing_statuses : DEFAULT_PRICING_STATUS_OPTIONS;
  const scheduleTypeOptions = options?.schedule_types || [];
  const recurrencePatternOptions = options?.recurrence_patterns || [];
  const stopTypeOptions = options?.stop_types || [];

  const loadOptions = async () => {
    if (options || isLoadingOptions) {
      return;
    }
    setIsLoadingOptions(true);
    try {
      setOptions(await fetchDispatchRequestOptions());
    } catch (error) {
      setPageNotice(getErrorMessage(error, 'Dispatch request options are temporarily unavailable.'));
    } finally {
      setIsLoadingOptions(false);
    }
  };

  const loadRequests = async ({ refresh = false }: { refresh?: boolean } = {}) => {
    if (refresh) {
      setIsRefreshing(true);
    } else {
      setIsLoading(true);
    }
    setPageError('');
    try {
      const response =
        currentView === 'queue'
          ? await fetchDispatchRequests({
              page: currentPage,
              page_size: 25,
              q: debouncedSearchQuery || undefined,
              status: statusFilter || undefined,
              vehicle_type_needed: vehicleTypeFilter || undefined,
              date_from: dateFrom || undefined,
              date_to: dateTo || undefined,
            })
          : await fetchDispatchSchedule({
              page: currentPage,
              page_size: 25,
              status: statusFilter || undefined,
              vehicle_type_needed: vehicleTypeFilter || undefined,
              pricing_status: pricingStatusFilter || undefined,
              schedule_type: scheduleTypeFilter || undefined,
              date_from: dateFrom || undefined,
              date_to: dateTo || undefined,
            });
      setRequests(response.requests || []);
      setPagination(response.pagination || { page: 1, page_size: 25, total: 0, total_pages: 1 });
    } catch (error) {
      setRequests([]);
      setPagination({ page: 1, page_size: 25, total: 0, total_pages: 1 });
      setPageError(
        getErrorMessage(
          error,
          currentView === 'queue' ? 'Unable to load dispatch requests right now.' : 'Unable to load scheduled dispatch right now.',
        ),
      );
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  };

  useEffect(() => {
    void loadOptions();
  }, []);

  useEffect(() => {
    setCurrentPage(1);
  }, [currentView]);

  useEffect(() => {
    void loadRequests();
  }, [currentView, currentPage, debouncedSearchQuery, statusFilter, vehicleTypeFilter, pricingStatusFilter, scheduleTypeFilter, dateFrom, dateTo]);

  const replaceRequestInState = (requestItem: DispatchRequestRecord) => {
    setRequests((current) => current.map((item) => (item.id === requestItem.id ? requestItem : item)));
    setDetailCache((current) => ({ ...current, [requestItem.id]: requestItem }));
    if (detailRequest?.id === requestItem.id) {
      setDetailRequest(requestItem);
    }
  };

  const openCreateModal = async () => {
    const nextForm = initialFormState();
    if (requestTypeOptions[0]) nextForm.request_type = requestTypeOptions[0];
    if (pickupLocationOptions[0]) nextForm.pickup_location = pickupLocationOptions[0];
    if (vehicleTypeOptions[0]) nextForm.vehicle_type_needed = vehicleTypeOptions[0];
    if (loadTypeOptions[0]) nextForm.load_type = loadTypeOptions[0];
    if (urgencyOptions[0]) nextForm.urgency = urgencyOptions[0];
    if (paymentStatusOptions.length && !paymentStatusOptions.includes(nextForm.payment_status)) {
      nextForm.payment_status = paymentStatusOptions[0];
    }
    setEditingRequest(null);
    setFormError('');
    setFormState(nextForm);
    setIsFormOpen(true);
    void loadOptions();
  };

  const openEditModal = async (requestItem: DispatchRequestRecord) => {
    setEditingRequest(requestItem);
    setFormError('');
    setFormState({
      request_type: requestItem.request_type,
      customer_name: requestItem.customer_name,
      customer_phone: requestItem.customer_phone,
      customer_company: requestItem.customer_company || '',
      pickup_location: requestItem.pickup_location,
      destination: requestItem.destination,
      vehicle_type_needed: requestItem.vehicle_type_needed,
      load_type: requestItem.load_type || 'Goods',
      load_weight_category: requestItem.load_weight_category || '',
      load_size_category: requestItem.load_size_category || '',
      load_description: requestItem.load_description || '',
      preferred_pickup_date: requestItem.preferred_pickup_date,
      preferred_pickup_time: requestItem.preferred_pickup_time,
      expected_delivery_time: toDateTimeLocalValue(requestItem.expected_delivery_time),
      urgency: requestItem.urgency || 'Normal',
      proposed_charge: String(requestItem.proposed_charge ?? 0),
      payment_status: requestItem.payment_status || 'Unpaid',
      dispatch_financial_type: requestItem.dispatch_financial_type || 'external_paid',
      partner_organization_reference: requestItem.partner_organization_reference || '',
      partner_billing_method: requestItem.partner_billing_method || '',
      payment_method: requestItem.payment_method || '',
      amount_paid: String(requestItem.amount_paid ?? 0),
      driver_compensation_type: requestItem.driver_compensation_type || 'none',
      driver_compensation_value: String(requestItem.driver_compensation_value ?? 0),
      notes: requestItem.notes || '',
      status: toEditableStatus(requestItem.status),
    });
    setIsFormOpen(true);
    void loadOptions();
  };

  const closeFormModal = () => {
    setIsFormOpen(false);
    setEditingRequest(null);
    setFormError('');
    setFormState(initialFormState());
  };

  const openDetailsDrawer = async (requestItem: DispatchRequestRecord) => {
    setSelectedRequestId(requestItem.id);
    setDetailRequest(detailCache[requestItem.id] || requestItem);
    setDetailError('');
    if (detailCache[requestItem.id]) {
      return;
    }
    setIsLoadingDetail(true);
    try {
      const detail = await fetchDispatchRequestById(requestItem.id);
      setDetailCache((current) => ({ ...current, [requestItem.id]: detail }));
      setDetailRequest(detail);
    } catch (error) {
      setDetailError(getErrorMessage(error, 'Unable to load dispatch request details right now.'));
    } finally {
      setIsLoadingDetail(false);
    }
  };

  const closeDetailsDrawer = () => {
    setSelectedRequestId(null);
    setDetailRequest(null);
    setDetailError('');
    setIsLoadingDetail(false);
  };

  const openActionModal = (requestItem: DispatchRequestRecord, action: RequestAction) => {
    setActionTarget(requestItem);
    setActionType(action);
    setActionError('');
    setApprovalForm({ approved_charge: String(requestItem.approved_charge ?? requestItem.proposed_charge ?? 0) });
    setRejectForm(initialRejectFormState());
    setCancelForm(initialCancelFormState());
  };

  const openPricingModal = (requestItem: DispatchRequestRecord, action: PricingAction) => {
    setPricingTarget(requestItem);
    setPricingAction(action);
    setPricingError('');
    setPricingForm({
      proposed_charge: String(requestItem.proposed_charge ?? 0),
      approved_charge: String(requestItem.approved_charge ?? ''),
      pricing_notes: requestItem.pricing_notes || '',
      distance_estimate_km: requestItem.distance_estimate_km !== null && requestItem.distance_estimate_km !== undefined ? String(requestItem.distance_estimate_km) : '',
      fuel_estimate_amount: requestItem.fuel_estimate_amount !== null && requestItem.fuel_estimate_amount !== undefined ? String(requestItem.fuel_estimate_amount) : '',
      fuel_estimate_cost: requestItem.fuel_estimate_cost !== null && requestItem.fuel_estimate_cost !== undefined ? String(requestItem.fuel_estimate_cost) : '',
      other_expected_costs: requestItem.other_expected_costs !== null && requestItem.other_expected_costs !== undefined ? String(requestItem.other_expected_costs) : '',
    });
  };

  const closePricingModal = () => {
    setPricingTarget(null);
    setPricingAction(null);
    setPricingError('');
    setIsPricingSubmitting(false);
  };

  const openScheduleModal = (requestItem: DispatchRequestRecord) => {
    setScheduleTarget(requestItem);
    setScheduleError('');
    setScheduleForm({
      schedule_type: requestItem.schedule_type || 'immediate',
      scheduled_start_time: toDateTimeLocalValue(requestItem.scheduled_start_time),
      scheduled_end_time: toDateTimeLocalValue(requestItem.scheduled_end_time),
      expected_return_time: toDateTimeLocalValue(requestItem.expected_return_time),
      recurrence_pattern: requestItem.recurrence_pattern || '',
      recurrence_end_date: requestItem.recurrence_end_date || '',
      schedule_notes: requestItem.schedule_notes || '',
    });
  };

  const closeScheduleModal = () => {
    setScheduleTarget(null);
    setScheduleError('');
    setIsScheduleSubmitting(false);
  };

  const openStopModal = (requestItem: DispatchRequestRecord, stop?: DispatchRequestStopRecord | null) => {
    setStopTarget(requestItem);
    setEditingStop(stop || null);
    setStopError('');
    setStopForm(
      stop
        ? {
            stop_sequence: String(stop.stop_sequence),
            stop_type: stop.stop_type,
            location: stop.location,
            contact_name: stop.contact_name || '',
            contact_phone: stop.contact_phone || '',
            load_note: stop.load_note || '',
            planned_arrival_time: toDateTimeLocalValue(stop.planned_arrival_time),
            planned_departure_time: toDateTimeLocalValue(stop.planned_departure_time),
            stop_charge: stop.stop_charge !== null && stop.stop_charge !== undefined ? String(stop.stop_charge) : '',
          }
        : {
            ...initialStopFormState(),
            stop_sequence: String((requestItem.stops?.length || 0) + 1),
          },
    );
  };

  const closeStopModal = () => {
    setStopTarget(null);
    setEditingStop(null);
    setStopError('');
    setIsStopSubmitting(false);
  };

  const handleSubmitForm = async (event: React.FormEvent) => {
    event.preventDefault();
    setIsSubmitting(true);
    setFormError('');
    try {
      const payload = buildRequestPayload(formState);
      const savedRequest = editingRequest
        ? await updateDispatchRequest(editingRequest.id, payload)
        : await createDispatchRequest(payload);
      replaceRequestInState(savedRequest);
      closeFormModal();
      setPageNotice(editingRequest ? 'Dispatch request updated successfully.' : 'Dispatch request created successfully.');
      setCurrentPage(1);
      await loadRequests({ refresh: true });
    } catch (error) {
      setFormError(getErrorMessage(error, 'Unable to save the dispatch request right now.'));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleActionSubmit = async (event?: React.FormEvent) => {
    event?.preventDefault();
    if (!actionTarget || !actionType) {
      return;
    }
    setActionError('');
    setIsActionSubmitting(true);
    try {
      const updatedRequest =
        actionType === 'approve'
          ? await approveDispatchRequest(actionTarget.id, {
              approved_charge: approvalForm.approved_charge ? Number(approvalForm.approved_charge) : undefined,
            })
          : actionType === 'reject'
            ? await rejectDispatchRequest(actionTarget.id, { rejection_reason: rejectForm.rejection_reason })
            : await cancelDispatchRequest(actionTarget.id, { cancellation_reason: cancelForm.cancellation_reason });
      replaceRequestInState(updatedRequest);
      toast.success(`Dispatch request ${STATUS_LABELS[updatedRequest.status].toLowerCase()} successfully.`);
      setActionTarget(null);
      setActionType(null);
      await loadRequests({ refresh: true });
    } catch (error) {
      setActionError(getErrorMessage(error, 'Unable to update the dispatch request right now.'));
    } finally {
      setIsActionSubmitting(false);
    }
  };

  const handlePricingSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!pricingTarget || !pricingAction) {
      return;
    }
    setPricingError('');
    setIsPricingSubmitting(true);
    try {
      const payload = {
        proposed_charge: pricingForm.proposed_charge ? Number(pricingForm.proposed_charge) : undefined,
        approved_charge: pricingForm.approved_charge ? Number(pricingForm.approved_charge) : undefined,
        pricing_notes: pricingForm.pricing_notes || undefined,
        distance_estimate_km: pricingForm.distance_estimate_km ? Number(pricingForm.distance_estimate_km) : undefined,
        fuel_estimate_amount: pricingForm.fuel_estimate_amount ? Number(pricingForm.fuel_estimate_amount) : undefined,
        fuel_estimate_cost: pricingForm.fuel_estimate_cost ? Number(pricingForm.fuel_estimate_cost) : undefined,
        other_expected_costs: pricingForm.other_expected_costs ? Number(pricingForm.other_expected_costs) : undefined,
      };
      const updatedRequest =
        pricingAction === 'approve'
          ? await approveDispatchPricing(pricingTarget.id, payload)
          : pricingAction === 'reject'
            ? await rejectDispatchPricing(pricingTarget.id, payload)
            : await reviseDispatchPricing(pricingTarget.id, payload);
      replaceRequestInState(updatedRequest);
      closePricingModal();
      toast.success(
        pricingAction === 'approve'
          ? 'Pricing approved successfully.'
          : pricingAction === 'reject'
            ? 'Pricing rejected successfully.'
            : 'Pricing updated successfully.',
      );
      await loadRequests({ refresh: true });
    } catch (error) {
      setPricingError(getErrorMessage(error, 'Unable to save pricing right now.'));
    } finally {
      setIsPricingSubmitting(false);
    }
  };

  const handleScheduleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!scheduleTarget) {
      return;
    }
    setScheduleError('');
    setIsScheduleSubmitting(true);
    try {
      const updatedRequest = await updateDispatchSchedule(scheduleTarget.id, {
        schedule_type: scheduleForm.schedule_type,
        scheduled_start_time: scheduleForm.scheduled_start_time || undefined,
        scheduled_end_time: scheduleForm.scheduled_end_time || undefined,
        expected_return_time: scheduleForm.expected_return_time || undefined,
        recurrence_pattern: scheduleForm.recurrence_pattern || undefined,
        recurrence_end_date: scheduleForm.recurrence_end_date || undefined,
        schedule_notes: scheduleForm.schedule_notes || undefined,
      });
      replaceRequestInState(updatedRequest);
      closeScheduleModal();
      toast.success('Dispatch schedule updated successfully.');
      await loadRequests({ refresh: true });
    } catch (error) {
      setScheduleError(getErrorMessage(error, 'Unable to save scheduling right now.'));
    } finally {
      setIsScheduleSubmitting(false);
    }
  };

  const handleStopSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!stopTarget) {
      return;
    }
    setStopError('');
    setIsStopSubmitting(true);
    try {
      const payload = {
        stop_sequence: Number(stopForm.stop_sequence),
        stop_type: stopForm.stop_type,
        location: stopForm.location,
        contact_name: stopForm.contact_name || undefined,
        contact_phone: stopForm.contact_phone || undefined,
        load_note: stopForm.load_note || undefined,
        planned_arrival_time: stopForm.planned_arrival_time || undefined,
        planned_departure_time: stopForm.planned_departure_time || undefined,
        stop_charge: stopForm.stop_charge ? Number(stopForm.stop_charge) : undefined,
      };
      const updatedRequest = editingStop
        ? await updateDispatchStop(stopTarget.id, editingStop.stop_id, payload)
        : await addDispatchStop(stopTarget.id, payload);
      replaceRequestInState(updatedRequest);
      closeStopModal();
      toast.success(editingStop ? 'Dispatch stop updated successfully.' : 'Dispatch stop added successfully.');
      await loadRequests({ refresh: true });
    } catch (error) {
      setStopError(getErrorMessage(error, 'Unable to save the dispatch stop right now.'));
    } finally {
      setIsStopSubmitting(false);
    }
  };

  const handleDeleteStop = async (requestId: string, stopId: string) => {
    if (typeof window !== 'undefined' && !window.confirm('Remove this stop from the dispatch plan?')) {
      return;
    }
    try {
      const updatedRequest = await deleteDispatchStop(requestId, stopId);
      replaceRequestInState(updatedRequest);
      toast.success('Dispatch stop removed successfully.');
      await loadRequests({ refresh: true });
    } catch (error) {
      toast.error(getErrorMessage(error, 'Unable to remove the dispatch stop right now.'));
    }
  };

  const totalOpen = useMemo(
    () => requests.filter((item) => ['new', 'reviewing', 'pricing_pending'].includes(item.status)).length,
    [requests],
  );
  const totalApproved = useMemo(() => requests.filter((item) => item.status === 'approved').length, [requests]);
  const totalScheduled = useMemo(() => requests.filter((item) => item.scheduled_start_time).length, [requests]);
  const expectedRevenuePreview = useMemo(
    () => computeExpectedNetRevenue(pricingForm, pricingTarget),
    [pricingForm, pricingTarget],
  );

  return (
    <div className="space-y-6 p-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-[#0F172A]">Dispatch Requests</h1>
          <p className="mt-1 text-gray-600">
            Capture intake, review pricing, prepare schedules, and build multi-stop plans before assignment.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => void loadRequests({ refresh: true })}
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
            Create Request
          </button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <TabButton isActive={currentView === 'queue'} onClick={() => setCurrentView('queue')} icon={PackageCheck} label="Request Queue" />
        <TabButton isActive={currentView === 'scheduled'} onClick={() => setCurrentView('scheduled')} icon={CalendarDays} label="Scheduled Dispatch" />
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <StatCard icon={PackageCheck} label="This Page" value={requests.length} tint="bg-blue-100 text-blue-700" />
        <StatCard icon={Tag} label="Open Intake" value={totalOpen} tint="bg-amber-100 text-amber-700" />
        <StatCard icon={currentView === 'scheduled' ? CalendarDays : CircleDollarSign} label={currentView === 'scheduled' ? 'Scheduled on Page' : 'Approved / Scheduled'} value={currentView === 'scheduled' ? totalScheduled : totalApproved + totalScheduled} tint="bg-green-100 text-green-700" />
      </div>

      <div className="rounded-xl border border-gray-200 bg-white p-4">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-center">
          {currentView === 'queue' && (
            <div className="relative min-w-0 flex-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
              <input
                value={searchQuery}
                onChange={(event) => {
                  setSearchQuery(event.target.value);
                  setCurrentPage(1);
                }}
                placeholder="Search request ID, customer, phone, pickup, destination..."
                className="w-full rounded-lg border border-gray-300 py-2.5 pl-10 pr-4 text-sm focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
              />
            </div>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <Filter className="h-4 w-4 text-gray-500" />
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
              value={vehicleTypeFilter}
              onChange={(event) => {
                setVehicleTypeFilter(event.target.value);
                setCurrentPage(1);
              }}
              className="rounded-lg border border-gray-300 px-3 py-2.5 text-sm focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
            >
              <option value="">All Vehicle Types</option>
              {vehicleTypeOptions.map((vehicleType) => (
                <option key={vehicleType} value={vehicleType}>
                  {formatLabel(vehicleType)}
                </option>
              ))}
            </select>
            {currentView === 'scheduled' && (
              <>
                <select
                  value={pricingStatusFilter}
                  onChange={(event) => {
                    setPricingStatusFilter(event.target.value);
                    setCurrentPage(1);
                  }}
                  className="rounded-lg border border-gray-300 px-3 py-2.5 text-sm focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                >
                  <option value="">All Pricing Statuses</option>
                  {pricingStatusOptions.map((pricingStatus) => (
                    <option key={pricingStatus} value={pricingStatus}>
                      {PRICING_STATUS_LABELS[pricingStatus]}
                    </option>
                  ))}
                </select>
                <select
                  value={scheduleTypeFilter}
                  onChange={(event) => {
                    setScheduleTypeFilter(event.target.value);
                    setCurrentPage(1);
                  }}
                  className="rounded-lg border border-gray-300 px-3 py-2.5 text-sm focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                >
                  <option value="">All Schedule Types</option>
                  {scheduleTypeOptions.map((scheduleType) => (
                    <option key={scheduleType} value={scheduleType}>
                      {formatLabel(scheduleType)}
                    </option>
                  ))}
                </select>
              </>
            )}
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
            <h2 className="text-lg font-semibold text-[#0F172A]">{currentView === 'queue' ? 'Request Queue' : 'Scheduled Dispatch'}</h2>
            <p className="text-sm text-gray-500">
              Page {pagination.page} of {pagination.total_pages} • {pagination.total} total requests
            </p>
          </div>
        </div>

        {isLoading ? (
          <DispatchRequestsTableSkeleton />
        ) : pageError ? (
          <div className="px-6 py-8">
            <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-4 text-sm text-red-700">{pageError}</div>
          </div>
        ) : requests.length === 0 ? (
          <div className="px-6 py-16 text-center">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-blue-50 text-[#2563EB]">
              {currentView === 'queue' ? <PackageCheck className="h-6 w-6" /> : <CalendarDays className="h-6 w-6" />}
            </div>
            <h3 className="mt-4 text-lg font-semibold text-[#0F172A]">
              {currentView === 'queue' ? 'No dispatch requests yet' : 'No scheduled dispatch yet'}
            </h3>
            <p className="mt-2 text-sm text-gray-500">
              {currentView === 'queue'
                ? 'Create the first intake request to start pricing and scheduling review.'
                : 'Approved and scheduled requests will appear here once a dispatch date is set.'}
            </p>
            {currentView === 'queue' && (
              <button
                type="button"
                onClick={() => void openCreateModal()}
                className="mt-5 inline-flex items-center gap-2 rounded-lg bg-[#2563EB] px-4 py-2.5 text-sm font-medium text-white transition-all hover:bg-[#1d4ed8]"
              >
                <Plus className="h-4 w-4" />
                Create Request
              </button>
            )}
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    {(currentView === 'queue'
                      ? ['Request', 'Customer', 'Route', 'Vehicle Need', 'Pickup', 'Charges', 'Status', 'Actions']
                      : ['Request', 'Customer', 'Schedule', 'Route', 'Pricing', 'Schedule Type', 'Status', 'Actions']).map((header) => (
                      <th key={header} className="px-6 py-3 text-left text-xs font-semibold uppercase tracking-[0.18em] text-gray-500">
                        {header}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200 bg-white">
                  {requests.map((requestItem) => (
                    <tr key={requestItem.id} className="align-top">
                      <td className="px-6 py-4">
                        <div className="text-sm font-semibold text-[#0F172A]">{requestItem.request_id}</div>
                        <div className="mt-1 text-xs text-gray-500">{formatRequestTypeLabel(requestItem.request_type)}</div>
                      </td>
                      <td className="px-6 py-4">
                        <div className="text-sm font-medium text-[#0F172A]">{requestItem.customer_name}</div>
                        <div className="mt-1 text-xs text-gray-500">{requestItem.customer_phone}</div>
                        <div className="mt-1 text-xs text-gray-500">{requestItem.customer_company || 'Individual'}</div>
                      </td>
                      {currentView === 'queue' ? (
                        <>
                          <td className="px-6 py-4">
                            <div className="text-sm text-[#0F172A]">{requestItem.pickup_location}</div>
                            <div className="mt-1 text-xs text-gray-500">to {requestItem.destination}</div>
                          </td>
                          <td className="px-6 py-4">
                            <div className="text-sm text-[#0F172A]">{formatLabel(requestItem.vehicle_type_needed)}</div>
                            <div className="mt-1 text-xs text-gray-500">
                              {[requestItem.load_type, requestItem.load_weight_category, requestItem.load_size_category]
                                .filter(Boolean)
                                .map((value) => formatLabel(value))
                                .join(' • ') || 'No load tags'}
                            </div>
                          </td>
                          <td className="px-6 py-4">
                            <div className="text-sm text-[#0F172A]">{requestItem.preferred_pickup_date}</div>
                            <div className="mt-1 text-xs text-gray-500">{requestItem.preferred_pickup_time}</div>
                          </td>
                          <td className="px-6 py-4">
                            <div className="text-sm text-[#0F172A]">{formatCurrency(requestItem.proposed_charge)}</div>
                            <div className="mt-1 text-xs text-gray-500">
                              Approved: {formatCurrency(requestItem.approved_charge)}
                            </div>
                          </td>
                        </>
                      ) : (
                        <>
                          <td className="px-6 py-4">
                            <div className="text-sm text-[#0F172A]">{formatDateTime(requestItem.scheduled_start_time)}</div>
                            <div className="mt-1 text-xs text-gray-500">
                              Return: {formatDateTime(requestItem.expected_return_time)}
                            </div>
                          </td>
                          <td className="px-6 py-4">
                            <div className="text-sm text-[#0F172A]">{requestItem.pickup_location}</div>
                            <div className="mt-1 text-xs text-gray-500">to {requestItem.destination}</div>
                            <div className="mt-1 text-xs text-gray-500">{requestItem.stops_count || 0} planned stops</div>
                          </td>
                          <td className="px-6 py-4">
                            <div className="text-sm text-[#0F172A]">{formatCurrency(requestItem.approved_charge ?? requestItem.proposed_charge)}</div>
                            <div className="mt-1 text-xs text-gray-500">
                              Net: {requestItem.expected_net_revenue !== null && requestItem.expected_net_revenue !== undefined ? formatCurrency(requestItem.expected_net_revenue) : 'Pending'}
                            </div>
                          </td>
                          <td className="px-6 py-4">
                            <div className="text-sm text-[#0F172A]">{formatLabel(requestItem.schedule_type)}</div>
                            <div className="mt-1 text-xs text-gray-500">
                              {requestItem.pricing_status ? PRICING_STATUS_LABELS[requestItem.pricing_status] : 'Pricing Pending'}
                            </div>
                          </td>
                        </>
                      )}
                      <td className="px-6 py-4">
                        <div className="flex flex-col gap-2">
                          <span className={`inline-flex w-fit rounded-full border px-3 py-1 text-xs font-semibold ${STATUS_BADGES[requestItem.status]}`}>
                            {STATUS_LABELS[requestItem.status]}
                          </span>
                          {requestItem.pricing_status && (
                            <span className={`inline-flex w-fit rounded-full border px-3 py-1 text-xs font-semibold ${PRICING_STATUS_BADGES[requestItem.pricing_status]}`}>
                              {PRICING_STATUS_LABELS[requestItem.pricing_status]}
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="px-6 py-4">
                        <div className="flex flex-wrap items-center gap-2">
                          <button
                            type="button"
                            onClick={() => void openDetailsDrawer(requestItem)}
                            className="inline-flex items-center gap-1 rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-700 transition-all hover:bg-gray-50"
                          >
                            <Eye className="h-3.5 w-3.5" />
                            View
                          </button>
                          <button
                            type="button"
                            onClick={() => void openEditModal(requestItem)}
                            className="inline-flex items-center gap-1 rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-700 transition-all hover:bg-gray-50"
                          >
                            <Pencil className="h-3.5 w-3.5" />
                            Edit
                          </button>
                          {getActionableActions(requestItem.status).map((action) => (
                            <ActionBadge key={action} action={action} onClick={() => openActionModal(requestItem, action)} />
                          ))}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="flex items-center justify-between border-t border-gray-200 px-6 py-4">
              <p className="text-sm text-gray-500">
                Showing {(pagination.page - 1) * pagination.page_size + 1} to {Math.min(pagination.page * pagination.page_size, pagination.total)} of {pagination.total}
              </p>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setCurrentPage((current) => Math.max(1, current - 1))}
                  disabled={pagination.page <= 1}
                  className="inline-flex items-center gap-1 rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-700 transition-all hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <ChevronLeft className="h-4 w-4" />
                  Previous
                </button>
                <button
                  type="button"
                  onClick={() => setCurrentPage((current) => Math.min(pagination.total_pages, current + 1))}
                  disabled={pagination.page >= pagination.total_pages}
                  className="inline-flex items-center gap-1 rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-700 transition-all hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Next
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            </div>
          </>
        )}
      </div>

      {isFormOpen && (
        <ModalShell
          title={editingRequest ? 'Edit Dispatch Request' : 'Create Dispatch Request'}
          subtitle={editingRequest ? editingRequest.request_id : 'Capture a customer delivery request before assignment.'}
          onClose={closeFormModal}
          maxWidth="max-w-5xl"
        >
          <form onSubmit={handleSubmitForm} className="flex min-h-0 flex-1 flex-col overflow-hidden">
            <div className="grid gap-4 overflow-y-auto px-6 py-5 md:grid-cols-2">
              <SelectField label="Request Type" value={formState.request_type} onChange={(value) => setFormState((current) => ({ ...current, request_type: value as DispatchRequestType }))}>
                {requestTypeOptions.map((requestType) => (
                  <option key={requestType} value={requestType}>
                    {formatRequestTypeLabel(requestType)}
                  </option>
                ))}
              </SelectField>
              <SelectField label="Vehicle Type Needed" value={formState.vehicle_type_needed} onChange={(value) => setFormState((current) => ({ ...current, vehicle_type_needed: value as DispatchVehicleTypeNeeded }))}>
                <option value="">Select vehicle type</option>
                {vehicleTypeOptions.map((vehicleType) => (
                  <option key={vehicleType} value={vehicleType}>
                    {formatLabel(vehicleType)}
                  </option>
                ))}
              </SelectField>
              <InputField label="Customer Name" value={formState.customer_name} onChange={(value) => setFormState((current) => ({ ...current, customer_name: value }))} />
              <InputField label="Customer Phone" value={formState.customer_phone} onChange={(value) => setFormState((current) => ({ ...current, customer_phone: value }))} />
              <InputField label="Customer Company (Optional)" value={formState.customer_company} onChange={(value) => setFormState((current) => ({ ...current, customer_company: value }))} />
              <SelectField label="Urgency" value={formState.urgency} onChange={(value) => setFormState((current) => ({ ...current, urgency: value as DispatchUrgency }))}>
                {urgencyOptions.map((urgency) => (
                  <option key={urgency} value={urgency}>
                    {formatLabel(urgency)}
                  </option>
                ))}
              </SelectField>
              <SelectField label="Pickup Location" value={formState.pickup_location} onChange={(value) => setFormState((current) => ({ ...current, pickup_location: value }))}>
                <option value="">Select pickup location</option>
                {pickupLocationOptions.map((pickupLocation) => (
                  <option key={pickupLocation} value={pickupLocation}>
                    {pickupLocation}
                  </option>
                ))}
              </SelectField>
              <InputField label="Destination" value={formState.destination} onChange={(value) => setFormState((current) => ({ ...current, destination: value }))} />
              <SelectField label="Load Type" value={formState.load_type} onChange={(value) => setFormState((current) => ({ ...current, load_type: value as DispatchLoadType }))}>
                {loadTypeOptions.map((loadType) => (
                  <option key={loadType} value={loadType}>
                    {formatLabel(loadType)}
                  </option>
                ))}
              </SelectField>
              <SelectField label="Load Weight Category" value={formState.load_weight_category} onChange={(value) => setFormState((current) => ({ ...current, load_weight_category: value as DispatchLoadWeightCategory | '' }))}>
                <option value="">Optional</option>
                {loadWeightCategoryOptions.map((category) => (
                  <option key={category} value={category}>
                    {formatLabel(category)}
                  </option>
                ))}
              </SelectField>
              <SelectField label="Load Size Category" value={formState.load_size_category} onChange={(value) => setFormState((current) => ({ ...current, load_size_category: value as DispatchLoadSizeCategory | '' }))}>
                <option value="">Optional</option>
                {loadSizeCategoryOptions.map((category) => (
                  <option key={category} value={category}>
                    {formatLabel(category)}
                  </option>
                ))}
              </SelectField>
              <SelectField label="Editable Status" value={formState.status} onChange={(value) => setFormState((current) => ({ ...current, status: value as DispatchRequestFormState['status'] }))}>
                <option value="">Keep current</option>
                <option value="new">New</option>
                <option value="reviewing">Reviewing</option>
                <option value="pricing_pending">Pricing Pending</option>
              </SelectField>
              <InputField label="Preferred Pickup Date" type="date" value={formState.preferred_pickup_date} onChange={(value) => setFormState((current) => ({ ...current, preferred_pickup_date: value }))} />
              <InputField label="Preferred Pickup Time" type="time" value={formState.preferred_pickup_time} onChange={(value) => setFormState((current) => ({ ...current, preferred_pickup_time: value }))} />
              <InputField label="Expected Delivery Time (Optional)" type="datetime-local" value={formState.expected_delivery_time} onChange={(value) => setFormState((current) => ({ ...current, expected_delivery_time: value }))} />
              <div className="md:col-span-2 rounded-xl border border-blue-100 bg-blue-50/60 p-4">
                <SelectField label="Dispatch Payment Classification" value={formState.dispatch_financial_type} onChange={(value) => setFormState((current) => ({ ...current, dispatch_financial_type: value as DispatchFinancialType }))}>
                  <option value="external_paid">External Paid</option>
                  <option value="internal_company">Internal Company</option>
                  <option value="partner_contract">Partner Contract</option>
                  <option value="complimentary">Complimentary</option>
                </SelectField>
                <p className="mt-2 text-xs text-blue-800">
                  {formState.dispatch_financial_type === 'external_paid' && 'Customer-funded dispatch. Charge and payment are tracked as customer revenue and receivables.'}
                  {formState.dispatch_financial_type === 'internal_company' && 'Company-funded internal movement. No customer charge or receivable is created.'}
                  {formState.dispatch_financial_type === 'partner_contract' && 'Partner-funded work. Billing follows the selected contract method and is reported separately.'}
                  {formState.dispatch_financial_type === 'complimentary' && 'No-charge dispatch. Operational costs and driver compensation are still tracked.'}
                </p>
              </div>
              {formState.dispatch_financial_type === 'partner_contract' && (
                <>
                  <InputField label="Partner Organization / Reference" value={formState.partner_organization_reference} onChange={(value) => setFormState((current) => ({ ...current, partner_organization_reference: value }))} />
                  <SelectField label="Partner Billing Method" value={formState.partner_billing_method} onChange={(value) => setFormState((current) => ({ ...current, partner_billing_method: value as PartnerBillingMethod }))}>
                    <option value="">Select billing method</option>
                    <option value="no_individual_payment">No Individual Payment</option>
                    <option value="billed_later">Billed Later</option>
                    <option value="monthly_contract">Monthly Contract</option>
                    <option value="prepaid_contract">Prepaid Contract</option>
                    <option value="manual_settlement">Manual Settlement</option>
                  </SelectField>
                </>
              )}
              {(formState.dispatch_financial_type === 'external_paid' || formState.dispatch_financial_type === 'partner_contract') && (
                <InputField label={formState.dispatch_financial_type === 'partner_contract' ? 'Contract / Agreed Charge' : 'Proposed Charge'} type="number" value={formState.proposed_charge} onChange={(value) => setFormState((current) => ({ ...current, proposed_charge: value }))} />
              )}
              {(formState.dispatch_financial_type === 'external_paid' || formState.partner_billing_method === 'manual_settlement') && (
                <>
                  <SelectField label="Payment Status" value={formState.payment_status} onChange={(value) => setFormState((current) => ({ ...current, payment_status: value as DispatchPaymentStatus }))}>
                    {paymentStatusOptions.map((paymentStatus) => <option key={paymentStatus} value={paymentStatus}>{formatLabel(paymentStatus)}</option>)}
                  </SelectField>
                  <InputField label="Payment Method" value={formState.payment_method} onChange={(value) => setFormState((current) => ({ ...current, payment_method: value }))} />
                  <InputField label="Amount Paid" type="number" value={formState.amount_paid} onChange={(value) => setFormState((current) => ({ ...current, amount_paid: value }))} />
                </>
              )}
              <SelectField label="Driver Compensation" value={formState.driver_compensation_type} onChange={(value) => setFormState((current) => ({ ...current, driver_compensation_type: value as DriverCompensationType }))}>
                <option value="none">None</option>
                <option value="fixed_tip">Fixed Tip</option>
                <option value="fixed_allowance">Fixed Allowance</option>
                <option value="percentage_of_charge">Percentage of Charge</option>
                <option value="manual_amount">Manual Amount</option>
              </SelectField>
              {formState.driver_compensation_type !== 'none' && (
                <InputField label={formState.driver_compensation_type === 'percentage_of_charge' ? 'Compensation Percentage' : 'Compensation Amount'} type="number" value={formState.driver_compensation_value} onChange={(value) => setFormState((current) => ({ ...current, driver_compensation_value: value }))} />
              )}
              <div className="md:col-span-2">
                <TextAreaField label="Load Description" value={formState.load_description} onChange={(value) => setFormState((current) => ({ ...current, load_description: value }))} placeholder="Describe the goods, package count, handling notes, or special requirements." />
              </div>
              <div className="md:col-span-2">
                <TextAreaField label="Notes" value={formState.notes} onChange={(value) => setFormState((current) => ({ ...current, notes: value }))} placeholder="Add customer context, pricing notes, or review remarks." />
              </div>
              {formError && <ErrorBanner message={formError} className="md:col-span-2" />}
            </div>
            <ModalFooter onCancel={closeFormModal} submitLabel={isSubmitting ? 'Saving...' : editingRequest ? 'Save Request' : 'Create Request'} isSubmitting={isSubmitting} />
          </form>
        </ModalShell>
      )}

      <Drawer open={Boolean(selectedRequestId)} direction="right" onOpenChange={(open) => !open && closeDetailsDrawer()}>
        <DrawerContent className="w-full max-w-3xl border-l border-gray-200 bg-white">
          <DrawerHeader className="border-b border-gray-200 px-6 py-4 text-left">
            <DrawerTitle className="text-xl font-semibold text-[#0F172A]">{detailRequest?.request_id || 'Dispatch Request'}</DrawerTitle>
            <DrawerDescription className="text-sm text-gray-500">
              Review intake, pricing, schedule preparation, and multi-stop planning.
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
              <ErrorBanner message={detailError} />
            ) : detailRequest ? (
              <div className="space-y-6">
                <div className="flex flex-wrap gap-2">
                  {canManagePricing && (
                    <button
                      type="button"
                      onClick={() => openPricingModal(detailRequest, 'revise')}
                      className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 transition-all hover:bg-gray-50"
                    >
                      <CircleDollarSign className="h-4 w-4" />
                      Revise Pricing
                    </button>
                  )}
                  {canApprovePricing && (
                    <>
                      <button
                        type="button"
                        onClick={() => openPricingModal(detailRequest, 'approve')}
                        className="inline-flex items-center gap-2 rounded-lg border border-green-200 bg-green-50 px-3 py-2 text-sm font-medium text-green-700 transition-all hover:bg-green-100"
                      >
                        <CheckCircle className="h-4 w-4" />
                        Approve Pricing
                      </button>
                      <button
                        type="button"
                        onClick={() => openPricingModal(detailRequest, 'reject')}
                        className="inline-flex items-center gap-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm font-medium text-rose-700 transition-all hover:bg-rose-100"
                      >
                        <XCircle className="h-4 w-4" />
                        Reject Pricing
                      </button>
                    </>
                  )}
                  <button
                    type="button"
                    onClick={() => openScheduleModal(detailRequest)}
                    className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 transition-all hover:bg-gray-50"
                  >
                    <CalendarDays className="h-4 w-4" />
                    Schedule Request
                  </button>
                  <button
                    type="button"
                    onClick={() => openStopModal(detailRequest)}
                    className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 transition-all hover:bg-gray-50"
                  >
                    <Route className="h-4 w-4" />
                    Add Stop
                  </button>
                </div>

                <DetailSection title="Overview">
                  <DetailGrid>
                    <DetailRow label="Customer" value={detailRequest.customer_name} />
                    <DetailRow label="Phone" value={detailRequest.customer_phone} />
                    <DetailRow label="Company" value={detailRequest.customer_company || 'Individual'} />
                    <DetailRow label="Request Type" value={formatRequestTypeLabel(detailRequest.request_type)} />
                    <DetailRow label="Vehicle Type Needed" value={formatLabel(detailRequest.vehicle_type_needed)} />
                    <DetailRow label="Status" value={STATUS_LABELS[detailRequest.status]} />
                  </DetailGrid>
                </DetailSection>

                <DetailSection title="Route & Load">
                  <DetailGrid>
                    <DetailRow label="Pickup Location" value={detailRequest.pickup_location} />
                    <DetailRow label="Destination" value={detailRequest.destination} />
                    <DetailRow label="Load Type" value={formatLabel(detailRequest.load_type)} />
                    <DetailRow label="Weight Category" value={formatLabel(detailRequest.load_weight_category)} />
                    <DetailRow label="Size Category" value={formatLabel(detailRequest.load_size_category)} />
                    <DetailRow label="Urgency" value={formatLabel(detailRequest.urgency)} />
                  </DetailGrid>
                </DetailSection>

                <DetailSection title="Pricing Review">
                  <DetailGrid>
                    <DetailRow label="Pricing Status" value={detailRequest.pricing_status ? PRICING_STATUS_LABELS[detailRequest.pricing_status] : 'Pricing Pending'} />
                    <DetailRow label="Proposed Charge" value={formatCurrency(detailRequest.proposed_charge)} />
                    <DetailRow label="Approved Charge" value={formatCurrency(detailRequest.approved_charge)} />
                    <DetailRow label="Distance Estimate" value={detailRequest.distance_estimate_km !== null && detailRequest.distance_estimate_km !== undefined ? `${detailRequest.distance_estimate_km} km` : 'Not recorded'} />
                    <DetailRow label="Fuel Estimate" value={detailRequest.fuel_estimate_amount !== null && detailRequest.fuel_estimate_amount !== undefined ? `${detailRequest.fuel_estimate_amount} L` : 'Not recorded'} />
                    <DetailRow label="Fuel Cost" value={detailRequest.fuel_estimate_cost !== null && detailRequest.fuel_estimate_cost !== undefined ? formatCurrency(detailRequest.fuel_estimate_cost) : 'Not recorded'} />
                    <DetailRow label="Other Costs" value={detailRequest.other_expected_costs !== null && detailRequest.other_expected_costs !== undefined ? formatCurrency(detailRequest.other_expected_costs) : 'Not recorded'} />
                    <DetailRow label="Expected Net Revenue" value={detailRequest.expected_net_revenue !== null && detailRequest.expected_net_revenue !== undefined ? formatCurrency(detailRequest.expected_net_revenue) : 'Pending'} />
                    <DetailRow label="Pricing Reviewed By" value={detailRequest.pricing_reviewed_by_user?.full_name || 'Not recorded'} />
                    <DetailRow label="Pricing Reviewed At" value={formatDateTime(detailRequest.pricing_reviewed_at)} />
                  </DetailGrid>
                  <div className="mt-4 rounded-lg border border-gray-200 bg-gray-50 px-4 py-4 text-sm text-gray-700">
                    {detailRequest.pricing_notes || 'No pricing notes recorded yet.'}
                  </div>
                </DetailSection>

                <DetailSection title="Scheduling">
                  <DetailGrid>
                    <DetailRow label="Schedule Type" value={formatLabel(detailRequest.schedule_type)} />
                    <DetailRow label="Scheduled Start" value={formatDateTime(detailRequest.scheduled_start_time)} />
                    <DetailRow label="Scheduled End" value={formatDateTime(detailRequest.scheduled_end_time)} />
                    <DetailRow label="Expected Return" value={formatDateTime(detailRequest.expected_return_time)} />
                    <DetailRow label="Recurrence Pattern" value={formatLabel(detailRequest.recurrence_pattern)} />
                    <DetailRow label="Recurrence End Date" value={detailRequest.recurrence_end_date || 'Not recorded'} />
                  </DetailGrid>
                  <div className="mt-4 rounded-lg border border-gray-200 bg-gray-50 px-4 py-4 text-sm text-gray-700">
                    {detailRequest.schedule_notes || 'No schedule notes recorded yet.'}
                  </div>
                </DetailSection>

                <DetailSection title="Multi-Stop Planning">
                  {!detailRequest.stops?.length ? (
                    <div className="rounded-xl border border-dashed border-gray-300 bg-gray-50 px-4 py-6 text-sm text-gray-600">
                      No stops planned yet. Add a stop to prepare a multi-stop dispatch.
                    </div>
                  ) : (
                    <div className="space-y-3">
                      {detailRequest.stops.map((stop) => (
                        <div key={stop.stop_id} className="rounded-xl border border-gray-200 p-4">
                          <div className="flex flex-wrap items-start justify-between gap-3">
                            <div>
                              <div className="text-sm font-semibold text-[#0F172A]">
                                Stop {stop.stop_sequence}: {formatLabel(stop.stop_type)}
                              </div>
                              <div className="mt-1 text-sm text-gray-600">{stop.location}</div>
                              <div className="mt-2 text-xs text-gray-500">
                                Arrival: {formatDateTime(stop.planned_arrival_time)} • Departure: {formatDateTime(stop.planned_departure_time)}
                              </div>
                              <div className="mt-2 text-xs text-gray-500">
                                Delivery: {stop.delivery_status === 'delivered' ? `Delivered at ${formatDateTime(stop.delivered_at)}` : 'Pending'}
                              </div>
                            </div>
                            <div className="flex flex-wrap gap-2">
                              <button
                                type="button"
                                onClick={() => openStopModal(detailRequest, stop)}
                                className="inline-flex items-center gap-1 rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-700 transition-all hover:bg-gray-50"
                              >
                                <Pencil className="h-3.5 w-3.5" />
                                Edit
                              </button>
                              <button
                                type="button"
                                onClick={() => void handleDeleteStop(detailRequest.id, stop.stop_id)}
                                className="inline-flex items-center gap-1 rounded-lg border border-rose-200 bg-rose-50 px-2.5 py-1.5 text-xs font-medium text-rose-700 transition-all hover:bg-rose-100"
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                                Remove
                              </button>
                            </div>
                          </div>
                          <div className="mt-3 grid gap-3 md:grid-cols-2">
                            <DetailRow label="Contact" value={stop.contact_name || 'Not recorded'} compact />
                            <DetailRow label="Phone" value={stop.contact_phone || 'Not recorded'} compact />
                            <DetailRow label="Load Note" value={stop.load_note || 'Not recorded'} compact />
                            <DetailRow label="Stop Charge" value={stop.stop_charge !== null && stop.stop_charge !== undefined ? formatCurrency(stop.stop_charge) : 'Not recorded'} compact />
                          </div>
                          {stop.delivery_note ? (
                            <div className="mt-3 rounded-lg border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-700">
                              {stop.delivery_note}
                            </div>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  )}
                </DetailSection>

                <DetailSection title="Workflow">
                  <DetailGrid>
                    <DetailRow label="Created By" value={detailRequest.created_by_user?.full_name || 'Unknown'} />
                    <DetailRow label="Reviewed By" value={detailRequest.reviewed_by_user?.full_name || 'Not recorded'} />
                    <DetailRow label="Approved By" value={detailRequest.approved_by_user?.full_name || 'Not recorded'} />
                    <DetailRow label="Rejected By" value={detailRequest.rejected_by_user?.full_name || 'Not recorded'} />
                    <DetailRow label="Rejected Reason" value={detailRequest.rejection_reason || 'Not rejected'} />
                    <DetailRow label="Cancelled Reason" value={detailRequest.cancellation_reason || 'Not cancelled'} />
                  </DetailGrid>
                </DetailSection>

                <DetailSection title="Notes">
                  <div className="space-y-3">
                    <div className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-4 text-sm text-gray-700">
                      {detailRequest.load_description || 'No load description recorded.'}
                    </div>
                    <div className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-4 text-sm text-gray-700">
                      {detailRequest.notes || 'No intake notes recorded.'}
                    </div>
                  </div>
                </DetailSection>
              </div>
            ) : null}
          </div>
        </DrawerContent>
      </Drawer>

      {actionTarget && actionType && (
        <ModalShell title={getActionTitle(actionType)} subtitle={actionTarget.request_id} onClose={() => {
          setActionTarget(null);
          setActionType(null);
          setActionError('');
        }} maxWidth="max-w-2xl">
          <form onSubmit={handleActionSubmit} className="flex min-h-0 flex-1 flex-col overflow-hidden">
            <div className="space-y-4 overflow-y-auto px-6 py-5">
              {actionType === 'approve' && (
                <InputField label="Approved Charge" type="number" value={approvalForm.approved_charge} onChange={(value) => setApprovalForm({ approved_charge: value })} />
              )}
              {actionType === 'reject' && (
                <TextAreaField label="Rejection Reason" value={rejectForm.rejection_reason} onChange={(value) => setRejectForm({ rejection_reason: value })} placeholder="Explain why this request is being rejected." />
              )}
              {actionType === 'cancel' && (
                <TextAreaField label="Cancellation Reason" value={cancelForm.cancellation_reason} onChange={(value) => setCancelForm({ cancellation_reason: value })} placeholder="Explain why this request is being cancelled." />
              )}
              {actionError && <ErrorBanner message={actionError} />}
            </div>
            <ModalFooter onCancel={() => {
              setActionTarget(null);
              setActionType(null);
              setActionError('');
            }} submitLabel={isActionSubmitting ? 'Saving...' : getActionSubmitLabel(actionType)} isSubmitting={isActionSubmitting} />
          </form>
        </ModalShell>
      )}

      {pricingTarget && pricingAction && (
        <ModalShell title={pricingAction === 'approve' ? 'Approve Pricing' : pricingAction === 'reject' ? 'Reject Pricing' : 'Revise Pricing'} subtitle={pricingTarget.request_id} onClose={closePricingModal} maxWidth="max-w-4xl">
          <form onSubmit={handlePricingSubmit} className="flex min-h-0 flex-1 flex-col overflow-hidden">
            <div className="grid gap-4 overflow-y-auto px-6 py-5 md:grid-cols-2">
              <InputField label="Proposed Charge" type="number" value={pricingForm.proposed_charge} onChange={(value) => setPricingForm((current) => ({ ...current, proposed_charge: value }))} />
              <InputField label="Approved Charge" type="number" value={pricingForm.approved_charge} onChange={(value) => setPricingForm((current) => ({ ...current, approved_charge: value }))} />
              <InputField label="Distance Estimate (KM)" type="number" value={pricingForm.distance_estimate_km} onChange={(value) => setPricingForm((current) => ({ ...current, distance_estimate_km: value }))} />
              <InputField label="Fuel Estimate Amount" type="number" value={pricingForm.fuel_estimate_amount} onChange={(value) => setPricingForm((current) => ({ ...current, fuel_estimate_amount: value }))} />
              <InputField label="Fuel Estimate Cost" type="number" value={pricingForm.fuel_estimate_cost} onChange={(value) => setPricingForm((current) => ({ ...current, fuel_estimate_cost: value }))} />
              <InputField label="Other Expected Costs" type="number" value={pricingForm.other_expected_costs} onChange={(value) => setPricingForm((current) => ({ ...current, other_expected_costs: value }))} />
              <div className="rounded-xl border border-blue-200 bg-blue-50 px-4 py-4 md:col-span-2">
                <div className="text-xs font-semibold uppercase tracking-[0.18em] text-blue-700">Expected Net Revenue Preview</div>
                <div className="mt-2 text-xl font-semibold text-[#0F172A]">{formatCurrency(expectedRevenuePreview)}</div>
              </div>
              <div className="md:col-span-2">
                <TextAreaField label={pricingAction === 'reject' ? 'Pricing Rejection Reason' : 'Pricing Notes'} value={pricingForm.pricing_notes} onChange={(value) => setPricingForm((current) => ({ ...current, pricing_notes: value }))} placeholder="Capture pricing comments, approval remarks, or revision notes." />
              </div>
              {pricingError && <ErrorBanner message={pricingError} className="md:col-span-2" />}
            </div>
            <ModalFooter onCancel={closePricingModal} submitLabel={isPricingSubmitting ? 'Saving...' : pricingAction === 'approve' ? 'Approve Pricing' : pricingAction === 'reject' ? 'Reject Pricing' : 'Save Pricing'} isSubmitting={isPricingSubmitting} />
          </form>
        </ModalShell>
      )}

      {scheduleTarget && (
        <ModalShell title="Schedule Dispatch" subtitle={scheduleTarget.request_id} onClose={closeScheduleModal} maxWidth="max-w-4xl">
          <form onSubmit={handleScheduleSubmit} className="flex min-h-0 flex-1 flex-col overflow-hidden">
            <div className="grid gap-4 overflow-y-auto px-6 py-5 md:grid-cols-2">
              <SelectField label="Schedule Type" value={scheduleForm.schedule_type} onChange={(value) => setScheduleForm((current) => ({ ...current, schedule_type: value as DispatchScheduleType }))}>
                {scheduleTypeOptions.map((scheduleType) => (
                  <option key={scheduleType} value={scheduleType}>
                    {formatLabel(scheduleType)}
                  </option>
                ))}
              </SelectField>
              <InputField label="Scheduled Start Time" type="datetime-local" value={scheduleForm.scheduled_start_time} onChange={(value) => setScheduleForm((current) => ({ ...current, scheduled_start_time: value }))} />
              <InputField label="Scheduled End Time" type="datetime-local" value={scheduleForm.scheduled_end_time} onChange={(value) => setScheduleForm((current) => ({ ...current, scheduled_end_time: value }))} />
              <InputField label="Expected Return Time" type="datetime-local" value={scheduleForm.expected_return_time} onChange={(value) => setScheduleForm((current) => ({ ...current, expected_return_time: value }))} />
              {scheduleForm.schedule_type === 'recurring' && (
                <>
                  <SelectField label="Recurrence Pattern" value={scheduleForm.recurrence_pattern} onChange={(value) => setScheduleForm((current) => ({ ...current, recurrence_pattern: value as DispatchRecurrencePattern | '' }))}>
                    <option value="">Select recurrence pattern</option>
                    {recurrencePatternOptions.map((pattern) => (
                      <option key={pattern} value={pattern}>
                        {formatLabel(pattern)}
                      </option>
                    ))}
                  </SelectField>
                  <InputField label="Recurrence End Date" type="date" value={scheduleForm.recurrence_end_date} onChange={(value) => setScheduleForm((current) => ({ ...current, recurrence_end_date: value }))} />
                </>
              )}
              <div className="md:col-span-2">
                <TextAreaField label="Schedule Notes" value={scheduleForm.schedule_notes} onChange={(value) => setScheduleForm((current) => ({ ...current, schedule_notes: value }))} placeholder="Add planning notes, dispatch prep remarks, or recurring schedule context." />
              </div>
              {scheduleError && <ErrorBanner message={scheduleError} className="md:col-span-2" />}
            </div>
            <ModalFooter onCancel={closeScheduleModal} submitLabel={isScheduleSubmitting ? 'Saving...' : 'Save Schedule'} isSubmitting={isScheduleSubmitting} />
          </form>
        </ModalShell>
      )}

      {stopTarget && (
        <ModalShell title={editingStop ? 'Edit Dispatch Stop' : 'Add Dispatch Stop'} subtitle={stopTarget.request_id} onClose={closeStopModal} maxWidth="max-w-4xl">
          <form onSubmit={handleStopSubmit} className="flex min-h-0 flex-1 flex-col overflow-hidden">
            <div className="grid gap-4 overflow-y-auto px-6 py-5 md:grid-cols-2">
              <InputField label="Stop Sequence" type="number" value={stopForm.stop_sequence} onChange={(value) => setStopForm((current) => ({ ...current, stop_sequence: value }))} />
              <SelectField label="Stop Type" value={stopForm.stop_type} onChange={(value) => setStopForm((current) => ({ ...current, stop_type: value as DispatchStopType }))}>
                {stopTypeOptions.map((stopType) => (
                  <option key={stopType} value={stopType}>
                    {formatLabel(stopType)}
                  </option>
                ))}
              </SelectField>
              <InputField label="Location" value={stopForm.location} onChange={(value) => setStopForm((current) => ({ ...current, location: value }))} />
              <InputField label="Contact Name (Optional)" value={stopForm.contact_name} onChange={(value) => setStopForm((current) => ({ ...current, contact_name: value }))} />
              <InputField label="Contact Phone (Optional)" value={stopForm.contact_phone} onChange={(value) => setStopForm((current) => ({ ...current, contact_phone: value }))} />
              <InputField label="Stop Charge (Optional)" type="number" value={stopForm.stop_charge} onChange={(value) => setStopForm((current) => ({ ...current, stop_charge: value }))} />
              <InputField label="Planned Arrival Time" type="datetime-local" value={stopForm.planned_arrival_time} onChange={(value) => setStopForm((current) => ({ ...current, planned_arrival_time: value }))} />
              <InputField label="Planned Departure Time" type="datetime-local" value={stopForm.planned_departure_time} onChange={(value) => setStopForm((current) => ({ ...current, planned_departure_time: value }))} />
              <div className="md:col-span-2">
                <TextAreaField label="Load Note (Optional)" value={stopForm.load_note} onChange={(value) => setStopForm((current) => ({ ...current, load_note: value }))} placeholder="Capture pickup or dropoff handling notes for this stop." />
              </div>
              {stopError && <ErrorBanner message={stopError} className="md:col-span-2" />}
            </div>
            <ModalFooter onCancel={closeStopModal} submitLabel={isStopSubmitting ? 'Saving...' : editingStop ? 'Save Stop' : 'Add Stop'} isSubmitting={isStopSubmitting} />
          </form>
        </ModalShell>
      )}
    </div>
  );
}

function TabButton({
  isActive,
  onClick,
  icon: Icon,
  label,
}: {
  isActive: boolean;
  onClick: () => void;
  icon: typeof PackageCheck;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex items-center gap-2 rounded-full border px-4 py-2 text-sm font-medium transition-all ${
        isActive ? 'border-blue-600 bg-blue-600 text-white' : 'border-gray-300 bg-white text-gray-700 hover:bg-gray-50'
      }`}
    >
      <Icon className="h-4 w-4" />
      {label}
    </button>
  );
}

function StatCard({
  icon: Icon,
  label,
  value,
  tint,
}: {
  icon: typeof PackageCheck;
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

function ActionBadge({ action, onClick }: { action: RequestAction; onClick: () => void }) {
  const config: Record<RequestAction, { label: string; className: string; icon: typeof CheckCircle }> = {
    approve: { label: 'Approve', className: 'border-green-200 bg-green-50 text-green-700 hover:bg-green-100', icon: CheckCircle },
    reject: { label: 'Reject', className: 'border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100', icon: XCircle },
    cancel: { label: 'Cancel', className: 'border-amber-200 bg-amber-50 text-amber-700 hover:bg-amber-100', icon: XCircle },
  };
  const Icon = config[action].icon;
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex items-center gap-1 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-all ${config[action].className}`}
    >
      <Icon className="h-3.5 w-3.5" />
      {config[action].label}
    </button>
  );
}

function DispatchRequestsTableSkeleton() {
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
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  children: ReactNode;
}) {
  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-gray-700">{label}</label>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
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
    <section className="rounded-xl border border-gray-200 bg-white">
      <div className="border-b border-gray-200 px-4 py-3 text-sm font-semibold text-[#0F172A]">{title}</div>
      <div className="p-4">{children}</div>
    </section>
  );
}

function DetailGrid({ children }: { children: ReactNode }) {
  return <div className="grid gap-4 md:grid-cols-2">{children}</div>;
}

function DetailRow({
  label,
  value,
  compact = false,
}: {
  label: string;
  value: string;
  compact?: boolean;
}) {
  return (
    <div className={compact ? '' : 'rounded-lg border border-gray-200 bg-gray-50 px-4 py-3'}>
      <div className="text-xs font-semibold uppercase tracking-[0.14em] text-gray-500">{label}</div>
      <div className="mt-1 text-sm text-[#0F172A]">{value}</div>
    </div>
  );
}

function ErrorBanner({ message, className = '' }: { message: string; className?: string }) {
  return (
    <div className={`rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 ${className}`}>
      {message}
    </div>
  );
}

function getActionTitle(action: RequestAction) {
  if (action === 'approve') {
    return 'Approve Dispatch Request';
  }
  if (action === 'reject') {
    return 'Reject Dispatch Request';
  }
  return 'Cancel Dispatch Request';
}

function getActionSubmitLabel(action: RequestAction) {
  if (action === 'approve') {
    return 'Approve Request';
  }
  if (action === 'reject') {
    return 'Reject Request';
  }
  return 'Cancel Request';
}
