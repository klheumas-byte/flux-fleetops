import { useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Eye,
  Loader2,
  MessageSquareMore,
  RefreshCcw,
  Search,
  Send,
  XCircle,
} from 'lucide-react';
import { toast } from 'sonner';

import {
  approveDispatchOpportunity,
  convertDispatchOpportunity,
  fetchDispatchOpportunities,
  fetchDispatchOpportunityById,
  fetchDispatchOpportunityOptions,
  type DispatchOpportunityOptionsResponse,
  type DispatchOpportunityRecord,
  type DispatchOpportunityStatus,
  rejectDispatchOpportunity,
  requestDispatchOpportunityClarification,
  reviewDispatchOpportunity,
} from '../../lib/dispatch-opportunity-api';
import { Drawer, DrawerContent, DrawerDescription, DrawerHeader, DrawerTitle } from '../ui/drawer';
import { Skeleton } from '../ui/skeleton';

type ReviewFormState = {
  proposed_charge: string;
  approved_charge: string;
  payment_status: string;
  review_notes: string;
  clarification_request: string;
  rejection_reason: string;
};

const STATUS_LABELS: Record<DispatchOpportunityStatus, string> = {
  draft: 'Draft',
  submitted: 'Submitted',
  under_review: 'Under Review',
  needs_clarification: 'Needs Clarification',
  approved: 'Approved',
  converted_to_dispatch_request: 'Converted',
  rejected: 'Rejected',
  withdrawn: 'Withdrawn',
};

const STATUS_BADGES: Record<DispatchOpportunityStatus, string> = {
  draft: 'border-slate-200 bg-slate-100 text-slate-700',
  submitted: 'border-blue-200 bg-blue-100 text-blue-700',
  under_review: 'border-amber-200 bg-amber-100 text-amber-800',
  needs_clarification: 'border-orange-200 bg-orange-100 text-orange-800',
  approved: 'border-emerald-200 bg-emerald-100 text-emerald-800',
  converted_to_dispatch_request: 'border-indigo-200 bg-indigo-100 text-indigo-800',
  rejected: 'border-rose-200 bg-rose-100 text-rose-800',
  withdrawn: 'border-gray-200 bg-gray-100 text-gray-700',
};

function initialReviewState(record?: DispatchOpportunityRecord | null) {
  return {
    proposed_charge: record?.proposed_charge != null ? String(record.proposed_charge) : '',
    approved_charge: record?.approved_charge != null ? String(record.approved_charge) : '',
    payment_status: record?.payment_status || '',
    review_notes: record?.review_notes || '',
    clarification_request: record?.clarification_request || '',
    rejection_reason: record?.rejection_reason || '',
  };
}

function formatCurrency(value?: number | null) {
  if (value == null) {
    return 'Not set';
  }
  return `GHS ${Number(value).toLocaleString()}`;
}

type ActionName = 'save' | 'clarification' | 'reject' | 'approve' | 'convert' | null;

function canSaveReview(status?: DispatchOpportunityStatus | null) {
  return status != null && !['rejected', 'withdrawn', 'converted_to_dispatch_request'].includes(status);
}

function canRequestClarification(status?: DispatchOpportunityStatus | null) {
  return status != null && ['submitted', 'under_review', 'needs_clarification'].includes(status);
}

function canRejectOpportunity(status?: DispatchOpportunityStatus | null) {
  return status != null && !['rejected', 'withdrawn', 'converted_to_dispatch_request'].includes(status);
}

function canApproveOpportunity(status?: DispatchOpportunityStatus | null) {
  return status != null && ['submitted', 'under_review'].includes(status);
}

function canConvertOpportunity(status?: DispatchOpportunityStatus | null) {
  return status === 'approved';
}

export default function DispatchOpportunitiesReview() {
  const [options, setOptions] = useState<DispatchOpportunityOptionsResponse | null>(null);
  const [items, setItems] = useState<DispatchOpportunityRecord[]>([]);
  const [pagination, setPagination] = useState({ page: 1, page_size: 20, total: 0, total_pages: 1 });
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [pageError, setPageError] = useState('');
  const [selectedOpportunityId, setSelectedOpportunityId] = useState<string | null>(null);
  const [detail, setDetail] = useState<DispatchOpportunityRecord | null>(null);
  const [reviewForm, setReviewForm] = useState<ReviewFormState>(initialReviewState());
  const [isLoadingDetail, setIsLoadingDetail] = useState(false);
  const [detailError, setDetailError] = useState('');
  const [activeAction, setActiveAction] = useState<ActionName>(null);

  const loadOptions = async () => {
    const response = await fetchDispatchOpportunityOptions();
    setOptions(response);
  };

  const loadItems = async ({ refresh = false, page = currentPage, status = statusFilter, query = searchQuery }: {
    refresh?: boolean;
    page?: number;
    status?: string;
    query?: string;
  } = {}) => {
    if (refresh) {
      setIsRefreshing(true);
    } else {
      setIsLoading(true);
    }
    setPageError('');
    try {
      const response = await fetchDispatchOpportunities({
        page,
        page_size: 20,
        q: query || undefined,
        status: status || undefined,
      });
      setItems(response.opportunities || []);
      setPagination(response.pagination);
    } catch (error) {
      setItems([]);
      setPagination({ page: 1, page_size: 20, total: 0, total_pages: 1 });
      setPageError(error instanceof Error ? error.message : 'Unable to load dispatch opportunities right now.');
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  };

  useEffect(() => {
    void loadOptions();
  }, []);

  useEffect(() => {
    void loadItems();
  }, [currentPage, statusFilter]);

  const openDetail = async (opportunityId: string) => {
    setSelectedOpportunityId(opportunityId);
    setDetail(null);
    setDetailError('');
    setIsLoadingDetail(true);
    try {
      const response = await fetchDispatchOpportunityById(opportunityId);
      setDetail(response);
      setReviewForm(initialReviewState(response));
    } catch (error) {
      setDetailError(error instanceof Error ? error.message : 'Unable to load this opportunity right now.');
    } finally {
      setIsLoadingDetail(false);
    }
  };

  const replaceItem = (record: DispatchOpportunityRecord) => {
    setItems((current) => {
      const nextItems: DispatchOpportunityRecord[] = [];
      let replaced = false;
      current.forEach((item) => {
        if (item.id === record.id) {
          replaced = true;
          if (!statusFilter || record.status === statusFilter) {
            nextItems.push(record);
          }
          return;
        }
        nextItems.push(item);
      });
      if (!replaced && (!statusFilter || record.status === statusFilter)) {
        nextItems.unshift(record);
      }
      return nextItems;
    });
    setDetail(record);
    setReviewForm(initialReviewState(record));
  };

  const reviewPayload = useMemo(() => ({
    proposed_charge: reviewForm.proposed_charge ? Number(reviewForm.proposed_charge) : undefined,
    approved_charge: reviewForm.approved_charge ? Number(reviewForm.approved_charge) : undefined,
    payment_status: reviewForm.payment_status || undefined,
    review_notes: reviewForm.review_notes || undefined,
  }), [reviewForm]);

  const handleSaveReview = async () => {
    if (!detail) {
      return;
    }
    setActiveAction('save');
    try {
      const response = await reviewDispatchOpportunity(detail.id, reviewPayload);
      replaceItem(response);
      toast.success('Review notes saved.');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Unable to save this review right now.');
    } finally {
      setActiveAction(null);
    }
  };

  const handleClarification = async () => {
    if (!detail) {
      return;
    }
    setActiveAction('clarification');
    try {
      const response = await requestDispatchOpportunityClarification(detail.id, {
        ...reviewPayload,
        clarification_request: reviewForm.clarification_request || undefined,
      });
      replaceItem(response);
      toast.success('Clarification requested.');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Unable to request clarification right now.');
    } finally {
      setActiveAction(null);
    }
  };

  const handleApprove = async () => {
    if (!detail) {
      return;
    }
    setActiveAction('approve');
    try {
      const response = await approveDispatchOpportunity(detail.id, reviewPayload);
      replaceItem(response);
      toast.success('Dispatch opportunity approved.');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Unable to approve this opportunity right now.');
    } finally {
      setActiveAction(null);
    }
  };

  const handleReject = async () => {
    if (!detail) {
      return;
    }
    setActiveAction('reject');
    try {
      const response = await rejectDispatchOpportunity(detail.id, {
        ...reviewPayload,
        rejection_reason: reviewForm.rejection_reason || undefined,
      });
      replaceItem(response);
      toast.success('Dispatch opportunity rejected.');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Unable to reject this opportunity right now.');
    } finally {
      setActiveAction(null);
    }
  };

  const handleConvert = async () => {
    if (!detail) {
      return;
    }
    setActiveAction('convert');
    try {
      const response = await convertDispatchOpportunity(detail.id, {
        review_notes: reviewForm.review_notes || undefined,
      });
      replaceItem(response.opportunity);
      toast.success(`Converted to dispatch request ${response.dispatch_request.request_id}.`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Unable to convert this opportunity right now.');
    } finally {
      setActiveAction(null);
    }
  };

  const openDispatchRequestsPage = () => {
    if (typeof window === 'undefined') {
      return;
    }
    const state = { page: 'dispatch-requests', selectedVehicleId: null };
    window.history.pushState(state, '');
    window.dispatchEvent(new PopStateEvent('popstate', { state }));
  };

  return (
    <div className="space-y-6 p-4 sm:p-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-[#0F172A]">Dispatch Opportunities Review</h1>
          <p className="mt-1 text-gray-600">
            Review driver-submitted field leads, request clarification, approve pricing direction, and convert valid opportunities into official dispatch requests.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void loadItems({ refresh: true })}
          className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          {isRefreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCcw className="h-4 w-4" />}
          Refresh
        </button>
      </div>

      <div className="rounded-xl border border-gray-200 bg-white p-4 sm:p-5">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            setCurrentPage(1);
            void loadItems({ refresh: true, page: 1, status: statusFilter, query: searchQuery });
          }}
          className="grid grid-cols-1 gap-3 lg:grid-cols-[1fr_220px_auto]"
        >
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
            <input
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder="Search opportunity ID, customer, phone, pickup, or destination"
              className="w-full rounded-lg border border-gray-300 py-2.5 pl-9 pr-3 text-sm"
            />
          </div>
          <select
            value={statusFilter}
            onChange={(event) => {
              setStatusFilter(event.target.value);
              setCurrentPage(1);
            }}
            className="rounded-lg border border-gray-300 px-3 py-2.5 text-sm"
          >
            <option value="">All statuses</option>
            {(options?.statuses || []).map((status) => (
              <option key={status} value={status}>
                {STATUS_LABELS[status]}
              </option>
            ))}
          </select>
          <button type="submit" className="rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-medium text-white hover:bg-slate-800">
            Search
          </button>
        </form>
      </div>

      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
        {isLoading ? (
          <div className="space-y-3 px-6 py-5">
            {Array.from({ length: 6 }).map((_, index) => (
              <div key={index} className="grid grid-cols-1 gap-3 rounded-xl border border-gray-200 p-4 md:grid-cols-6">
                {Array.from({ length: 6 }).map((__, innerIndex) => (
                  <Skeleton key={innerIndex} className="h-5 w-full" />
                ))}
              </div>
            ))}
          </div>
        ) : pageError ? (
          <div className="px-6 py-6 text-sm text-red-700">{pageError}</div>
        ) : items.length === 0 ? (
          <div className="px-6 py-10 text-center text-sm text-gray-500">No dispatch opportunities matched the current filters.</div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200 text-sm">
                <thead className="bg-gray-50">
                  <tr className="text-left text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">
                    <th className="px-4 py-3">Opportunity</th>
                    <th className="px-4 py-3">Driver</th>
                    <th className="px-4 py-3">Customer</th>
                    <th className="px-4 py-3">Route</th>
                    <th className="px-4 py-3">Proposed / Approved</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">Submitted</th>
                    <th className="px-4 py-3">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200 bg-white">
                  {items.map((item) => (
                    <tr key={item.id}>
                      <td className="px-4 py-3 font-medium text-[#0F172A]">{item.opportunity_id}</td>
                      <td className="px-4 py-3 text-gray-700">{item.submitted_by_driver?.full_name || 'Driver'}</td>
                      <td className="px-4 py-3">
                        <div className="font-medium text-[#0F172A]">{item.customer_name || 'Draft'}</div>
                        <div className="text-xs text-gray-500">{item.customer_phone || 'No phone yet'}</div>
                      </td>
                      <td className="px-4 py-3 text-gray-700">{[item.pickup_location, item.destination].filter(Boolean).join(' -> ') || 'Not set'}</td>
                      <td className="px-4 py-3 text-gray-700">{formatCurrency(item.proposed_charge)} / {formatCurrency(item.approved_charge)}</td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${STATUS_BADGES[item.status]}`}>
                          {STATUS_LABELS[item.status]}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-gray-700">{item.submitted_at ? new Date(item.submitted_at).toLocaleString() : 'Not submitted'}</td>
                      <td className="px-4 py-3">
                        <button
                          type="button"
                          onClick={() => void openDetail(item.id)}
                          className="inline-flex items-center gap-2 rounded-lg border border-gray-300 px-3 py-2 text-xs font-medium text-gray-700 hover:bg-gray-50"
                        >
                          <Eye className="h-3.5 w-3.5" />
                          Review
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex items-center justify-between border-t border-gray-200 px-4 py-3 text-sm">
              <div className="text-gray-500">
                Page {pagination.page} of {pagination.total_pages} • {pagination.total} total
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  disabled={pagination.page <= 1}
                  onClick={() => setCurrentPage((current) => Math.max(1, current - 1))}
                  className="inline-flex items-center gap-1 rounded-lg border border-gray-300 px-3 py-2 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <ChevronLeft className="h-4 w-4" />
                  Prev
                </button>
                <button
                  type="button"
                  disabled={pagination.page >= pagination.total_pages}
                  onClick={() => setCurrentPage((current) => Math.min(pagination.total_pages, current + 1))}
                  className="inline-flex items-center gap-1 rounded-lg border border-gray-300 px-3 py-2 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Next
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            </div>
          </>
        )}
      </div>

      <Drawer open={Boolean(selectedOpportunityId)} onOpenChange={(open) => { if (!open) setSelectedOpportunityId(null); }}>
        <DrawerContent className="max-h-[100dvh] overflow-hidden border-t border-gray-200 bg-white sm:max-h-[92vh]">
          <DrawerHeader className="border-b border-gray-200 px-4 py-4 text-left sm:px-6">
            <DrawerTitle>{detail?.opportunity_id || 'Dispatch Opportunity Review'}</DrawerTitle>
            <DrawerDescription>
              Keep review and conversion under operations control while preserving a clean handoff into the existing dispatch request workflow.
            </DrawerDescription>
          </DrawerHeader>

          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-6">
            {isLoadingDetail ? (
              <div className="space-y-3">
                <Skeleton className="h-8 w-full" />
                <Skeleton className="h-28 w-full" />
                <Skeleton className="h-28 w-full" />
              </div>
            ) : detailError ? (
              <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{detailError}</div>
            ) : detail ? (
              <>
                <section className="rounded-xl border border-gray-200 bg-gray-50 p-4">
                  <div className="flex flex-wrap items-center gap-3">
                    <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${STATUS_BADGES[detail.status]}`}>
                      {STATUS_LABELS[detail.status]}
                    </span>
                    {detail.dispatch_request_id ? <span className="text-sm text-gray-600">Dispatch request: {detail.dispatch_request_id}</span> : null}
                  </div>
                  <DetailGrid>
                    <DetailRow label="Submitted Driver" value={detail.submitted_by_driver?.full_name || 'Driver'} />
                    <DetailRow label="Customer" value={detail.customer_name || '-'} />
                    <DetailRow label="Phone" value={detail.customer_phone || '-'} />
                    <DetailRow label="Company" value={detail.customer_company || '-'} />
                    <DetailRow label="Pickup" value={detail.pickup_location || '-'} />
                    <DetailRow label="Destination" value={detail.destination || '-'} />
                    <DetailRow label="Load Type" value={detail.load_type || '-'} />
                    <DetailRow label="Vehicle Type Needed" value={detail.vehicle_type_needed || '-'} />
                    <DetailRow label="Weight Category" value={detail.load_weight_category || '-'} />
                    <DetailRow label="Size Category" value={detail.load_size_category || '-'} />
                    <DetailRow label="Preferred Pickup" value={[detail.preferred_pickup_date, detail.preferred_pickup_time].filter(Boolean).join(' ') || '-'} />
                    <DetailRow label="Driver Notes" value={detail.notes || '-'} />
                  </DetailGrid>
                  {detail.load_description ? <InfoLine label="Goods / Load Description" value={detail.load_description} /> : null}
                  {detail.clarification_request ? <InfoLine label="Clarification Request" value={detail.clarification_request} /> : null}
                  {detail.rejection_reason ? <InfoLine label="Rejection Reason" value={detail.rejection_reason} /> : null}
                </section>

                <section>
                  <h3 className="mb-3 text-sm font-semibold uppercase tracking-[0.16em] text-gray-500">Review Workspace</h3>
                  <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                    <InputField label="Driver Proposed Charge" type="number" value={reviewForm.proposed_charge} onChange={(value) => setReviewForm((current) => ({ ...current, proposed_charge: value }))} />
                    <InputField label="Approved Charge" type="number" value={reviewForm.approved_charge} onChange={(value) => setReviewForm((current) => ({ ...current, approved_charge: value }))} />
                    <SelectField label="Payment Status" value={reviewForm.payment_status} onChange={(value) => setReviewForm((current) => ({ ...current, payment_status: value }))}>
                      <option value="">Select payment status</option>
                      {(options?.payment_statuses || []).map((item) => <option key={item} value={item}>{item}</option>)}
                    </SelectField>
                    <div className="lg:col-span-2">
                      <TextAreaField label="Review Notes" value={reviewForm.review_notes} onChange={(value) => setReviewForm((current) => ({ ...current, review_notes: value }))} />
                    </div>
                    <div className="lg:col-span-2">
                      <TextAreaField label="Clarification Request" value={reviewForm.clarification_request} onChange={(value) => setReviewForm((current) => ({ ...current, clarification_request: value }))} />
                    </div>
                    <div className="lg:col-span-2">
                      <TextAreaField label="Rejection Reason" value={reviewForm.rejection_reason} onChange={(value) => setReviewForm((current) => ({ ...current, rejection_reason: value }))} />
                    </div>
                  </div>
                </section>
              </>
            ) : null}
          </div>

          <div className="border-t border-gray-200 bg-white px-4 py-4 sm:px-6">
            <div className="flex flex-col-reverse gap-3 sm:flex-row sm:flex-wrap sm:justify-between">
              <button
                type="button"
                onClick={() => setSelectedOpportunityId(null)}
                className="inline-flex w-full items-center justify-center rounded-lg border border-gray-300 px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 sm:w-auto"
              >
                Close
              </button>
              {detail ? (
                <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:justify-end">
                  <button
                    type="button"
                    onClick={() => void handleSaveReview()}
                    disabled={activeAction !== null || !canSaveReview(detail.status)}
                    className="inline-flex w-full items-center justify-center gap-2 rounded-lg border border-gray-300 px-4 py-2.5 text-sm font-medium text-gray-700 disabled:cursor-not-allowed disabled:opacity-60 sm:w-auto"
                  >
                    {activeAction === 'save' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                    Save Review
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleClarification()}
                    disabled={activeAction !== null || !canRequestClarification(detail.status)}
                    className="inline-flex w-full items-center justify-center gap-2 rounded-lg border border-amber-300 px-4 py-2.5 text-sm font-medium text-amber-700 disabled:cursor-not-allowed disabled:opacity-60 sm:w-auto"
                  >
                    {activeAction === 'clarification' ? <Loader2 className="h-4 w-4 animate-spin" /> : <MessageSquareMore className="h-4 w-4" />}
                    Request Clarification
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleReject()}
                    disabled={activeAction !== null || !canRejectOpportunity(detail.status)}
                    className="inline-flex w-full items-center justify-center gap-2 rounded-lg border border-rose-300 px-4 py-2.5 text-sm font-medium text-rose-700 disabled:cursor-not-allowed disabled:opacity-60 sm:w-auto"
                  >
                    {activeAction === 'reject' ? <Loader2 className="h-4 w-4 animate-spin" /> : <XCircle className="h-4 w-4" />}
                    Reject
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleApprove()}
                    disabled={activeAction !== null || !canApproveOpportunity(detail.status)}
                    className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-emerald-600 px-4 py-2.5 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-60 sm:w-auto"
                  >
                    {activeAction === 'approve' ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                    Approve Opportunity
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleConvert()}
                    disabled={activeAction !== null || !canConvertOpportunity(detail.status)}
                    className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-[#2563EB] px-4 py-2.5 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-60 sm:w-auto"
                  >
                    {activeAction === 'convert' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                    Convert To Dispatch Request
                  </button>
                  {detail.dispatch_request_id ? (
                    <button
                      type="button"
                      onClick={openDispatchRequestsPage}
                      className="inline-flex w-full items-center justify-center gap-2 rounded-lg border border-[#2563EB] px-4 py-2.5 text-sm font-medium text-[#2563EB] sm:w-auto"
                    >
                      Open Dispatch Request
                    </button>
                  ) : null}
                </div>
              ) : null}
            </div>
          </div>
        </DrawerContent>
      </Drawer>
    </div>
  );
}

function InfoLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="mt-3 text-sm text-gray-700">
      <span className="font-medium text-[#0F172A]">{label}:</span> {value}
    </div>
  );
}

function DetailGrid({ children }: { children: ReactNode }) {
  return <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">{children}</div>;
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white px-4 py-3">
      <div className="text-xs font-semibold uppercase tracking-[0.14em] text-gray-500">{label}</div>
      <div className="mt-1 text-sm font-medium text-[#0F172A]">{value}</div>
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
        className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm"
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
        className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm"
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
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-gray-700">{label}</label>
      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="min-h-[100px] w-full rounded-lg border border-gray-300 px-4 py-3 text-sm"
      />
    </div>
  );
}
