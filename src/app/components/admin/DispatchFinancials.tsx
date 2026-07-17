import { useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  DollarSign,
  FileWarning,
  Loader2,
  PiggyBank,
  Receipt,
  RefreshCcw,
  Search,
  ShieldAlert,
  WalletCards,
} from 'lucide-react';
import { toast } from 'sonner';
import {
  closeDispatchFinancial,
  createDispatchFinancialIncident,
  fetchDispatchFinancialDetail,
  fetchDispatchFinancialOptions,
  fetchDispatchFinancials,
  reviewDispatchExpense,
  reviewDispatchIncident,
  verifyDispatchFinancial,
  type DispatchFinancialDetail,
  type DispatchFinancialExpense,
  type DispatchFinancialExpenseStatus,
  type DispatchFinancialIncident,
  type DispatchFinancialListItem,
  type DriverCompensationType,
} from '../../lib/dispatch-financial-api';
import { Drawer, DrawerContent, DrawerDescription, DrawerHeader, DrawerTitle } from '../ui/drawer';
import { Skeleton } from '../ui/skeleton';

function formatCurrency(value?: number | null) {
  const amount = typeof value === 'number' && !Number.isNaN(value) ? value : 0;
  return `GHS ${amount.toLocaleString()}`;
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

function formatLabel(value?: string | null) {
  if (!value) {
    return '-';
  }
  return value
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function parsePositiveNumber(value: string) {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  const parsed = Number(trimmed);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return null;
  }
  return parsed;
}

type ExpenseReviewState = Record<string, { status: DispatchFinancialExpenseStatus; rejection_reason: string }>;
type IncidentReviewState = Record<string, {
  status: string;
  responsibility_type: string;
  company_share: string;
  driver_share: string;
  final_responsible_party: string;
  admin_notes: string;
  rejection_reason: string;
}>;

const initialIncidentCreateState = {
  incident_type: 'other',
  incident_date: new Date().toISOString().slice(0, 10),
  incident_location: '',
  amount: '',
  responsibility_type: 'under_investigation',
  company_share: '',
  driver_share: '',
  final_responsible_party: '',
  description: '',
  evidence_reference: '',
  admin_notes: '',
};

export default function DispatchFinancials() {
  const [items, setItems] = useState<DispatchFinancialListItem[]>([]);
  const [pagination, setPagination] = useState({ page: 1, page_size: 20, total: 0, total_pages: 1 });
  const [summary, setSummary] = useState({
    dispatch_revenue: 0,
    paid_dispatch_revenue: 0,
    internal_dispatch_operating_costs: 0,
    partner_contract_dispatches: 0,
    partner_contract_revenue: 0,
    partner_contract_costs: 0,
    complimentary_dispatch_costs: 0,
    driver_dispatch_compensation: 0,
    outstanding_dispatch_payments: 0,
    driver_liabilities: 0,
    company_operational_costs: 0,
    dispatch_profitability: 0,
    incident_trends: {
      total: 0,
      under_investigation: 0,
      driver_responsible: 0,
      company_responsible: 0,
      shared: 0,
    },
  });
  const [options, setOptions] = useState<{
    financial_statuses: string[];
    expense_types: string[];
    expense_statuses: string[];
    incident_types: string[];
    responsibility_types: string[];
    incident_statuses: string[];
    dispatch_financial_types?: string[];
    partner_billing_methods?: string[];
    driver_compensation_types?: string[];
  } | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [pageError, setPageError] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [detail, setDetail] = useState<DispatchFinancialDetail | null>(null);
  const [detailCache, setDetailCache] = useState<Record<string, DispatchFinancialDetail>>({});
  const [detailError, setDetailError] = useState('');
  const [isLoadingDetail, setIsLoadingDetail] = useState(false);
  const [financeNotes, setFinanceNotes] = useState('');
  const [compensationType, setCompensationType] = useState<DriverCompensationType>('none');
  const [compensationValue, setCompensationValue] = useState('0');
  const [expenseReviews, setExpenseReviews] = useState<ExpenseReviewState>({});
  const [incidentReviews, setIncidentReviews] = useState<IncidentReviewState>({});
  const [newIncident, setNewIncident] = useState(initialIncidentCreateState);
  const [isSaving, setIsSaving] = useState<Record<string, boolean>>({});

  const loadPage = async ({ refresh = false }: { refresh?: boolean } = {}) => {
    if (refresh) {
      setIsRefreshing(true);
    } else {
      setIsLoading(true);
    }
    setPageError('');
    try {
      const [listResponse, optionsResponse] = await Promise.all([
        fetchDispatchFinancials({
          page: currentPage,
          page_size: 20,
          q: searchQuery || undefined,
          financial_status: statusFilter || undefined,
        }),
        options ? Promise.resolve(options) : fetchDispatchFinancialOptions(),
      ]);
      setItems(listResponse.records || []);
      setPagination(listResponse.pagination);
      setSummary(listResponse.summary);
      if (!options) {
        setOptions(optionsResponse);
      }
    } catch (error) {
      setItems([]);
      setPagination({ page: 1, page_size: 20, total: 0, total_pages: 1 });
      setPageError(error instanceof Error ? error.message : 'Unable to load dispatch financials right now.');
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  };

  useEffect(() => {
    void loadPage();
  }, [currentPage, statusFilter]);

  const hydrateDetailState = (nextDetail: DispatchFinancialDetail) => {
    setDetail(nextDetail);
    const cacheKey = nextDetail.job?.id || nextDetail.record.dispatch_job_id;
    setDetailCache((current) => ({ ...current, [cacheKey]: nextDetail }));
    setFinanceNotes(nextDetail.record.finance_notes || '');
    setCompensationType(nextDetail.record.driver_compensation_type || 'none');
    setCompensationValue(String(nextDetail.record.driver_compensation_value || 0));
    setExpenseReviews(
      Object.fromEntries(
        nextDetail.expenses.map((expense) => [
          expense.id,
          {
            status: expense.status,
            rejection_reason: expense.rejection_reason || '',
          },
        ]),
      ),
    );
    setIncidentReviews(
      Object.fromEntries(
        nextDetail.incidents.map((incident) => [
          incident.id,
          {
            status: incident.status,
            responsibility_type: incident.responsibility_type,
            company_share: incident.company_share ? String(incident.company_share) : '',
            driver_share: incident.driver_share ? String(incident.driver_share) : '',
            final_responsible_party: incident.final_responsible_party || '',
            admin_notes: incident.admin_notes || '',
            rejection_reason: incident.rejection_reason || '',
          },
        ]),
      ),
    );
  };

  const openDetail = async (jobId: string) => {
    setSelectedJobId(jobId);
    const cachedDetail = detailCache[jobId];
    setDetail(cachedDetail || null);
    setDetailError('');
    if (cachedDetail) {
      return;
    }
    setIsLoadingDetail(true);
    try {
      const response = await fetchDispatchFinancialDetail(jobId);
      hydrateDetailState(response);
    } catch (error) {
      setDetailError(error instanceof Error ? error.message : 'Unable to load dispatch financial detail right now.');
    } finally {
      setIsLoadingDetail(false);
    }
  };

  const refreshDetail = async (jobId: string) => {
    const response = await fetchDispatchFinancialDetail(jobId);
    hydrateDetailState(response);
    await loadPage({ refresh: true });
  };

  const handleSearch = async (event: React.FormEvent) => {
    event.preventDefault();
    setCurrentPage(1);
    await loadPage({ refresh: true });
  };

  const setBusy = (key: string, busy: boolean) => {
    setIsSaving((current) => ({ ...current, [key]: busy }));
  };

  const handleVerify = async () => {
    if (!detail) {
      return;
    }
    const busyKey = 'verify';
    setBusy(busyKey, true);
    try {
      const response = await verifyDispatchFinancial(detail.job?.id || detail.record.dispatch_job_id, {
        finance_notes: financeNotes || undefined,
        driver_compensation_type: compensationType,
        driver_compensation_value: Number(compensationValue || 0),
      });
      hydrateDetailState(response);
      toast.success('Dispatch financials verified.');
      await loadPage({ refresh: true });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Unable to verify this financial record right now.');
    } finally {
      setBusy(busyKey, false);
    }
  };

  const handleClose = async () => {
    if (!detail) {
      return;
    }
    const busyKey = 'close';
    setBusy(busyKey, true);
    try {
      const response = await closeDispatchFinancial(detail.job?.id || detail.record.dispatch_job_id, { finance_notes: financeNotes || undefined });
      hydrateDetailState(response);
      toast.success('Dispatch financial record closed.');
      await loadPage({ refresh: true });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Unable to close this financial record right now.');
    } finally {
      setBusy(busyKey, false);
    }
  };

  const handleExpenseReview = async (expense: DispatchFinancialExpense) => {
    const reviewState = expenseReviews[expense.id];
    if (!reviewState) {
      return;
    }
    if (reviewState.status === 'rejected' && !reviewState.rejection_reason.trim()) {
      toast.error('Add a rejection reason before rejecting this expense.');
      return;
    }
    const busyKey = `expense-${expense.id}`;
    setBusy(busyKey, true);
    try {
      const response = await reviewDispatchExpense(expense.id, reviewState);
      hydrateDetailState(response);
      toast.success('Expense review saved.');
      await loadPage({ refresh: true });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Unable to review this expense right now.');
    } finally {
      setBusy(busyKey, false);
    }
  };

  const handleIncidentReview = async (incident: DispatchFinancialIncident) => {
    const reviewState = incidentReviews[incident.id];
    if (!reviewState) {
      return;
    }
    const companyShare = reviewState.company_share ? Number(reviewState.company_share) : undefined;
    const driverShare = reviewState.driver_share ? Number(reviewState.driver_share) : undefined;
    if (reviewState.status === 'rejected' && !reviewState.rejection_reason.trim()) {
      toast.error('Add a rejection reason before rejecting this incident.');
      return;
    }
    if (
      reviewState.responsibility_type === 'shared_responsibility'
      && (!(companyShare && companyShare > 0) || !(driverShare && driverShare > 0))
    ) {
      toast.error('Shared responsibility requires both company and driver shares.');
      return;
    }
    const busyKey = `incident-${incident.id}`;
    setBusy(busyKey, true);
    try {
      const response = await reviewDispatchIncident(incident.id, {
        ...reviewState,
        company_share: companyShare,
        driver_share: driverShare,
      });
      hydrateDetailState(response);
      toast.success('Incident review saved.');
      await loadPage({ refresh: true });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Unable to review this incident right now.');
    } finally {
      setBusy(busyKey, false);
    }
  };

  const handleCreateIncident = async () => {
    if (!detail) {
      return;
    }
    const amount = parsePositiveNumber(newIncident.amount);
    const companyShare = newIncident.company_share ? Number(newIncident.company_share) : undefined;
    const driverShare = newIncident.driver_share ? Number(newIncident.driver_share) : undefined;
    if (!amount) {
      toast.error('Enter a valid incident amount greater than zero.');
      return;
    }
    if (!newIncident.incident_location.trim()) {
      toast.error('Incident location is required.');
      return;
    }
    if (!newIncident.description.trim()) {
      toast.error('Incident description is required.');
      return;
    }
    if (
      newIncident.responsibility_type === 'shared_responsibility'
      && (!(companyShare && companyShare > 0) || !(driverShare && driverShare > 0))
    ) {
      toast.error('Shared responsibility requires both company and driver shares.');
      return;
    }
    const busyKey = 'create-incident';
    setBusy(busyKey, true);
    try {
      const response = await createDispatchFinancialIncident(detail.job?.id || detail.record.dispatch_job_id, {
        ...newIncident,
        amount,
        company_share: companyShare,
        driver_share: driverShare,
      });
      hydrateDetailState(response);
      setNewIncident(initialIncidentCreateState);
      toast.success('Dispatch incident recorded.');
      await loadPage({ refresh: true });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Unable to record this incident right now.');
    } finally {
      setBusy(busyKey, false);
    }
  };

  const outstandingCount = useMemo(() => items.filter((item) => item.financial_status === 'outstanding').length, [items]);
  const verifiedCount = useMemo(() => items.filter((item) => item.financial_status === 'verified').length, [items]);
  const canCreateIncident = Boolean(
    detail
    && !detail.record.is_financially_closed
    && parsePositiveNumber(newIncident.amount)
    && newIncident.incident_location.trim()
    && newIncident.description.trim()
    && (
      newIncident.responsibility_type !== 'shared_responsibility'
      || (parsePositiveNumber(newIncident.company_share) && parsePositiveNumber(newIncident.driver_share))
    ),
  );
  const canVerifyRecord = Boolean(
    detail
    && !detail.record.is_financially_closed
    && !detail.record.verified_at
    && ['inspection_completed', 'dispatch_closed'].includes(detail.job?.return_status || '')
    && !detail.incidents.some(
      (incident) =>
        incident.responsibility_type === 'under_investigation'
        && ['reported', 'under_review', 'approved', 'company_paid', 'driver_liable', 'shared_payment'].includes(incident.status),
    ),
  );
  const canCloseRecord = Boolean(detail && !detail.record.is_financially_closed && detail.record.verified_at);

  return (
    <div className="space-y-6 p-6" aria-busy={isLoading || isRefreshing}>
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-[#0F172A]">Dispatch Financials</h1>
          <p className="mt-1 text-gray-600">
            Review dispatch money submissions, approve expenses, resolve financial incidents, and close dispatch financial accountability without posting into wallet or collections.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void loadPage({ refresh: true })}
          disabled={isLoading || isRefreshing}
          className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 transition-all hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {isLoading || isRefreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCcw className="h-4 w-4" />}
          {isLoading ? 'Loading…' : isRefreshing ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      {isLoading ? (
        <div role="status" className="flex items-center gap-3 rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-sm font-medium text-blue-800">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading dispatch financial records and dashboard totals…
        </div>
      ) : null}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-5">
        <StatCard icon={PiggyBank} label="Paid Dispatch Revenue" value={formatCurrency(summary.paid_dispatch_revenue)} tint="bg-blue-100 text-blue-700" loading={isLoading} />
        <StatCard icon={FileWarning} label="Outstanding" value={formatCurrency(summary.outstanding_dispatch_payments)} tint="bg-amber-100 text-amber-700" loading={isLoading} />
        <StatCard icon={AlertTriangle} label="Driver Liability" value={formatCurrency(summary.driver_liabilities)} tint="bg-rose-100 text-rose-700" loading={isLoading} />
        <StatCard icon={Receipt} label="Company Cost" value={formatCurrency(summary.company_operational_costs)} tint="bg-slate-100 text-slate-700" loading={isLoading} />
        <StatCard icon={DollarSign} label="Profitability" value={formatCurrency(summary.dispatch_profitability)} tint="bg-emerald-100 text-emerald-700" loading={isLoading} />
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <MiniStat label="Internal Operating Costs" value={formatCurrency(summary.internal_dispatch_operating_costs)} loading={isLoading} />
        <MiniStat label="Partner Contract Revenue" value={formatCurrency(summary.partner_contract_revenue)} loading={isLoading} />
        <MiniStat label="Complimentary Costs" value={formatCurrency(summary.complimentary_dispatch_costs)} loading={isLoading} />
        <MiniStat label="Driver Compensation" value={formatCurrency(summary.driver_dispatch_compensation)} loading={isLoading} />
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <MiniStat label="Records Outstanding" value={String(outstandingCount)} loading={isLoading} />
        <MiniStat label="Verified Records" value={String(verifiedCount)} loading={isLoading} />
        <MiniStat label="Incidents Under Investigation" value={String(summary.incident_trends.under_investigation)} loading={isLoading} />
      </div>

      <div className="rounded-xl border border-gray-200 bg-white p-5">
        <form onSubmit={handleSearch} className="grid grid-cols-1 gap-3 lg:grid-cols-[1fr_240px_auto]">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
            <input
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder="Search dispatch ID"
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
            <option value="">All Financial Statuses</option>
            {(options?.financial_statuses || []).map((status) => (
              <option key={status} value={status}>{formatLabel(status)}</option>
            ))}
          </select>
          <button type="submit" className="rounded-lg bg-[#2563EB] px-4 py-2.5 text-sm font-medium text-white hover:bg-[#1d4ed8]">
            Search
          </button>
        </form>
      </div>

      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
        {isLoading ? (
          <div className="space-y-3 px-6 py-5">
            {Array.from({ length: 6 }).map((_, index) => (
              <div key={index} className="grid grid-cols-1 gap-3 rounded-xl border border-gray-200 p-4 md:grid-cols-7">
                {Array.from({ length: 7 }).map((__, innerIndex) => (
                  <Skeleton key={innerIndex} className="h-5 w-full" />
                ))}
              </div>
            ))}
          </div>
        ) : pageError ? (
          <div className="px-6 py-6 text-sm text-red-700">{pageError}</div>
        ) : items.length === 0 ? (
          <div className="px-6 py-10 text-center text-sm text-gray-500">No dispatch financial records matched the current filters. Records appear after returned dispatches move into handover and finance review.</div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200 text-sm">
                <thead className="bg-gray-50">
                  <tr className="text-left text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">
                    <th className="px-4 py-3">Dispatch</th>
                    <th className="px-4 py-3">Vehicle</th>
                    <th className="px-4 py-3">Driver</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">Approved Charge</th>
                    <th className="px-4 py-3">Submitted</th>
                    <th className="px-4 py-3">Outstanding</th>
                    <th className="px-4 py-3">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200 bg-white">
                  {items.map((item) => (
                    <tr key={item.id}>
                      <td className="px-4 py-4">
                        <div className="font-medium text-[#0F172A]">{item.job?.dispatch_job_id || item.dispatch_job_id}</div>
                        <div className="text-xs text-gray-500">{formatLabel(item.job?.return_status || '-')}</div>
                      </td>
                      <td className="px-4 py-4 text-gray-700">{item.vehicle?.registration_number || 'Unassigned'}</td>
                      <td className="px-4 py-4 text-gray-700">{item.driver?.full_name || 'Unassigned'}</td>
                      <td className="px-4 py-4">
                        <span className="inline-flex rounded-full border border-gray-200 bg-gray-50 px-3 py-1 text-xs font-semibold text-gray-700">
                          {formatLabel(item.financial_status)}
                        </span>
                      </td>
                      <td className="px-4 py-4 text-gray-700">{formatCurrency(item.approved_charge)}</td>
                      <td className="px-4 py-4 text-gray-700">{formatCurrency(item.amount_submitted_by_driver)}</td>
                      <td className="px-4 py-4 text-amber-700">{formatCurrency(item.outstanding_balance)}</td>
                      <td className="px-4 py-4">
                        <button
                          type="button"
                          onClick={() => void openDetail(item.job?.id || item.dispatch_job_id)}
                          className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3 py-2 text-xs font-medium text-gray-700 hover:bg-gray-50"
                        >
                          <WalletCards className="h-3.5 w-3.5" />
                          Open Workspace
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {pagination.total_pages > 1 ? (
              <div className="flex items-center justify-between border-t border-gray-200 px-4 py-3 text-sm text-gray-600">
                <div>Page {pagination.page} of {pagination.total_pages}</div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    disabled={pagination.page <= 1}
                    onClick={() => setCurrentPage((current) => Math.max(1, current - 1))}
                    className="rounded-lg border border-gray-300 px-3 py-2 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    Previous
                  </button>
                  <button
                    type="button"
                    disabled={pagination.page >= pagination.total_pages}
                    onClick={() => setCurrentPage((current) => Math.min(pagination.total_pages, current + 1))}
                    className="rounded-lg border border-gray-300 px-3 py-2 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    Next
                  </button>
                </div>
              </div>
            ) : null}
          </>
        )}
      </div>

      <Drawer open={Boolean(selectedJobId)} onOpenChange={(open) => { if (!open) { setSelectedJobId(null); } }}>
        <DrawerContent className="sm:max-w-[980px]">
          <DrawerHeader>
            <DrawerTitle>{detail?.job?.dispatch_job_id || 'Dispatch Financial Workspace'}</DrawerTitle>
            <DrawerDescription>
              Verify money, review expenses, resolve incident liabilities, and close the dispatch financial record safely.
            </DrawerDescription>
          </DrawerHeader>
          <div className="max-h-[82vh] overflow-y-auto px-6 pb-8">
            {isLoadingDetail ? (
              <div className="space-y-4 py-4">
                <Skeleton className="h-24 w-full" />
                <Skeleton className="h-40 w-full" />
                <Skeleton className="h-40 w-full" />
              </div>
            ) : detailError ? (
              <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{detailError}</div>
            ) : detail ? (
              <div className="space-y-6">
                <Section title="Overview">
                  <Grid>
                    <Info label="Dispatch" value={detail.job?.dispatch_job_id || '-'} />
                    <Info label="Driver" value={detail.driver?.full_name || '-'} />
                    <Info label="Vehicle" value={detail.vehicle?.registration_number || '-'} />
                    <Info label="Dispatch Status" value={formatLabel(String(detail.job?.status || '-'))} />
                    <Info label="Return Status" value={formatLabel(String(detail.job?.return_status || '-'))} />
                    <Info label="Financial Status" value={formatLabel(detail.record.financial_status)} />
                    <Info label="Payment Classification" value={`${formatLabel(detail.record.dispatch_financial_type)}${detail.record.dispatch_financial_type_is_legacy ? ' (legacy inferred)' : ''}`} />
                    <Info label="Partner / Reference" value={detail.record.partner_organization_reference || 'Not applicable'} />
                    <Info label="Partner Billing" value={formatLabel(detail.record.partner_billing_method)} />
                    <Info label="Approved Charge" value={formatCurrency(detail.record.approved_charge)} />
                    <Info label="Outstanding Balance" value={formatCurrency(detail.record.outstanding_balance)} />
                    <Info label="Expected Net Revenue" value={formatCurrency(detail.record.expected_net_revenue)} />
                    <Info label="Actual Net Revenue" value={formatCurrency(detail.record.actual_net_revenue)} />
                  </Grid>
                </Section>

                <Section title="Money Accountability">
                  <Grid>
                    <Info label="Collected From Customer" value={formatCurrency(detail.record.amount_collected_from_customer)} />
                    <Info label="Submitted By Driver" value={formatCurrency(detail.record.amount_submitted_by_driver)} />
                    <Info label="Payment Method" value={detail.record.payment_method || 'Not provided'} />
                    <Info label="Payment Reference" value={detail.record.payment_reference || 'Not provided'} />
                    <Info label="Submitted At" value={formatDateTime(detail.record.submitted_at)} />
                    <Info label="Verified At" value={formatDateTime(detail.record.verified_at)} />
                    <Info label="Driver Compensation" value={`${formatLabel(detail.record.driver_compensation_type)} · ${formatCurrency(detail.record.driver_compensation_amount)}`} />
                  </Grid>
                  <div className="mt-4 grid gap-4 md:grid-cols-2">
                    <label className="text-sm font-medium text-gray-700">Compensation Type
                      <select value={compensationType} onChange={(event) => setCompensationType(event.target.value as DriverCompensationType)} className="mt-2 w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm">
                        <option value="none">None</option><option value="fixed_tip">Fixed Tip</option><option value="fixed_allowance">Fixed Allowance</option><option value="percentage_of_charge">Percentage of Charge</option><option value="manual_amount">Manual Amount</option>
                      </select>
                    </label>
                    <label className="text-sm font-medium text-gray-700">Compensation Value
                      <input type="number" min="0" value={compensationValue} onChange={(event) => setCompensationValue(event.target.value)} className="mt-2 w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm" />
                    </label>
                  </div>
                  <div className="mt-4">
                    <label className="mb-2 block text-sm font-medium text-gray-700">Finance Notes</label>
                    <textarea
                      value={financeNotes}
                      onChange={(event) => setFinanceNotes(event.target.value)}
                      className="min-h-[100px] w-full rounded-lg border border-gray-300 px-4 py-3 text-sm"
                      placeholder="Record review notes, cash handling remarks, disputed points, or closure context."
                    />
                  </div>
                  <div className="mt-4 flex flex-wrap justify-end gap-3">
                    <button
                      type="button"
                      onClick={() => void refreshDetail(detail.job?.id || detail.record.dispatch_job_id)}
                      className="rounded-lg border border-gray-300 px-4 py-2.5 text-sm font-medium text-gray-700"
                    >
                      Refresh Detail
                    </button>
                    <button
                      type="button"
                      onClick={() => void handleVerify()}
                      disabled={isSaving.verify || !canVerifyRecord}
                      className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2.5 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {isSaving.verify ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                      Verify Financials
                    </button>
                  </div>
                </Section>

                <Section title="Expense Review">
                  <div className="space-y-4">
                    {detail.expenses.length ? detail.expenses.map((expense) => {
                      const review = expenseReviews[expense.id];
                      return (
                        <div key={expense.id} className="rounded-xl border border-gray-200 bg-gray-50 p-4">
                          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_220px_1fr_auto]">
                            <div>
                              <div className="text-sm font-semibold text-[#0F172A]">{formatLabel(expense.expense_type)} • {formatCurrency(expense.amount)}</div>
                              <div className="mt-1 text-sm text-gray-600">{expense.note}</div>
                              <div className="mt-1 text-xs text-gray-500">Submitted {formatDateTime(expense.submitted_at)}</div>
                            </div>
                            <select
                              value={review?.status || expense.status}
                              onChange={(event) => setExpenseReviews((current) => ({
                                ...current,
                                [expense.id]: { ...(current[expense.id] || { status: expense.status, rejection_reason: '' }), status: event.target.value as DispatchFinancialExpenseStatus },
                              }))}
                              className="rounded-lg border border-gray-300 px-3 py-2.5 text-sm"
                            >
                              {(options?.expense_statuses || []).map((status) => (
                                <option key={status} value={status}>{formatLabel(status)}</option>
                              ))}
                            </select>
                            <input
                              value={review?.rejection_reason || ''}
                              onChange={(event) => setExpenseReviews((current) => ({
                                ...current,
                                [expense.id]: { ...(current[expense.id] || { status: expense.status, rejection_reason: '' }), rejection_reason: event.target.value },
                              }))}
                              className="rounded-lg border border-gray-300 px-3 py-2.5 text-sm"
                              placeholder="Rejection reason if needed"
                            />
                            <button
                              type="button"
                              onClick={() => void handleExpenseReview(expense)}
                              disabled={isSaving[`expense-${expense.id}`] || Boolean(review?.status === 'rejected' && !review?.rejection_reason.trim())}
                              className="inline-flex items-center justify-center gap-2 rounded-lg bg-[#2563EB] px-4 py-2.5 text-sm font-medium text-white disabled:opacity-60"
                            >
                              {isSaving[`expense-${expense.id}`] ? <Loader2 className="h-4 w-4 animate-spin" /> : <Receipt className="h-4 w-4" />}
                              Save
                            </button>
                          </div>
                        </div>
                      );
                    }) : (
                      <EmptyState label="No dispatch expenses submitted yet." />
                    )}
                  </div>
                </Section>

                <Section title="Incident Charges & Liability">
                  <div className="rounded-xl border border-gray-200 bg-white p-4">
                    <div className="mb-3 text-sm font-semibold text-[#0F172A]">Record New Dispatch Incident</div>
                    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                      <SelectField label="Incident Type" value={newIncident.incident_type} onChange={(value) => setNewIncident((current) => ({ ...current, incident_type: value }))}>
                        {(options?.incident_types || []).map((type) => (
                          <option key={type} value={type}>{formatLabel(type)}</option>
                        ))}
                      </SelectField>
                      <InputField label="Incident Date" type="date" value={newIncident.incident_date} onChange={(value) => setNewIncident((current) => ({ ...current, incident_date: value }))} />
                      <InputField label="Incident Location" value={newIncident.incident_location} onChange={(value) => setNewIncident((current) => ({ ...current, incident_location: value }))} />
                      <InputField label="Amount" type="number" value={newIncident.amount} onChange={(value) => setNewIncident((current) => ({ ...current, amount: value }))} />
                      <SelectField label="Responsibility" value={newIncident.responsibility_type} onChange={(value) => setNewIncident((current) => ({ ...current, responsibility_type: value }))}>
                        {(options?.responsibility_types || []).map((type) => (
                          <option key={type} value={type}>{formatLabel(type)}</option>
                        ))}
                      </SelectField>
                      <InputField label="Final Responsible Party" value={newIncident.final_responsible_party} onChange={(value) => setNewIncident((current) => ({ ...current, final_responsible_party: value }))} />
                      <InputField label="Company Share" type="number" value={newIncident.company_share} onChange={(value) => setNewIncident((current) => ({ ...current, company_share: value }))} />
                      <InputField label="Driver Share" type="number" value={newIncident.driver_share} onChange={(value) => setNewIncident((current) => ({ ...current, driver_share: value }))} />
                      <InputField label="Evidence Reference" value={newIncident.evidence_reference} onChange={(value) => setNewIncident((current) => ({ ...current, evidence_reference: value }))} />
                      <TextAreaField label="Description" value={newIncident.description} onChange={(value) => setNewIncident((current) => ({ ...current, description: value }))} placeholder="Describe the penalty, fine, operational error, or incident cost." />
                      <TextAreaField label="Admin Notes" value={newIncident.admin_notes} onChange={(value) => setNewIncident((current) => ({ ...current, admin_notes: value }))} placeholder="Optional review context or internal notes." />
                    </div>
                    <div className="mt-4 flex justify-end">
                      <button
                        type="button"
                        onClick={() => void handleCreateIncident()}
                        disabled={isSaving['create-incident'] || !canCreateIncident}
                        className="inline-flex items-center gap-2 rounded-lg bg-rose-600 px-4 py-2.5 text-sm font-medium text-white disabled:opacity-60"
                      >
                        {isSaving['create-incident'] ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldAlert className="h-4 w-4" />}
                        Record Incident
                      </button>
                    </div>
                  </div>

                  <div className="mt-4 space-y-4">
                    {detail.incidents.length ? detail.incidents.map((incident) => {
                      const review = incidentReviews[incident.id];
                      return (
                        <div key={incident.id} className="rounded-xl border border-gray-200 bg-gray-50 p-4">
                          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
                            <Info label="Type" value={formatLabel(incident.incident_type)} />
                            <Info label="Amount" value={formatCurrency(incident.amount)} />
                            <Info label="Responsibility" value={formatLabel(incident.responsibility_type)} />
                            <Info label="Reported" value={formatDateTime(incident.submitted_at)} />
                          </div>
                          <div className="mt-3 text-sm text-gray-700">{incident.description}</div>
                          <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                            <SelectField label="Incident Status" value={review?.status || incident.status} onChange={(value) => setIncidentReviews((current) => ({
                              ...current,
                              [incident.id]: { ...(current[incident.id] || {
                                status: incident.status,
                                responsibility_type: incident.responsibility_type,
                                company_share: incident.company_share ? String(incident.company_share) : '',
                                driver_share: incident.driver_share ? String(incident.driver_share) : '',
                                final_responsible_party: incident.final_responsible_party || '',
                                admin_notes: incident.admin_notes || '',
                                rejection_reason: incident.rejection_reason || '',
                              }), status: value },
                            }))}>
                              {(options?.incident_statuses || []).map((status) => (
                                <option key={status} value={status}>{formatLabel(status)}</option>
                              ))}
                            </SelectField>
                            <SelectField label="Responsibility" value={review?.responsibility_type || incident.responsibility_type} onChange={(value) => setIncidentReviews((current) => ({
                              ...current,
                              [incident.id]: { ...(current[incident.id] || {
                                status: incident.status,
                                responsibility_type: incident.responsibility_type,
                                company_share: incident.company_share ? String(incident.company_share) : '',
                                driver_share: incident.driver_share ? String(incident.driver_share) : '',
                                final_responsible_party: incident.final_responsible_party || '',
                                admin_notes: incident.admin_notes || '',
                                rejection_reason: incident.rejection_reason || '',
                              }), responsibility_type: value },
                            }))}>
                              {(options?.responsibility_types || []).map((type) => (
                                <option key={type} value={type}>{formatLabel(type)}</option>
                              ))}
                            </SelectField>
                            <InputField label="Final Responsible Party" value={review?.final_responsible_party || ''} onChange={(value) => setIncidentReviews((current) => ({
                              ...current,
                              [incident.id]: { ...(current[incident.id] || {
                                status: incident.status,
                                responsibility_type: incident.responsibility_type,
                                company_share: incident.company_share ? String(incident.company_share) : '',
                                driver_share: incident.driver_share ? String(incident.driver_share) : '',
                                final_responsible_party: incident.final_responsible_party || '',
                                admin_notes: incident.admin_notes || '',
                                rejection_reason: incident.rejection_reason || '',
                              }), final_responsible_party: value },
                            }))} />
                            <InputField label="Company Share" type="number" value={review?.company_share || ''} onChange={(value) => setIncidentReviews((current) => ({
                              ...current,
                              [incident.id]: { ...(current[incident.id] || {
                                status: incident.status,
                                responsibility_type: incident.responsibility_type,
                                company_share: incident.company_share ? String(incident.company_share) : '',
                                driver_share: incident.driver_share ? String(incident.driver_share) : '',
                                final_responsible_party: incident.final_responsible_party || '',
                                admin_notes: incident.admin_notes || '',
                                rejection_reason: incident.rejection_reason || '',
                              }), company_share: value },
                            }))} />
                            <InputField label="Driver Share" type="number" value={review?.driver_share || ''} onChange={(value) => setIncidentReviews((current) => ({
                              ...current,
                              [incident.id]: { ...(current[incident.id] || {
                                status: incident.status,
                                responsibility_type: incident.responsibility_type,
                                company_share: incident.company_share ? String(incident.company_share) : '',
                                driver_share: incident.driver_share ? String(incident.driver_share) : '',
                                final_responsible_party: incident.final_responsible_party || '',
                                admin_notes: incident.admin_notes || '',
                                rejection_reason: incident.rejection_reason || '',
                              }), driver_share: value },
                            }))} />
                            <InputField label="Rejection Reason" value={review?.rejection_reason || ''} onChange={(value) => setIncidentReviews((current) => ({
                              ...current,
                              [incident.id]: { ...(current[incident.id] || {
                                status: incident.status,
                                responsibility_type: incident.responsibility_type,
                                company_share: incident.company_share ? String(incident.company_share) : '',
                                driver_share: incident.driver_share ? String(incident.driver_share) : '',
                                final_responsible_party: incident.final_responsible_party || '',
                                admin_notes: incident.admin_notes || '',
                                rejection_reason: incident.rejection_reason || '',
                              }), rejection_reason: value },
                            }))} />
                          </div>
                          <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-[1fr_auto]">
                            <TextAreaField label="Admin Notes" value={review?.admin_notes || ''} onChange={(value) => setIncidentReviews((current) => ({
                              ...current,
                              [incident.id]: { ...(current[incident.id] || {
                                status: incident.status,
                                responsibility_type: incident.responsibility_type,
                                company_share: incident.company_share ? String(incident.company_share) : '',
                                driver_share: incident.driver_share ? String(incident.driver_share) : '',
                                final_responsible_party: incident.final_responsible_party || '',
                                admin_notes: incident.admin_notes || '',
                                rejection_reason: incident.rejection_reason || '',
                              }), admin_notes: value },
                            }))} placeholder="Add review notes, liability explanation, or recovery remarks." />
                            <button
                              type="button"
                              onClick={() => void handleIncidentReview(incident)}
                              disabled={
                                isSaving[`incident-${incident.id}`]
                                || !review
                                || (review.status === 'rejected' && !review.rejection_reason.trim())
                                || (
                                  review.responsibility_type === 'shared_responsibility'
                                  && (!parsePositiveNumber(review.company_share) || !parsePositiveNumber(review.driver_share))
                                )
                              }
                              className="inline-flex items-center justify-center gap-2 rounded-lg bg-[#2563EB] px-4 py-2.5 text-sm font-medium text-white disabled:opacity-60"
                            >
                              {isSaving[`incident-${incident.id}`] ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldAlert className="h-4 w-4" />}
                              Save Review
                            </button>
                          </div>
                        </div>
                      );
                    }) : (
                      <EmptyState label="No dispatch incidents recorded yet." />
                    )}
                  </div>
                </Section>

                <Section title="Financial Closure">
                  <Grid>
                    <Info label="Company Operational Cost" value={formatCurrency(detail.record.company_operational_cost)} />
                    <Info label="Driver Liability Total" value={formatCurrency(detail.record.driver_liability_total)} />
                    <Info label="Closed" value={detail.record.is_financially_closed ? formatDateTime(detail.record.financial_closed_at) : 'Not closed'} />
                    <Info label="Closed By" value={detail.record.financial_closed_by || 'Not closed'} />
                  </Grid>
                  <div className="mt-4 flex justify-end">
                    <button
                      type="button"
                      onClick={() => void handleClose()}
                      disabled={isSaving.close || !canCloseRecord}
                      className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {isSaving.close ? <Loader2 className="h-4 w-4 animate-spin" /> : <WalletCards className="h-4 w-4" />}
                      Close Financial Record
                    </button>
                  </div>
                </Section>
              </div>
            ) : null}
          </div>
        </DrawerContent>
      </Drawer>
    </div>
  );
}

function StatCard({
  icon: Icon,
  label,
  value,
  tint,
  loading = false,
}: {
  icon: typeof DollarSign;
  label: string;
  value: string;
  tint: string;
  loading?: boolean;
}) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5">
      <div className={`mb-3 flex h-10 w-10 items-center justify-center rounded-lg ${tint}`}>
        <Icon className="h-5 w-5" />
      </div>
      {loading ? <Skeleton className="mb-1 h-7 w-28" /> : <div className="text-xl font-semibold text-[#0F172A]">{value}</div>}
      <div className="text-sm text-gray-600">{label}</div>
    </div>
  );
}

function MiniStat({ label, value, loading = false }: { label: string; value: string; loading?: boolean }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      <div className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">{label}</div>
      {loading ? <Skeleton className="mt-2 h-8 w-24" /> : <div className="mt-2 text-2xl font-semibold text-[#0F172A]">{value}</div>}
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h3 className="mb-3 text-sm font-semibold uppercase tracking-[0.18em] text-gray-500">{title}</h3>
      {children}
    </section>
  );
}

function Grid({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">{children}</div>;
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3">
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
        className="min-h-[100px] w-full rounded-lg border border-gray-300 px-4 py-3 text-sm"
      />
    </div>
  );
}

function EmptyState({ label }: { label: string }) {
  return <div className="rounded-xl border border-dashed border-gray-300 bg-gray-50 px-4 py-8 text-center text-sm text-gray-500">{label}</div>;
}
