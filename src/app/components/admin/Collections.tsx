import { useEffect, useMemo, useState } from 'react';
import {
  CheckCircle,
  DollarSign,
  Filter,
  Loader2,
  Plus,
  RotateCcw,
  Search,
  Wallet,
  XCircle,
} from 'lucide-react';
import { apiRequest, ApiRequestError } from '../../lib/api';
import { getStoredSessionUser } from '../../lib/auth-session';
import { useDebouncedValue } from '../../lib/use-debounced-value';

type CollectionStatus = 'pending' | 'submitted' | 'received' | 'approved' | 'rejected' | 'reversed';
type PaymentMethod = 'cash' | 'momo' | 'bank' | 'other';

interface UserSummary {
  id: string;
  full_name: string;
  phone: string;
  role: 'owner' | 'admin' | 'driver';
}

interface AssignmentOption {
  id: string;
  driver_id: string;
  vehicle_id: string;
  weekly_target: number;
  daily_target: number;
  start_date: string;
  status: string;
  driver: UserSummary | null;
  vehicle: {
    id: string;
    registration_number: string;
    vehicle_type: string;
  } | null;
}

interface CollectionRecord {
  id: string;
  driver_id: string;
  vehicle_id: string;
  assignment_id: string;
  amount: number;
  submitted_amount?: number | null;
  admin_received_amount?: number | null;
  collection_date: string;
  payment_method: PaymentMethod;
  reference_number: string | null;
  notes: string | null;
  driver_note?: string | null;
  admin_approval_note?: string | null;
  status: CollectionStatus;
  cycle_key?: string;
  week_start?: string;
  week_end?: string;
  payment_deadline?: string;
  rejection_reason?: string | null;
  is_late?: boolean;
  received_by_admin_id: string;
  approved_by_admin_id: string | null;
  driver: UserSummary | null;
  vehicle: {
    id: string;
    registration_number: string;
    vehicle_type: string;
  } | null;
  assignment: AssignmentOption | null;
  received_by_admin: UserSummary | null;
  approved_by_admin: UserSummary | null;
}

interface CollectionsResponse {
  success: boolean;
  data: {
    collections: CollectionRecord[];
    pagination?: {
      page: number;
      page_size: number;
      total_records: number;
      total_pages: number;
    };
    summary?: {
      total_records: number;
      approved_total: number;
      approved_count: number;
      pending_count: number;
      rejected_count: number;
      reversed_count: number;
    };
  };
}

interface CollectionOptionsResponse {
  success: boolean;
  data: {
    assignments: AssignmentOption[];
    admins: UserSummary[];
  };
}

interface PendingCollectionsResponse {
  success: boolean;
  data: {
    collections?: CollectionRecord[];
    pending_submissions?: CollectionRecord[];
  };
}

interface WeeklyDriverStatusRecord {
  assignment: AssignmentOption | null;
  driver: UserSummary | null;
  vehicle: {
    id: string;
    registration_number: string;
    vehicle_type: string;
  } | null;
  cycle: {
    cycle_key: string;
    assignment_id: string;
    week_start: string;
    week_end: string;
    payment_deadline: string;
    weekly_target: number;
    submitted_total: number;
    approved_total: number;
    outstanding_balance: number;
    achievement_percentage: number;
    status: 'open' | 'completed' | 'overdue';
  };
}

interface WeeklyStatusResponse {
  success: boolean;
  data: {
    drivers?: WeeklyDriverStatusRecord[];
    cycles?: WeeklyDriverStatusRecord[];
  };
}

interface CollectionMutationResponse {
  success: boolean;
  data: {
    collection: CollectionRecord;
  };
}

interface ApprovalFormState {
  admin_received_amount: string;
  admin_approval_note: string;
}

interface CollectionFormState {
  driver_id: string;
  assignment_id: string;
  amount: string;
  collection_date: string;
  payment_method: PaymentMethod;
  reference_number: string;
  notes: string;
  received_by_admin_id: string;
}

const initialFormState: CollectionFormState = {
  driver_id: '',
  assignment_id: '',
  amount: '',
  collection_date: new Date().toISOString().slice(0, 10),
  payment_method: 'cash',
  reference_number: '',
  notes: '',
  received_by_admin_id: '',
};

function formatCurrency(value: number) {
  return `GHS ${value.toLocaleString()}`;
}

function statusClassName(status: CollectionStatus) {
  switch (status) {
    case 'pending':
    case 'submitted':
    case 'received':
      return 'bg-amber-100 text-amber-800 border-amber-200';
    case 'approved':
      return 'bg-green-100 text-green-800 border-green-200';
    case 'rejected':
      return 'bg-rose-100 text-rose-800 border-rose-200';
    case 'reversed':
      return 'bg-red-100 text-red-800 border-red-200';
    default:
      return 'bg-gray-100 text-gray-800 border-gray-200';
  }
}

function getSubmittedAmount(collection: CollectionRecord) {
  return Number(collection.submitted_amount ?? collection.amount ?? 0);
}

function getStatusLabel(status: CollectionStatus) {
  if (status === 'pending' || status === 'submitted' || status === 'received') {
    return 'Pending';
  }
  return status.charAt(0).toUpperCase() + status.slice(1);
}

function toCollectionList(value: unknown): CollectionRecord[] {
  return Array.isArray(value) ? (value as CollectionRecord[]) : [];
}

function toWeeklyStatusList(value: unknown): WeeklyDriverStatusRecord[] {
  return Array.isArray(value) ? (value as WeeklyDriverStatusRecord[]) : [];
}

export default function Collections() {
  const [collections, setCollections] = useState<CollectionRecord[]>([]);
  const [pendingCollections, setPendingCollections] = useState<CollectionRecord[]>([]);
  const [weeklyStatuses, setWeeklyStatuses] = useState<WeeklyDriverStatusRecord[]>([]);
  const [assignments, setAssignments] = useState<AssignmentOption[]>([]);
  const [admins, setAdmins] = useState<UserSummary[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [driverFilter, setDriverFilter] = useState('all');
  const [paymentMethodFilter, setPaymentMethodFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [dateFilter, setDateFilter] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [approvalTarget, setApprovalTarget] = useState<CollectionRecord | null>(null);
  const [rejectionTarget, setRejectionTarget] = useState<CollectionRecord | null>(null);
  const [approvalForm, setApprovalForm] = useState<ApprovalFormState>({
    admin_received_amount: '',
    admin_approval_note: '',
  });
  const [rejectionReason, setRejectionReason] = useState('');
  const [actionError, setActionError] = useState('');
  const [isActionSubmitting, setIsActionSubmitting] = useState(false);
  const [pageError, setPageError] = useState('');
  const [pageNotice, setPageNotice] = useState('');
  const [formError, setFormError] = useState('');
  const [formState, setFormState] = useState<CollectionFormState>(initialFormState);
  const [currentPage, setCurrentPage] = useState(1);
  const [pagination, setPagination] = useState({ page: 1, page_size: 25, total_records: 0, total_pages: 1 });
  const debouncedSearchQuery = useDebouncedValue(searchQuery, 300);
  const [summary, setSummary] = useState({
    total_records: 0,
    approved_total: 0,
    approved_count: 0,
    pending_count: 0,
    rejected_count: 0,
    reversed_count: 0,
  });

  const sessionUser = getStoredSessionUser();
  const currentRole = sessionUser?.role || null;
  const currentUserId = sessionUser?.id || '';

  const getSettledData = <T,>(result: PromiseSettledResult<T>, fallback: T): T =>
    result.status === 'fulfilled' ? result.value : fallback;

  const loadCollections = async () => {
    setIsLoading(true);
    setPageError('');
    setPageNotice('');

    try {
      const collectionsResponse = await apiRequest<CollectionsResponse>(
        `/collections?page=${currentPage}&page_size=25&status=${encodeURIComponent(statusFilter)}&driver_id=${encodeURIComponent(driverFilter)}&payment_method=${encodeURIComponent(paymentMethodFilter)}&collection_date=${encodeURIComponent(dateFilter)}&search=${encodeURIComponent(debouncedSearchQuery)}`,
        { cacheTtlMs: 5000, timeoutMs: 15000 },
      );

      setCollections(toCollectionList(collectionsResponse?.data?.collections));
      setPagination(collectionsResponse?.data?.pagination || { page: 1, page_size: 25, total_records: 0, total_pages: 1 });
      setSummary(
        collectionsResponse?.data?.summary || {
          total_records: 0,
          approved_total: 0,
          approved_count: 0,
          pending_count: 0,
          rejected_count: 0,
          reversed_count: 0,
        },
      );
      setFormState((current) => ({
        ...current,
        received_by_admin_id: current.received_by_admin_id || currentUserId,
      }));
      setIsLoading(false);

      const [optionsResult, pendingResult, weeklyStatusResult] = await Promise.allSettled([
        apiRequest<CollectionOptionsResponse>('/collections/options', { cacheTtlMs: 10000, timeoutMs: 15000 }),
        apiRequest<PendingCollectionsResponse>('/collections/pending-submissions', { cacheTtlMs: 10000, timeoutMs: 15000 }),
        apiRequest<WeeklyStatusResponse>('/collections/weekly-status', { cacheTtlMs: 10000, timeoutMs: 15000 }),
      ]);
      const optionsResponse = getSettledData<CollectionOptionsResponse | null>(optionsResult, null);
      const pendingResponse = getSettledData<PendingCollectionsResponse | null>(pendingResult, null);
      const weeklyStatusResponse = getSettledData<WeeklyStatusResponse | null>(weeklyStatusResult, null);

      setAssignments(Array.isArray(optionsResponse?.data?.assignments) ? optionsResponse.data.assignments : []);
      setAdmins(Array.isArray(optionsResponse?.data?.admins) ? optionsResponse.data.admins : []);
      setPendingCollections(toCollectionList(pendingResponse?.data?.pending_submissions ?? pendingResponse?.data?.collections));
      setWeeklyStatuses(toWeeklyStatusList(weeklyStatusResponse?.data?.cycles ?? weeklyStatusResponse?.data?.drivers));

      const unavailableSections: string[] = [];
      if (optionsResult.status === 'rejected') unavailableSections.push('collection options');
      if (pendingResult.status === 'rejected') unavailableSections.push('pending submissions');
      if (weeklyStatusResult.status === 'rejected') unavailableSections.push('weekly status');
      if (unavailableSections.length > 0) {
        setPageNotice(`Some sections are temporarily unavailable: ${unavailableSections.join(', ')}.`);
      }
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setPageError(error.message);
      } else {
        setPageError('Unable to load collections right now.');
      }
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (currentRole === 'driver') {
      setIsLoading(false);
      return;
    }
    void loadCollections();
  }, [currentRole, currentPage, statusFilter, driverFilter, paymentMethodFilter, dateFilter, debouncedSearchQuery]);

  useEffect(() => {
    setCurrentPage(1);
  }, [statusFilter, driverFilter, paymentMethodFilter, dateFilter, debouncedSearchQuery]);

  const driverOptions = useMemo(() => {
    const seen = new Map<string, UserSummary>();
    assignments.forEach((assignment) => {
      if (assignment.driver && !seen.has(assignment.driver.id)) {
        seen.set(assignment.driver.id, assignment.driver);
      }
    });
    collections.forEach((collection) => {
      if (collection.driver && !seen.has(collection.driver.id)) {
        seen.set(collection.driver.id, collection.driver);
      }
    });
    return Array.from(seen.values());
  }, [assignments, collections]);

  const filteredAssignments = useMemo(() => {
    if (!formState.driver_id) {
      return assignments;
    }
    return assignments.filter((assignment) => assignment.driver_id === formState.driver_id);
  }, [assignments, formState.driver_id]);

  const selectedAssignment =
    assignments.find((assignment) => assignment.id === formState.assignment_id) || null;

  const filteredCollections = collections;

  const totals = useMemo(() => {
    return {
      totalCollected: summary.approved_total,
      approvedTotal: summary.approved_total,
      pendingCount: summary.pending_count,
      reversedCount: summary.reversed_count,
      outstandingHolding: summary.approved_total,
    };
  }, [summary]);

  const closeModal = () => {
    setShowModal(false);
    setFormError('');
    setFormState({
      ...initialFormState,
      collection_date: new Date().toISOString().slice(0, 10),
      received_by_admin_id: currentUserId,
    });
  };

  const closeApprovalModal = () => {
    setApprovalTarget(null);
    setApprovalForm({
      admin_received_amount: '',
      admin_approval_note: '',
    });
    setActionError('');
    setIsActionSubmitting(false);
  };

  const closeRejectionModal = () => {
    setRejectionTarget(null);
    setRejectionReason('');
    setActionError('');
    setIsActionSubmitting(false);
  };

  const handleFieldChange = <K extends keyof CollectionFormState>(
    field: K,
    value: CollectionFormState[K],
  ) => {
    setFormState((current) => ({
      ...current,
      [field]: value,
      ...(field === 'driver_id' ? { assignment_id: '' } : {}),
    }));
  };

  const handleCreateCollection = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!selectedAssignment) {
      setFormError('Please select an active assignment.');
      return;
    }

    setIsSubmitting(true);
    setFormError('');

    try {
      await apiRequest<CollectionMutationResponse>('/collections', {
        method: 'POST',
        body: JSON.stringify({
          driver_id: selectedAssignment.driver_id,
          vehicle_id: selectedAssignment.vehicle_id,
          assignment_id: selectedAssignment.id,
          amount: Number(formState.amount),
          status: 'approved',
          collection_date: formState.collection_date,
          payment_method: formState.payment_method,
          reference_number: formState.reference_number,
          notes: formState.notes,
          received_by_admin_id: formState.received_by_admin_id || currentUserId,
          approved_by_admin_id: formState.received_by_admin_id || currentUserId,
          admin_received_amount: Number(formState.amount),
          admin_approval_note: formState.notes,
        }),
      });

      closeModal();
      await loadCollections();
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setFormError(error.message);
      } else {
        setFormError('Unable to save manual collection entry right now.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleStatusUpdate = async (
    collectionId: string,
    status: CollectionStatus,
    options?: { admin_received_amount?: number; admin_approval_note?: string; rejection_reason?: string },
  ) => {
    setPageError('');
    try {
      if (status === 'approved') {
        await apiRequest<CollectionMutationResponse>(`/collections/pending-submissions/${collectionId}/confirm`, {
          method: 'PATCH',
          body: JSON.stringify({
            admin_received_amount: options?.admin_received_amount,
            admin_approval_note: options?.admin_approval_note,
          }),
        });
      } else if (status === 'rejected') {
        await apiRequest<CollectionMutationResponse>(`/collections/pending-submissions/${collectionId}/reject`, {
          method: 'PATCH',
          body: JSON.stringify({ rejection_reason: options?.rejection_reason }),
        });
      } else {
        await apiRequest<CollectionMutationResponse>(`/collections/${collectionId}/status`, {
          method: 'PATCH',
          body: JSON.stringify({
            status,
            rejection_reason: options?.rejection_reason,
            admin_received_amount: options?.admin_received_amount,
            admin_approval_note: options?.admin_approval_note,
          }),
        });
      }
      await loadCollections();
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setPageError(error.message);
        setActionError(error.message);
      } else {
        setPageError('Unable to update collection status right now.');
        setActionError('Unable to update collection status right now.');
      }
      throw error;
    }
  };

  const openApprovalModal = (collection: CollectionRecord) => {
    setApprovalTarget(collection);
    setApprovalForm({
      admin_received_amount: String(getSubmittedAmount(collection)),
      admin_approval_note: '',
    });
    setActionError('');
  };

  const openRejectionModal = (collection: CollectionRecord) => {
    setRejectionTarget(collection);
    setRejectionReason('');
    setActionError('');
  };

  const submitApproval = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!approvalTarget) {
      return;
    }

    const enteredAmount = Number(approvalForm.admin_received_amount);
    const submittedAmount = getSubmittedAmount(approvalTarget);

    if (!Number.isFinite(enteredAmount) || enteredAmount <= 0) {
      setActionError('Enter the amount received by admin.');
      return;
    }

    if (Number(enteredAmount.toFixed(2)) !== Number(submittedAmount.toFixed(2))) {
      setActionError('Received amount must match submitted amount.');
      return;
    }

    setActionError('');
    setIsActionSubmitting(true);

    try {
      await handleStatusUpdate(approvalTarget.id, 'approved', {
        admin_received_amount: enteredAmount,
        admin_approval_note: approvalForm.admin_approval_note,
      });
      closeApprovalModal();
    } catch {
      // Errors are surfaced through actionError/pageError in handleStatusUpdate.
    } finally {
      setIsActionSubmitting(false);
    }
  };

  const submitRejection = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!rejectionTarget) {
      return;
    }

    if (!rejectionReason.trim()) {
      setActionError('Rejection reason is required.');
      return;
    }

    setActionError('');
    setIsActionSubmitting(true);

    try {
      await handleStatusUpdate(rejectionTarget.id, 'rejected', {
        rejection_reason: rejectionReason.trim(),
      });
      closeRejectionModal();
    } catch {
      // Errors are surfaced through actionError/pageError in handleStatusUpdate.
    } finally {
      setIsActionSubmitting(false);
    }
  };

  if (currentRole === 'driver') {
    return (
      <div className="p-6">
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Drivers do not have access to the Collections page.
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-[#0F172A]">Collections</h1>
          <p className="mt-1 text-gray-600">Review submitted payments, confirm or reject them, and manage reversals</p>
          <p className="mt-2 text-sm text-gray-500">
            Use Manual Collection Entry only when a driver payment was not submitted through the Driver Portal.
          </p>
        </div>
        <button
          onClick={() => setShowModal(true)}
          className="flex items-center gap-2 rounded-lg bg-[#2563EB] px-4 py-2.5 font-medium text-white transition-all hover:bg-[#1d4ed8]"
          title="Use only when a driver payment was not submitted through the Driver Portal."
        >
          <Plus className="h-5 w-5" />
          Manual Collection Entry
        </button>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-lg bg-blue-100">
            <DollarSign className="h-5 w-5 text-blue-600" />
          </div>
          <div className="text-2xl font-semibold text-[#0F172A]">{formatCurrency(totals.totalCollected)}</div>
          <div className="text-sm text-gray-600">Confirmed Payments</div>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-lg bg-green-100">
            <CheckCircle className="h-5 w-5 text-green-600" />
          </div>
          <div className="text-2xl font-semibold text-[#0F172A]">{formatCurrency(totals.approvedTotal)}</div>
          <div className="text-sm text-gray-600">Approved Total</div>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-lg bg-amber-100">
            <Wallet className="h-5 w-5 text-amber-600" />
          </div>
          <div className="text-2xl font-semibold text-[#0F172A]">
            {formatCurrency(totals.outstandingHolding)}
          </div>
          <div className="text-sm text-gray-600">Holding Balance</div>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-lg bg-red-100">
            <RotateCcw className="h-5 w-5 text-red-600" />
          </div>
          <div className="text-2xl font-semibold text-[#0F172A]">{totals.pendingCount}</div>
          <div className="text-sm text-gray-600">Pending Submissions</div>
        </div>
      </div>

      <div className="rounded-xl border border-gray-200 bg-white p-4">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-gray-400" />
            <input
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder="Search by driver, vehicle, or reference..."
              className="w-full rounded-lg border border-gray-300 py-2.5 pl-10 pr-4 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
            />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Filter className="h-5 w-5 text-gray-500" />
            <select
              value={driverFilter}
              onChange={(event) => setDriverFilter(event.target.value)}
              className="rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
            >
              <option value="all">All Drivers</option>
              {driverOptions.map((driver) => (
                <option key={driver.id} value={driver.id}>
                  {driver.full_name}
                </option>
              ))}
            </select>
            <input
              type="date"
              value={dateFilter}
              onChange={(event) => setDateFilter(event.target.value)}
              className="rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
            />
            <select
              value={paymentMethodFilter}
              onChange={(event) => setPaymentMethodFilter(event.target.value)}
              className="rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
            >
              <option value="all">All Methods</option>
              <option value="cash">Cash</option>
              <option value="momo">MoMo</option>
              <option value="bank">Bank</option>
              <option value="other">Other</option>
            </select>
            <select
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value)}
              className="rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
            >
              <option value="all">All Status</option>
              <option value="pending">Pending</option>
              <option value="submitted">Submitted</option>
              <option value="received">Received</option>
              <option value="approved">Approved</option>
              <option value="rejected">Rejected</option>
              <option value="reversed">Reversed</option>
            </select>
          </div>
        </div>
      </div>

      {pageError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <span>{pageError}</span>
            <button
              onClick={() => void loadCollections()}
              className="rounded-lg border border-red-200 bg-white px-3 py-2 text-xs font-medium text-red-700 hover:bg-red-100"
            >
              Retry
            </button>
          </div>
        </div>
      )}

      {pageNotice && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          {pageNotice}
        </div>
      )}

      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
        <div className="border-b border-gray-200 px-6 py-4">
          <h2 className="text-lg font-semibold text-[#0F172A]">Pending Payment Submissions</h2>
          <p className="mt-1 text-sm text-gray-600">Payments waiting for confirmation or rejection</p>
        </div>
        {isLoading ? (
          <div className="flex items-center justify-center gap-3 px-6 py-12 text-gray-500">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span>Loading collections...</span>
          </div>
        ) : (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="border-b border-gray-200 bg-gray-50">
              <tr>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Driver</th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Vehicle</th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Amount</th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Submitted</th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Deadline</th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {pendingCollections.map((collection) => (
                <tr key={`pending-${collection.id}`} className="transition-colors hover:bg-gray-50">
                  <td className="px-6 py-4">
                    <div className="font-medium text-[#0F172A]">{collection.driver?.full_name || 'Unknown Driver'}</div>
                    <div className="text-xs text-gray-500">{collection.driver?.phone || 'No phone'}</div>
                  </td>
                  <td className="px-6 py-4">
                    <div className="font-medium text-[#0F172A]">
                      {collection.vehicle?.registration_number || 'Unknown Vehicle'}
                    </div>
                    <div className="text-xs capitalize text-gray-500">{collection.payment_method}</div>
                  </td>
                  <td className="px-6 py-4 font-semibold text-[#0F172A]">
                    {formatCurrency(getSubmittedAmount(collection))}
                  </td>
                  <td className="px-6 py-4 text-gray-700">{collection.collection_date}</td>
                  <td className="px-6 py-4">
                    <div className="text-gray-700">{collection.payment_deadline || 'N/A'}</div>
                    {collection.is_late && <div className="mt-1 text-xs text-red-600">Late submission</div>}
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => openApprovalModal(collection)}
                        className="rounded p-1.5 text-green-600 transition-all hover:bg-green-50"
                        title="Approve payment"
                      >
                        <CheckCircle className="h-4 w-4" />
                      </button>
                      <button
                        onClick={() => openRejectionModal(collection)}
                        className="rounded p-1.5 text-rose-600 transition-all hover:bg-rose-50"
                        title="Reject payment"
                      >
                        <XCircle className="h-4 w-4" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {pendingCollections.length === 0 && (
            <div className="px-6 py-12 text-center text-gray-500">No pending payment submissions right now.</div>
          )}
        </div>
        )}
      </div>

      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
        <div className="border-b border-gray-200 px-6 py-4">
          <h2 className="text-lg font-semibold text-[#0F172A]">Driver Weekly Target Status</h2>
          <p className="mt-1 text-sm text-gray-600">Live progress for each active assignment this week</p>
        </div>
        {isLoading ? (
          <div className="flex items-center justify-center gap-3 px-6 py-12 text-gray-500">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span>Loading collections...</span>
          </div>
        ) : (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="border-b border-gray-200 bg-gray-50">
              <tr>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Driver</th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Vehicle</th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Weekly Target</th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Submitted</th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Approved</th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Outstanding</th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Deadline</th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {weeklyStatuses.map((record) => (
                <tr key={`${record.assignment?.id || 'assignment'}-${record.cycle.cycle_key}`} className="transition-colors hover:bg-gray-50">
                  <td className="px-6 py-4">
                    <div className="font-medium text-[#0F172A]">{record.driver?.full_name || 'Unknown Driver'}</div>
                    <div className="text-xs text-gray-500">{record.driver?.phone || 'No phone'}</div>
                  </td>
                  <td className="px-6 py-4">
                    <div className="font-medium text-[#0F172A]">
                      {record.vehicle?.registration_number || 'No vehicle'}
                    </div>
                    <div className="text-xs capitalize text-gray-500">{record.vehicle?.vehicle_type || 'n/a'}</div>
                  </td>
                  <td className="px-6 py-4 text-gray-700">{formatCurrency(record.cycle.weekly_target)}</td>
                  <td className="px-6 py-4 text-blue-700">{formatCurrency(record.cycle.submitted_total)}</td>
                  <td className="px-6 py-4 text-green-700">{formatCurrency(record.cycle.approved_total)}</td>
                  <td className="px-6 py-4 text-red-700">{formatCurrency(record.cycle.outstanding_balance)}</td>
                  <td className="px-6 py-4 text-gray-700">{record.cycle.payment_deadline}</td>
                  <td className="px-6 py-4">
                    <span
                      className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${
                        record.cycle.status === 'completed'
                          ? 'border-green-200 bg-green-100 text-green-800'
                          : record.cycle.status === 'overdue'
                            ? 'border-red-200 bg-red-100 text-red-800'
                            : 'border-amber-200 bg-amber-100 text-amber-800'
                      }`}
                    >
                      {record.cycle.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {weeklyStatuses.length === 0 && (
            <div className="px-6 py-12 text-center text-gray-500">No active weekly driver cycles found.</div>
          )}
        </div>
        )}
      </div>

      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
        <div className="border-b border-gray-200 px-6 py-4">
          <h2 className="text-lg font-semibold text-[#0F172A]">Collection History</h2>
          <p className="mt-1 text-sm text-gray-600">Approved, received, pending, rejected, and reversed collections</p>
        </div>
        {isLoading ? (
          <div className="flex items-center justify-center gap-3 px-6 py-16 text-gray-500">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span>Loading collections...</span>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="border-b border-gray-200 bg-gray-50">
                <tr>
                  <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Driver</th>
                  <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Vehicle</th>
                  <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Amount</th>
                  <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Method</th>
                  <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Date</th>
                  <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Status</th>
                  <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Deadline</th>
                  <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Received By</th>
                  <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {filteredCollections.map((collection) => (
                  <tr key={collection.id} className="transition-colors hover:bg-gray-50">
                    <td className="px-6 py-4">
                      <div className="font-medium text-[#0F172A]">{collection.driver?.full_name || 'Unknown Driver'}</div>
                      <div className="text-xs text-gray-500">{collection.assignment_id}</div>
                    </td>
                    <td className="px-6 py-4">
                      <div className="font-medium text-[#0F172A]">
                        {collection.vehicle?.registration_number || 'Unknown Vehicle'}
                      </div>
                      <div className="text-xs text-gray-500">{collection.reference_number || 'No reference'}</div>
                    </td>
                    <td className="px-6 py-4 font-semibold text-[#0F172A]">{formatCurrency(collection.amount)}</td>
                    <td className="px-6 py-4 capitalize text-gray-700">{collection.payment_method}</td>
                    <td className="px-6 py-4 text-gray-700">{collection.collection_date}</td>
                    <td className="px-6 py-4">
                      <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${statusClassName(collection.status)}`}>
                        {getStatusLabel(collection.status)}
                      </span>
                      {collection.is_late && (
                        <div className="mt-1 text-xs text-red-600">Late submission</div>
                      )}
                      {collection.rejection_reason && (
                        <div className="mt-1 text-xs text-red-600">{collection.rejection_reason}</div>
                      )}
                    </td>
                    <td className="px-6 py-4 text-gray-700">
                      {collection.payment_deadline || 'N/A'}
                    </td>
                    <td className="px-6 py-4 text-gray-700">
                      {collection.received_by_admin?.full_name || 'Unknown Admin'}
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-2">
                        {(
                          collection.status === 'pending' ||
                          collection.status === 'submitted' ||
                          collection.status === 'received'
                        ) && (
                          <button
                            onClick={() => openApprovalModal(collection)}
                            className="rounded p-1.5 text-green-600 transition-all hover:bg-green-50"
                            title="Approve payment"
                          >
                            <CheckCircle className="h-4 w-4" />
                          </button>
                        )}
                        {(
                          collection.status === 'pending' ||
                          collection.status === 'submitted' ||
                          collection.status === 'received'
                        ) && (
                          <button
                            onClick={() => openRejectionModal(collection)}
                            className="rounded p-1.5 text-rose-600 transition-all hover:bg-rose-50"
                            title="Reject payment"
                          >
                            <XCircle className="h-4 w-4" />
                          </button>
                        )}
                        {collection.status === 'approved' && (
                          <button
                            onClick={() => void handleStatusUpdate(collection.id, 'reversed')}
                            className="rounded p-1.5 text-red-600 transition-all hover:bg-red-50"
                            title="Reverse collection"
                          >
                            <XCircle className="h-4 w-4" />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {filteredCollections.length === 0 && (
              <div className="px-6 py-12 text-center text-gray-500">
                {collections.length === 0
                  ? 'No collections recorded yet. Use Manual Collection Entry only when a driver payment was not submitted through the Driver Portal.'
                  : 'No matching records found.'}
              </div>
            )}
            <div className="flex flex-col gap-3 border-t border-gray-200 px-6 py-4 text-sm text-gray-600 sm:flex-row sm:items-center sm:justify-between">
              <div>Showing {filteredCollections.length} of {pagination.total_records} collections</div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setCurrentPage((page) => Math.max(page - 1, 1))}
                  disabled={currentPage <= 1}
                  className="rounded-lg border border-gray-300 px-3 py-2 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Previous
                </button>
                <span>Page {pagination.page} of {pagination.total_pages}</span>
                <button
                  onClick={() => setCurrentPage((page) => Math.min(page + 1, pagination.total_pages))}
                  disabled={currentPage >= pagination.total_pages}
                  className="rounded-lg border border-gray-300 px-3 py-2 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Next
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {approvalTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4">
          <div className="flex max-h-[90vh] w-full max-w-xl flex-col overflow-hidden rounded-xl border border-gray-200 bg-white shadow-2xl">
            <div className="shrink-0 border-b border-gray-200 px-6 py-4">
              <div className="flex items-start justify-between gap-4">
              <h2 className="text-xl font-semibold text-[#0F172A]">Confirm Driver Payment</h2>
              <button onClick={closeApprovalModal} className="rounded-lg p-2 transition-all hover:bg-gray-100">
                <XCircle className="h-5 w-5 text-gray-500" />
              </button>
              </div>
            </div>

            <form onSubmit={submitApproval} className="flex min-h-0 flex-1 flex-col">
              <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-6 py-5">
                {actionError && (
                <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                  {actionError}
                </div>
                )}

                <div className="rounded-lg border border-blue-100 bg-blue-50 px-4 py-3 text-sm text-blue-700">
                  Submitted amount: {formatCurrency(getSubmittedAmount(approvalTarget))}
                </div>

                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  <div className="min-w-0">
                    <div className="mb-2 text-sm font-medium text-gray-700">Driver</div>
                    <div className="truncate rounded-lg border border-gray-200 bg-gray-50 px-4 py-2.5 text-sm text-gray-700">
                      {approvalTarget.driver?.full_name || 'Unknown Driver'}
                    </div>
                  </div>
                  <div className="min-w-0">
                    <div className="mb-2 text-sm font-medium text-gray-700">Payment Method</div>
                    <div className="truncate rounded-lg border border-gray-200 bg-gray-50 px-4 py-2.5 text-sm capitalize text-gray-700">
                      {approvalTarget.payment_method}
                    </div>
                  </div>
                </div>

                <div>
                  <label className="mb-2 block text-sm font-medium text-gray-700">Reference Number</label>
                  <div
                    className={`rounded-lg border px-4 py-2.5 text-sm ${
                      approvalTarget.reference_number
                        ? 'border-gray-200 bg-gray-50 text-gray-700'
                        : 'border-dashed border-gray-200 bg-gray-50/70 text-gray-400'
                    }`}
                  >
                    {approvalTarget.reference_number || 'No reference'}
                  </div>
                </div>

                <div>
                  <label className="mb-2 block text-sm font-medium text-gray-700">Driver Note</label>
                  <div
                    className={`rounded-lg border px-4 py-2.5 text-sm ${
                      approvalTarget.driver_note || approvalTarget.notes
                        ? 'min-h-[72px] border-gray-200 bg-gray-50 text-gray-700'
                        : 'border-dashed border-gray-200 bg-gray-50/70 text-gray-400'
                    }`}
                  >
                    {approvalTarget.driver_note || approvalTarget.notes || 'No driver note'}
                  </div>
                </div>

                <div>
                  <label className="mb-2 block text-sm font-medium text-gray-700">Amount Received By Admin (GHS)</label>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    required
                    value={approvalForm.admin_received_amount}
                    onChange={(event) =>
                      setApprovalForm((current) => ({
                        ...current,
                        admin_received_amount: event.target.value,
                      }))
                    }
                    className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                  />
                </div>

                <div>
                  <label className="mb-2 block text-sm font-medium text-gray-700">Admin Approval Note</label>
                  <textarea
                    value={approvalForm.admin_approval_note}
                    onChange={(event) =>
                      setApprovalForm((current) => ({
                        ...current,
                        admin_approval_note: event.target.value,
                      }))
                    }
                    className="min-h-[100px] w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                    placeholder="Optional admin note"
                  />
                </div>
              </div>

              <div className="sticky bottom-0 shrink-0 border-t border-gray-200 bg-white px-6 py-4">
                <div className="flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-end">
                <button
                  type="button"
                  onClick={closeApprovalModal}
                  className="w-full rounded-lg border border-gray-300 px-4 py-2.5 font-medium text-gray-700 transition-all hover:bg-gray-50 sm:w-auto"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isActionSubmitting}
                  className="flex w-full items-center justify-center gap-2 rounded-lg bg-[#2563EB] px-4 py-2.5 font-medium text-white transition-all hover:bg-[#1d4ed8] disabled:cursor-not-allowed disabled:opacity-70 sm:w-auto"
                >
                  {isActionSubmitting && <Loader2 className="h-4 w-4 animate-spin" />}
                  {isActionSubmitting ? 'Confirming...' : 'Confirm Approval'}
                </button>
                </div>
              </div>
            </form>
          </div>
        </div>
      )}

      {rejectionTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4">
          <div className="w-full max-w-xl rounded-xl border border-gray-200 bg-white shadow-2xl">
            <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
              <h2 className="text-xl font-semibold text-[#0F172A]">Reject Driver Payment</h2>
              <button onClick={closeRejectionModal} className="rounded-lg p-2 transition-all hover:bg-gray-100">
                <XCircle className="h-5 w-5 text-gray-500" />
              </button>
            </div>

            <form onSubmit={submitRejection} className="space-y-4 px-6 py-5">
              {actionError && (
                <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                  {actionError}
                </div>
              )}

              <div className="rounded-lg border border-amber-100 bg-amber-50 px-4 py-3 text-sm text-amber-700">
                Driver submitted {formatCurrency(getSubmittedAmount(rejectionTarget))} via{' '}
                <span className="capitalize">{rejectionTarget.payment_method}</span>.
              </div>

              <div>
                <label className="mb-2 block text-sm font-medium text-gray-700">Rejection Reason</label>
                <textarea
                  required
                  value={rejectionReason}
                  onChange={(event) => setRejectionReason(event.target.value)}
                  className="min-h-[120px] w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                  placeholder="Enter reason for rejecting this payment submission"
                />
              </div>

              <div className="flex items-center justify-end gap-3 border-t border-gray-200 pt-4">
                <button
                  type="button"
                  onClick={closeRejectionModal}
                  className="rounded-lg border border-gray-300 px-4 py-2.5 font-medium text-gray-700 transition-all hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isActionSubmitting}
                  className="flex items-center gap-2 rounded-lg bg-rose-600 px-4 py-2.5 font-medium text-white transition-all hover:bg-rose-700 disabled:cursor-not-allowed disabled:opacity-70"
                >
                  {isActionSubmitting && <Loader2 className="h-4 w-4 animate-spin" />}
                  {isActionSubmitting ? 'Rejecting...' : 'Confirm Rejection'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4">
          <div className="flex h-[85vh] w-full max-w-2xl flex-col overflow-hidden rounded-xl border border-gray-200 bg-white shadow-2xl">
            <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
              <div>
                <h2 className="text-xl font-semibold text-[#0F172A]">Manual Collection Entry</h2>
                <p className="mt-1 text-sm text-gray-500">
                  Use only when a driver payment was not submitted through the Driver Portal.
                </p>
              </div>
              <button onClick={closeModal} className="rounded-lg p-2 transition-all hover:bg-gray-100">
                <XCircle className="h-5 w-5 text-gray-500" />
              </button>
            </div>

            <form onSubmit={handleCreateCollection} className="flex min-h-0 flex-1 flex-col">
              <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-6 py-5">
                {formError && (
                  <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                    {formError}
                  </div>
                )}

                <div>
                  <label className="mb-2 block text-sm font-medium text-gray-700">Driver</label>
                  <select
                    value={formState.driver_id}
                    onChange={(event) => handleFieldChange('driver_id', event.target.value)}
                    className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                    required
                  >
                    <option value="">Choose driver...</option>
                    {driverOptions.map((driver) => (
                      <option key={driver.id} value={driver.id}>
                        {driver.full_name} - {driver.phone}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="mb-2 block text-sm font-medium text-gray-700">Assignment</label>
                  <select
                    value={formState.assignment_id}
                    onChange={(event) => handleFieldChange('assignment_id', event.target.value)}
                    className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                    required
                  >
                    <option value="">Choose assignment...</option>
                    {filteredAssignments.map((assignment) => (
                      <option key={assignment.id} value={assignment.id}>
                        {(assignment.driver?.full_name || 'Driver')} -{' '}
                        {(assignment.vehicle?.registration_number || 'Vehicle')}
                      </option>
                    ))}
                  </select>
                </div>

                {selectedAssignment && (
                  <div className="rounded-lg border border-blue-100 bg-blue-50 px-4 py-3 text-sm text-blue-700">
                    Vehicle: {selectedAssignment.vehicle?.registration_number || 'Unknown'} | Weekly
                    target: {formatCurrency(selectedAssignment.weekly_target)}
                  </div>
                )}

                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  <div>
                    <label className="mb-2 block text-sm font-medium text-gray-700">Amount (GHS)</label>
                    <input
                      type="number"
                      step="0.01"
                      value={formState.amount}
                      onChange={(event) => handleFieldChange('amount', event.target.value)}
                      className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                      required
                    />
                  </div>
                  <div>
                    <label className="mb-2 block text-sm font-medium text-gray-700">Collection Date</label>
                    <input
                      type="date"
                      value={formState.collection_date}
                      onChange={(event) => handleFieldChange('collection_date', event.target.value)}
                      className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                      required
                    />
                  </div>
                </div>

                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  <div>
                    <label className="mb-2 block text-sm font-medium text-gray-700">Payment Method</label>
                    <select
                      value={formState.payment_method}
                      onChange={(event) =>
                        handleFieldChange('payment_method', event.target.value as PaymentMethod)
                      }
                      className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                    >
                      <option value="cash">Cash</option>
                      <option value="momo">MoMo</option>
                      <option value="bank">Bank</option>
                      <option value="other">Other</option>
                    </select>
                  </div>
                  <div>
                    <label className="mb-2 block text-sm font-medium text-gray-700">Received By</label>
                    <select
                      value={formState.received_by_admin_id}
                      onChange={(event) => handleFieldChange('received_by_admin_id', event.target.value)}
                      className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                      required
                    >
                      <option value="">Choose admin...</option>
                      {admins.map((admin) => (
                        <option key={admin.id} value={admin.id}>
                          {admin.full_name}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                <div>
                  <label className="mb-2 block text-sm font-medium text-gray-700">Reference Number</label>
                  <input
                    value={formState.reference_number}
                    onChange={(event) => handleFieldChange('reference_number', event.target.value)}
                    className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                    placeholder="Optional payment reference"
                  />
                </div>

                <div>
                  <label className="mb-2 block text-sm font-medium text-gray-700">Notes</label>
                  <textarea
                    value={formState.notes}
                    onChange={(event) => handleFieldChange('notes', event.target.value)}
                    className="min-h-[100px] w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                    placeholder="Optional notes"
                  />
                </div>
              </div>

              <div className="shrink-0 border-t border-gray-200 bg-gray-50 px-6 py-4">
                <div className="flex items-center justify-end gap-3">
                  <button
                    type="button"
                    onClick={closeModal}
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
                    {isSubmitting ? 'Saving Manual Entry...' : 'Save Manual Entry'}
                  </button>
                </div>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
