import { ChangeEvent, useEffect, useMemo, useState } from 'react';
import {
  Building2,
  CheckCircle,
  Clock3,
  Landmark,
  Loader2,
  Plus,
  Receipt,
  ShieldCheck,
  Upload,
  Wallet,
  XCircle,
} from 'lucide-react';
import { apiRequest, ApiRequestError } from '../../lib/api';
import { getStoredSessionUser } from '../../lib/auth-session';

type DepositMethod = 'cash_deposit' | 'momo_transfer' | 'bank_transfer';
type DepositStatus = 'submitted' | 'verified' | 'rejected';

interface UserSummary {
  id: string;
  full_name: string;
  email: string;
  phone: string;
  role: 'owner' | 'admin' | 'driver';
  status: string;
}

interface DepositRecord {
  id: string;
  admin_id: string;
  finance_account_id?: string | null;
  amount: number;
  deposit_date: string;
  deposit_method: DepositMethod;
  destination_name: string;
  finance_account_snapshot?: {
    id: string | null;
    account_name: string;
    account_type: string;
    provider_name?: string | null;
    account_number?: string | null;
    branch?: string | null;
    status?: string | null;
  } | null;
  reference_number: string | null;
  receipt_image: string | null;
  notes: string | null;
  status: DepositStatus;
  submitted_by: string | null;
  verified_by: string | null;
  rejected_by?: string | null;
  rejection_reason?: string | null;
  submitted_at: string | null;
  verified_at: string | null;
  rejected_at?: string | null;
  admin?: UserSummary | null;
  submitted_by_user?: UserSummary | null;
  verified_by_user?: UserSummary | null;
  rejected_by_user?: UserSummary | null;
}

interface HoldingBalanceRecord {
  admin: UserSummary | null;
  total_collected: number;
  total_deposited: number;
  holding_balance: number;
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

interface CompanyFundsSummary {
  available_funds: number;
  verified_deposits_total: number;
  verified_deposits_count: number;
  pending_deposits_total: number;
  pending_deposits_count: number;
  rejected_deposits_total: number;
  rejected_deposits_count: number;
}

interface DepositsResponse {
  success: boolean;
  data: {
    deposits: DepositRecord[];
    pagination?: {
      page: number;
      page_size: number;
      total_records: number;
      total_pages: number;
    };
    summary?: {
      total_records: number;
      total_amount: number;
      verified_total: number;
      pending_total: number;
      rejected_total: number;
      verified_count: number;
      pending_count: number;
      rejected_count: number;
    };
  };
}

interface DepositMutationResponse {
  success: boolean;
  data: {
    deposit: DepositRecord;
  };
}

interface HoldingBalancesResponse {
  success: boolean;
  data: {
    admins: HoldingBalanceRecord[];
  };
}

interface CompanyFundsResponse {
  success: boolean;
  data: {
    funds: CompanyFundsSummary;
  };
}

interface FinanceAccountsResponse {
  success: boolean;
  data: {
    accounts: FinanceAccount[];
  };
}

interface DepositFormState {
  amount: string;
  deposit_date: string;
  deposit_method: DepositMethod;
  finance_account_id: string;
  reference_number: string;
  receipt_image: string;
  notes: string;
}

const initialDepositForm: DepositFormState = {
  amount: '',
  deposit_date: new Date().toISOString().slice(0, 10),
  deposit_method: 'bank_transfer',
  finance_account_id: '',
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

function formatDepositMethod(method: DepositMethod) {
  return method
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function statusClassName(status: DepositStatus) {
  switch (status) {
    case 'verified':
      return 'bg-green-100 text-green-800 border-green-200';
    case 'rejected':
      return 'bg-rose-100 text-rose-800 border-rose-200';
    default:
      return 'bg-amber-100 text-amber-800 border-amber-200';
  }
}

function getSettledData<T>(result: PromiseSettledResult<T>) {
  return result.status === 'fulfilled' ? result.value : null;
}

export default function Deposits() {
  const sessionUser = getStoredSessionUser();
  const currentRole = sessionUser?.role || null;
  const currentUserId = sessionUser?.id || '';
  const isOwner = currentRole === 'owner';
  const isAdmin = currentRole === 'admin';

  const [deposits, setDeposits] = useState<DepositRecord[]>([]);
  const [holdingBalances, setHoldingBalances] = useState<HoldingBalanceRecord[]>([]);
  const [financeAccounts, setFinanceAccounts] = useState<FinanceAccount[]>([]);
  const [companyFunds, setCompanyFunds] = useState<CompanyFundsSummary | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isActionSubmitting, setIsActionSubmitting] = useState(false);
  const [pageError, setPageError] = useState('');
  const [pageNotice, setPageNotice] = useState('');
  const [formError, setFormError] = useState('');
  const [actionError, setActionError] = useState('');
  const [showModal, setShowModal] = useState(false);
  const [rejectTarget, setRejectTarget] = useState<DepositRecord | null>(null);
  const [rejectReason, setRejectReason] = useState('');
  const [receiptFileName, setReceiptFileName] = useState('');
  const [formState, setFormState] = useState<DepositFormState>(initialDepositForm);
  const [currentPage, setCurrentPage] = useState(1);
  const [depositPagination, setDepositPagination] = useState({ page: 1, page_size: 25, total_records: 0, total_pages: 1 });
  const [depositSummary, setDepositSummary] = useState({
    total_records: 0,
    total_amount: 0,
    verified_total: 0,
    pending_total: 0,
    rejected_total: 0,
    verified_count: 0,
    pending_count: 0,
    rejected_count: 0,
  });

  const loadDeposits = async () => {
    setIsLoading(true);
    setPageError('');
    setPageNotice('');

    try {
      const depositsResponse = await apiRequest<DepositsResponse>(`/deposits?page=${currentPage}&page_size=25`, {
        cacheTtlMs: 5000,
        timeoutMs: 15000,
      });

      setDeposits(Array.isArray(depositsResponse?.data?.deposits) ? depositsResponse.data.deposits : []);
      setDepositPagination(depositsResponse?.data?.pagination || { page: 1, page_size: 25, total_records: 0, total_pages: 1 });
      setDepositSummary(
        depositsResponse?.data?.summary || {
          total_records: 0,
          total_amount: 0,
          verified_total: 0,
          pending_total: 0,
          rejected_total: 0,
          verified_count: 0,
          pending_count: 0,
          rejected_count: 0,
        },
      );
      setIsLoading(false);

      const requests: Promise<HoldingBalancesResponse | FinanceAccountsResponse | CompanyFundsResponse>[] = [
        apiRequest<HoldingBalancesResponse>('/admins/holding-balances', { cacheTtlMs: 10000, timeoutMs: 15000 }),
        apiRequest<FinanceAccountsResponse>('/finance/accounts', { cacheTtlMs: 10000, timeoutMs: 15000 }),
      ];
      if (isOwner) {
        requests.push(apiRequest<CompanyFundsResponse>('/company-funds', { cacheTtlMs: 10000, timeoutMs: 15000 }));
      }

      const results = await Promise.allSettled(requests);
      const [balancesResult, financeAccountsResult, companyFundsResult] = results;
      const balancesResponse = getSettledData(balancesResult) as HoldingBalancesResponse | null;
      const financeAccountsResponse = getSettledData(financeAccountsResult) as FinanceAccountsResponse | null;
      const companyFundsResponse = companyFundsResult ? (getSettledData(companyFundsResult) as CompanyFundsResponse | null) : null;

      setHoldingBalances(Array.isArray(balancesResponse?.data?.admins) ? balancesResponse.data.admins : []);
      setFinanceAccounts(Array.isArray(financeAccountsResponse?.data?.accounts) ? financeAccountsResponse.data.accounts : []);
      setCompanyFunds(isOwner ? companyFundsResponse?.data?.funds || null : null);

      const unavailableSections: string[] = [];
      if (balancesResult.status === 'rejected') unavailableSections.push('holding balances');
      if (financeAccountsResult.status === 'rejected') unavailableSections.push('finance accounts');
      if (companyFundsResult?.status === 'rejected') unavailableSections.push('company funds');
      if (unavailableSections.length > 0) {
        setPageNotice(`Some sections are temporarily unavailable: ${unavailableSections.join(', ')}.`);
      }
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setPageError(error.message);
      } else {
        setPageError('Unable to load deposits right now.');
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
    void loadDeposits();
  }, [currentRole, currentPage]);

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

  const myHoldingBalance = useMemo(
    () => holdingBalances.find((record) => record.admin?.id === currentUserId) || holdingBalances[0] || null,
    [currentUserId, holdingBalances],
  );

  const depositTotals = useMemo(() => {
    return {
      total: depositSummary.total_amount,
      pending: depositSummary.pending_total,
      pendingCount: depositSummary.pending_count,
      verified: depositSummary.verified_total,
      verifiedCount: depositSummary.verified_count,
      rejected: depositSummary.rejected_total,
      rejectedCount: depositSummary.rejected_count,
    };
  }, [depositSummary]);

  const totalHoldingBalance = useMemo(
    () => holdingBalances.reduce((sum, record) => sum + record.holding_balance, 0),
    [holdingBalances],
  );

  const selectedFinanceAccount =
    financeAccounts.find((account) => account.id === formState.finance_account_id) || null;
  const hasActiveFinanceAccounts = financeAccounts.some((account) => account.status === 'active');

  const closeModal = () => {
    const firstActiveAccount = financeAccounts.find((account) => account.status === 'active');
    setShowModal(false);
    setFormError('');
    setReceiptFileName('');
    setFormState({
      ...initialDepositForm,
      deposit_date: new Date().toISOString().slice(0, 10),
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

  const handleSubmitDeposit = async (event: React.FormEvent) => {
    event.preventDefault();
    setIsSubmitting(true);
    setFormError('');

    try {
      await apiRequest<DepositMutationResponse>('/deposits', {
        method: 'POST',
        body: JSON.stringify({
          amount: Number(formState.amount),
          deposit_date: formState.deposit_date,
          deposit_method: formState.deposit_method,
          finance_account_id: formState.finance_account_id,
          reference_number: formState.reference_number,
          receipt_image: formState.receipt_image || null,
          notes: formState.notes,
        }),
      });
      closeModal();
      await loadDeposits();
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setFormError(error.message);
      } else {
        setFormError('Unable to submit deposit right now.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleVerifyDeposit = async (depositId: string) => {
    setPageError('');
    setActionError('');
    setIsActionSubmitting(true);
    try {
      await apiRequest<DepositMutationResponse>(`/deposits/${depositId}/verify`, {
        method: 'PATCH',
        body: JSON.stringify({
          finance_account_id:
            deposits.find((deposit) => deposit.id === depositId)?.finance_account_id || null,
        }),
      });
      await loadDeposits();
    } catch (error) {
      const message = error instanceof ApiRequestError ? error.message : 'Unable to verify deposit right now.';
      setPageError(message);
      setActionError(message);
    } finally {
      setIsActionSubmitting(false);
    }
  };

  const handleRejectDeposit = async (event: React.FormEvent) => {
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
      await apiRequest<DepositMutationResponse>(`/deposits/${rejectTarget.id}/reject`, {
        method: 'PATCH',
        body: JSON.stringify({
          rejection_reason: rejectReason.trim(),
        }),
      });
      closeRejectModal();
      await loadDeposits();
    } catch (error) {
      const message = error instanceof ApiRequestError ? error.message : 'Unable to reject deposit right now.';
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
          Drivers do not have access to the Deposits page.
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-[#0F172A]">Deposits</h1>
          <p className="mt-1 text-gray-600">
            Submit verified cash-out deposits, monitor admin holding balances, and track company funds.
          </p>
        </div>
        {isAdmin && (
          <button
            onClick={() => setShowModal(true)}
            disabled={!hasActiveFinanceAccounts}
            className="flex items-center gap-2 rounded-lg bg-[#2563EB] px-4 py-2.5 font-medium text-white transition-all hover:bg-[#1d4ed8] disabled:cursor-not-allowed disabled:opacity-60"
            title={hasActiveFinanceAccounts ? 'Submit deposit' : 'Owner must create an active finance account first'}
          >
            <Plus className="h-5 w-5" />
            Submit Deposit
          </button>
        )}
      </div>

      {pageError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <span>{pageError}</span>
            <button
              onClick={() => void loadDeposits()}
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

      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-lg bg-amber-100">
            <Wallet className="h-5 w-5 text-amber-600" />
          </div>
          <div className="text-2xl font-semibold text-[#0F172A]">
            {formatCurrency(myHoldingBalance?.holding_balance || 0)}
          </div>
          <div className="text-sm text-gray-600">{isOwner ? 'Owner Holding Balance' : 'My Holding Balance'}</div>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-lg bg-blue-100">
            <Receipt className="h-5 w-5 text-blue-600" />
          </div>
          <div className="text-2xl font-semibold text-[#0F172A]">{formatCurrency(depositTotals.pending)}</div>
          <div className="text-sm text-gray-600">Submitted Deposits</div>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-lg bg-green-100">
            <CheckCircle className="h-5 w-5 text-green-600" />
          </div>
          <div className="text-2xl font-semibold text-[#0F172A]">{formatCurrency(depositTotals.verified)}</div>
          <div className="text-sm text-gray-600">Verified Deposits</div>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-lg bg-slate-100">
            <Landmark className="h-5 w-5 text-slate-600" />
          </div>
          <div className="text-2xl font-semibold text-[#0F172A]">
            {formatCurrency(isOwner ? companyFunds?.available_funds || 0 : myHoldingBalance?.total_deposited || 0)}
          </div>
          <div className="text-sm text-gray-600">{isOwner ? 'Company Available Funds' : 'Deposited To Company'}</div>
        </div>
      </div>

      {isOwner && (
        <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
          <div className="rounded-xl border border-gray-200 bg-white p-6 xl:col-span-2">
            <div className="flex items-center gap-3">
              <Building2 className="h-5 w-5 text-gray-600" />
              <div>
                <h2 className="text-lg font-semibold text-[#0F172A]">Company Funds</h2>
                <p className="mt-1 text-sm text-gray-600">Verified deposits available to the business</p>
              </div>
            </div>
            <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-3">
              <div className="rounded-lg border border-gray-200 bg-gray-50 p-4">
                <div className="text-sm text-gray-500">Available Funds</div>
                <div className="mt-2 text-2xl font-semibold text-[#0F172A]">
                  {formatCurrency(companyFunds?.available_funds || 0)}
                </div>
              </div>
              <div className="rounded-lg border border-gray-200 bg-gray-50 p-4">
                <div className="text-sm text-gray-500">Pending Deposits</div>
                <div className="mt-2 text-2xl font-semibold text-amber-700">
                  {companyFunds?.pending_deposits_count || 0}
                </div>
                <div className="mt-1 text-xs text-gray-500">
                  {formatCurrency(companyFunds?.pending_deposits_total || 0)}
                </div>
              </div>
              <div className="rounded-lg border border-gray-200 bg-gray-50 p-4">
                <div className="text-sm text-gray-500">Rejected Deposits</div>
                <div className="mt-2 text-2xl font-semibold text-rose-700">
                  {companyFunds?.rejected_deposits_count || 0}
                </div>
                <div className="mt-1 text-xs text-gray-500">
                  {formatCurrency(companyFunds?.rejected_deposits_total || 0)}
                </div>
              </div>
            </div>
          </div>

          <div className="rounded-xl border border-gray-200 bg-white p-6">
            <div className="flex items-center gap-3">
              <ShieldCheck className="h-5 w-5 text-gray-600" />
              <div>
                <h2 className="text-lg font-semibold text-[#0F172A]">Holding Overview</h2>
                <p className="mt-1 text-sm text-gray-600">Current cash held by all admins</p>
              </div>
            </div>
            <div className="mt-6 text-3xl font-semibold text-[#0F172A]">
              {formatCurrency(totalHoldingBalance)}
            </div>
            <div className="mt-2 text-sm text-gray-500">
              Based on approved collections minus verified deposits
            </div>
          </div>
        </div>
      )}

      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
        <div className="border-b border-gray-200 px-6 py-4">
          <h2 className="text-lg font-semibold text-[#0F172A]">
            {isOwner ? 'All Deposits' : 'My Deposit History'}
          </h2>
          <p className="mt-1 text-sm text-gray-600">
            {isOwner
              ? 'Review submitted deposits, verify proof, or reject invalid submissions'
              : 'Track every deposit submitted from your holding balance'}
          </p>
        </div>
        {isLoading ? (
          <div className="flex items-center justify-center gap-3 px-6 py-16 text-gray-500">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span>Loading deposits...</span>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="border-b border-gray-200 bg-gray-50">
                <tr>
                  <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Admin</th>
                  <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Amount</th>
                  <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Method</th>
                  <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Destination</th>
                  <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Status</th>
                  <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Receipt</th>
                  <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {deposits.map((deposit) => (
                  <tr key={deposit.id} className="transition-colors hover:bg-gray-50">
                    <td className="px-6 py-4">
                      <div className="font-medium text-[#0F172A]">{deposit.admin?.full_name || 'Unknown Admin'}</div>
                      <div className="text-xs text-gray-500">
                        Submitted {formatDate(deposit.submitted_at || deposit.deposit_date)}
                      </div>
                    </td>
                    <td className="px-6 py-4 font-semibold text-[#0F172A]">{formatCurrency(deposit.amount)}</td>
                    <td className="px-6 py-4 text-gray-700">{formatDepositMethod(deposit.deposit_method)}</td>
                    <td className="px-6 py-4">
                      <div className="text-gray-700">{deposit.destination_name}</div>
                      <div className="text-xs text-gray-500">
                        {deposit.finance_account_snapshot?.account_type
                          ? `${deposit.finance_account_snapshot.account_type} account`
                          : deposit.reference_number || 'No reference'}
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <span
                        className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${statusClassName(deposit.status)}`}
                      >
                        {deposit.status.charAt(0).toUpperCase() + deposit.status.slice(1)}
                      </span>
                      {deposit.rejection_reason && (
                        <div className="mt-1 text-xs text-rose-600">{deposit.rejection_reason}</div>
                      )}
                    </td>
                    <td className="px-6 py-4">
                      {deposit.receipt_image ? (
                        <a
                          href={deposit.receipt_image}
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
                      {isOwner && deposit.status === 'submitted' ? (
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => void handleVerifyDeposit(deposit.id)}
                            disabled={isActionSubmitting}
                            className="rounded p-1.5 text-green-600 transition-all hover:bg-green-50 disabled:cursor-not-allowed disabled:opacity-60"
                            title="Verify deposit"
                          >
                            <CheckCircle className="h-4 w-4" />
                          </button>
                          <button
                            onClick={() => {
                              setRejectTarget(deposit);
                              setRejectReason('');
                              setActionError('');
                            }}
                            disabled={isActionSubmitting}
                            className="rounded p-1.5 text-rose-600 transition-all hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-60"
                            title="Reject deposit"
                          >
                            <XCircle className="h-4 w-4" />
                          </button>
                        </div>
                      ) : (
                        <span className="text-sm text-gray-400">
                          {deposit.status === 'submitted'
                            ? 'Awaiting owner review'
                            : deposit.finance_account_snapshot?.account_name || 'No action required'}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {deposits.length === 0 && (
              <div className="px-6 py-12 text-center text-gray-500">No deposits recorded yet.</div>
            )}
            <div className="flex flex-col gap-3 border-t border-gray-200 px-6 py-4 text-sm text-gray-600 sm:flex-row sm:items-center sm:justify-between">
              <div>Showing {deposits.length} of {depositPagination.total_records} deposits</div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setCurrentPage((page) => Math.max(page - 1, 1))}
                  disabled={currentPage <= 1}
                  className="rounded-lg border border-gray-300 px-3 py-2 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Previous
                </button>
                <span>Page {depositPagination.page} of {depositPagination.total_pages}</span>
                <button
                  onClick={() => setCurrentPage((page) => Math.min(page + 1, depositPagination.total_pages))}
                  disabled={currentPage >= depositPagination.total_pages}
                  className="rounded-lg border border-gray-300 px-3 py-2 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Next
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {isOwner && (
        <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
          <div className="border-b border-gray-200 px-6 py-4">
            <h2 className="text-lg font-semibold text-[#0F172A]">Admin Holding Balances</h2>
            <p className="mt-1 text-sm text-gray-600">
              Approved collections currently held by each admin after verified deposits
            </p>
          </div>
          {isLoading ? (
            <div className="flex items-center justify-center gap-3 px-6 py-12 text-gray-500">
              <Loader2 className="h-5 w-5 animate-spin" />
              <span>Loading holding balances...</span>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="border-b border-gray-200 bg-gray-50">
                  <tr>
                    <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Admin</th>
                    <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Collected</th>
                    <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Deposited</th>
                    <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Holding Balance</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {holdingBalances.map((record) => (
                    <tr key={record.admin?.id || 'admin'} className="transition-colors hover:bg-gray-50">
                      <td className="px-6 py-4">
                        <div className="font-medium text-[#0F172A]">{record.admin?.full_name || 'Unknown Admin'}</div>
                        <div className="text-xs text-gray-500">{record.admin?.role || 'admin'}</div>
                      </td>
                      <td className="px-6 py-4 text-gray-700">{formatCurrency(record.total_collected)}</td>
                      <td className="px-6 py-4 text-gray-700">{formatCurrency(record.total_deposited)}</td>
                      <td className="px-6 py-4 font-semibold text-[#0F172A]">
                        {formatCurrency(record.holding_balance)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {holdingBalances.length === 0 && (
                <div className="px-6 py-12 text-center text-gray-500">No admin holding balances available yet.</div>
              )}
            </div>
          )}
        </div>
      )}

      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4">
          <div className="flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-xl border border-gray-200 bg-white shadow-2xl">
            <div className="shrink-0 border-b border-gray-200 px-6 py-4">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-xl font-semibold text-[#0F172A]">Submit Deposit</h2>
                  <p className="mt-1 text-sm text-gray-500">
                    Submit a deposit from your current holding balance with proof of transfer or receipt.
                  </p>
                </div>
                <button onClick={closeModal} className="rounded-lg p-2 transition-all hover:bg-gray-100">
                  <XCircle className="h-5 w-5 text-gray-500" />
                </button>
              </div>
            </div>

            <form onSubmit={handleSubmitDeposit} className="flex min-h-0 flex-1 flex-col">
              <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-6 py-5">
                {formError && (
                  <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                    {formError}
                  </div>
                )}

                <div className="rounded-lg border border-blue-100 bg-blue-50 px-4 py-3 text-sm text-blue-700">
                  Available holding balance: {formatCurrency(myHoldingBalance?.holding_balance || 0)}
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
                    <label className="mb-2 block text-sm font-medium text-gray-700">Deposit Date</label>
                    <input
                      type="date"
                      required
                      value={formState.deposit_date}
                      onChange={(event) =>
                        setFormState((current) => ({ ...current, deposit_date: event.target.value }))
                      }
                      className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                    />
                  </div>
                </div>

                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  <div>
                    <label className="mb-2 block text-sm font-medium text-gray-700">Deposit Method</label>
                    <select
                      value={formState.deposit_method}
                      onChange={(event) =>
                        setFormState((current) => ({
                          ...current,
                          deposit_method: event.target.value as DepositMethod,
                        }))
                      }
                      className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                    >
                      <option value="cash_deposit">Cash Deposit</option>
                      <option value="momo_transfer">MoMo Transfer</option>
                      <option value="bank_transfer">Bank Transfer</option>
                    </select>
                  </div>
                  <div>
                    <label className="mb-2 block text-sm font-medium text-gray-700">Destination Finance Account</label>
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
                            {account.account_name} - {account.account_type}
                          </option>
                        ))}
                    </select>
                  </div>
                </div>

                {selectedFinanceAccount && (
                  <div className="rounded-lg border border-blue-100 bg-blue-50 px-4 py-3 text-sm text-blue-700">
                    Destination: {selectedFinanceAccount.account_name}
                    {selectedFinanceAccount.provider_name ? ` / ${selectedFinanceAccount.provider_name}` : ''}
                    {' / '}
                    Current Balance: {formatCurrency(selectedFinanceAccount.current_balance)}
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
                    placeholder="Optional deposit reference"
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
                    placeholder="Optional note about this deposit"
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
                    {isSubmitting ? 'Submitting Deposit...' : 'Submit Deposit'}
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
                <h2 className="text-xl font-semibold text-[#0F172A]">Reject Deposit</h2>
                <p className="mt-1 text-sm text-gray-500">
                  Provide a reason for rejecting this deposit submission.
                </p>
              </div>
              <button onClick={closeRejectModal} className="rounded-lg p-2 transition-all hover:bg-gray-100">
                <XCircle className="h-5 w-5 text-gray-500" />
              </button>
            </div>

            <form onSubmit={handleRejectDeposit} className="space-y-4 px-6 py-5">
              {actionError && (
                <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                  {actionError}
                </div>
              )}
              <div className="rounded-lg border border-amber-100 bg-amber-50 px-4 py-3 text-sm text-amber-700">
                {rejectTarget.admin?.full_name || 'This admin'} submitted {formatCurrency(rejectTarget.amount)} to{' '}
                {rejectTarget.destination_name}.
              </div>
              <div>
                <label className="mb-2 block text-sm font-medium text-gray-700">Rejection Reason</label>
                <textarea
                  required
                  value={rejectReason}
                  onChange={(event) => setRejectReason(event.target.value)}
                  className="min-h-[120px] w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                  placeholder="Explain why this deposit is being rejected"
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
                  {isActionSubmitting ? 'Rejecting...' : 'Reject Deposit'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
