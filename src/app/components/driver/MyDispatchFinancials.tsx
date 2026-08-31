import { useEffect, useState, type ReactNode } from 'react';
import {
  AlertTriangle,
  DollarSign,
  Loader2,
  Receipt,
  RefreshCcw,
  Route,
  ShieldAlert,
  WalletCards,
} from 'lucide-react';
import { toast } from 'sonner';
import {
  fetchDriverDispatchFinancialDetail,
  fetchDriverDispatchFinancials,
  submitDriverDispatchExpense,
  submitDriverDispatchIncident,
  submitDriverDispatchMoney,
  type DriverDispatchMoneySubmissionResponse,
  type DispatchFinancialDetail,
  type DispatchFinancialListItem,
} from '../../lib/dispatch-financial-api';

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

const initialMoneyState = {
  amount_collected_from_customer: '',
  amount_submitted_by_driver: '',
  payment_method: '',
  payment_reference: '',
  finance_notes: '',
};

const initialExpenseState = {
  expense_type: 'fuel',
  amount: '',
  note: '',
  receipt_reference: '',
};

const initialIncidentState = {
  incident_type: 'other',
  incident_date: new Date().toISOString().slice(0, 10),
  incident_location: '',
  duration_minutes: '',
  amount: '',
  responsibility_type: 'under_investigation',
  company_share: '',
  driver_share: '',
  final_responsible_party: '',
  description: '',
  evidence_reference: '',
  admin_notes: '',
};

export default function MyDispatchFinancials() {
  const [items, setItems] = useState<DispatchFinancialListItem[]>([]);
  const [pagination, setPagination] = useState({ page: 1, page_size: 10, total: 0, total_pages: 1 });
  const [statuses, setStatuses] = useState<string[]>([]);
  const [currentPage, setCurrentPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [pageError, setPageError] = useState('');
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [detail, setDetail] = useState<DispatchFinancialDetail | null>(null);
  const [detailCache, setDetailCache] = useState<Record<string, DispatchFinancialDetail>>({});
  const [detailError, setDetailError] = useState('');
  const [isLoadingDetail, setIsLoadingDetail] = useState(false);
  const [moneyForm, setMoneyForm] = useState(initialMoneyState);
  const [expenseForm, setExpenseForm] = useState(initialExpenseState);
  const [incidentForm, setIncidentForm] = useState(initialIncidentState);
  const [isSaving, setIsSaving] = useState<Record<string, boolean>>({});

  const loadPage = async () => {
    setIsLoading(true);
    setPageError('');
    try {
      const response = await fetchDriverDispatchFinancials({
        page: currentPage,
        page_size: 10,
        financial_status: statusFilter || undefined,
      });
      setItems(response.records || []);
      setPagination(response.pagination);
      setStatuses(response.statuses || []);
    } catch (error) {
      setItems([]);
      setPageError(error instanceof Error ? error.message : 'Unable to load dispatch financials right now.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void loadPage();
  }, [currentPage, statusFilter]);

  const hydrateDetail = (nextDetail: DispatchFinancialDetail) => {
    setDetail(nextDetail);
    const cacheKey = nextDetail.job?.id || nextDetail.record.dispatch_job_id;
    setDetailCache((current) => ({ ...current, [cacheKey]: nextDetail }));
    setMoneyForm({
      amount_collected_from_customer: nextDetail.record.amount_collected_from_customer ? String(nextDetail.record.amount_collected_from_customer) : '',
      amount_submitted_by_driver: nextDetail.record.amount_submitted_by_driver ? String(nextDetail.record.amount_submitted_by_driver) : '',
      payment_method: nextDetail.record.payment_method || '',
      payment_reference: nextDetail.record.payment_reference || '',
      finance_notes: nextDetail.record.finance_notes || '',
    });
    setExpenseForm(initialExpenseState);
    setIncidentForm(initialIncidentState);
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
      const response = await fetchDriverDispatchFinancialDetail(jobId);
      hydrateDetail(response);
    } catch (error) {
      setDetailError(error instanceof Error ? error.message : 'Unable to load this dispatch financial record right now.');
    } finally {
      setIsLoadingDetail(false);
    }
  };

  const refreshDetail = async (jobId: string) => {
    const response = await fetchDriverDispatchFinancialDetail(jobId);
    hydrateDetail(response);
    await loadPage();
  };

  const setBusy = (key: string, busy: boolean) => {
    setIsSaving((current) => ({ ...current, [key]: busy }));
  };

  const handleSubmitMoney = async () => {
    if (!detail) {
      return;
    }
    const amountCollected = parsePositiveNumber(moneyForm.amount_collected_from_customer);
    const amountSubmitted = parsePositiveNumber(moneyForm.amount_submitted_by_driver);
    if (!amountCollected || !amountSubmitted) {
      toast.error('Enter valid submitted amounts greater than zero.');
      return;
    }
    setBusy('money', true);
    try {
      const response: DriverDispatchMoneySubmissionResponse = await submitDriverDispatchMoney(detail.job?.id || detail.record.dispatch_job_id, {
        amount_collected_from_customer: amountCollected,
        amount_submitted_by_driver: amountSubmitted,
        payment_method: moneyForm.payment_method,
        payment_reference: moneyForm.payment_reference,
        finance_notes: moneyForm.finance_notes,
      });
      await refreshDetail(response.dispatch_job_id || detail.job?.id || detail.record.dispatch_job_id);
      toast.success('Dispatch money submitted successfully.');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Unable to submit dispatch money right now.');
    } finally {
      setBusy('money', false);
    }
  };

  const handleSubmitExpense = async () => {
    if (!detail) {
      return;
    }
    const amount = parsePositiveNumber(expenseForm.amount);
    if (!amount) {
      toast.error('Enter a valid expense amount greater than zero.');
      return;
    }
    if (!expenseForm.note.trim()) {
      toast.error('Add an expense note before submitting.');
      return;
    }
    setBusy('expense', true);
    try {
      const response = await submitDriverDispatchExpense(detail.job?.id || detail.record.dispatch_job_id, {
        expense_type: expenseForm.expense_type,
        amount,
        note: expenseForm.note,
        receipt_reference: expenseForm.receipt_reference || undefined,
      });
      hydrateDetail(response);
      setExpenseForm(initialExpenseState);
      toast.success('Dispatch expense submitted.');
      await loadPage();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Unable to submit this dispatch expense right now.');
    } finally {
      setBusy('expense', false);
    }
  };

  const handleSubmitIncident = async () => {
    if (!detail) {
      return;
    }
    const amount = parsePositiveNumber(incidentForm.amount);
    const companyShare = incidentForm.company_share ? Number(incidentForm.company_share) : undefined;
    const driverShare = incidentForm.driver_share ? Number(incidentForm.driver_share) : undefined;
    if (!amount) {
      toast.error('Enter a valid incident amount greater than zero.');
      return;
    }
    if (!incidentForm.incident_location.trim()) {
      toast.error('Incident location is required.');
      return;
    }
    if (!incidentForm.description.trim()) {
      toast.error('Incident description is required.');
      return;
    }
    if (
      incidentForm.responsibility_type === 'shared_responsibility'
      && (!(companyShare && companyShare > 0) || !(driverShare && driverShare > 0))
    ) {
      toast.error('Shared responsibility requires both company and driver shares.');
      return;
    }
    setBusy('incident', true);
    try {
      const response = await submitDriverDispatchIncident(detail.job?.id || detail.record.dispatch_job_id, {
        ...incidentForm,
        amount,
        duration_minutes: Number(incidentForm.duration_minutes || 0),
        company_share: companyShare,
        driver_share: driverShare,
      });
      hydrateDetail(response);
      setIncidentForm(initialIncidentState);
      toast.success('Dispatch incident submitted.');
      await loadPage();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Unable to submit this dispatch incident right now.');
    } finally {
      setBusy('incident', false);
    }
  };

  const canSubmitMoney = Boolean(
    detail
    && !detail.record.is_financially_closed
    && parsePositiveNumber(moneyForm.amount_collected_from_customer)
    && parsePositiveNumber(moneyForm.amount_submitted_by_driver),
  );
  const canSubmitExpense = Boolean(
    detail
    && !detail.record.is_financially_closed
    && parsePositiveNumber(expenseForm.amount)
    && expenseForm.note.trim(),
  );
  const canSubmitIncident = Boolean(
    detail
    && !detail.record.is_financially_closed
    && parsePositiveNumber(incidentForm.amount)
    && incidentForm.incident_location.trim()
    && incidentForm.description.trim()
    && (
      incidentForm.responsibility_type !== 'shared_responsibility'
      || (parsePositiveNumber(incidentForm.company_share) && parsePositiveNumber(incidentForm.driver_share))
    ),
  );

  return (
    <div className="space-y-6 p-4 sm:p-6">
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-slate-900">My Dispatch Financials</h1>
            <p className="text-sm text-slate-500">Submit dispatch money, log related expenses, report financial incidents, and follow review status after vehicle return.</p>
          </div>
          <button
            type="button"
            onClick={() => void loadPage()}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            <RefreshCcw className="h-4 w-4" />
            Refresh
          </button>
        </div>
        <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-4">
          <TopCard label="Open Records" value={String(items.length)} icon={WalletCards} />
          <TopCard label="Submitted Total" value={formatCurrency(items.reduce((sum, item) => sum + (item.amount_submitted_by_driver || 0), 0))} icon={DollarSign} />
          <TopCard label="Outstanding" value={formatCurrency(items.reduce((sum, item) => sum + (item.outstanding_balance || 0), 0))} icon={AlertTriangle} />
          <TopCard label="Expenses Pending" value={String(items.filter((item) => item.financial_status === 'under_review').length)} icon={Receipt} />
        </div>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-[220px_auto]">
          <select
            value={statusFilter}
            onChange={(event) => {
              setStatusFilter(event.target.value);
              setCurrentPage(1);
            }}
            className="rounded-lg border border-slate-300 px-3 py-2.5 text-sm"
          >
            <option value="">All Statuses</option>
            {statuses.map((status) => (
              <option key={status} value={status}>{formatLabel(status)}</option>
            ))}
          </select>
          <div className="text-sm text-slate-500">Only your own dispatch financial records are shown here. Verified or closed records remain visible but cannot be edited.</div>
        </div>
      </div>

      <div className="space-y-4">
        {isLoading ? (
          <>
            <div className="h-32 animate-pulse rounded-2xl bg-slate-100" />
            <div className="h-32 animate-pulse rounded-2xl bg-slate-100" />
          </>
        ) : pageError ? (
          <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{pageError}</div>
        ) : items.length ? (
          items.map((item) => (
            <article key={item.id} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div>
                  <div className="text-xs font-semibold uppercase tracking-[0.18em] text-blue-600">{item.job?.dispatch_job_id || item.dispatch_job_id}</div>
                  <h2 className="mt-2 text-lg font-semibold text-slate-900">{item.vehicle?.registration_number || 'Assigned vehicle'} • {item.driver?.full_name || 'Driver'}</h2>
                  <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-600">
                    <span className="rounded-full bg-slate-100 px-2.5 py-1">{formatLabel(item.financial_status)}</span>
                    <span className="rounded-full bg-slate-100 px-2.5 py-1">{formatLabel(item.job?.return_status || '-')}</span>
                    <span className="rounded-full bg-slate-100 px-2.5 py-1">{formatDateTime(item.submitted_at)}</span>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => void openDetail(item.job?.id || item.dispatch_job_id)}
                  className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
                >
                  <Route className="h-4 w-4" />
                  Open Financial Record
                </button>
              </div>
              <div className="mt-4 grid gap-4 md:grid-cols-4">
                <MiniInfo label="Approved Charge" value={formatCurrency(item.approved_charge)} />
                <MiniInfo label="Submitted" value={formatCurrency(item.amount_submitted_by_driver)} />
                <MiniInfo label="Outstanding" value={formatCurrency(item.outstanding_balance)} />
                <MiniInfo label="Actual Net Revenue" value={formatCurrency(item.actual_net_revenue)} />
              </div>
            </article>
          ))
        ) : (
          <div className="rounded-xl border border-dashed border-slate-300 bg-white px-4 py-10 text-center text-sm text-slate-500">No dispatch financial records matched the current filter.</div>
        )}
      </div>

      {pagination.total_pages > 1 ? (
        <div className="flex items-center justify-between rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600 shadow-sm">
          <div>Page {pagination.page} of {pagination.total_pages}</div>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={pagination.page <= 1}
              onClick={() => setCurrentPage((current) => Math.max(1, current - 1))}
              className="rounded-lg border border-slate-200 px-3 py-2 disabled:cursor-not-allowed disabled:opacity-60"
            >
              Previous
            </button>
            <button
              type="button"
              disabled={pagination.page >= pagination.total_pages}
              onClick={() => setCurrentPage((current) => Math.min(pagination.total_pages, current + 1))}
              className="rounded-lg border border-slate-200 px-3 py-2 disabled:cursor-not-allowed disabled:opacity-60"
            >
              Next
            </button>
          </div>
        </div>
      ) : null}

      {selectedJobId ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-4">
          <div className="max-h-[92vh] w-full max-w-6xl overflow-y-auto rounded-2xl bg-white shadow-2xl">
            <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-5 py-4">
              <div>
                <h3 className="text-lg font-semibold text-slate-900">{detail?.job?.dispatch_job_id || 'Dispatch Financial Record'}</h3>
                <p className="mt-1 text-sm text-slate-500">Submit money, record expenses, report incidents, and monitor approval flow for this dispatch.</p>
              </div>
              <button type="button" onClick={() => setSelectedJobId(null)} className="rounded-lg px-3 py-2 text-sm text-slate-500 hover:bg-slate-100 hover:text-slate-700">
                Close
              </button>
            </div>
            <div className="px-5 py-5">
              {isLoadingDetail ? (
                <div className="space-y-3">
                  <div className="h-24 animate-pulse rounded-xl bg-slate-100" />
                  <div className="h-40 animate-pulse rounded-xl bg-slate-100" />
                  <div className="h-40 animate-pulse rounded-xl bg-slate-100" />
                </div>
              ) : detailError ? (
                <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{detailError}</div>
              ) : detail ? (
                <div className="space-y-6">
                  <div className="grid gap-4 md:grid-cols-4">
                    <TopInfo label="Financial Status" value={formatLabel(detail.record.financial_status)} />
                    <TopInfo label="Submitted Amount" value={formatCurrency(detail.record.amount_submitted_by_driver)} />
                    <TopInfo label="Outstanding" value={formatCurrency(detail.record.outstanding_balance)} />
                    <TopInfo label="Verified" value={detail.record.verified_at ? formatDateTime(detail.record.verified_at) : 'Pending review'} />
                  </div>

                  <Panel title="Dispatch Money Submission">
                    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                      <InputField label="Amount Collected" type="number" value={moneyForm.amount_collected_from_customer} onChange={(value) => setMoneyForm((current) => ({ ...current, amount_collected_from_customer: value }))} />
                      <InputField label="Amount Submitted" type="number" value={moneyForm.amount_submitted_by_driver} onChange={(value) => setMoneyForm((current) => ({ ...current, amount_submitted_by_driver: value }))} />
                      <InputField label="Payment Method" value={moneyForm.payment_method} onChange={(value) => setMoneyForm((current) => ({ ...current, payment_method: value }))} />
                      <InputField label="Payment Reference" value={moneyForm.payment_reference} onChange={(value) => setMoneyForm((current) => ({ ...current, payment_reference: value }))} />
                      <TextAreaField label="Finance Notes" value={moneyForm.finance_notes} onChange={(value) => setMoneyForm((current) => ({ ...current, finance_notes: value }))} placeholder="Explain submission differences, customer payment notes, or pending amounts." />
                    </div>
                    <div className="mt-4 flex justify-end">
                      <button
                        type="button"
                        onClick={() => void handleSubmitMoney()}
                        disabled={isSaving.money || !canSubmitMoney}
                        className="inline-flex items-center gap-2 rounded-lg bg-[#2563EB] px-4 py-2.5 text-sm font-medium text-white disabled:opacity-60"
                      >
                        {isSaving.money ? <Loader2 className="h-4 w-4 animate-spin" /> : <WalletCards className="h-4 w-4" />}
                        Submit Money
                      </button>
                    </div>
                  </Panel>

                  <Panel title="Dispatch Expense Submission">
                    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                      <SelectField label="Expense Type" value={expenseForm.expense_type} onChange={(value) => setExpenseForm((current) => ({ ...current, expense_type: value }))}>
                        {['fuel', 'loading', 'offloading', 'toll', 'parking', 'helper_payment', 'customer_refund', 'emergency_purchase', 'other'].map((type) => (
                          <option key={type} value={type}>{formatLabel(type)}</option>
                        ))}
                      </SelectField>
                      <InputField label="Amount" type="number" value={expenseForm.amount} onChange={(value) => setExpenseForm((current) => ({ ...current, amount: value }))} />
                      <InputField label="Receipt Reference" value={expenseForm.receipt_reference} onChange={(value) => setExpenseForm((current) => ({ ...current, receipt_reference: value }))} />
                      <TextAreaField label="Expense Note" value={expenseForm.note} onChange={(value) => setExpenseForm((current) => ({ ...current, note: value }))} placeholder="Describe the cost and why it was necessary for this dispatch." />
                    </div>
                    <div className="mt-4 flex justify-end">
                      <button
                        type="button"
                        onClick={() => void handleSubmitExpense()}
                        disabled={isSaving.expense || !canSubmitExpense}
                        className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2.5 text-sm font-medium text-white disabled:opacity-60"
                      >
                        {isSaving.expense ? <Loader2 className="h-4 w-4 animate-spin" /> : <Receipt className="h-4 w-4" />}
                        Submit Expense
                      </button>
                    </div>
                    <div className="mt-4 space-y-3">
                      {detail.expenses.length ? detail.expenses.map((expense) => (
                        <div key={expense.id} className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
                          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                            <div>
                              <div className="font-medium text-slate-900">{formatLabel(expense.expense_type)} • {formatCurrency(expense.amount)}</div>
                              <div className="mt-1 text-sm text-slate-600">{expense.note}</div>
                            </div>
                            <div className="text-xs uppercase tracking-[0.16em] text-slate-500">{formatLabel(expense.status)}</div>
                          </div>
                          {expense.rejection_reason ? <div className="mt-2 text-sm text-rose-700">Reason: {expense.rejection_reason}</div> : null}
                        </div>
                      )) : <EmptyState label="No dispatch expenses submitted yet." />}
                    </div>
                  </Panel>

                  <Panel title="Financial Incident Reporting">
                    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                      <SelectField label="Incident Type" value={incidentForm.incident_type} onChange={(value) => setIncidentForm((current) => ({ ...current, incident_type: value }))}>
                        {['police_arrest', 'traffic_fine', 'wrong_turn_penalty', 'wrong_parking', 'overloading_fine', 'vehicle_documentation_issue', 'insurance_claim', 'accident_cost', 'vehicle_impound_charges', 'towing', 'driver_misconduct', 'company_operational_error', 'other'].map((type) => (
                          <option key={type} value={type}>{formatLabel(type)}</option>
                        ))}
                      </SelectField>
                      <InputField label="Incident Date" type="date" value={incidentForm.incident_date} onChange={(value) => setIncidentForm((current) => ({ ...current, incident_date: value }))} />
                      <InputField label="Incident Location" value={incidentForm.incident_location} onChange={(value) => setIncidentForm((current) => ({ ...current, incident_location: value }))} />
                      <InputField label="Amount" type="number" value={incidentForm.amount} onChange={(value) => setIncidentForm((current) => ({ ...current, amount: value }))} />
                      <SelectField label="Responsibility" value={incidentForm.responsibility_type} onChange={(value) => setIncidentForm((current) => ({ ...current, responsibility_type: value }))}>
                        {['driver_responsible', 'company_responsible', 'shared_responsibility', 'under_investigation'].map((type) => (
                          <option key={type} value={type}>{formatLabel(type)}</option>
                        ))}
                      </SelectField>
                      <InputField label="Final Responsible Party" value={incidentForm.final_responsible_party} onChange={(value) => setIncidentForm((current) => ({ ...current, final_responsible_party: value }))} />
                      <InputField label="Company Share" type="number" value={incidentForm.company_share} onChange={(value) => setIncidentForm((current) => ({ ...current, company_share: value }))} />
                      <InputField label="Driver Share" type="number" value={incidentForm.driver_share} onChange={(value) => setIncidentForm((current) => ({ ...current, driver_share: value }))} />
                      <InputField label="Evidence Reference" value={incidentForm.evidence_reference} onChange={(value) => setIncidentForm((current) => ({ ...current, evidence_reference: value }))} />
                      <TextAreaField label="Description" value={incidentForm.description} onChange={(value) => setIncidentForm((current) => ({ ...current, description: value }))} placeholder="Describe the fine, penalty, operational issue, or liability event." />
                    </div>
                    <div className="mt-4 flex justify-end">
                      <button
                        type="button"
                        onClick={() => void handleSubmitIncident()}
                        disabled={isSaving.incident || !canSubmitIncident}
                        className="inline-flex items-center gap-2 rounded-lg bg-rose-600 px-4 py-2.5 text-sm font-medium text-white disabled:opacity-60"
                      >
                        {isSaving.incident ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldAlert className="h-4 w-4" />}
                        Submit Incident
                      </button>
                    </div>
                    <div className="mt-4 space-y-3">
                      {detail.incidents.length ? detail.incidents.map((incident) => (
                        <div key={incident.id} className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
                          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                            <div>
                              <div className="font-medium text-slate-900">{formatLabel(incident.incident_type)} • {formatCurrency(incident.amount)}</div>
                              <div className="mt-1 text-sm text-slate-600">{incident.description}</div>
                            </div>
                            <div className="text-xs uppercase tracking-[0.16em] text-slate-500">{formatLabel(incident.status)}</div>
                          </div>
                          <div className="mt-2 text-sm text-slate-600">Responsibility: {formatLabel(incident.responsibility_type)}</div>
                          {incident.rejection_reason ? <div className="mt-2 text-sm text-rose-700">Reason: {incident.rejection_reason}</div> : null}
                        </div>
                      )) : <EmptyState label="No financial incidents reported yet." />}
                    </div>
                  </Panel>

                  <Panel title="Review Timeline">
                    <div className="grid gap-4 md:grid-cols-4">
                      <TopInfo label="Submitted At" value={formatDateTime(detail.record.submitted_at)} />
                      <TopInfo label="Verified At" value={formatDateTime(detail.record.verified_at)} />
                      <TopInfo label="Closed At" value={detail.record.is_financially_closed ? formatDateTime(detail.record.financial_closed_at) : 'Open'} />
                      <TopInfo label="Current Profitability" value={formatCurrency(detail.record.actual_net_revenue)} />
                    </div>
                    <div className="mt-4 flex justify-end">
                      <button
                        type="button"
                        onClick={() => void refreshDetail(detail.job?.id || detail.record.dispatch_job_id)}
                        className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
                      >
                        <RefreshCcw className="h-4 w-4" />
                        Refresh Detail
                      </button>
                    </div>
                  </Panel>
                </div>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function TopCard({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: string;
  icon: typeof WalletCards;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
      <div className="flex items-center gap-2 text-sm font-medium text-slate-600">
        <Icon className="h-4 w-4" />
        {label}
      </div>
      <div className="mt-2 text-2xl font-semibold text-slate-900">{value}</div>
    </div>
  );
}

function TopInfo({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
      <div className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">{label}</div>
      <div className="mt-1 text-sm font-medium text-slate-900">{value}</div>
    </div>
  );
}

function MiniInfo({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-slate-50 px-4 py-3 ring-1 ring-slate-200">
      <div className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">{label}</div>
      <div className="mt-1 text-sm font-medium text-slate-900">{value}</div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4">
      <h4 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500">{title}</h4>
      <div className="mt-4">{children}</div>
    </section>
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
      <label className="mb-2 block text-sm font-medium text-slate-700">{label}</label>
      <input
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-lg border border-slate-300 px-4 py-2.5 text-sm"
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
      <label className="mb-2 block text-sm font-medium text-slate-700">{label}</label>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-lg border border-slate-300 px-4 py-2.5 text-sm"
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
      <label className="mb-2 block text-sm font-medium text-slate-700">{label}</label>
      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="min-h-[100px] w-full rounded-lg border border-slate-300 px-4 py-3 text-sm"
      />
    </div>
  );
}

function EmptyState({ label }: { label: string }) {
  return <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">{label}</div>;
}
