import { useEffect, useMemo, useState } from 'react';
import { CalendarDays, Landmark, Loader2, ShieldCheck, Wallet } from 'lucide-react';
import { apiRequest, ApiRequestError } from '../../lib/api';
import { getActiveSessionRole, getStoredSessionUser } from '../../lib/auth-session';

interface AdminUser {
  id: string;
  full_name: string;
  role: 'owner' | 'admin' | 'driver';
  phone: string;
}

interface AccountabilityRecord {
  admin: AdminUser;
  total_collected: number;
  total_approved: number;
  current_holding_balance: number;
}

interface AccountabilityResponse {
  success: boolean;
  data: {
    admins: AccountabilityRecord[];
  };
}

interface WeeklyOverview {
  total_expected: number;
  total_approved: number;
  total_outstanding: number;
  arrears: number;
  drivers_below_target: Array<{
    driver: AdminUser | null;
    assignment_id: string;
    cycle: {
      weekly_target: number;
      approved_total: number;
      outstanding_balance: number;
      status: string;
      payment_deadline: string;
    };
  }>;
}

interface FinanceReportResponse {
  success: boolean;
  data: {
    weekly_payment_overview: WeeklyOverview;
  };
}

interface RemittanceAgreementRow {
  agreement: { assignment_id: string; weekly_amount: number; effective_start: string; week_pattern: string; payment_deadline: string; status: string };
  position: { adjusted_expected: number; confirmed_receipts: number; outstanding: number; arrears: number; applicable_credit: number };
  driver: AdminUser | null;
  vehicle: { id: string; registration_number: string; make?: string; model?: string } | null;
}

interface RemittanceLedger {
  driver?: AdminUser | null;
  vehicle?: { id: string; registration_number: string; make?: string; model?: string } | null;
  agreement?: { effective_start: string; effective_end?: string | null; weekly_amount: number; payment_deadline: string };
  position: RemittanceAgreementRow['position'] & { gross_expected: number; approved_waivers_reductions: number; pending_confirmation: number; overdue_balance: number; current_week_unpaid: number; total_unpaid: number; available_credit: number; defaulted_week_count: number; defaulted_weeks: string[]; range_start?: string; range_end?: string };
  weeks: Array<{
    cycle_key: string; week_start: string; week_end: string; payment_deadline: string; original_amount: number;
    approved_adjustment: number; final_due: number; confirmed_allocated_payments: number; pending_total: number;
    outstanding: number; status: string; payment_status: string; original_deadline: string; effective_deadline: string;
    defaulted?: boolean; is_overdue?: boolean; is_partial?: boolean; request_status?: string; next_responsible_person?: string;
    payment_status_label?: string; exception_reason?: string | null; exception_explanation?: string | null;
    problem_request?: NonWorkingRequest | null; revision_history?: Array<Record<string, unknown>>;
    payments?: Array<{ id: string; amount: number; allocated_amount?: number; collection_date: string; actual_payment_date?: string; submitted_at?: string; approved_at?: string; rejected_at?: string; reversed_at?: string; status: string; is_late?: boolean; payment_method?: string | null; reference_number?: string | null; decision_reason?: string | null; reversal_reason?: string | null; weeks_covered?: string[]; submitted_by_user?: { full_name?: string; role?: string } | null; confirmed_by_user?: { full_name?: string; role?: string } | null; reversed_by_user?: { full_name?: string; role?: string } | null }>;
  }>;
  credit_payments?: Array<{ id: string; amount: number; allocated_amount: number; unallocated_amount: number; collection_date: string; submitted_at?: string; approved_at?: string; allocations: Array<{ cycle_key: string; week_start: string; amount: number }> }>;
}

interface MigrationReport {
  explicit_agreement_count: number; safely_mapped_legacy_count: number; unmappable_count: number;
  historical_timestamp_gaps: { approved_payments_without_approved_at: number; reversals_without_reversed_at_or_status_history: number };
}

interface NonWorkingRequest {
  id: string; driver_id: string; cycle_key: string; start_date: string; end_date: string; reason: string;
  notes?: string | null; explanation?: string | null; reason_code?: string; requested_action?: string; request_status?: string;
  attachments?: Array<string | { url?: string; name?: string }>; attendance_status: string; financial_status: string;
  financial_treatment?: string | null; original_amount?: number; approved_adjustment?: number;
  revised_amount_due?: number | null; approved_amount?: number | null; decision_reason?: string | null;
  affected_dates?: string[]; affected_working_days?: number; selection_type?: string;
  approver_id?: string | null; approval_timestamp?: string | null;
  approver_snapshot?: { id?: string; full_name?: string | null; role?: string | null; email?: string | null } | null;
  affected_weeks?: string[];
  affected_week_decisions?: Record<string, { original_amount: number; approved_adjustment: number; revised_amount_due: number }>;
  created_at?: string;
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
    : 'Unable to load admin accountability right now.';
}

function formatCurrency(value: number) {
  return `GHS ${value.toLocaleString()}`;
}

export default function AdminAccountability({ remittanceWorkspace = false, onNavigate }: { remittanceWorkspace?: boolean; onNavigate?: (page: string) => void } = {}) {
  const [records, setRecords] = useState<AccountabilityRecord[]>([]);
  const [weeklyOverview, setWeeklyOverview] = useState<WeeklyOverview | null>(null);
  const [agreements, setAgreements] = useState<RemittanceAgreementRow[]>([]);
  const [nonWorkingRequests, setNonWorkingRequests] = useState<NonWorkingRequest[]>([]);
  const [migrationReport, setMigrationReport] = useState<MigrationReport | null>(null);
  const [ledger, setLedger] = useState<RemittanceLedger | null>(null);
  const [ledgerAssignmentId, setLedgerAssignmentId] = useState('');
  const [ledgerAsOf, setLedgerAsOf] = useState(new Date().toISOString().slice(0, 10));
  const [ledgerStart, setLedgerStart] = useState('');
  const [ledgerFilter, setLedgerFilter] = useState('all');
  const [isLedgerLoading, setIsLedgerLoading] = useState(false);
  const [isApplyingCredit, setIsApplyingCredit] = useState(false);
  const [decisionDrafts, setDecisionDrafts] = useState<Record<string, { decision_type: string; revised_amount_due: string; decision_reason: string }>>({});
  const [savingRequestId, setSavingRequestId] = useState('');
  const [isRecordingException, setIsRecordingException] = useState(false);
  const [exceptionDraft, setExceptionDraft] = useState({ assignment_id: '', selection_type: 'single_day', start_date: '', end_date: '', affected_dates: '', reason_code: 'sick_health', explanation: '', evidence: '', requested_action: 'full_exemption' });
  const [isLoading, setIsLoading] = useState(true);
  const [pageError, setPageError] = useState('');
  const [pageNotice, setPageNotice] = useState('');

  const currentRole = getActiveSessionRole(getStoredSessionUser());

  const loadRecords = async () => {
      setIsLoading(true);
      setPageError('');
      setPageNotice('');
      try {
        const results = await Promise.allSettled([
          apiRequest<AccountabilityResponse>('/admins/accountability', { cacheTtlMs: 10000, timeoutMs: 15000 }),
          apiRequest<FinanceReportResponse>('/reports/finance', { cacheTtlMs: 10000, timeoutMs: 15000 }),
          apiRequest<{ data: { agreements: RemittanceAgreementRow[]; migration_report: MigrationReport } }>('/collections/remittance/agreements', { cacheTtlMs: 10000, timeoutMs: 15000 }),
          apiRequest<{ data: { requests: NonWorkingRequest[] } }>('/collections/remittance/non-working', { cacheTtlMs: 10000, timeoutMs: 15000 }),
        ]);
        const accountabilityResponse = getSettledData(results[0]);
        if (!accountabilityResponse) throw results[0].status === 'rejected' ? results[0].reason : new Error('Unable to load accountability.');
        setRecords(Array.isArray(accountabilityResponse?.data?.admins) ? accountabilityResponse.data.admins : []);
        const financeResponse = getSettledData(results[1]);
        setWeeklyOverview(financeResponse?.data?.weekly_payment_overview || null);
        setAgreements(getSettledData(results[2])?.data?.agreements || []);
        setMigrationReport(getSettledData(results[2])?.data?.migration_report || null);
        setNonWorkingRequests(getSettledData(results[3])?.data?.requests || []);
        if (results.slice(1).some((result) => getSettledError(result))) setPageNotice('Some weekly remittance details are temporarily unavailable.');
      } catch (error) {
        if (error instanceof ApiRequestError) {
          setPageError(error.message);
        } else {
          setPageError('Unable to load admin accountability right now.');
        }
      } finally {
        setIsLoading(false);
      }
    };

  const loadLedger = async (assignmentId: string, asOf = ledgerAsOf) => {
    setIsLedgerLoading(true); setPageError('');
    try {
      const response = await apiRequest<{ data: RemittanceLedger }>(`/collections/remittance/position?assignment_id=${encodeURIComponent(assignmentId)}&end_date=${encodeURIComponent(asOf)}&start_date=${encodeURIComponent(ledgerStart)}&limit=52`);
      setLedger(response.data); setLedgerAssignmentId(assignmentId);
    } catch (error) {
      setPageError(error instanceof ApiRequestError ? error.message : 'Unable to load weekly remittance history.');
    } finally { setIsLedgerLoading(false); }
  };

  const saveNonWorkingDecision = async (requestId: string) => {
    const draft = decisionDrafts[requestId] || { decision_type: 'under_review', revised_amount_due: '', decision_reason: '' };
    setSavingRequestId(requestId); setPageError('');
    try {
      await apiRequest(`/collections/remittance/requests/${requestId}/decision`, { method: 'PATCH', headers: { 'Idempotency-Key': crypto.randomUUID() }, body: JSON.stringify({ ...draft, revised_amount_due: ['reduce', 'partial_approval'].includes(draft.decision_type) ? Number(draft.revised_amount_due) : undefined }) });
      setPageNotice('Work-exception decision saved. The weekly balance has been recalculated.');
      await loadRecords();
    } catch (error) {
      setPageError(error instanceof ApiRequestError ? error.message : 'Unable to save the non-working decision.');
    } finally { setSavingRequestId(''); }
  };

  const recordHistoricalException = async (event: React.FormEvent) => {
    event.preventDefault();
    const agreement = agreements.find((row) => row.agreement.assignment_id === exceptionDraft.assignment_id);
    if (!agreement) { setPageError('Select a driver remittance agreement.'); return; }
    setIsRecordingException(true); setPageError(''); setPageNotice('');
    try {
      const affectedDates = exceptionDraft.affected_dates.split(',').map((value) => value.trim()).filter(Boolean);
      const evidence = exceptionDraft.evidence.split(',').map((value) => value.trim()).filter(Boolean);
      await apiRequest('/collections/remittance/requests', {
        method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() },
        body: JSON.stringify({
          driver_id: agreement.agreement.driver_id, assignment_id: exceptionDraft.assignment_id,
          selection_type: exceptionDraft.selection_type, start_date: exceptionDraft.start_date,
          end_date: exceptionDraft.end_date || exceptionDraft.start_date,
          affected_dates: exceptionDraft.selection_type === 'multiple_days' ? affectedDates : undefined,
          reason_code: exceptionDraft.reason_code, explanation: exceptionDraft.explanation,
          evidence, requested_action: exceptionDraft.requested_action,
        }),
      });
      setPageNotice('Historical Work Exception recorded with the actual affected dates. It remains pending until an Admin/Owner decision is saved.');
      setExceptionDraft((current) => ({ ...current, start_date: '', end_date: '', affected_dates: '', explanation: '', evidence: '' }));
      await loadRecords();
    } catch (error) {
      setPageError(error instanceof ApiRequestError ? error.message : 'Unable to record the historical Work Exception.');
    } finally { setIsRecordingException(false); }
  };

  const changeAgreementAmount = async (row: RemittanceAgreementRow) => {
    const amount = window.prompt('New weekly remittance amount (GHS)', String(row.agreement.weekly_amount));
    if (!amount) return;
    const effectiveFrom = window.prompt('Effective date (YYYY-MM-DD)', new Date().toISOString().slice(0, 10));
    if (!effectiveFrom) return;
    const reason = window.prompt('Reason for the effective-dated change');
    if (!reason?.trim()) return;
    try {
      await apiRequest(`/collections/remittance/agreements/${row.agreement.assignment_id}`, { method: 'PATCH', body: JSON.stringify({ weekly_amount: Number(amount), effective_from: effectiveFrom, reason }) });
      await loadRecords();
    } catch (error) { setPageError(error instanceof ApiRequestError ? error.message : 'Unable to update the agreement.'); }
  };

  const changeAgreementStatus = async (row: RemittanceAgreementRow, status: 'active' | 'paused' | 'ended') => {
    const reason = window.prompt(`Reason to mark this agreement ${status}`);
    if (!reason?.trim()) return;
    try {
      await apiRequest(`/collections/remittance/agreements/${row.agreement.assignment_id}`, { method: 'PATCH', body: JSON.stringify({ status, status_effective_from: new Date().toISOString().slice(0, 10), reason }) });
      await loadRecords();
    } catch (error) { setPageError(error instanceof ApiRequestError ? error.message : 'Unable to update the agreement.'); }
  };

  const changeAgreementTerms = async (row: RemittanceAgreementRow) => {
    const weekPattern = window.prompt('Work week: mon_sat or mon_sun', row.agreement.week_pattern || 'mon_sat');
    if (!weekPattern) return;
    const paymentDeadline = window.prompt('Payment deadline: week_end, saturday, sunday, or monday_next_week', row.agreement.payment_deadline || 'week_end');
    if (!paymentDeadline) return;
    const effectiveEnd = window.prompt('Optional agreement end date (YYYY-MM-DD). Leave blank for no end.', '');
    if (effectiveEnd === null) return;
    try {
      await apiRequest(`/collections/remittance/agreements/${row.agreement.assignment_id}`, { method: 'PATCH', body: JSON.stringify({ week_pattern: weekPattern, payment_deadline: paymentDeadline, effective_end: effectiveEnd || null }) });
      await loadRecords();
    } catch (error) { setPageError(error instanceof ApiRequestError ? error.message : 'Unable to update agreement terms.'); }
  };

  const applyCreditToArrears = async () => {
    if (!ledgerAssignmentId || !ledger?.position.available_credit || !ledger.position.overdue_balance) return;
    setIsApplyingCredit(true); setPageError(''); setPageNotice('');
    try {
      const response = await apiRequest<{ data: { applied: number } }>('/collections/remittance/credit/apply', { method: 'POST', body: JSON.stringify({ assignment_id: ledgerAssignmentId }) });
      setPageNotice(`${formatCurrency(response.data.applied)} of confirmed credit was allocated oldest-first.`);
      await loadLedger(ledgerAssignmentId, ledgerAsOf);
      await loadRecords();
    } catch (error) {
      setPageError(error instanceof ApiRequestError ? error.message : 'Unable to apply confirmed credit.');
    } finally { setIsApplyingCredit(false); }
  };

  useEffect(() => {
    if (currentRole === 'driver') {
      setIsLoading(false);
      return;
    }
    void loadRecords();
  }, [currentRole]);

  const totals = useMemo(() => {
    return records.reduce(
      (summary, record) => ({
        totalCollected: summary.totalCollected + record.total_collected,
        totalApproved: summary.totalApproved + record.total_approved,
        totalHolding: summary.totalHolding + record.current_holding_balance,
      }),
      { totalCollected: 0, totalApproved: 0, totalHolding: 0 },
    );
  }, [records]);

  const filteredLedgerWeeks = useMemo(() => (ledger?.weeks || []).filter((week) => {
    if (ledgerFilter === 'unpaid') return week.outstanding > 0;
    if (ledgerFilter === 'overdue') return Boolean(week.is_overdue && week.outstanding > 0);
    if (ledgerFilter === 'part_paid') return Boolean(week.is_partial);
    if (ledgerFilter === 'paid_late') return week.payment_status === 'paid_late';
    if (ledgerFilter === 'paid') return ['paid_on_time', 'paid_late'].includes(week.payment_status);
    if (ledgerFilter === 'excused') return week.payment_status === 'excused_no_payment_due';
    return true;
  }), [ledger, ledgerFilter]);

  if (currentRole === 'driver') {
    return (
      <div className="p-6">
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Drivers do not have access to Admin Accountability.
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-[#0F172A]">{remittanceWorkspace ? 'Driver Remittances' : 'Admin Accountability'}</h1>
        <p className="mt-1 text-gray-600">{remittanceWorkspace ? 'Weekly obligations, arrears, confirmed allocations and available credit' : 'Track who collected funds, approved collections, and still holds cash'}</p>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-lg bg-blue-100">
            <Landmark className="h-5 w-5 text-blue-600" />
          </div>
          <div className="text-2xl font-semibold text-[#0F172A]">{formatCurrency(totals.totalCollected)}</div>
          <div className="text-sm text-gray-600">Total Collected</div>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-lg bg-green-100">
            <ShieldCheck className="h-5 w-5 text-green-600" />
          </div>
          <div className="text-2xl font-semibold text-[#0F172A]">{formatCurrency(totals.totalApproved)}</div>
          <div className="text-sm text-gray-600">Total Approved</div>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-lg bg-amber-100">
            <Wallet className="h-5 w-5 text-amber-600" />
          </div>
          <div className="text-2xl font-semibold text-[#0F172A]">{formatCurrency(totals.totalHolding)}</div>
          <div className="text-sm text-gray-600">Current Holding Balance</div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="text-2xl font-semibold text-[#0F172A]">{formatCurrency(weeklyOverview?.total_expected || 0)}</div>
          <div className="text-sm text-gray-600">Total Expected</div>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="text-2xl font-semibold text-green-700">{formatCurrency(weeklyOverview?.total_approved || 0)}</div>
          <div className="text-sm text-gray-600">Total Approved / Collected</div>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="text-2xl font-semibold text-red-700">{formatCurrency(weeklyOverview?.total_outstanding || 0)}</div>
          <div className="text-sm text-gray-600">Total Outstanding</div>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="text-2xl font-semibold text-amber-700">{formatCurrency(weeklyOverview?.arrears || 0)}</div>
          <div className="text-sm text-gray-600">Arrears</div>
        </div>
      </div>

      <form onSubmit={recordHistoricalException} className="rounded-xl border border-gray-200 bg-white p-5">
        <h2 className="text-lg font-semibold text-[#0F172A]">Record Historical Work Exception</h2>
        <p className="mb-4 text-sm text-gray-500">The affected dates may be historical; the record and approval timestamps remain the real current timestamps.</p>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
          <label className="text-xs font-medium text-gray-600">Driver / agreement<select required value={exceptionDraft.assignment_id} onChange={(event) => setExceptionDraft((value) => ({ ...value, assignment_id: event.target.value }))} className="mt-1 min-h-11 w-full rounded-lg border px-3 text-sm"><option value="">Select driver</option>{agreements.map((row) => <option key={row.agreement.assignment_id} value={row.agreement.assignment_id}>{row.driver?.full_name || 'Unknown driver'} · {row.vehicle?.registration_number || 'No vehicle'}</option>)}</select></label>
          <label className="text-xs font-medium text-gray-600">Affected period<select value={exceptionDraft.selection_type} onChange={(event) => setExceptionDraft((value) => ({ ...value, selection_type: event.target.value }))} className="mt-1 min-h-11 w-full rounded-lg border px-3 text-sm"><option value="single_day">One day</option><option value="multiple_days">Multiple specific days</option><option value="date_range">Date range</option><option value="whole_week">Full week</option></select></label>
          <label className="text-xs font-medium text-gray-600">Reason<select value={exceptionDraft.reason_code} onChange={(event) => setExceptionDraft((value) => ({ ...value, reason_code: event.target.value }))} className="mt-1 min-h-11 w-full rounded-lg border px-3 text-sm"><option value="sick_health">Sick / Health</option><option value="emergency_personal">Emergency / Personal</option><option value="vehicle_issue">Vehicle Issue</option><option value="company_assignment">Company Assignment</option><option value="low_work_market_issue">Low Work / Market Issue</option><option value="external_issue">External Issue</option><option value="other">Other</option></select></label>
          {exceptionDraft.selection_type === 'multiple_days' ? <label className="text-xs font-medium text-gray-600 lg:col-span-2">Affected dates (comma-separated YYYY-MM-DD)<input required value={exceptionDraft.affected_dates} onChange={(event) => setExceptionDraft((value) => ({ ...value, affected_dates: event.target.value }))} placeholder="2026-07-20, 2026-07-22" className="mt-1 min-h-11 w-full rounded-lg border px-3 text-sm" /></label> : <><label className="text-xs font-medium text-gray-600">{exceptionDraft.selection_type === 'whole_week' ? 'Any date in affected week' : 'Start / affected date'}<input required type="date" value={exceptionDraft.start_date} onChange={(event) => setExceptionDraft((value) => ({ ...value, start_date: event.target.value }))} className="mt-1 min-h-11 w-full rounded-lg border px-3 text-sm" /></label>{exceptionDraft.selection_type === 'date_range' && <label className="text-xs font-medium text-gray-600">End date<input required type="date" value={exceptionDraft.end_date} onChange={(event) => setExceptionDraft((value) => ({ ...value, end_date: event.target.value }))} className="mt-1 min-h-11 w-full rounded-lg border px-3 text-sm" /></label>}</>}
          <label className="text-xs font-medium text-gray-600">Requested treatment<select value={exceptionDraft.requested_action} onChange={(event) => setExceptionDraft((value) => ({ ...value, requested_action: event.target.value }))} className="mt-1 min-h-11 w-full rounded-lg border px-3 text-sm"><option value="full_exemption">Full exemption</option><option value="reduction">Set reduced amount</option></select></label>
          <label className="text-xs font-medium text-gray-600 lg:col-span-2">Explanation<textarea required value={exceptionDraft.explanation} onChange={(event) => setExceptionDraft((value) => ({ ...value, explanation: event.target.value }))} className="mt-1 min-h-20 w-full rounded-lg border px-3 py-2 text-sm" /></label>
          <label className="text-xs font-medium text-gray-600">Optional evidence links/references (comma-separated)<textarea value={exceptionDraft.evidence} onChange={(event) => setExceptionDraft((value) => ({ ...value, evidence: event.target.value }))} className="mt-1 min-h-20 w-full rounded-lg border px-3 py-2 text-sm" /></label>
        </div>
        <div className="mt-4 flex justify-end"><button disabled={isRecordingException} className="min-h-11 rounded-lg bg-blue-600 px-4 text-sm font-medium text-white disabled:opacity-60">{isRecordingException ? 'Recording…' : 'Record Work Exception'}</button></div>
      </form>

      <div className="rounded-xl border border-gray-200 bg-white p-5">
        <div className="mb-4 flex items-center gap-3"><CalendarDays className="h-5 w-5 text-blue-600" /><div><h2 className="text-lg font-semibold text-[#0F172A]">Weekly Remittance Agreements</h2><p className="text-sm text-gray-500">Existing driver/vehicle assignments are reused; balances use historical weekly obligations.</p></div></div>
        {migrationReport && <div className="mb-4 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">{migrationReport.explicit_agreement_count} configured · {migrationReport.safely_mapped_legacy_count} safely mapped from weekly targets · {migrationReport.unmappable_count} preserved for data review</div>}
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          {agreements.map((row) => (
            <div key={row.agreement.assignment_id} className="rounded-lg border border-gray-200 p-4">
              <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between"><div><div className="font-semibold text-gray-900">{row.driver?.full_name || 'Unknown driver'}</div><div className="text-sm text-gray-500">{row.vehicle?.registration_number || 'No vehicle'} · {row.vehicle?.make} {row.vehicle?.model}</div></div><span className="mt-1 w-fit rounded-full bg-blue-50 px-2.5 py-1 text-xs font-medium uppercase text-blue-700">{row.agreement.status}</span></div>
              <div className="mt-4 grid grid-cols-2 gap-3 text-sm"><div><span className="block text-gray-500">Weekly amount</span><strong>{formatCurrency(row.agreement.weekly_amount)}</strong></div><div><span className="block text-gray-500">Started</span><strong>{row.agreement.effective_start}</strong></div><div><span className="block text-gray-500">Overdue arrears</span><strong className="text-red-700">{formatCurrency(row.position.arrears)}</strong></div><div><span className="block text-gray-500">Available credit</span><strong className="text-green-700">{formatCurrency(row.position.applicable_credit)}</strong></div></div>
              <div className="mt-4 flex flex-wrap gap-2"><button onClick={() => { setLedgerFilter('overdue'); void loadLedger(row.agreement.assignment_id); }} className="rounded-lg bg-amber-600 px-3 py-2 text-xs font-medium text-white">View Arrears Breakdown</button><button onClick={() => onNavigate?.('collections')} className="rounded-lg bg-blue-600 px-3 py-2 text-xs font-medium text-white">Pay Arrears</button><button onClick={() => { setLedgerFilter('all'); void loadLedger(row.agreement.assignment_id); }} className="rounded-lg border border-gray-300 px-3 py-2 text-xs font-medium">View Credit / Allocations</button><button onClick={() => void changeAgreementAmount(row)} className="rounded-lg border border-gray-300 px-3 py-2 text-xs font-medium">Change Amount</button><button onClick={() => void changeAgreementTerms(row)} className="rounded-lg border border-gray-300 px-3 py-2 text-xs font-medium">Schedule / Deadline</button>{row.agreement.status === 'paused' ? <button onClick={() => void changeAgreementStatus(row, 'active')} className="rounded-lg border border-green-300 px-3 py-2 text-xs font-medium text-green-700">Resume</button> : <button onClick={() => void changeAgreementStatus(row, 'paused')} className="rounded-lg border border-amber-300 px-3 py-2 text-xs font-medium text-amber-700">Pause</button>}<button onClick={() => void changeAgreementStatus(row, 'ended')} className="rounded-lg border border-red-300 px-3 py-2 text-xs font-medium text-red-700">End</button></div>
            </div>
          ))}
          {!agreements.length && <div className="py-6 text-sm text-gray-500">No safely mappable weekly agreements found.</div>}
        </div>
        {ledgerAssignmentId && <div className="mt-5 border-t pt-5">
          <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between"><div><h3 className="font-semibold text-gray-900">Driver / Vehicle Weekly Ledger</h3><p className="text-sm text-gray-500">Position is reconstructed from obligations and confirmations known by the selected date.</p></div><label className="text-sm text-gray-600">As of<input type="date" value={ledgerAsOf} onChange={(event) => setLedgerAsOf(event.target.value)} className="mt-1 block min-h-11 w-full rounded-lg border px-3 sm:w-auto" /></label><button disabled={isLedgerLoading} onClick={() => void loadLedger(ledgerAssignmentId, ledgerAsOf)} className="min-h-11 rounded-lg border px-4 text-sm font-medium disabled:opacity-60">{isLedgerLoading ? 'Loading…' : 'Apply Date'}</button></div>
          {ledger && <><div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{[
            ['Overdue arrears', ledger.position.overdue_balance], ['Current week remaining', ledger.position.current_week_unpaid],
            ['Total unpaid', ledger.position.total_unpaid], ['Available credit', ledger.position.available_credit],
          ].map(([label, value]) => <div key={String(label)} className="rounded-lg bg-slate-50 p-3"><div className="text-xs text-slate-500">{label}</div><div className="mt-1 font-semibold">{formatCurrency(Number(value))}</div></div>)}</div>
          <div className="mt-4 flex flex-wrap gap-2">{[['all','All'],['unpaid','Unpaid'],['overdue','Overdue'],['part_paid','Part-paid'],['paid_late','Paid late'],['paid','Paid'],['excused','Excused']].map(([value,label]) => <button key={value} onClick={() => setLedgerFilter(value)} className={`min-h-10 rounded-lg border px-3 text-sm ${ledgerFilter === value ? 'border-blue-600 bg-blue-600 text-white' : 'border-gray-300'}`}>{label}</button>)}</div>
          {ledger.position.available_credit > 0 && <div className="mt-4 rounded-lg border border-green-200 bg-green-50 p-4"><div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"><div><strong>Confirmed unallocated money: {formatCurrency(ledger.position.available_credit)}</strong><p className="text-xs text-green-800">Historical bulk money remains credit until assigned to specific obligations.</p></div><button disabled={isApplyingCredit || !ledger.position.overdue_balance} onClick={() => void applyCreditToArrears()} className="min-h-11 rounded-lg bg-green-700 px-4 text-sm font-medium text-white disabled:opacity-50">{isApplyingCredit ? 'Applying…' : 'Apply Credit to Arrears'}</button></div>{ledger.credit_payments?.map((payment) => <div key={payment.id} className="mt-3 rounded bg-white p-2 text-xs text-gray-600">{formatCurrency(payment.unallocated_amount)} unallocated from {formatCurrency(payment.amount)} paid {payment.collection_date} · submitted {payment.submitted_at ? new Date(payment.submitted_at).toLocaleString() : 'legacy time unavailable'} · confirmed {payment.approved_at ? new Date(payment.approved_at).toLocaleString() : 'unknown'}</div>)}</div>}
          <div className="mt-4 grid grid-cols-1 gap-3 lg:grid-cols-2">{filteredLedgerWeeks.map((week) => <article key={week.cycle_key} className={`rounded-lg border p-4 ${week.is_overdue && week.outstanding > 0 ? 'border-red-300 bg-red-50/40' : ''}`}><div className="flex items-start justify-between gap-3"><div><div className="font-medium">{week.week_start} to {week.week_end}</div><div className="text-xs text-gray-500">Effective deadline {week.effective_deadline}</div></div><span className="rounded-full bg-slate-100 px-2 py-1 text-xs uppercase">{week.payment_status_label || week.payment_status.replaceAll('_', ' ')}</span></div><div className="mt-3 grid grid-cols-2 gap-2 text-sm sm:grid-cols-3"><div>Original Due <strong className="block">{formatCurrency(week.original_amount)}</strong></div><div>Approved Adjustment <strong className="block">{formatCurrency(week.approved_adjustment)}</strong></div><div>Revised Due <strong className="block">{formatCurrency(week.final_due)}</strong></div><div>Confirmed Paid <strong className="block text-green-700">{formatCurrency(week.confirmed_allocated_payments)}</strong></div><div>Pending <strong className="block text-amber-700">{formatCurrency(week.pending_total)}</strong></div><div>Remaining <strong className="block text-red-700">{formatCurrency(week.outstanding)}</strong></div></div>{week.exception_reason && <div className="mt-3 rounded bg-blue-50 px-3 py-2 text-xs capitalize text-blue-800">Reason: {week.exception_reason.replaceAll('_', ' ')}{week.exception_explanation ? ` - ${week.exception_explanation}` : ''}</div>}{week.payments?.map((payment) => { const pending = ['pending', 'submitted', 'received'].includes(payment.status); return <div key={payment.id} className="mt-3 rounded bg-white p-2 text-xs text-gray-600"><div className="font-medium text-gray-800">{pending ? 'Pending Confirmation' : payment.status === 'approved' ? 'Confirmed' : payment.status.replaceAll('_', ' ')}</div><div>Payment amount: {formatCurrency(payment.amount)}</div><div>Allocated to this week: {formatCurrency(payment.allocated_amount || 0)}</div><div>Weeks covered: {(payment.weeks_covered || [week.cycle_key]).join(', ')}</div><div>Payment date: {payment.actual_payment_date || payment.collection_date}</div><div>Submitted: {payment.submitted_at ? new Date(payment.submitted_at).toLocaleString() : 'Legacy time unavailable'}{payment.submitted_by_user?.full_name ? ` by ${payment.submitted_by_user.full_name}` : ''}</div>{payment.status === 'approved' && <><div>Confirmed: {payment.approved_at ? new Date(payment.approved_at).toLocaleString() : 'Legacy time unavailable'} by {payment.confirmed_by_user?.full_name || 'Legacy confirmer unavailable'}{payment.confirmed_by_user?.role ? ` (${payment.confirmed_by_user.role})` : ''}</div><div>Confirmation reason: {payment.decision_reason || 'Legacy reason unavailable'}</div></>}{payment.status === 'reversed' && <div className="text-red-700">Reversed: {payment.reversed_at ? new Date(payment.reversed_at).toLocaleString() : 'Legacy time unavailable'} by {payment.reversed_by_user?.full_name || 'Legacy corrector unavailable'}{payment.reversed_by_user?.role ? ` (${payment.reversed_by_user.role})` : ''} · Reason: {payment.reversal_reason || 'Legacy reason unavailable'}</div>}{pending && <div className="font-medium text-amber-700">Awaiting Admin confirmation</div>}<div className="capitalize">{payment.payment_method || 'Payment'}{payment.reference_number ? ` · Ref ${payment.reference_number}` : ''}</div></div>; })}</article>)}</div></>}
        </div>}
      </div>

      <div className="rounded-xl border border-gray-200 bg-white p-5">
        <h2 className="text-lg font-semibold text-[#0F172A]">Work Exception Review Queue</h2>
        <p className="mb-4 text-sm text-gray-500">A submission never changes debt. Only an authorised final decision can revise the exact amount due.</p>
        <div className="space-y-3">
          {nonWorkingRequests.map((item) => {
            const draft = decisionDrafts[item.id] || { decision_type: 'under_review', revised_amount_due: '', decision_reason: '' };
            const original = Number(item.original_amount || 0);
            const revised = draft.decision_type === 'full_exemption' ? 0 : Number(draft.revised_amount_due || original);
            return <div key={item.id} className="rounded-lg border border-gray-200 p-4"><div className="mb-3"><div className="font-medium text-gray-900">{item.start_date} to {item.end_date} · {(item.affected_dates || []).length ? `${item.affected_dates?.length} affected day(s)` : item.cycle_key}</div><div className="text-sm capitalize text-gray-600">{item.reason_code?.replaceAll('_', ' ') || 'Other'}{item.explanation ? ` - ${item.explanation}` : ''}</div>{item.affected_dates?.length ? <div className="mt-1 text-xs text-gray-500">Dates: {item.affected_dates.join(', ')}</div> : null}<div className="mt-1 text-xs text-gray-500">Recorded: {item.created_at ? new Date(item.created_at).toLocaleString() : 'Legacy timestamp unavailable'}</div><div className="mt-1 text-xs uppercase text-gray-500">Status: {item.request_status?.replaceAll('_', ' ') || item.attendance_status} · Finance: {item.financial_status}</div>{item.financial_status !== 'pending' && <div className="mt-3 rounded bg-slate-50 p-3 text-xs text-slate-700"><div>Approved/decided by: {item.approver_snapshot?.full_name || 'Legacy approver unavailable'} ({item.approver_snapshot?.role || 'account unavailable'})</div><div>Decision time: {item.approval_timestamp ? new Date(item.approval_timestamp).toLocaleString() : 'Legacy timestamp unavailable'}</div><div>Decision reason: {item.decision_reason || 'Legacy reason unavailable'}</div><div>Affected weeks: {(item.affected_weeks || [item.cycle_key]).join(', ')}</div>{Object.entries(item.affected_week_decisions || {}).map(([week, values]) => <div key={week} className="mt-1">{week}: Original {formatCurrency(values.original_amount)} · Adjustment {formatCurrency(values.approved_adjustment)} · Revised {formatCurrency(values.revised_amount_due)}</div>)}</div>}</div>
              {item.financial_status === 'pending' && <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <label className="text-xs font-medium text-gray-600">Decision<select value={draft.decision_type} onChange={(event) => setDecisionDrafts((all) => ({ ...all, [item.id]: { ...draft, decision_type: event.target.value } }))} className="mt-1 min-h-11 w-full rounded-lg border px-3 text-sm"><option value="under_review">Mark Under Review</option><option value="request_more_information">Needs More Information</option><option value="explanation_only">Approve — Full Amount Remains</option><option value="reduce">Approve Reduced Amount</option><option value="partial_approval">Partially Approve</option><option value="full_exemption">Approve Full Exemption</option><option value="decline">Decline</option></select></label>
                {['reduce', 'partial_approval'].includes(draft.decision_type) && <label className="text-xs font-medium text-gray-600">Exact revised amount due<input type="number" min="0" max={original || undefined} step="0.01" required value={draft.revised_amount_due} onChange={(event) => setDecisionDrafts((all) => ({ ...all, [item.id]: { ...draft, revised_amount_due: event.target.value } }))} placeholder="GHS 0.00" className="mt-1 min-h-11 w-full rounded-lg border px-3 text-sm" /></label>}
                <label className="text-xs font-medium text-gray-600 md:col-span-2">Decision reason<textarea required={draft.decision_type !== 'under_review'} value={draft.decision_reason} onChange={(event) => setDecisionDrafts((all) => ({ ...all, [item.id]: { ...draft, decision_reason: event.target.value } }))} placeholder="Explain the decision" className="mt-1 min-h-20 w-full rounded-lg border px-3 py-2 text-sm" /></label>
                {['reduce', 'partial_approval', 'full_exemption'].includes(draft.decision_type) && <div className="rounded-lg bg-slate-50 p-3 text-sm md:col-span-2"><div className="grid grid-cols-3 gap-2"><div><span className="block text-xs text-gray-500">Original</span>{formatCurrency(original)}</div><div><span className="block text-xs text-gray-500">Adjustment</span>-{formatCurrency(Math.max(original - revised, 0))}</div><div><span className="block text-xs text-gray-500">Final due</span>{formatCurrency(Math.max(revised, 0))}</div></div></div>}
                <button onClick={() => void saveNonWorkingDecision(item.id)} disabled={savingRequestId === item.id || (draft.decision_type !== 'under_review' && !draft.decision_reason.trim()) || (['reduce', 'partial_approval'].includes(draft.decision_type) && draft.revised_amount_due === '')} className="min-h-11 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-60 md:col-start-2">{savingRequestId === item.id ? 'Saving...' : 'Save Decision'}</button>
              </div>}
            </div>;
          })}
          {!nonWorkingRequests.length && <div className="py-6 text-sm text-gray-500">No work-exception requests submitted.</div>}
        </div>
      </div>

      {pageError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <span>{pageError}</span>
            <button
              onClick={() => void loadRecords()}
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
        {isLoading ? (
          <div className="flex items-center justify-center gap-3 px-6 py-16 text-gray-500">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span>Loading accountability records...</span>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="border-b border-gray-200 bg-gray-50">
                <tr>
                  <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Admin</th>
                  <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Role</th>
                  <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Total Collected</th>
                  <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Total Approved</th>
                  <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Holding Balance</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {records.map((record) => (
                  <tr key={record.admin.id} className="transition-colors hover:bg-gray-50">
                    <td className="px-6 py-4">
                      <div className="font-medium text-[#0F172A]">{record.admin.full_name}</div>
                      <div className="text-xs text-gray-500">{record.admin.phone}</div>
                    </td>
                    <td className="px-6 py-4 capitalize text-gray-700">{record.admin.role}</td>
                    <td className="px-6 py-4 font-semibold text-[#0F172A]">
                      {formatCurrency(record.total_collected)}
                    </td>
                    <td className="px-6 py-4 font-semibold text-green-700">
                      {formatCurrency(record.total_approved)}
                    </td>
                    <td className="px-6 py-4 font-semibold text-amber-700">
                      {formatCurrency(record.current_holding_balance)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {records.length === 0 && (
              <div className="px-6 py-12 text-center text-gray-500">No admin accountability records found.</div>
            )}
          </div>
        )}
      </div>

      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
        <div className="border-b border-gray-200 px-6 py-4">
          <h2 className="text-lg font-semibold text-[#0F172A]">Drivers Below Target</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="border-b border-gray-200 bg-gray-50">
              <tr>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Driver</th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Target</th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Approved</th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Outstanding</th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Deadline</th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {(weeklyOverview?.drivers_below_target || []).map((record) => (
                <tr key={`${record.driver?.id || 'driver'}-${record.assignment_id}`} className="transition-colors hover:bg-gray-50">
                  <td className="px-6 py-4">
                    <div className="font-medium text-[#0F172A]">{record.driver?.full_name || 'Unknown Driver'}</div>
                    <div className="text-xs text-gray-500">{record.driver?.phone || record.assignment_id}</div>
                  </td>
                  <td className="px-6 py-4 text-gray-700">{formatCurrency(record.cycle.weekly_target)}</td>
                  <td className="px-6 py-4 text-green-700">{formatCurrency(record.cycle.approved_total)}</td>
                  <td className="px-6 py-4 text-red-700">{formatCurrency(record.cycle.outstanding_balance)}</td>
                  <td className="px-6 py-4 text-gray-700">{record.cycle.payment_deadline}</td>
                  <td className="px-6 py-4 capitalize text-gray-700">{record.cycle.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {(weeklyOverview?.drivers_below_target || []).length === 0 && (
            <div className="px-6 py-12 text-center text-gray-500">No drivers are below target right now.</div>
          )}
        </div>
      </div>
    </div>
  );
}
