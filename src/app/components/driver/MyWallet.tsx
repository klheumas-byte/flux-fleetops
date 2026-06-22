import { useMemo, useState } from 'react';
import {
  Calendar,
  CreditCard,
  Loader2,
  Receipt,
  Target,
  TrendingUp,
  Wallet,
  X,
} from 'lucide-react';
import type { SessionUser } from '../../lib/auth-session';
import { submitDriverPayment, type DriverWalletData } from '../../lib/driver-api';
import { ApiRequestError } from '../../lib/api';

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

export default function MyWallet({ currentUser, walletData, onRefresh }: MyWalletProps) {
  const [showSubmitModal, setShowSubmitModal] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState('');
  const [paymentForm, setPaymentForm] = useState({
    amount: '',
    collection_date: new Date().toISOString().slice(0, 10),
    payment_method: 'cash' as PaymentMethod,
    reference_number: '',
    notes: '',
  });

  const hasLedger = Boolean(walletData?.ledger_entries?.length);
  const weeklyCycle = walletData?.weekly_cycle || null;
  const weeklyHistory = walletData?.weekly_history || [];
  const canSubmitPayment = Boolean(walletData?.active_assignment_id);

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
    weeklyTarget: weeklyCycle?.weekly_target ?? walletData?.weekly_target ?? 0,
    submittedTotal: weeklyCycle?.submitted_total ?? 0,
    approvedTotal: weeklyCycle?.approved_total ?? walletData?.total_credits ?? 0,
    outstandingBalance: weeklyCycle?.outstanding_balance ?? walletData?.outstanding_balance ?? 0,
    achievementPercentage: weeklyCycle?.achievement_percentage ?? walletData?.achievement_percentage ?? 0,
    totalDebits: walletData?.total_debits ?? 0,
    deadline: weeklyCycle?.payment_deadline ?? null,
    cycleStatus: weeklyCycle?.status ?? 'open',
  };

  const closeModal = () => {
    setShowSubmitModal(false);
    setFormError('');
    setPaymentForm({
      amount: '',
      collection_date: new Date().toISOString().slice(0, 10),
      payment_method: 'cash',
      reference_number: '',
      notes: '',
    });
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
      });
      await onRefresh();
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
    <div className="max-w-full space-y-6 overflow-x-hidden p-4 sm:p-6">
      <div className="max-w-full rounded-lg bg-gradient-to-r from-[#0F172A] to-[#1e293b] p-5 text-white sm:p-6">
        <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
          <div className="min-w-0">
            <h1 className="mb-2 text-2xl font-semibold">My Wallet</h1>
            <p className="max-w-full text-sm text-slate-300 sm:text-base">
              Weekly payment cycle and wallet summary for {currentUser?.full_name || 'your account'}.
            </p>
          </div>
          <button
            onClick={() => setShowSubmitModal(true)}
            disabled={!canSubmitPayment}
            className="w-full rounded-lg bg-white px-4 py-2.5 text-sm font-medium text-[#0F172A] transition-all hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-60 md:w-auto"
          >
            Submit Payment
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:gap-6 md:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-blue-100">
            <Target className="h-6 w-6 text-blue-600" />
          </div>
          <div className="mb-2 break-words text-3xl font-semibold text-gray-900">
            {formatCurrency(summary.weeklyTarget)}
          </div>
          <div className="text-sm text-gray-600">Weekly Target</div>
        </div>

        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-amber-100">
            <CreditCard className="h-6 w-6 text-amber-600" />
          </div>
          <div className="mb-2 break-words text-3xl font-semibold text-amber-600">
            {formatCurrency(summary.submittedTotal)}
          </div>
          <div className="text-sm text-gray-600">Submitted Total</div>
        </div>

        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-green-100">
            <Wallet className="h-6 w-6 text-green-600" />
          </div>
          <div className="mb-2 break-words text-3xl font-semibold text-green-600">
            {formatCurrency(summary.approvedTotal)}
          </div>
          <div className="text-sm text-gray-600">Approved Total</div>
        </div>

        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-red-100">
            <TrendingUp className="h-6 w-6 text-red-600" />
          </div>
          <div className="mb-2 break-words text-3xl font-semibold text-red-600">
            {formatCurrency(summary.outstandingBalance)}
          </div>
          <div className="text-sm text-gray-600">Outstanding Balance</div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <h3 className="mb-3 text-lg font-semibold text-gray-900">Current Week</h3>
          <div className="space-y-3 text-sm">
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
                    <div className="text-xs text-gray-500">
                      {formatDate(entry.collection_date)} / {entry.status}
                      {entry.is_late ? ' / Late' : ''}
                    </div>
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

      <div className="rounded-lg border border-gray-200 bg-white">
        <div className="border-b border-gray-200 p-6">
          <div className="flex items-center gap-3">
            <Receipt className="h-5 w-5 text-gray-600" />
            <h3 className="text-lg font-semibold text-gray-900">Weekly History</h3>
          </div>
        </div>
        {weeklyHistory.length === 0 ? (
          <div className="px-6 py-12 text-center text-gray-500">
            No weekly payment cycles found yet.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Week</th>
                  <th className="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Target</th>
                  <th className="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Submitted</th>
                  <th className="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Approved</th>
                  <th className="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Outstanding</th>
                  <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Deadline</th>
                  <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {weeklyHistory.map((cycle) => (
                  <tr key={cycle.cycle_key}>
                    <td className="px-6 py-4 text-sm text-gray-700">
                      {cycle.week_start} to {cycle.week_end}
                    </td>
                    <td className="px-6 py-4 text-right text-sm text-gray-900">
                      {formatCurrency(cycle.weekly_target)}
                    </td>
                    <td className="px-6 py-4 text-right text-sm text-amber-700">
                      {formatCurrency(cycle.submitted_total)}
                    </td>
                    <td className="px-6 py-4 text-right text-sm text-green-700">
                      {formatCurrency(cycle.approved_total)}
                    </td>
                    <td className="px-6 py-4 text-right text-sm text-red-700">
                      {formatCurrency(cycle.outstanding_balance)}
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-700">{cycle.payment_deadline}</td>
                    <td className="px-6 py-4 text-sm capitalize text-gray-700">{cycle.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
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
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4">
          <div className="w-full max-w-xl rounded-xl border border-gray-200 bg-white shadow-2xl">
            <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
              <h2 className="text-xl font-semibold text-[#0F172A]">Submit Weekly Payment</h2>
              <button onClick={closeModal} className="rounded-lg p-2 transition-all hover:bg-gray-100">
                <X className="h-5 w-5 text-gray-500" />
              </button>
            </div>

            <form onSubmit={handleSubmitPayment} className="space-y-4 px-6 py-5">
              {formError && (
                <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                  {formError}
                </div>
              )}

              <div className="rounded-lg border border-blue-100 bg-blue-50 px-4 py-3 text-sm text-blue-700">
                Deadline: {formatDate(summary.deadline)} / Outstanding: {formatCurrency(summary.outstandingBalance)}
              </div>

              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div>
                  <label className="mb-2 block text-sm font-medium text-gray-700">Amount (GHS)</label>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    required
                    value={paymentForm.amount}
                    onChange={(event) => setPaymentForm((current) => ({ ...current, amount: event.target.value }))}
                    className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                  />
                </div>
                <div>
                  <label className="mb-2 block text-sm font-medium text-gray-700">Payment Date</label>
                  <input
                    type="date"
                    required
                    value={paymentForm.collection_date}
                    onChange={(event) => setPaymentForm((current) => ({ ...current, collection_date: event.target.value }))}
                    className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                  />
                </div>
              </div>

              <div>
                <label className="mb-2 block text-sm font-medium text-gray-700">Payment Method</label>
                <select
                  value={paymentForm.payment_method}
                  onChange={(event) =>
                    setPaymentForm((current) => ({
                      ...current,
                      payment_method: event.target.value as PaymentMethod,
                    }))
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
                <label className="mb-2 block text-sm font-medium text-gray-700">Reference Number</label>
                <input
                  value={paymentForm.reference_number}
                  onChange={(event) => setPaymentForm((current) => ({ ...current, reference_number: event.target.value }))}
                  className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                  placeholder="Optional transfer or receipt reference"
                />
              </div>

              <div>
                <label className="mb-2 block text-sm font-medium text-gray-700">Notes</label>
                <textarea
                  value={paymentForm.notes}
                  onChange={(event) => setPaymentForm((current) => ({ ...current, notes: event.target.value }))}
                  className="min-h-[100px] w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                  placeholder="Optional payment note"
                />
              </div>

              <div className="flex items-center justify-end gap-3 border-t border-gray-200 pt-4">
                <button
                  type="button"
                  onClick={closeModal}
                  className="rounded-lg border border-gray-300 px-4 py-2.5 font-medium text-gray-700 transition-all hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="flex items-center gap-2 rounded-lg bg-[#2563EB] px-4 py-2.5 font-medium text-white transition-all hover:bg-[#1d4ed8] disabled:cursor-not-allowed disabled:opacity-70"
                >
                  {isSubmitting && <Loader2 className="h-4 w-4 animate-spin" />}
                  {isSubmitting ? 'Submitting...' : 'Submit Payment'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
