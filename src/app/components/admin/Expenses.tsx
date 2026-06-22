import { ChangeEvent, useEffect, useMemo, useState } from 'react';
import {
  CheckCircle,
  Clock3,
  CreditCard,
  Loader2,
  Plus,
  Receipt,
  Upload,
  Wallet,
  XCircle,
} from 'lucide-react';
import { apiRequest, ApiRequestError } from '../../lib/api';
import { getStoredSessionUser } from '../../lib/auth-session';

type ExpenseCategory =
  | 'fuel'
  | 'repairs'
  | 'servicing'
  | 'insurance'
  | 'roadworthy'
  | 'tyres'
  | 'battery'
  | 'car_wash'
  | 'driver_advance'
  | 'office'
  | 'other';
type ExpenseStatus = 'pending' | 'approved' | 'rejected' | 'paid';
type PaymentMethod = 'cash' | 'momo_transfer' | 'bank_transfer' | 'card' | 'other';

interface UserSummary {
  id: string;
  full_name: string;
  email: string;
  phone: string;
  role: 'owner' | 'admin' | 'driver';
  status: string;
}

interface VehicleSummary {
  id: string;
  registration_number: string;
  make: string;
  model: string;
  status: string;
}

interface FinanceAccount {
  id: string;
  account_name: string;
  account_type: 'bank' | 'momo' | 'cash' | 'reserve';
  provider_name: string | null;
  account_number: string | null;
  branch: string | null;
  opening_balance: number;
  current_balance: number;
  status: 'active' | 'inactive';
}

interface ExpenseRecord {
  id: string;
  expense_title: string;
  expense_category: ExpenseCategory;
  amount: number;
  expense_date: string;
  vehicle_id: string | null;
  driver_id: string | null;
  finance_account_id: string | null;
  finance_account_snapshot?: {
    id: string | null;
    account_name: string;
    account_type: string;
    provider_name?: string | null;
    account_number?: string | null;
    branch?: string | null;
    status?: string | null;
  } | null;
  payment_method: PaymentMethod;
  reference_number: string | null;
  receipt_image: string | null;
  notes: string | null;
  status: ExpenseStatus;
  requested_by: string | null;
  approved_by: string | null;
  paid_by: string | null;
  rejected_by?: string | null;
  approved_at: string | null;
  rejected_at?: string | null;
  paid_at?: string | null;
  rejection_reason?: string | null;
  created_at: string | null;
  updated_at: string | null;
  requested_by_user?: UserSummary | null;
  approved_by_user?: UserSummary | null;
  paid_by_user?: UserSummary | null;
  rejected_by_user?: UserSummary | null;
  driver?: UserSummary | null;
  vehicle?: VehicleSummary | null;
  finance_account?: {
    id: string | null;
    account_name: string;
    account_type: string;
    provider_name?: string | null;
    account_number?: string | null;
    branch?: string | null;
    status?: string | null;
  } | null;
}

interface ExpensesResponse {
  success: boolean;
  data: {
    expenses: ExpenseRecord[];
  };
}

interface ExpenseMutationResponse {
  success: boolean;
  data: {
    expense: ExpenseRecord;
  };
}

interface DriversResponse {
  success: boolean;
  data: {
    drivers: UserSummary[];
  };
}

interface VehiclesResponse {
  success: boolean;
  data: {
    vehicles: VehicleSummary[];
  };
}

interface FinanceAccountsResponse {
  success: boolean;
  data: {
    accounts: FinanceAccount[];
  };
}

interface ExpenseFormState {
  expense_title: string;
  expense_category: ExpenseCategory;
  amount: string;
  expense_date: string;
  vehicle_id: string;
  driver_id: string;
  finance_account_id: string;
  payment_method: PaymentMethod;
  reference_number: string;
  receipt_image: string;
  notes: string;
}

const initialFormState: ExpenseFormState = {
  expense_title: '',
  expense_category: 'fuel',
  amount: '',
  expense_date: new Date().toISOString().slice(0, 10),
  vehicle_id: '',
  driver_id: '',
  finance_account_id: '',
  payment_method: 'cash',
  reference_number: '',
  receipt_image: '',
  notes: '',
};

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

function formatEnumLabel(value: string) {
  return value
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function statusClassName(status: ExpenseStatus) {
  switch (status) {
    case 'approved':
      return 'bg-blue-100 text-blue-800 border-blue-200';
    case 'paid':
      return 'bg-green-100 text-green-800 border-green-200';
    case 'rejected':
      return 'bg-rose-100 text-rose-800 border-rose-200';
    default:
      return 'bg-amber-100 text-amber-800 border-amber-200';
  }
}

export default function Expenses() {
  const sessionUser = getStoredSessionUser();
  const currentRole = sessionUser?.role || null;
  const isOwner = currentRole === 'owner';
  const canCreateExpense = currentRole === 'owner' || currentRole === 'admin';

  const [expenses, setExpenses] = useState<ExpenseRecord[]>([]);
  const [drivers, setDrivers] = useState<UserSummary[]>([]);
  const [vehicles, setVehicles] = useState<VehicleSummary[]>([]);
  const [financeAccounts, setFinanceAccounts] = useState<FinanceAccount[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isActionSubmitting, setIsActionSubmitting] = useState(false);
  const [pageError, setPageError] = useState('');
  const [formError, setFormError] = useState('');
  const [actionError, setActionError] = useState('');
  const [showModal, setShowModal] = useState(false);
  const [rejectTarget, setRejectTarget] = useState<ExpenseRecord | null>(null);
  const [rejectReason, setRejectReason] = useState('');
  const [receiptFileName, setReceiptFileName] = useState('');
  const [formState, setFormState] = useState<ExpenseFormState>(initialFormState);

  const loadExpenses = async () => {
    setIsLoading(true);
    setPageError('');

    try {
      const [expensesResponse, driversResponse, vehiclesResponse, financeAccountsResponse] = await Promise.all([
        apiRequest<ExpensesResponse>('/expenses'),
        apiRequest<DriversResponse>('/drivers'),
        apiRequest<VehiclesResponse>('/vehicles'),
        apiRequest<FinanceAccountsResponse>('/finance/accounts'),
      ]);
      setExpenses(Array.isArray(expensesResponse.data?.expenses) ? expensesResponse.data.expenses : []);
      setDrivers(Array.isArray(driversResponse.data?.drivers) ? driversResponse.data.drivers : []);
      setVehicles(Array.isArray(vehiclesResponse.data?.vehicles) ? vehiclesResponse.data.vehicles : []);
      setFinanceAccounts(
        Array.isArray(financeAccountsResponse.data?.accounts) ? financeAccountsResponse.data.accounts : [],
      );
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setPageError(error.message);
      } else {
        setPageError('Unable to load expenses right now.');
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
    void loadExpenses();
  }, [currentRole]);

  useEffect(() => {
    if (!showModal || formState.finance_account_id) {
      return;
    }
    const firstActiveAccount = financeAccounts.find((account) => account.status === 'active');
    if (firstActiveAccount) {
      setFormState((current) => ({
        ...current,
        finance_account_id: firstActiveAccount.id,
      }));
    }
  }, [financeAccounts, formState.finance_account_id, showModal]);

  const totals = useMemo(() => {
    return expenses.reduce(
      (summary, expense) => {
        summary.total += expense.amount;
        if (expense.status === 'pending') {
          summary.pending += expense.amount;
          summary.pendingCount += 1;
        }
        if (expense.status === 'approved') {
          summary.approved += expense.amount;
          summary.approvedCount += 1;
        }
        if (expense.status === 'paid') {
          summary.paid += expense.amount;
          summary.paidCount += 1;
        }
        if (expense.status === 'rejected') {
          summary.rejectedCount += 1;
        }
        return summary;
      },
      {
        total: 0,
        pending: 0,
        pendingCount: 0,
        approved: 0,
        approvedCount: 0,
        paid: 0,
        paidCount: 0,
        rejectedCount: 0,
      },
    );
  }, [expenses]);

  const hasActiveFinanceAccounts = financeAccounts.some((account) => account.status === 'active');
  const selectedFinanceAccount =
    financeAccounts.find((account) => account.id === formState.finance_account_id) || null;

  const closeModal = () => {
    const firstActiveAccount = financeAccounts.find((account) => account.status === 'active');
    setShowModal(false);
    setFormError('');
    setReceiptFileName('');
    setFormState({
      ...initialFormState,
      expense_date: new Date().toISOString().slice(0, 10),
      finance_account_id: firstActiveAccount?.id || '',
    });
  };

  const closeRejectModal = () => {
    setRejectTarget(null);
    setRejectReason('');
    setActionError('');
  };

  const handleReceiptChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) {
      setReceiptFileName('');
      setFormState((current) => ({ ...current, receipt_image: '' }));
      return;
    }

    const reader = new FileReader();
    reader.onload = () => {
      setReceiptFileName(file.name);
      setFormState((current) => ({
        ...current,
        receipt_image: typeof reader.result === 'string' ? reader.result : '',
      }));
    };
    reader.readAsDataURL(file);
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setIsSubmitting(true);
    setFormError('');

    try {
      await apiRequest<ExpenseMutationResponse>('/expenses', {
        method: 'POST',
        body: JSON.stringify({
          expense_title: formState.expense_title,
          expense_category: formState.expense_category,
          amount: Number(formState.amount),
          expense_date: formState.expense_date,
          vehicle_id: formState.vehicle_id || null,
          driver_id: formState.driver_id || null,
          finance_account_id: formState.finance_account_id,
          payment_method: formState.payment_method,
          reference_number: formState.reference_number,
          receipt_image: formState.receipt_image || null,
          notes: formState.notes,
        }),
      });
      closeModal();
      await loadExpenses();
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setFormError(error.message);
      } else {
        setFormError('Unable to submit expense right now.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleApproveExpense = async (expenseId: string) => {
    setPageError('');
    setActionError('');
    setIsActionSubmitting(true);
    try {
      await apiRequest<ExpenseMutationResponse>(`/expenses/${expenseId}/approve`, {
        method: 'PATCH',
      });
      await loadExpenses();
    } catch (error) {
      const message = error instanceof ApiRequestError ? error.message : 'Unable to approve expense right now.';
      setPageError(message);
      setActionError(message);
    } finally {
      setIsActionSubmitting(false);
    }
  };

  const handleRejectExpense = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!rejectTarget) {
      return;
    }
    if (!rejectReason.trim()) {
      setActionError('Rejection reason is required.');
      return;
    }

    setPageError('');
    setActionError('');
    setIsActionSubmitting(true);
    try {
      await apiRequest<ExpenseMutationResponse>(`/expenses/${rejectTarget.id}/reject`, {
        method: 'PATCH',
        body: JSON.stringify({
          rejection_reason: rejectReason.trim(),
        }),
      });
      closeRejectModal();
      await loadExpenses();
    } catch (error) {
      const message = error instanceof ApiRequestError ? error.message : 'Unable to reject expense right now.';
      setPageError(message);
      setActionError(message);
    } finally {
      setIsActionSubmitting(false);
    }
  };

  const handleMarkPaid = async (expenseId: string) => {
    setPageError('');
    setActionError('');
    setIsActionSubmitting(true);
    try {
      await apiRequest<ExpenseMutationResponse>(`/expenses/${expenseId}/mark-paid`, {
        method: 'PATCH',
      });
      await loadExpenses();
    } catch (error) {
      const message = error instanceof ApiRequestError ? error.message : 'Unable to mark expense as paid right now.';
      setPageError(message);
      setActionError(message);
    } finally {
      setIsActionSubmitting(false);
    }
  };

  if (currentRole === 'driver') {
    return (
      <div className="p-6">
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Drivers do not have access to the Expenses page.
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-[#0F172A]">Expenses</h1>
          <p className="mt-1 text-gray-600">
            Track money leaving the business, review requests, and pay approved expenses from finance accounts.
          </p>
        </div>
        {canCreateExpense && (
          <button
            onClick={() => setShowModal(true)}
            disabled={!hasActiveFinanceAccounts}
            className="flex items-center gap-2 rounded-lg bg-[#2563EB] px-4 py-2.5 font-medium text-white transition-all hover:bg-[#1d4ed8] disabled:cursor-not-allowed disabled:opacity-60"
            title={hasActiveFinanceAccounts ? 'Add expense' : 'Create an active finance account first'}
          >
            <Plus className="h-5 w-5" />
            Add Expense
          </button>
        )}
      </div>

      {pageError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {pageError}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-lg bg-slate-100">
            <Receipt className="h-5 w-5 text-slate-600" />
          </div>
          <div className="text-2xl font-semibold text-[#0F172A]">{formatCurrency(totals.total)}</div>
          <div className="text-sm text-gray-600">Total Expenses</div>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-lg bg-amber-100">
            <Clock3 className="h-5 w-5 text-amber-600" />
          </div>
          <div className="text-2xl font-semibold text-[#0F172A]">{formatCurrency(totals.pending)}</div>
          <div className="text-sm text-gray-600">Pending Expenses</div>
          <div className="mt-1 text-xs text-gray-500">{totals.pendingCount} request(s)</div>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-lg bg-blue-100">
            <CheckCircle className="h-5 w-5 text-blue-600" />
          </div>
          <div className="text-2xl font-semibold text-[#0F172A]">{formatCurrency(totals.approved)}</div>
          <div className="text-sm text-gray-600">Approved Expenses</div>
          <div className="mt-1 text-xs text-gray-500">{totals.approvedCount} awaiting payment</div>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-lg bg-green-100">
            <Wallet className="h-5 w-5 text-green-600" />
          </div>
          <div className="text-2xl font-semibold text-[#0F172A]">{formatCurrency(totals.paid)}</div>
          <div className="text-sm text-gray-600">Paid Expenses</div>
          <div className="mt-1 text-xs text-gray-500">{totals.paidCount} settled</div>
        </div>
      </div>

      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
        <div className="border-b border-gray-200 px-6 py-4">
          <h2 className="text-lg font-semibold text-[#0F172A]">Expense List</h2>
          <p className="mt-1 text-sm text-gray-600">
            {isOwner
              ? 'Approve, reject, and pay expense requests across the business.'
              : 'Create expense requests and track their approval and payment status.'}
          </p>
        </div>
        {isLoading ? (
          <div className="flex items-center justify-center gap-3 px-6 py-16 text-gray-500">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span>Loading expenses...</span>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="border-b border-gray-200 bg-gray-50">
                <tr>
                  <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Expense</th>
                  <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Driver / Vehicle</th>
                  <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Account</th>
                  <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Amount</th>
                  <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Status</th>
                  <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Receipt</th>
                  <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {expenses.map((expense) => (
                  <tr key={expense.id} className="transition-colors hover:bg-gray-50">
                    <td className="px-6 py-4">
                      <div className="font-medium text-[#0F172A]">{expense.expense_title}</div>
                      <div className="text-xs text-gray-500">
                        {formatEnumLabel(expense.expense_category)} on {formatDate(expense.expense_date)}
                      </div>
                      <div className="mt-1 text-xs text-gray-500">
                        Requested by {expense.requested_by_user?.full_name || 'Unknown user'}
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <div className="text-gray-700">{expense.driver?.full_name || 'No driver linked'}</div>
                      <div className="text-xs text-gray-500">
                        {expense.vehicle?.registration_number
                          ? `${expense.vehicle.registration_number} ${expense.vehicle.make || ''} ${expense.vehicle.model || ''}`.trim()
                          : 'No vehicle linked'}
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <div className="text-gray-700">
                        {expense.finance_account_snapshot?.account_name || 'No account selected'}
                      </div>
                      <div className="text-xs text-gray-500">
                        {formatEnumLabel(expense.payment_method)}
                        {expense.reference_number ? ` / Ref: ${expense.reference_number}` : ''}
                      </div>
                    </td>
                    <td className="px-6 py-4 font-semibold text-[#0F172A]">{formatCurrency(expense.amount)}</td>
                    <td className="px-6 py-4">
                      <span
                        className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${statusClassName(expense.status)}`}
                      >
                        {formatEnumLabel(expense.status)}
                      </span>
                      {expense.rejection_reason && (
                        <div className="mt-1 max-w-xs text-xs text-rose-600">{expense.rejection_reason}</div>
                      )}
                    </td>
                    <td className="px-6 py-4">
                      {expense.receipt_image ? (
                        <a
                          href={expense.receipt_image}
                          target="_blank"
                          rel="noreferrer"
                          className="text-sm font-medium text-[#2563EB] hover:underline"
                        >
                          View receipt
                        </a>
                      ) : (
                        <span className="text-sm text-gray-400">No receipt</span>
                      )}
                    </td>
                    <td className="px-6 py-4">
                      {isOwner ? (
                        <div className="flex items-center gap-2">
                          {expense.status === 'pending' && (
                            <>
                              <button
                                onClick={() => void handleApproveExpense(expense.id)}
                                disabled={isActionSubmitting}
                                className="rounded p-1.5 text-blue-600 transition-all hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-60"
                                title="Approve expense"
                              >
                                <CheckCircle className="h-4 w-4" />
                              </button>
                              <button
                                onClick={() => {
                                  setRejectTarget(expense);
                                  setRejectReason('');
                                  setActionError('');
                                }}
                                disabled={isActionSubmitting}
                                className="rounded p-1.5 text-rose-600 transition-all hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-60"
                                title="Reject expense"
                              >
                                <XCircle className="h-4 w-4" />
                              </button>
                            </>
                          )}
                          {expense.status === 'approved' && (
                            <button
                              onClick={() => void handleMarkPaid(expense.id)}
                              disabled={isActionSubmitting}
                              className="rounded p-1.5 text-green-600 transition-all hover:bg-green-50 disabled:cursor-not-allowed disabled:opacity-60"
                              title="Mark expense as paid"
                            >
                              <CreditCard className="h-4 w-4" />
                            </button>
                          )}
                          {(expense.status === 'paid' || expense.status === 'rejected') && (
                            <span className="text-sm text-gray-400">No action required</span>
                          )}
                        </div>
                      ) : (
                        <span className="text-sm text-gray-400">
                          {expense.status === 'pending'
                            ? 'Awaiting owner review'
                            : expense.status === 'approved'
                              ? 'Awaiting payment'
                              : expense.status === 'paid'
                                ? 'Paid from finance account'
                                : 'Rejected by owner'}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {expenses.length === 0 && (
              <div className="px-6 py-12 text-center text-gray-500">No expenses recorded yet.</div>
            )}
          </div>
        )}
      </div>

      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4">
          <div className="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-xl border border-gray-200 bg-white shadow-2xl">
            <div className="shrink-0 border-b border-gray-200 px-6 py-4">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-xl font-semibold text-[#0F172A]">Add Expense</h2>
                  <p className="mt-1 text-sm text-gray-500">
                    Create a new expense request and route it through owner approval before payment.
                  </p>
                </div>
                <button onClick={closeModal} className="rounded-lg p-2 transition-all hover:bg-gray-100">
                  <XCircle className="h-5 w-5 text-gray-500" />
                </button>
              </div>
            </div>

            <form onSubmit={handleSubmit} className="flex min-h-0 flex-1 flex-col">
              <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-6 py-5">
                {formError && (
                  <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                    {formError}
                  </div>
                )}

                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  <div>
                    <label className="mb-2 block text-sm font-medium text-gray-700">Expense Title</label>
                    <input
                      required
                      value={formState.expense_title}
                      onChange={(event) =>
                        setFormState((current) => ({ ...current, expense_title: event.target.value }))
                      }
                      className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                    />
                  </div>
                  <div>
                    <label className="mb-2 block text-sm font-medium text-gray-700">Expense Category</label>
                    <select
                      value={formState.expense_category}
                      onChange={(event) =>
                        setFormState((current) => ({
                          ...current,
                          expense_category: event.target.value as ExpenseCategory,
                        }))
                      }
                      className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                    >
                      {[
                        'fuel',
                        'repairs',
                        'servicing',
                        'insurance',
                        'roadworthy',
                        'tyres',
                        'battery',
                        'car_wash',
                        'driver_advance',
                        'office',
                        'other',
                      ].map((category) => (
                        <option key={category} value={category}>
                          {formatEnumLabel(category)}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  <div>
                    <label className="mb-2 block text-sm font-medium text-gray-700">Amount (GHS)</label>
                    <input
                      type="number"
                      step="0.01"
                      min="0"
                      required
                      value={formState.amount}
                      onChange={(event) => setFormState((current) => ({ ...current, amount: event.target.value }))}
                      className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                    />
                  </div>
                  <div>
                    <label className="mb-2 block text-sm font-medium text-gray-700">Expense Date</label>
                    <input
                      type="date"
                      required
                      value={formState.expense_date}
                      onChange={(event) =>
                        setFormState((current) => ({ ...current, expense_date: event.target.value }))
                      }
                      className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                    />
                  </div>
                </div>

                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  <div>
                    <label className="mb-2 block text-sm font-medium text-gray-700">Driver</label>
                    <select
                      value={formState.driver_id}
                      onChange={(event) => setFormState((current) => ({ ...current, driver_id: event.target.value }))}
                      className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                    >
                      <option value="">No driver linked</option>
                      {drivers
                        .filter((driver) => driver.role === 'driver')
                        .map((driver) => (
                          <option key={driver.id} value={driver.id}>
                            {driver.full_name}
                          </option>
                        ))}
                    </select>
                  </div>
                  <div>
                    <label className="mb-2 block text-sm font-medium text-gray-700">Vehicle</label>
                    <select
                      value={formState.vehicle_id}
                      onChange={(event) => setFormState((current) => ({ ...current, vehicle_id: event.target.value }))}
                      className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                    >
                      <option value="">No vehicle linked</option>
                      {vehicles.map((vehicle) => (
                        <option key={vehicle.id} value={vehicle.id}>
                          {vehicle.registration_number} {vehicle.make} {vehicle.model}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  <div>
                    <label className="mb-2 block text-sm font-medium text-gray-700">Finance Account</label>
                    <select
                      required
                      value={formState.finance_account_id}
                      onChange={(event) =>
                        setFormState((current) => ({ ...current, finance_account_id: event.target.value }))
                      }
                      className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                    >
                      <option value="">Choose finance account...</option>
                      {financeAccounts
                        .filter((account) => account.status === 'active')
                        .map((account) => (
                          <option key={account.id} value={account.id}>
                            {account.account_name} - {formatEnumLabel(account.account_type)}
                          </option>
                        ))}
                    </select>
                  </div>
                  <div>
                    <label className="mb-2 block text-sm font-medium text-gray-700">Payment Method</label>
                    <select
                      value={formState.payment_method}
                      onChange={(event) =>
                        setFormState((current) => ({
                          ...current,
                          payment_method: event.target.value as PaymentMethod,
                        }))
                      }
                      className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                    >
                      <option value="cash">Cash</option>
                      <option value="momo_transfer">MoMo Transfer</option>
                      <option value="bank_transfer">Bank Transfer</option>
                      <option value="card">Card</option>
                      <option value="other">Other</option>
                    </select>
                  </div>
                </div>

                {selectedFinanceAccount && (
                  <div className="rounded-lg border border-blue-100 bg-blue-50 px-4 py-3 text-sm text-blue-700">
                    Paying from {selectedFinanceAccount.account_name}
                    {selectedFinanceAccount.provider_name ? ` / ${selectedFinanceAccount.provider_name}` : ''}
                    {' / '}
                    Available balance: {formatCurrency(selectedFinanceAccount.current_balance)}
                  </div>
                )}

                <div>
                  <label className="mb-2 block text-sm font-medium text-gray-700">Reference Number</label>
                  <input
                    value={formState.reference_number}
                    onChange={(event) =>
                      setFormState((current) => ({ ...current, reference_number: event.target.value }))
                    }
                    className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                    placeholder="Optional payment reference"
                  />
                </div>

                <div>
                  <label className="mb-2 block text-sm font-medium text-gray-700">Receipt / Proof</label>
                  <label className="flex cursor-pointer flex-col items-center justify-center rounded-lg border border-dashed border-gray-300 bg-gray-50 px-4 py-6 text-center transition-all hover:border-[#2563EB] hover:bg-blue-50/40">
                    <Upload className="mb-3 h-5 w-5 text-gray-500" />
                    <span className="text-sm font-medium text-gray-700">
                      {receiptFileName || 'Click to upload receipt or proof image'}
                    </span>
                    <span className="mt-1 text-xs text-gray-500">PNG, JPG, or screenshot proof accepted</span>
                    <input type="file" accept="image/*" className="hidden" onChange={handleReceiptChange} />
                  </label>
                </div>

                <div>
                  <label className="mb-2 block text-sm font-medium text-gray-700">Notes</label>
                  <textarea
                    value={formState.notes}
                    onChange={(event) => setFormState((current) => ({ ...current, notes: event.target.value }))}
                    className="min-h-[100px] w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                    placeholder="Optional detail about this expense"
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
                    {isSubmitting ? 'Submitting Expense...' : 'Submit Expense'}
                  </button>
                </div>
              </div>
            </form>
          </div>
        </div>
      )}

      {rejectTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4">
          <div className="w-full max-w-xl rounded-xl border border-gray-200 bg-white shadow-2xl">
            <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
              <div>
                <h2 className="text-xl font-semibold text-[#0F172A]">Reject Expense</h2>
                <p className="mt-1 text-sm text-gray-500">
                  Provide a reason for rejecting this expense request.
                </p>
              </div>
              <button onClick={closeRejectModal} className="rounded-lg p-2 transition-all hover:bg-gray-100">
                <XCircle className="h-5 w-5 text-gray-500" />
              </button>
            </div>

            <form onSubmit={handleRejectExpense} className="space-y-4 px-6 py-5">
              {actionError && (
                <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                  {actionError}
                </div>
              )}
              <div className="rounded-lg border border-amber-100 bg-amber-50 px-4 py-3 text-sm text-amber-700">
                {rejectTarget.expense_title} for {formatCurrency(rejectTarget.amount)} will be rejected.
              </div>
              <div>
                <label className="mb-2 block text-sm font-medium text-gray-700">Rejection Reason</label>
                <textarea
                  required
                  value={rejectReason}
                  onChange={(event) => setRejectReason(event.target.value)}
                  className="min-h-[120px] w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                  placeholder="Explain why this expense is being rejected"
                />
              </div>
              <div className="flex items-center justify-end gap-3 border-t border-gray-200 pt-4">
                <button
                  type="button"
                  onClick={closeRejectModal}
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
                  {isActionSubmitting ? 'Rejecting...' : 'Reject Expense'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
