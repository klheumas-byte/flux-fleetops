import { useEffect, useMemo, useState } from 'react';
import {
  Calendar,
  CreditCard,
  Loader2,
  Receipt,
  TrendingUp,
  Wallet,
  X,
} from 'lucide-react';
import type { SessionUser } from '../../lib/auth-session';
import { submitDriverNonWorkingRequest, submitDriverPayment, type DriverWalletData, type DriverWeeklyCyclePayment } from '../../lib/driver-api';
import { ApiRequestError } from '../../lib/api';
import { clearDriverQuickActionIntent, peekDriverQuickActionIntent } from '../../lib/driver-quick-actions';

interface MyWalletProps {
  currentUser: SessionUser | null;
  walletData: DriverWalletData | null;
  onRefresh: () => Promise<void>;
}

type PaymentMethod = 'cash' | 'momo' | 'bank' | 'other';

function formatCurrency(value: number) {
  return `GHS ${value.toLocaleString()}`;
}

function formatDate(value: string | null | undefined) {
  if (!value) {
    return 'Not available';
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleDateString();
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return 'Legacy time unavailable';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function paymentConfirmationLabel(status: string) {
  if (['pending', 'submitted', 'received'].includes(status)) return 'Pending Confirmation';
  if (status === 'approved') return 'Confirmed';
  if (status === 'rejected') return 'Rejected';
  if (status === 'reversed') return 'Reversed';
  return status.replaceAll('_', ' ');
}

function PaymentAuditDetail({ payment, cycleKey }: { payment: DriverWeeklyCyclePayment; cycleKey: string }) {
  const pending = ['pending', 'submitted', 'received'].includes(payment.status);
  return <div className="mt-3 rounded bg-white p-2 text-xs text-gray-600">
    <div className="font-medium text-gray-800">{paymentConfirmationLabel(payment.status)} · Week {cycleKey}</div>
    <div>Applied to this week: {formatCurrency(payment.allocated_amount ?? payment.amount)}</div>
    {Number(payment.allocated_amount ?? payment.amount) !== Number(payment.amount) && <div>Original submission total: {formatCurrency(payment.amount)}</div>}
    <div>Weeks covered: {(payment.weeks_covered || payment.allocations?.map((item) => item.cycle_key) || [cycleKey]).join(', ')}</div>
    <div>Payment date: {formatDate(payment.actual_payment_date || payment.collection_date)}</div>
    <div>Submitted: {formatDateTime(payment.submitted_at)}{payment.submitted_by_user?.full_name ? ` by ${payment.submitted_by_user.full_name}` : ''}</div>
    {payment.status === 'approved' && <><div>Confirmed: {formatDateTime(payment.approved_at)} by {payment.confirmed_by_user?.full_name || 'Legacy confirmer unavailable'}{payment.confirmed_by_user?.role ? ` (${payment.confirmed_by_user.role})` : ''}</div><div>Confirmation reason: {payment.decision_reason || 'Legacy reason unavailable'}</div></>}
    {pending && <div className="font-medium text-amber-700">Awaiting Admin confirmation</div>}
    {payment.status === 'rejected' && <div className="text-red-600">Rejected: {formatDateTime(payment.rejected_at)}</div>}
    {payment.status === 'reversed' && <div className="text-red-600">Reversed: {formatDateTime(payment.reversed_at)} by {payment.reversed_by_user?.full_name || 'Legacy corrector unavailable'}{payment.reversed_by_user?.role ? ` (${payment.reversed_by_user.role})` : ''} · Reason: {payment.reversal_reason || 'Legacy reason unavailable'}</div>}
    {(payment.payment_method || payment.reference_number) && <div className="capitalize">{payment.payment_method || 'Payment'}{payment.reference_number ? ` · Ref ${payment.reference_number}` : ''}</div>}
  </div>;
}

export default function MyWallet({ currentUser, walletData, onRefresh }: MyWalletProps) {
  const [showSubmitModal, setShowSubmitModal] = useState(false);
  const [showArrears, setShowArrears] = useState(false);
  const [showCredit, setShowCredit] = useState(false);
  const [ledgerFilter, setLedgerFilter] = useState('all');
  const [allocationDraft, setAllocationDraft] = useState<Record<string, string>>({});
  const [paymentKind, setPaymentKind] = useState<'arrears' | 'current'>('current');
  const [successMessage, setSuccessMessage] = useState('');
  const [showNonWorkingModal, setShowNonWorkingModal] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState('');
  const [paymentForm, setPaymentForm] = useState({
    amount: '',
    collection_date: new Date().toISOString().slice(0, 10),
    payment_method: 'cash' as PaymentMethod,
    reference_number: '',
    notes: '',
    idempotency_key: crypto.randomUUID(),
  });
  const [nonWorkingForm, setNonWorkingForm] = useState({
    selection_type: 'single_day' as 'single_day' | 'multiple_days' | 'date_range' | 'whole_week',
    start_date: new Date().toISOString().slice(0, 10),
    end_date: new Date().toISOString().slice(0, 10),
    affected_dates: [] as string[],
    next_affected_date: new Date().toISOString().slice(0, 10),
    reason_code: 'sick_health',
    explanation: '',
    requested_action: 'reduction' as 'reduction' | 'full_exemption',
    attachment_url: '',
    idempotency_key: crypto.randomUUID(),
  });

  const hasLedger = Boolean(walletData?.ledger_entries?.length);
  const weeklyCycle = walletData?.weekly_cycle || null;
  const weeklyHistory = walletData?.weekly_history || [];
  const canSubmitPayment = Boolean(walletData?.active_assignment_id);
  const outstandingWeeks = useMemo(
    () => [...weeklyHistory].filter((week) => (week.outstanding ?? week.outstanding_balance) > 0).sort((a, b) => a.week_start.localeCompare(b.week_start)),
    [weeklyHistory],
  );
  const overdueWeeks = useMemo(() => outstandingWeeks.filter((week) => week.is_overdue), [outstandingWeeks]);
  const filteredWeeks = useMemo(() => weeklyHistory.filter((week) => {
    const outstanding = week.outstanding ?? week.outstanding_balance;
    if (ledgerFilter === 'unpaid') return outstanding > 0;
    if (ledgerFilter === 'overdue') return Boolean(week.is_overdue && outstanding > 0);
    if (ledgerFilter === 'part_paid') return Boolean(week.is_partial);
    if (ledgerFilter === 'paid_late') return week.payment_status === 'paid_late';
    if (ledgerFilter === 'paid') return ['paid', 'paid_late'].includes(week.payment_status || '');
    if (ledgerFilter === 'excused') return week.payment_status === 'excused_no_payment_due' || week.is_waived;
    return true;
  }), [ledgerFilter, weeklyHistory]);

  useEffect(() => {
    if (!canSubmitPayment) {
      return;
    }
    if (peekDriverQuickActionIntent() !== 'submit_collection') {
      return;
    }
    clearDriverQuickActionIntent();
    setShowSubmitModal(true);
  }, [canSubmitPayment]);

  const collectionHistory = useMemo(
    () =>
      weeklyHistory.flatMap((cycle) =>
        cycle.payments
          .filter((payment) => payment.amount > 0)
          .map((payment) => ({
            cycleKey: cycle.cycle_key,
            deadline: cycle.payment_deadline,
            ...payment,
          })),
      ),
    [weeklyHistory],
  );

  const summary = {
    weeklyTarget: weeklyCycle?.final_due ?? walletData?.remittance_agreement?.weekly_amount ?? walletData?.weekly_target ?? 0,
    submittedTotal: weeklyCycle?.submitted_total ?? 0,
    approvedTotal: weeklyCycle?.approved_total ?? walletData?.total_credits ?? 0,
    outstandingBalance: walletData?.financial_position?.outstanding ?? walletData?.outstanding_balance ?? 0,
    currentRemaining: weeklyCycle?.outstanding ?? weeklyCycle?.outstanding_balance ?? 0,
    achievementPercentage: weeklyCycle?.achievement_percentage ?? walletData?.achievement_percentage ?? 0,
    totalDebits: walletData?.total_debits ?? 0,
    deadline: weeklyCycle?.payment_deadline ?? null,
    cycleStatus: weeklyCycle?.status ?? 'open',
    arrears: walletData?.arrears ?? walletData?.financial_position?.arrears ?? 0,
    credit: walletData?.credit ?? walletData?.financial_position?.applicable_credit ?? 0,
  };

  const suggestAllocation = (amount: number, weeks = outstandingWeeks) => {
    let remaining = Math.max(amount || 0, 0);
    const next: Record<string, string> = {};
    for (const week of weeks) {
      const balance = week.outstanding ?? week.outstanding_balance;
      const allocated = Math.min(balance, remaining);
      if (allocated > 0) next[week.cycle_key] = allocated.toFixed(2);
      remaining = Math.max(remaining - allocated, 0);
    }
    setAllocationDraft(next);
  };

  const openPayment = (kind: 'arrears' | 'current') => {
    const weeks = kind === 'arrears' ? overdueWeeks : weeklyCycle ? [weeklyCycle] : [];
    const amount = weeks.reduce((total, week) => total + (week.outstanding ?? week.outstanding_balance), 0);
    setPaymentForm((current) => ({ ...current, amount: amount ? String(amount) : '' }));
    setPaymentKind(kind);
    suggestAllocation(amount, weeks);
    setFormError('');
    setShowSubmitModal(true);
  };

  const closeModal = () => {
    setShowSubmitModal(false);
    setFormError('');
    setAllocationDraft({});
    setPaymentForm({
      amount: '',
      collection_date: new Date().toISOString().slice(0, 10),
      payment_method: 'cash',
      reference_number: '',
      notes: '',
      idempotency_key: crypto.randomUUID(),
    });
  };

  const handleSubmitNonWorking = async (event: React.FormEvent) => {
    event.preventDefault();
    setIsSubmitting(true);
    setFormError('');
    try {
      await submitDriverNonWorkingRequest({
        selection_type: nonWorkingForm.selection_type,
        start_date: nonWorkingForm.start_date,
        end_date: ['single_day', 'whole_week'].includes(nonWorkingForm.selection_type) ? nonWorkingForm.start_date : nonWorkingForm.end_date,
        affected_dates: nonWorkingForm.selection_type === 'multiple_days' ? nonWorkingForm.affected_dates : undefined,
        reason_code: nonWorkingForm.reason_code,
        explanation: nonWorkingForm.explanation,
        requested_action: nonWorkingForm.requested_action,
        attachments: nonWorkingForm.attachment_url.trim() ? [nonWorkingForm.attachment_url.trim()] : [],
        idempotency_key: nonWorkingForm.idempotency_key,
      });
      await onRefresh();
      setShowNonWorkingModal(false);
      const today = new Date().toISOString().slice(0, 10);
      setNonWorkingForm({ selection_type: 'single_day', start_date: today, end_date: today, affected_dates: [], next_affected_date: today, reason_code: 'sick_health', explanation: '', requested_action: 'reduction', attachment_url: '', idempotency_key: crypto.randomUUID() });
    } catch (error) {
      setFormError(error instanceof ApiRequestError ? error.message : 'Unable to submit the non-working request right now.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSubmitPayment = async (event: React.FormEvent) => {
    event.preventDefault();
    setIsSubmitting(true);
    setFormError('');

    try {
      await submitDriverPayment({
        amount: Number(paymentForm.amount),
        collection_date: paymentForm.collection_date,
        payment_method: paymentForm.payment_method,
        reference_number: paymentForm.reference_number,
        notes: paymentForm.notes,
        idempotency_key: paymentForm.idempotency_key,
        remittance_allocations: Object.entries(allocationDraft)
          .map(([cycle_key, amount]) => ({ cycle_key, amount: Number(amount) }))
          .filter((item) => item.amount > 0),
      });
      await onRefresh();
      setSuccessMessage('Payment submitted for confirmation. Balances will change only after Admin confirms it.');
      closeModal();
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setFormError(error.message);
      } else {
        setFormError('Unable to submit payment right now.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="max-w-full space-y-4 overflow-x-hidden p-4 sm:space-y-6 sm:p-6">
      <div className="max-w-full rounded-lg bg-gradient-to-r from-[#0F172A] to-[#1e293b] p-4 text-white sm:p-6">
        <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
          <div className="min-w-0">
            <h1 className="mb-2 text-2xl font-semibold">Weekly Remittance</h1>
            <p className="max-w-full text-sm text-slate-300 sm:text-base">
              Current obligation, confirmed receipts, arrears and credit for {currentUser?.full_name || 'your account'}.
            </p>
          </div>
          <div className="flex w-full flex-col gap-2 sm:flex-row md:w-auto">
            <button onClick={() => setShowNonWorkingModal(true)} disabled={!canSubmitPayment} className="w-full rounded-lg border border-white/40 px-4 py-2.5 text-sm font-medium text-white hover:bg-white/10 disabled:opacity-60 md:w-auto">Report Work Exception</button>
            <button onClick={() => openPayment('current')} disabled={!canSubmitPayment} className="w-full rounded-lg bg-white px-4 py-2.5 text-sm font-medium text-[#0F172A] transition-all hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-60 md:w-auto">Pay Current Week</button>
          </div>
        </div>
      </div>

      {successMessage && <div className="rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-800">{successMessage}</div>}

      <div className="grid grid-cols-3 gap-2 sm:gap-4">
        {[
          { label: 'Current Due', value: summary.currentRemaining, icon: TrendingUp, iconClass: 'bg-red-100 text-red-600', valueClass: 'text-red-600' },
          { label: 'Arrears', value: summary.arrears, icon: CreditCard, iconClass: 'bg-amber-100 text-amber-600', valueClass: 'text-amber-600' },
          { label: 'Available Credit', value: summary.credit, icon: Wallet, iconClass: 'bg-green-100 text-green-600', valueClass: 'text-green-600' },
        ].map((stat) => {
          const Icon = stat.icon;
          return <div key={stat.label} className="min-w-0 rounded-lg border border-gray-200 bg-white p-2.5 sm:p-5"><div className={`mb-2 flex h-8 w-8 items-center justify-center rounded-lg sm:h-10 sm:w-10 ${stat.iconClass}`}><Icon className="h-4 w-4 sm:h-5 sm:w-5" /></div><div className={`mb-1 break-words text-sm font-semibold leading-tight [overflow-wrap:anywhere] min-[380px]:text-base sm:text-2xl ${stat.valueClass}`}>{formatCurrency(stat.value)}</div><div className="line-clamp-2 text-[11px] leading-tight text-gray-600 sm:text-sm">{stat.label}</div></div>;
        })}
      </div>

      {(summary.arrears > 0 || summary.credit > 0) && <div className="flex flex-wrap gap-2 rounded-lg border border-gray-200 bg-white p-2 sm:p-3">
        {summary.arrears > 0 && <><button onClick={() => setShowArrears((value) => !value)} className="min-h-11 flex-1 rounded-lg border border-amber-300 px-3 text-sm font-medium text-amber-800 sm:flex-none">{showArrears ? 'Hide Arrears Breakdown' : 'View Arrears Breakdown'}</button><button onClick={() => openPayment('arrears')} disabled={!overdueWeeks.length || isSubmitting} className="min-h-11 flex-1 rounded-lg bg-amber-600 px-3 text-sm font-medium text-white disabled:opacity-50 sm:flex-none">Pay Arrears</button></>}
        {summary.credit > 0 && <button onClick={() => setShowCredit((value) => !value)} className="min-h-11 flex-1 rounded-lg border border-green-300 px-3 text-sm font-medium text-green-800 sm:flex-none">{showCredit ? 'Hide Credit Allocation' : 'View Credit Allocation'}</button>}
      </div>}

      {showArrears && <section className="rounded-lg border border-amber-200 bg-amber-50/40 p-4 sm:p-6">
        <h2 className="text-lg font-semibold text-gray-900">Arrears Breakdown</h2>
        <div className="mt-3 grid grid-cols-3 gap-2 sm:gap-3"><div className="min-w-0 rounded-lg bg-white p-2.5 sm:p-3"><div className="text-[11px] leading-tight text-gray-500 sm:text-xs">Overdue arrears</div><strong className="block break-words text-sm leading-tight text-amber-700 [overflow-wrap:anywhere] sm:text-base">{formatCurrency(summary.arrears)}</strong></div><div className="min-w-0 rounded-lg bg-white p-2.5 sm:p-3"><div className="text-[11px] leading-tight text-gray-500 sm:text-xs">Current week unpaid</div><strong className="block break-words text-sm leading-tight [overflow-wrap:anywhere] sm:text-base">{formatCurrency(walletData?.financial_position?.current_week_unpaid ?? summary.currentRemaining)}</strong></div><div className="min-w-0 rounded-lg bg-white p-2.5 sm:p-3"><div className="text-[11px] leading-tight text-gray-500 sm:text-xs">Total unpaid</div><strong className="block break-words text-sm leading-tight [overflow-wrap:anywhere] sm:text-base">{formatCurrency(walletData?.financial_position?.total_unpaid ?? summary.outstandingBalance)}</strong></div></div>
        <div className="mt-4 space-y-3">{overdueWeeks.map((week) => <article key={week.cycle_key} className="rounded-lg border border-amber-200 bg-white p-4"><div className="flex items-start justify-between gap-3"><div><strong>{week.week_start} to {week.week_end}</strong><div className="text-xs text-gray-500">Effective deadline {week.effective_deadline || week.payment_deadline}</div></div><span className="rounded-full bg-red-100 px-2 py-1 text-xs font-medium uppercase text-red-700">{week.payment_status || week.status}</span></div><div className="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-3"><div>Original<strong className="block">{formatCurrency(week.original_amount ?? week.weekly_target)}</strong></div><div>Adjustment<strong className="block">{formatCurrency(week.approved_adjustment ?? 0)}</strong></div><div>Revised due<strong className="block">{formatCurrency(week.final_due ?? week.weekly_target)}</strong></div><div>Confirmed<strong className="block text-green-700">{formatCurrency(week.confirmed_allocated_payments ?? week.approved_total)}</strong></div><div>Pending<strong className="block text-amber-700">{formatCurrency(week.pending_total ?? 0)}</strong></div><div>Remaining<strong className="block text-red-700">{formatCurrency(week.outstanding ?? week.outstanding_balance)}</strong></div></div></article>)}{!overdueWeeks.length && <div className="rounded-lg bg-white p-4 text-sm text-gray-600">No past-due unpaid weeks.</div>}</div>
      </section>}

      {showCredit && <section className="rounded-lg border border-green-200 bg-green-50/40 p-4 sm:p-6"><h2 className="text-lg font-semibold text-gray-900">Confirmed Unallocated Credit</h2><p className="mt-1 text-sm text-gray-600">This is confirmed money not currently allocated to a weekly obligation. Admin can apply historical bulk credit to arrears.</p><div className="mt-3 space-y-2">{walletData?.credit_payments?.map((payment) => <div key={payment.id || payment.collection_date || ''} className="rounded-lg bg-white p-3 text-sm"><strong>{formatCurrency(payment.unallocated_amount)}</strong> unallocated from {formatCurrency(payment.amount)} paid {formatDate(payment.actual_payment_date || payment.collection_date)}<div className="text-xs text-gray-500">Submitted {payment.submitted_at ? new Date(payment.submitted_at).toLocaleString() : 'legacy time unavailable'} · Confirmed {payment.approved_at ? new Date(payment.approved_at).toLocaleString() : 'unknown'}</div></div>)}{!walletData?.credit_payments?.length && <div className="rounded-lg bg-white p-3 text-sm text-gray-600">No confirmed unallocated money.</div>}</div></section>}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <h3 className="mb-3 text-lg font-semibold text-gray-900">Current Week</h3>
          <div className="space-y-3 text-sm">
            <div className="flex items-center justify-between gap-4">
              <span className="text-gray-500">Weekly Obligation</span>
              <span className="font-medium text-gray-900">{formatCurrency(summary.weeklyTarget)}</span>
            </div>
            <div className="flex items-center justify-between gap-4">
              <span className="text-gray-500">Deadline</span>
              <span className="font-medium text-gray-900">{formatDate(summary.deadline)}</span>
            </div>
            <div className="flex items-center justify-between gap-4">
              <span className="text-gray-500">Status</span>
              <span className="font-medium capitalize text-gray-900">{summary.cycleStatus}</span>
            </div>
            <div className="flex items-center justify-between gap-4">
              <span className="text-gray-500">Daily Target</span>
              <span className="font-medium text-gray-900">
                {formatCurrency(walletData?.daily_target || 0)}
              </span>
            </div>
            <div className="flex items-center justify-between gap-4">
              <span className="text-gray-500">Achievement</span>
              <span className="font-medium text-gray-900">
                {summary.achievementPercentage.toFixed(2)}%
              </span>
            </div>
            <div className="flex items-center justify-between gap-4">
              <span className="text-gray-500">All Weeks Outstanding</span>
              <span className="font-medium text-red-700">{formatCurrency(summary.outstandingBalance)}</span>
            </div>
          </div>
        </div>

        <div className="rounded-lg border border-gray-200 bg-white p-6 lg:col-span-2">
          <h3 className="mb-3 text-lg font-semibold text-gray-900">Payment History</h3>
          {collectionHistory.length === 0 ? (
            <div className="rounded-lg bg-gray-50 px-4 py-8 text-center text-sm text-gray-500">
              No payment submissions yet for this assignment.
            </div>
          ) : (
            <div className="space-y-3">
              {collectionHistory.slice(0, 6).map((entry, index) => (
                <div
                  key={`${entry.id || entry.collection_date || 'payment'}-${index}`}
                  className="flex items-center justify-between gap-4 rounded-lg bg-gray-50 p-4"
                >
                  <div>
                    <div className="text-sm font-medium text-gray-900 capitalize">
                      {entry.payment_method || 'payment'} submission
                    </div>
                    <div className="text-xs font-medium text-gray-700">{paymentConfirmationLabel(entry.status)}{entry.is_late ? ' · Paid late' : ''}</div>
                    <div className="mt-1 text-xs text-gray-500">Covers {entry.cycleKey}{entry.allocated_amount ? ` · ${formatCurrency(entry.allocated_amount)}` : ''}</div>
                    <div className="mt-1 text-xs text-gray-500">Payment date: {formatDate(entry.actual_payment_date || entry.collection_date)}</div>
                    <div className="text-xs text-gray-500">Submitted by: {entry.submitted_by_user?.full_name || 'Legacy submitter unavailable'} · {formatDateTime(entry.submitted_at)}</div>
                    {entry.status === 'approved' && <div className="text-xs text-gray-500">Confirmed by: {entry.confirmed_by_user?.full_name || 'Legacy confirmer unavailable'}{entry.confirmed_by_user?.role ? ` (${entry.confirmed_by_user.role})` : ''} · {formatDateTime(entry.approved_at)}</div>}
                    {['pending', 'submitted', 'received'].includes(entry.status) && <div className="mt-1 text-xs font-medium text-amber-700">Awaiting Admin confirmation</div>}
                    {entry.status === 'rejected' && <div className="text-xs text-red-600">Rejected: {formatDateTime(entry.rejected_at)}</div>}
                    {entry.status === 'reversed' && <div className="text-xs text-red-600">Reversed: {formatDateTime(entry.reversed_at)}</div>}
                    {(entry.payment_method || entry.reference_number) && <div className="mt-1 text-xs capitalize text-gray-500">{entry.payment_method || 'Payment'}{entry.reference_number ? ` · Ref ${entry.reference_number}` : ''}</div>}
                    {entry.rejection_reason && (
                      <div className="mt-1 text-xs text-red-600">{entry.rejection_reason}</div>
                    )}
                  </div>
                  <div className="text-sm font-semibold text-[#0F172A]">
                    {formatCurrency(entry.amount)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="rounded-lg border border-gray-200 bg-white p-4 sm:p-6">
        <h3 className="text-lg font-semibold text-gray-900">Work Exception Requests</h3>
        <p className="mt-1 text-sm text-gray-500">Track review status and the final financial decision.</p>
        <div className="mt-4 space-y-3">
          {(walletData?.work_exception_requests || []).map((request) => <article key={request.id} className="rounded-lg border border-gray-200 p-4"><div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between"><div><div className="font-medium text-gray-900">{request.start_date} to {request.end_date}</div><div className="mt-1 text-sm capitalize text-gray-600">{request.reason_code.replaceAll('_', ' ')}{request.explanation ? ` — ${request.explanation}` : ''}</div><div className="mt-1 text-xs text-gray-500">{request.affected_working_days || request.affected_dates?.length || 0} affected day(s) · Requested: {request.requested_action.replaceAll('_', ' ')}</div></div><span className="h-fit w-fit rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium uppercase">{request.request_status.replaceAll('_', ' ')}</span></div>{['approved', 'partially_approved', 'declined'].includes(request.request_status) && <div className="mt-3 grid grid-cols-2 gap-2 rounded-lg bg-slate-50 p-3 text-sm sm:grid-cols-4"><div><span className="block text-xs text-gray-500">Original</span>{formatCurrency(Number(request.original_amount || 0))}</div><div><span className="block text-xs text-gray-500">Adjustment</span>-{formatCurrency(Number(request.approved_adjustment || 0))}</div><div><span className="block text-xs text-gray-500">Final due</span>{formatCurrency(Number(request.revised_amount_due ?? request.original_amount ?? 0))}</div><div><span className="block text-xs text-gray-500">Decision</span>{request.decision_reason || '—'}</div></div>}</article>)}
          {!walletData?.work_exception_requests?.length && <div className="rounded-lg bg-gray-50 px-4 py-6 text-center text-sm text-gray-500">No work-exception requests submitted.</div>}
        </div>
      </div>

      <div className="rounded-lg border border-gray-200 bg-white">
        <div className="border-b border-gray-200 p-6">
          <div className="flex items-center gap-3">
            <Receipt className="h-5 w-5 text-gray-600" />
            <h3 className="text-lg font-semibold text-gray-900">Weekly History</h3>
          </div>
          <div className="mt-4 flex flex-wrap gap-2">{[
            ['all', 'All'], ['unpaid', 'Unpaid'], ['overdue', 'Overdue'], ['part_paid', 'Part-paid'],
            ['paid_late', 'Paid late'], ['paid', 'Paid'], ['excused', 'Excused'],
          ].map(([value, label]) => <button key={value} onClick={() => setLedgerFilter(value)} className={`min-h-10 rounded-lg border px-3 text-sm ${ledgerFilter === value ? 'border-blue-600 bg-blue-600 text-white' : 'border-gray-300 bg-white text-gray-700'}`}>{label}</button>)}</div>
        </div>
        {filteredWeeks.length === 0 ? (
          <div className="px-6 py-12 text-center text-gray-500">
            No weekly payment cycles found yet.
          </div>
        ) : (
          <>
          <div className="space-y-3 p-4 md:hidden">
            {filteredWeeks.filter((cycle) => cycle.exception_reason).map((cycle) => <div key={`${cycle.cycle_key}-reason`} className="rounded-lg bg-blue-50 px-3 py-2 text-xs capitalize text-blue-800"><strong>{cycle.week_start}:</strong> {cycle.exception_reason?.replaceAll('_', ' ')}{cycle.exception_explanation ? ` - ${cycle.exception_explanation}` : ''}</div>)}
            {filteredWeeks.map((cycle) => <article key={cycle.cycle_key} className={`rounded-lg border p-4 ${cycle.is_overdue && (cycle.outstanding ?? cycle.outstanding_balance) > 0 ? 'border-red-300 bg-red-50/40' : 'border-gray-200'}`}><div className="flex items-start justify-between gap-3"><div><div className="text-sm font-medium text-gray-900">{cycle.week_start} to {cycle.week_end}</div><div className="text-xs text-gray-500">Due {cycle.effective_deadline || cycle.payment_deadline}</div></div><span className="rounded-full bg-gray-100 px-2 py-1 text-xs capitalize">{cycle.payment_status_label || (cycle.payment_status || cycle.status).replaceAll('_', ' ')}</span></div><div className="mt-3 grid grid-cols-2 gap-3 text-sm"><div><span className="block text-xs text-gray-500">Original</span>{formatCurrency(cycle.original_amount ?? cycle.weekly_target)}</div><div><span className="block text-xs text-gray-500">Adjustment</span>{formatCurrency(cycle.approved_adjustment ?? 0)}</div><div><span className="block text-xs text-gray-500">Revised Due</span>{formatCurrency(cycle.final_due ?? cycle.weekly_target)}</div><div><span className="block text-xs text-gray-500">Confirmed</span><span className="text-green-700">{formatCurrency(cycle.confirmed_allocated_payments ?? cycle.approved_total)}</span></div><div><span className="block text-xs text-gray-500">Pending</span><span className="text-amber-700">{formatCurrency(cycle.pending_total ?? 0)}</span></div><div><span className="block text-xs text-gray-500">Remaining</span><span className="text-red-700">{formatCurrency(cycle.outstanding ?? cycle.outstanding_balance)}</span></div></div>{cycle.payments.map((payment) => <PaymentAuditDetail key={`${payment.id || payment.collection_date || ''}-${cycle.cycle_key}`} payment={payment} cycleKey={cycle.cycle_key} />)}</article>)}
          </div>
          <div className="hidden overflow-x-auto md:block">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Week</th>
                  <th className="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Original</th>
                  <th className="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Adjustment</th>
                  <th className="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Revised Due</th>
                  <th className="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Confirmed</th>
                  <th className="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Pending</th>
                  <th className="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Remaining</th>
                  <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Deadline</th>
                  <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {filteredWeeks.map((cycle) => (
                  <tr key={cycle.cycle_key} className={cycle.is_overdue && (cycle.outstanding ?? cycle.outstanding_balance) > 0 ? 'bg-red-50' : ''}>
                    <td className="px-6 py-4 text-sm text-gray-700">
                      {cycle.week_start} to {cycle.week_end}
                      {cycle.exception_reason && <div className="mt-1 text-xs capitalize text-blue-700">{cycle.exception_reason.replaceAll('_', ' ')}{cycle.exception_explanation ? ` - ${cycle.exception_explanation}` : ''}</div>}
                    </td>
                    <td className="px-6 py-4 text-right text-sm text-gray-900">
                      {formatCurrency(cycle.original_amount ?? cycle.weekly_target)}
                    </td>
                    <td className="px-6 py-4 text-right text-sm text-gray-700">
                      {formatCurrency(cycle.approved_adjustment ?? 0)}
                    </td>
                    <td className="px-6 py-4 text-right text-sm text-gray-900">
                      {formatCurrency(cycle.final_due ?? cycle.weekly_target)}
                    </td>
                    <td className="px-6 py-4 text-right text-sm text-green-700">
                      {formatCurrency(cycle.confirmed_allocated_payments ?? cycle.approved_total)}
                    </td>
                    <td className="px-6 py-4 text-right text-sm text-amber-700">
                      {formatCurrency(cycle.pending_total ?? 0)}
                    </td>
                    <td className="px-6 py-4 text-right text-sm text-red-700">
                      {formatCurrency(cycle.outstanding_balance)}
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-700">{cycle.payment_deadline}</td>
                    <td className="px-6 py-4 text-sm text-gray-700">{cycle.payment_status_label || (cycle.payment_status || cycle.status).replaceAll('_', ' ')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          </>
        )}
      </div>

      <div className="rounded-lg border border-gray-200 bg-white">
        <div className="border-b border-gray-200 p-6">
          <div className="flex items-center gap-3">
            <Calendar className="h-5 w-5 text-gray-600" />
            <h3 className="text-lg font-semibold text-gray-900">Ledger Entries</h3>
          </div>
        </div>

        {!hasLedger ? (
          <div className="px-6 py-12 text-center text-gray-500">
            No wallet activity yet for approved payments.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Date</th>
                  <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Type</th>
                  <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Description</th>
                  <th className="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Debit</th>
                  <th className="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Credit</th>
                  <th className="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Balance After</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {walletData?.ledger_entries.map((entry, index) => (
                  <tr key={`${entry.reference_id || entry.date || 'ledger'}-${index}`}>
                    <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-600">
                      {formatDate(entry.date)}
                    </td>
                    <td className="whitespace-nowrap px-6 py-4 text-sm capitalize text-gray-700">
                      {entry.type}
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-700">{entry.description}</td>
                    <td className="whitespace-nowrap px-6 py-4 text-right text-sm text-red-600">
                      {entry.debit > 0 ? formatCurrency(entry.debit) : '-'}
                    </td>
                    <td className="whitespace-nowrap px-6 py-4 text-right text-sm text-green-600">
                      {entry.credit > 0 ? formatCurrency(entry.credit) : '-'}
                    </td>
                    <td className="whitespace-nowrap px-6 py-4 text-right text-sm font-medium text-gray-900">
                      {formatCurrency(entry.balance_after)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {showSubmitModal && (
        <div className="fixed inset-0 z-50 flex items-end justify-center overflow-hidden bg-black/50 p-0 sm:items-center sm:p-4">
          <div role="dialog" aria-modal="true" aria-labelledby="remittance-payment-title" className="flex h-[95dvh] w-full max-w-2xl flex-col overflow-hidden rounded-t-2xl border border-gray-200 bg-white shadow-2xl sm:h-auto sm:max-h-[85vh] sm:rounded-2xl">
            <div className="sticky top-0 z-10 flex shrink-0 items-start justify-between gap-4 border-b border-gray-200 bg-white px-4 py-3 sm:px-5 sm:py-4">
              <div className="min-w-0">
                <h2 id="remittance-payment-title" className="text-lg font-semibold text-[#0F172A] sm:text-xl">Allocate Weekly Payment</h2>
                <p className="mt-1 text-xs text-gray-500 sm:text-sm">Oldest outstanding weeks are suggested first. You can edit or clear any allocation.</p>
              </div>
              <button type="button" onClick={closeModal} disabled={isSubmitting} aria-label="Close payment modal" className="flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-lg transition-all hover:bg-gray-100 disabled:opacity-50">
                <X className="h-5 w-5 text-gray-500" />
              </button>
            </div>

            <form onSubmit={handleSubmitPayment} className="flex min-h-0 flex-1 flex-col">
              <div className="min-h-0 flex-1 space-y-4 overflow-x-hidden overflow-y-auto overscroll-contain px-4 py-4 sm:px-5 sm:py-5">
                {formError && (
                  <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                    {formError}
                  </div>
                )}

                <div className="rounded-lg border border-blue-100 bg-blue-50 px-3 py-2.5 text-sm text-blue-700 sm:px-4">
                  Deadline: {formatDate(summary.deadline)} / Outstanding: {formatCurrency(summary.outstandingBalance)}
                </div>

                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <div>
                    <label className="mb-1.5 block text-sm font-medium text-gray-700">Amount (GHS)</label>
                    <input
                      type="number"
                      step="0.01"
                      min="0"
                      required
                      value={paymentForm.amount}
                      onChange={(event) => { const amount = event.target.value; setPaymentForm((current) => ({ ...current, amount })); suggestAllocation(Number(amount), paymentKind === 'arrears' ? overdueWeeks : weeklyCycle ? [weeklyCycle] : []); }}
                      className="min-h-11 w-full min-w-0 rounded-lg border border-gray-300 px-4 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                    />
                  </div>
                  <div>
                    <label className="mb-1.5 block text-sm font-medium text-gray-700">Payment Date</label>
                    <input
                      type="date"
                      required
                      value={paymentForm.collection_date}
                      onChange={(event) => setPaymentForm((current) => ({ ...current, collection_date: event.target.value }))}
                      className="min-h-11 w-full min-w-0 rounded-lg border border-gray-300 px-4 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                    />
                  </div>
                </div>

                <fieldset className="min-w-0">
                  <legend className="text-sm font-medium text-gray-700">Weeks covered</legend>
                  <div className="mt-2 space-y-2">
                    {outstandingWeeks.map((week) => (
                      <div key={week.cycle_key} className="min-w-0 rounded-lg border border-gray-200 p-3">
                        <div className="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-[minmax(0,1fr)_8rem_auto] sm:items-center">
                          <div className="min-w-0 text-sm">
                            <div className="font-medium text-gray-900">{week.week_start} to {week.week_end}</div>
                            <div className="mt-0.5 text-xs text-gray-500">Remaining {formatCurrency(week.outstanding ?? week.outstanding_balance)}</div>
                          </div>
                          <label className="block min-w-0 text-xs font-medium text-gray-600">
                            Allocation
                            <input aria-label={`Allocation for ${week.cycle_key}`} type="number" min="0" step="0.01" max={week.outstanding ?? week.outstanding_balance} value={allocationDraft[week.cycle_key] || ''} onChange={(event) => setAllocationDraft((current) => ({ ...current, [week.cycle_key]: event.target.value }))} className="mt-1 min-h-11 w-full min-w-0 rounded-lg border border-gray-300 px-3 text-sm" />
                          </label>
                          <button type="button" onClick={() => setAllocationDraft((current) => ({ ...current, [week.cycle_key]: '' }))} disabled={!allocationDraft[week.cycle_key]} className="min-h-11 rounded-lg border border-gray-300 px-3 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40 sm:self-end">Clear</button>
                        </div>
                      </div>
                    ))}
                  </div>
                </fieldset>

                <div>
                  <label className="mb-1.5 block text-sm font-medium text-gray-700">Payment Method</label>
                  <select
                    value={paymentForm.payment_method}
                    onChange={(event) =>
                      setPaymentForm((current) => ({
                        ...current,
                        payment_method: event.target.value as PaymentMethod,
                      }))
                    }
                    className="min-h-11 w-full min-w-0 rounded-lg border border-gray-300 px-4 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                  >
                    <option value="cash">Cash</option>
                    <option value="momo">MoMo</option>
                    <option value="bank">Bank</option>
                    <option value="other">Other</option>
                  </select>
                </div>

                <div>
                  <label className="mb-1.5 block text-sm font-medium text-gray-700">Reference Number</label>
                  <input
                    value={paymentForm.reference_number}
                    onChange={(event) => setPaymentForm((current) => ({ ...current, reference_number: event.target.value }))}
                    className="min-h-11 w-full min-w-0 rounded-lg border border-gray-300 px-4 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                    placeholder="Optional transfer or receipt reference"
                  />
                </div>

                <div>
                  <label className="mb-1.5 block text-sm font-medium text-gray-700">Notes</label>
                  <textarea
                    value={paymentForm.notes}
                    onChange={(event) => setPaymentForm((current) => ({ ...current, notes: event.target.value }))}
                    className="min-h-24 w-full min-w-0 resize-y rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                    placeholder="Optional payment note"
                  />
                </div>
              </div>

              <div className="sticky bottom-0 z-10 shrink-0 border-t border-gray-200 bg-white px-4 pb-[max(1rem,env(safe-area-inset-bottom))] pt-3 sm:px-5 sm:pb-4">
                <div className="mb-3 flex items-center justify-between gap-3 text-sm">
                  <span className="text-gray-600">Allocated total</span>
                  <strong className="text-gray-900">{formatCurrency(Object.values(allocationDraft).reduce((total, value) => total + (Number(value) || 0), 0))}</strong>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <button
                    type="button"
                    onClick={closeModal}
                    disabled={isSubmitting}
                    className="min-h-12 rounded-lg border border-gray-300 px-4 font-medium text-gray-700 transition-all hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={isSubmitting}
                    className="flex min-h-12 items-center justify-center gap-2 rounded-lg bg-[#2563EB] px-4 font-medium text-white transition-all hover:bg-[#1d4ed8] disabled:cursor-not-allowed disabled:opacity-70"
                  >
                    {isSubmitting && <Loader2 className="h-4 w-4 animate-spin" />}
                    {isSubmitting ? 'Submitting...' : 'Submit Payment'}
                  </button>
                </div>
              </div>
            </form>
          </div>
        </div>
      )}

      {showNonWorkingModal && (
        <div className="fixed inset-0 z-50 flex items-end justify-center overflow-hidden bg-black/50 sm:items-center sm:p-4">
          <div role="dialog" aria-modal="true" aria-labelledby="work-exception-title" className="flex max-h-[95dvh] w-full max-w-2xl flex-col overflow-hidden rounded-t-2xl border border-gray-200 bg-white shadow-2xl sm:max-h-[85vh] sm:rounded-2xl">
            <div className="flex shrink-0 items-start justify-between gap-3 border-b border-gray-200 px-4 py-3 sm:px-5 sm:py-4">
              <div className="min-w-0"><h2 id="work-exception-title" className="text-lg font-semibold text-[#0F172A] sm:text-xl">Report Work Exception</h2><p className="mt-1 text-xs text-gray-500 sm:text-sm">Submitting does not change the amount due. Only an Admin decision can revise it.</p></div>
              <button type="button" aria-label="Close work exception" onClick={() => { setShowNonWorkingModal(false); setFormError(''); }} className="flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-lg hover:bg-gray-100"><X className="h-5 w-5 text-gray-500" /></button>
            </div>
            <form onSubmit={handleSubmitNonWorking} className="flex min-h-0 flex-1 flex-col">
              <div className="min-h-0 flex-1 space-y-3 overflow-x-hidden overflow-y-auto overscroll-contain px-4 py-4 sm:space-y-4 sm:px-5">
              {formError && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{formError}</div>}
              <label className="block text-sm font-medium text-gray-700">Affected date selection<select value={nonWorkingForm.selection_type} onChange={(event) => setNonWorkingForm((value) => ({ ...value, selection_type: event.target.value as typeof value.selection_type }))} className="mt-2 min-h-11 w-full rounded-lg border border-gray-300 px-3"><option value="single_day">One day</option><option value="multiple_days">Multiple specific days</option><option value="date_range">Date range</option><option value="whole_week">Whole week</option></select></label>
              {nonWorkingForm.selection_type === 'multiple_days' ? <div className="rounded-lg border border-gray-200 p-3"><label className="text-sm font-medium text-gray-700">Add affected date<div className="mt-2 flex gap-2"><input type="date" value={nonWorkingForm.next_affected_date} onChange={(event) => setNonWorkingForm((value) => ({ ...value, next_affected_date: event.target.value }))} className="min-h-11 min-w-0 flex-1 rounded-lg border border-gray-300 px-3" /><button type="button" onClick={() => setNonWorkingForm((value) => ({ ...value, affected_dates: [...new Set([...value.affected_dates, value.next_affected_date])].sort() }))} className="min-h-11 rounded-lg border px-3">Add</button></div></label><div className="mt-3 flex flex-wrap gap-2">{nonWorkingForm.affected_dates.map((date) => <button type="button" key={date} onClick={() => setNonWorkingForm((value) => ({ ...value, affected_dates: value.affected_dates.filter((item) => item !== date) }))} className="rounded-full bg-blue-50 px-3 py-1 text-xs text-blue-800">{date} ×</button>)}</div></div> : <div className="grid grid-cols-1 gap-4 sm:grid-cols-2"><label className="text-sm font-medium text-gray-700">{nonWorkingForm.selection_type === 'whole_week' ? 'Week containing' : 'From'}<input type="date" required value={nonWorkingForm.start_date} onChange={(event) => setNonWorkingForm((value) => ({ ...value, start_date: event.target.value }))} className="mt-2 min-h-11 w-full rounded-lg border border-gray-300 px-3" /></label>{nonWorkingForm.selection_type === 'date_range' && <label className="text-sm font-medium text-gray-700">To<input type="date" required value={nonWorkingForm.end_date} min={nonWorkingForm.start_date} onChange={(event) => setNonWorkingForm((value) => ({ ...value, end_date: event.target.value }))} className="mt-2 min-h-11 w-full rounded-lg border border-gray-300 px-3" /></label>}</div>}
              <label className="block text-sm font-medium text-gray-700">Reason<select value={nonWorkingForm.reason_code} onChange={(event) => setNonWorkingForm((value) => ({ ...value, reason_code: event.target.value }))} className="mt-2 min-h-11 w-full rounded-lg border border-gray-300 px-3"><option value="sick_health">Sick / Health</option><option value="emergency_personal">Emergency / Personal</option><option value="vehicle_issue">Vehicle Issue</option><option value="company_assignment">Company Assignment</option><option value="low_work_market_issue">Low Work / Market Issue</option><option value="external_issue">External Issue</option><option value="other">Other</option></select></label>
              <label className="block text-sm font-medium text-gray-700">Explanation<textarea required={nonWorkingForm.reason_code === 'other'} value={nonWorkingForm.explanation} onChange={(event) => setNonWorkingForm((value) => ({ ...value, explanation: event.target.value }))} className="mt-2 min-h-24 w-full rounded-lg border border-gray-300 px-3 py-2.5" placeholder="Briefly explain what prevented work" /></label>
              <label className="block text-sm font-medium text-gray-700">Requested action<select value={nonWorkingForm.requested_action} onChange={(event) => setNonWorkingForm((value) => ({ ...value, requested_action: event.target.value as typeof value.requested_action }))} className="mt-2 min-h-11 w-full rounded-lg border border-gray-300 px-3"><option value="reduction">Reduced amount</option><option value="full_exemption">Full exemption</option></select></label>
              <label className="block text-sm font-medium text-gray-700">Optional attachment link<input type="url" value={nonWorkingForm.attachment_url} onChange={(event) => setNonWorkingForm((value) => ({ ...value, attachment_url: event.target.value }))} className="mt-2 min-h-11 w-full rounded-lg border border-gray-300 px-3" placeholder="https://…" /></label>
              </div>
              <div className="sticky bottom-0 shrink-0 border-t border-gray-200 bg-white px-4 pb-[max(1rem,env(safe-area-inset-bottom))] pt-3 sm:px-5 sm:pb-4"><div className="grid grid-cols-2 gap-3"><button type="button" disabled={isSubmitting} onClick={() => setShowNonWorkingModal(false)} className="min-h-12 rounded-lg border px-4 font-medium disabled:opacity-50">Cancel</button><button disabled={isSubmitting || (nonWorkingForm.selection_type === 'multiple_days' && nonWorkingForm.affected_dates.length < 2)} className="min-h-12 rounded-lg bg-[#2563EB] px-4 font-medium text-white disabled:opacity-60">{isSubmitting ? 'Submitting...' : 'Submit'}</button></div></div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
