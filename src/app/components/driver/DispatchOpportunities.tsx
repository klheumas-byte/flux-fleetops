import { useEffect, useState, type ReactNode } from 'react';
import {
  ChevronLeft,
  ChevronRight,
  Eye,
  Loader2,
  Plus,
  RefreshCcw,
  Save,
  Search,
  Send,
  Undo2,
} from 'lucide-react';
import { toast } from 'sonner';

import {
  createDriverDispatchOpportunity,
  fetchDriverDispatchOpportunities,
  fetchDriverDispatchOpportunityById,
  fetchDriverDispatchOpportunityOptions,
  type DispatchOpportunityOptionsResponse,
  type DispatchOpportunityRecord,
  type DispatchOpportunityStatus,
  updateDriverDispatchOpportunity,
  withdrawDriverDispatchOpportunity,
} from '../../lib/dispatch-opportunity-api';
import { Drawer, DrawerContent, DrawerDescription, DrawerHeader, DrawerTitle } from '../ui/drawer';
import { Skeleton } from '../ui/skeleton';

type OpportunityFormState = {
  customer_name: string;
  customer_phone: string;
  customer_company: string;
  pickup_location: string;
  destination: string;
  load_description: string;
  load_type: string;
  load_weight_category: string;
  load_size_category: string;
  vehicle_type_needed: string;
  preferred_pickup_date: string;
  preferred_pickup_time: string;
  proposed_charge: string;
  payment_status: string;
  notes: string;
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

function initialFormState(options?: DispatchOpportunityOptionsResponse | null): OpportunityFormState {
  return {
    customer_name: '',
    customer_phone: '',
    customer_company: '',
    pickup_location: options?.pickup_locations?.[0] || '',
    destination: '',
    load_description: '',
    load_type: options?.load_types?.[0] || '',
    load_weight_category: options?.load_weight_categories?.[0] || '',
    load_size_category: options?.load_size_categories?.[0] || '',
    vehicle_type_needed: options?.vehicle_types?.[0] || '',
    preferred_pickup_date: new Date().toISOString().slice(0, 10),
    preferred_pickup_time: new Date().toISOString().slice(11, 16),
    proposed_charge: '',
    payment_status: options?.payment_statuses?.[0] || '',
    notes: '',
  };
}

function buildFormState(record: DispatchOpportunityRecord, options?: DispatchOpportunityOptionsResponse | null): OpportunityFormState {
  return {
    customer_name: record.customer_name || '',
    customer_phone: record.customer_phone || '',
    customer_company: record.customer_company || '',
    pickup_location: record.pickup_location || options?.pickup_locations?.[0] || '',
    destination: record.destination || '',
    load_description: record.load_description || '',
    load_type: record.load_type || options?.load_types?.[0] || '',
    load_weight_category: record.load_weight_category || options?.load_weight_categories?.[0] || '',
    load_size_category: record.load_size_category || options?.load_size_categories?.[0] || '',
    vehicle_type_needed: record.vehicle_type_needed || options?.vehicle_types?.[0] || '',
    preferred_pickup_date: record.preferred_pickup_date || new Date().toISOString().slice(0, 10),
    preferred_pickup_time: record.preferred_pickup_time || new Date().toISOString().slice(11, 16),
    proposed_charge: record.proposed_charge != null ? String(record.proposed_charge) : '',
    payment_status: record.payment_status || options?.payment_statuses?.[0] || '',
    notes: record.notes || '',
  };
}

function formatCurrency(value?: number | null) {
  if (value == null) {
    return 'Not set';
  }
  return `GHS ${Number(value).toLocaleString()}`;
}

function formatDateTime(date?: string | null, time?: string | null) {
  if (!date && !time) {
    return 'Not scheduled';
  }
  return [date, time].filter(Boolean).join(' ');
}

function isDriverEditable(status?: DispatchOpportunityStatus | null) {
  return status === 'draft' || status === 'submitted' || status === 'needs_clarification';
}

function isWithdrawable(status?: DispatchOpportunityStatus | null) {
  return status === 'draft' || status === 'submitted' || status === 'needs_clarification';
}

export default function DispatchOpportunities() {
  const [options, setOptions] = useState<DispatchOpportunityOptionsResponse | null>(null);
  const [items, setItems] = useState<DispatchOpportunityRecord[]>([]);
  const [pagination, setPagination] = useState({ page: 1, page_size: 10, total: 0, total_pages: 1 });
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [pageError, setPageError] = useState('');
  const [selectedOpportunityId, setSelectedOpportunityId] = useState<string | null>(null);
  const [detail, setDetail] = useState<DispatchOpportunityRecord | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [isLoadingDetail, setIsLoadingDetail] = useState(false);
  const [detailError, setDetailError] = useState('');
  const [form, setForm] = useState<OpportunityFormState>(initialFormState());
  const [withdrawalReason, setWithdrawalReason] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [isWithdrawing, setIsWithdrawing] = useState(false);

  const loadOptions = async () => {
    const response = await fetchDriverDispatchOpportunityOptions();
    setOptions(response);
    setForm((current) => (current.pickup_location ? current : initialFormState(response)));
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
      const response = await fetchDriverDispatchOpportunities({
        page,
        page_size: 10,
        q: query || undefined,
        status: status || undefined,
      });
      setItems(response.opportunities || []);
      setPagination(response.pagination);
    } catch (error) {
      setItems([]);
      setPagination({ page: 1, page_size: 10, total: 0, total_pages: 1 });
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

  const openCreate = () => {
    setIsCreating(true);
    setSelectedOpportunityId(null);
    setDetail(null);
    setDetailError('');
    setWithdrawalReason('');
    setForm(initialFormState(options));
  };

  const openDetail = async (opportunityId: string) => {
    setIsCreating(false);
    setSelectedOpportunityId(opportunityId);
    setDetail(null);
    setDetailError('');
    setWithdrawalReason('');
    setIsLoadingDetail(true);
    try {
      const response = await fetchDriverDispatchOpportunityById(opportunityId);
      setDetail(response);
      setForm(buildFormState(response, options));
      setWithdrawalReason(response.withdrawal_reason || '');
    } catch (error) {
      setDetailError(error instanceof Error ? error.message : 'Unable to load this opportunity right now.');
    } finally {
      setIsLoadingDetail(false);
    }
  };

  const replaceItem = (record: DispatchOpportunityRecord) => {
    setItems((current) => {
      const existing = current.some((item) => item.id === record.id);
      const next = existing
        ? current.map((item) => (item.id === record.id ? record : item))
        : [record, ...current];
      return next;
    });
    setDetail(record);
    setForm(buildFormState(record, options));
    setSelectedOpportunityId(record.id);
    setIsCreating(false);
  };

  const buildPayload = (targetStatus: 'draft' | 'submitted') => ({
    customer_name: form.customer_name,
    customer_phone: form.customer_phone,
    customer_company: form.customer_company || undefined,
    pickup_location: form.pickup_location || undefined,
    destination: form.destination || undefined,
    load_description: form.load_description || undefined,
    load_type: form.load_type || undefined,
    load_weight_category: form.load_weight_category || undefined,
    load_size_category: form.load_size_category || undefined,
    vehicle_type_needed: form.vehicle_type_needed || undefined,
    preferred_pickup_date: form.preferred_pickup_date || undefined,
    preferred_pickup_time: form.preferred_pickup_time || undefined,
    proposed_charge: form.proposed_charge ? Number(form.proposed_charge) : undefined,
    payment_status: form.payment_status || undefined,
    notes: form.notes || undefined,
    status: targetStatus,
  });

  const persistOpportunity = async (targetStatus: 'draft' | 'submitted') => {
    setIsSaving(true);
    try {
      const payload = buildPayload(targetStatus);
      const record = selectedOpportunityId && !isCreating
        ? await updateDriverDispatchOpportunity(selectedOpportunityId, payload)
        : await createDriverDispatchOpportunity(payload);
      replaceItem(record);
      toast.success(targetStatus === 'draft' ? 'Draft saved.' : 'Dispatch opportunity submitted.');
      await loadItems({ refresh: true, page: 1, status: statusFilter, query: searchQuery });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Unable to save this dispatch opportunity right now.');
    } finally {
      setIsSaving(false);
    }
  };

  const handleWithdraw = async () => {
    if (!detail) {
      return;
    }
    setIsWithdrawing(true);
    try {
      const record = await withdrawDriverDispatchOpportunity(detail.id, {
        withdrawal_reason: withdrawalReason || undefined,
      });
      replaceItem(record);
      toast.success('Dispatch opportunity withdrawn.');
      await loadItems({ refresh: true });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Unable to withdraw this opportunity right now.');
    } finally {
      setIsWithdrawing(false);
    }
  };

  const closeDrawer = () => {
    setSelectedOpportunityId(null);
    setDetail(null);
    setDetailError('');
    setIsCreating(false);
  };

  const detailStatus = detail?.status;
  const canEdit = isCreating || isDriverEditable(detailStatus);
  const canWithdraw = detail ? isWithdrawable(detail.status) : false;

  return (
    <div className="space-y-6 p-4 sm:p-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-[#0F172A]">Dispatch Opportunities</h1>
          <p className="mt-1 text-gray-600">
            Capture field opportunities as drafts or submit them for operations review without creating final dispatch jobs directly.
          </p>
        </div>
        <div className="flex flex-col gap-3 sm:flex-row">
          <button
            type="button"
            onClick={() => void loadItems({ refresh: true })}
            className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            {isRefreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCcw className="h-4 w-4" />}
            Refresh
          </button>
          <button
            type="button"
            onClick={openCreate}
            className="inline-flex items-center gap-2 rounded-lg bg-[#2563EB] px-4 py-2.5 text-sm font-medium text-white hover:bg-[#1d4ed8]"
          >
            <Plus className="h-4 w-4" />
            New Opportunity
          </button>
        </div>
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
              placeholder="Search customer, phone, pickup, or opportunity ID"
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
            {Array.from({ length: 5 }).map((_, index) => (
              <div key={index} className="grid grid-cols-1 gap-3 rounded-xl border border-gray-200 p-4 md:grid-cols-5">
                {Array.from({ length: 5 }).map((__, innerIndex) => (
                  <Skeleton key={innerIndex} className="h-5 w-full" />
                ))}
              </div>
            ))}
          </div>
        ) : pageError ? (
          <div className="px-6 py-6 text-sm text-red-700">{pageError}</div>
        ) : items.length === 0 ? (
          <div className="px-6 py-10 text-center text-sm text-gray-500">No dispatch opportunities found for your current filters.</div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200 text-sm">
                <thead className="bg-gray-50">
                  <tr className="text-left text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">
                    <th className="px-4 py-3">Opportunity</th>
                    <th className="px-4 py-3">Customer</th>
                    <th className="px-4 py-3">Route</th>
                    <th className="px-4 py-3">Charge</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">Pickup</th>
                    <th className="px-4 py-3">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200 bg-white">
                  {items.map((item) => (
                    <tr key={item.id}>
                      <td className="px-4 py-3 font-medium text-[#0F172A]">{item.opportunity_id}</td>
                      <td className="px-4 py-3">
                        <div className="font-medium text-[#0F172A]">{item.customer_name || 'Draft opportunity'}</div>
                        <div className="text-xs text-gray-500">{item.customer_phone || 'No phone yet'}</div>
                      </td>
                      <td className="px-4 py-3 text-gray-700">{[item.pickup_location, item.destination].filter(Boolean).join(' -> ') || 'Not set'}</td>
                      <td className="px-4 py-3 text-gray-700">{formatCurrency(item.proposed_charge)}</td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${STATUS_BADGES[item.status]}`}>
                          {STATUS_LABELS[item.status]}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-gray-700">{formatDateTime(item.preferred_pickup_date, item.preferred_pickup_time)}</td>
                      <td className="px-4 py-3">
                        <button
                          type="button"
                          onClick={() => void openDetail(item.id)}
                          className="inline-flex items-center gap-2 rounded-lg border border-gray-300 px-3 py-2 text-xs font-medium text-gray-700 hover:bg-gray-50"
                        >
                          <Eye className="h-3.5 w-3.5" />
                          View
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

      <Drawer open={isCreating || Boolean(selectedOpportunityId)} onOpenChange={(open) => { if (!open) closeDrawer(); }}>
        <DrawerContent className="max-h-[100dvh] overflow-hidden border-t border-gray-200 bg-white sm:max-h-[92vh]">
          <DrawerHeader className="border-b border-gray-200 px-4 py-4 text-left sm:px-6">
            <DrawerTitle>{isCreating ? 'New Dispatch Opportunity' : detail?.opportunity_id || 'Dispatch Opportunity'}</DrawerTitle>
            <DrawerDescription>
              Save your field lead as a draft or submit it for operations review. Drivers cannot create final dispatch jobs from this screen.
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
            ) : (
              <>
                {detail && !isCreating ? (
                  <div className="rounded-xl border border-gray-200 bg-gray-50 p-4">
                    <div className="flex flex-wrap items-center gap-3">
                      <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${STATUS_BADGES[detail.status]}`}>
                        {STATUS_LABELS[detail.status]}
                      </span>
                      {detail.dispatch_request_id ? (
                        <span className="text-sm text-gray-600">Linked request: {detail.dispatch_request_id}</span>
                      ) : null}
                    </div>
                    {detail.clarification_request ? <InfoLine label="Clarification" value={detail.clarification_request} /> : null}
                    {detail.review_notes ? <InfoLine label="Review Notes" value={detail.review_notes} /> : null}
                    {detail.rejection_reason ? <InfoLine label="Rejection Reason" value={detail.rejection_reason} /> : null}
                  </div>
                ) : null}

                <section>
                  <h3 className="mb-3 text-sm font-semibold uppercase tracking-[0.16em] text-gray-500">Opportunity Form</h3>
                  <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                    <InputField label="Customer Name" value={form.customer_name} onChange={(value) => setForm((current) => ({ ...current, customer_name: value }))} disabled={!canEdit} />
                    <InputField label="Customer Phone" value={form.customer_phone} onChange={(value) => setForm((current) => ({ ...current, customer_phone: value }))} disabled={!canEdit} />
                    <InputField label="Customer Company" value={form.customer_company} onChange={(value) => setForm((current) => ({ ...current, customer_company: value }))} disabled={!canEdit} />
                    <SelectField label="Pickup Location" value={form.pickup_location} onChange={(value) => setForm((current) => ({ ...current, pickup_location: value }))} disabled={!canEdit}>
                      <option value="">Select pickup location</option>
                      {(options?.pickup_locations || []).map((item) => <option key={item} value={item}>{item}</option>)}
                    </SelectField>
                    <InputField label="Destination" value={form.destination} onChange={(value) => setForm((current) => ({ ...current, destination: value }))} disabled={!canEdit} />
                    <SelectField label="Vehicle Type Needed" value={form.vehicle_type_needed} onChange={(value) => setForm((current) => ({ ...current, vehicle_type_needed: value }))} disabled={!canEdit}>
                      <option value="">Select vehicle type</option>
                      {(options?.vehicle_types || []).map((item) => <option key={item} value={item}>{item}</option>)}
                    </SelectField>
                    <SelectField label="Load Type" value={form.load_type} onChange={(value) => setForm((current) => ({ ...current, load_type: value }))} disabled={!canEdit}>
                      <option value="">Select load type</option>
                      {(options?.load_types || []).map((item) => <option key={item} value={item}>{item}</option>)}
                    </SelectField>
                    <SelectField label="Weight Category" value={form.load_weight_category} onChange={(value) => setForm((current) => ({ ...current, load_weight_category: value }))} disabled={!canEdit}>
                      <option value="">Select weight category</option>
                      {(options?.load_weight_categories || []).map((item) => <option key={item} value={item}>{item}</option>)}
                    </SelectField>
                    <SelectField label="Size Category" value={form.load_size_category} onChange={(value) => setForm((current) => ({ ...current, load_size_category: value }))} disabled={!canEdit}>
                      <option value="">Select size category</option>
                      {(options?.load_size_categories || []).map((item) => <option key={item} value={item}>{item}</option>)}
                    </SelectField>
                    <InputField label="Preferred Pickup Date" type="date" value={form.preferred_pickup_date} onChange={(value) => setForm((current) => ({ ...current, preferred_pickup_date: value }))} disabled={!canEdit} />
                    <InputField label="Preferred Pickup Time" type="time" value={form.preferred_pickup_time} onChange={(value) => setForm((current) => ({ ...current, preferred_pickup_time: value }))} disabled={!canEdit} />
                    <InputField label="Proposed Charge" type="number" value={form.proposed_charge} onChange={(value) => setForm((current) => ({ ...current, proposed_charge: value }))} disabled={!canEdit} />
                    <SelectField label="Payment Status" value={form.payment_status} onChange={(value) => setForm((current) => ({ ...current, payment_status: value }))} disabled={!canEdit}>
                      <option value="">Select payment status</option>
                      {(options?.payment_statuses || []).map((item) => <option key={item} value={item}>{item}</option>)}
                    </SelectField>
                    <div className="lg:col-span-2">
                      <TextAreaField label="Load / Goods Description" value={form.load_description} onChange={(value) => setForm((current) => ({ ...current, load_description: value }))} disabled={!canEdit} />
                    </div>
                    <div className="lg:col-span-2">
                      <TextAreaField label="Notes" value={form.notes} onChange={(value) => setForm((current) => ({ ...current, notes: value }))} disabled={!canEdit} />
                    </div>
                  </div>
                </section>
                {canWithdraw ? (
                  <section>
                    <h3 className="mb-3 text-sm font-semibold uppercase tracking-[0.16em] text-gray-500">Withdraw</h3>
                    <TextAreaField label="Withdrawal Reason" value={withdrawalReason} onChange={setWithdrawalReason} disabled={isWithdrawing} />
                  </section>
                ) : null}
              </>
            )}
          </div>

          <div className="border-t border-gray-200 bg-white px-4 py-4 sm:px-6">
            <div className="flex flex-col-reverse gap-3 sm:flex-row sm:flex-wrap sm:justify-between">
              <button
                type="button"
                onClick={closeDrawer}
                className="inline-flex w-full items-center justify-center rounded-lg border border-gray-300 px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 sm:w-auto"
              >
                Close
              </button>
              <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:justify-end">
                {canWithdraw ? (
                  <button
                    type="button"
                    onClick={() => void handleWithdraw()}
                    disabled={isWithdrawing}
                    className="inline-flex w-full items-center justify-center gap-2 rounded-lg border border-rose-300 px-4 py-2.5 text-sm font-medium text-rose-700 disabled:cursor-not-allowed disabled:opacity-60 sm:w-auto"
                  >
                    {isWithdrawing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Undo2 className="h-4 w-4" />}
                    Withdraw
                  </button>
                ) : null}
                {canEdit ? (
                  <>
                    <button
                      type="button"
                      onClick={() => void persistOpportunity('draft')}
                      disabled={isSaving}
                      className="inline-flex w-full items-center justify-center gap-2 rounded-lg border border-gray-300 px-4 py-2.5 text-sm font-medium text-gray-700 disabled:cursor-not-allowed disabled:opacity-60 sm:w-auto"
                    >
                      {isSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                      Save Draft
                    </button>
                    <button
                      type="button"
                      onClick={() => void persistOpportunity('submitted')}
                      disabled={isSaving}
                      className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-[#2563EB] px-4 py-2.5 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-60 sm:w-auto"
                    >
                      {isSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                      Submit For Review
                    </button>
                  </>
                ) : null}
              </div>
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

function InputField({
  label,
  value,
  onChange,
  type = 'text',
  disabled = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  disabled?: boolean;
}) {
  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-gray-700">{label}</label>
      <input
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm disabled:cursor-not-allowed disabled:bg-gray-50"
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
        className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm disabled:cursor-not-allowed disabled:bg-gray-50"
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
  disabled = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-gray-700">{label}</label>
      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        className="min-h-[100px] w-full rounded-lg border border-gray-300 px-4 py-3 text-sm disabled:cursor-not-allowed disabled:bg-gray-50"
      />
    </div>
  );
}
