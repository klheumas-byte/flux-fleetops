import { useEffect, useMemo, useState } from 'react';
import {
  Building2,
  ArrowRightLeft,
  History,
  Landmark,
  Loader2,
  Plus,
  Wallet,
  XCircle,
} from 'lucide-react';
import { apiRequest, ApiRequestError } from '../../lib/api';
import { getActiveSessionRole, getStoredSessionUser } from '../../lib/auth-session';

type FinanceAccountType = 'bank' | 'momo' | 'cash';
type FinanceAccountStatus = 'active' | 'inactive';

interface FinanceAccount {
  id: string;
  account_name: string;
  account_type: FinanceAccountType;
  provider_name: string | null;
  account_number: string | null;
  branch: string | null;
  opening_balance: number;
  current_balance: number;
  status: FinanceAccountStatus;
  created_by?: string | null;
}

interface FinanceAccountsResponse {
  success: boolean;
  data: {
    accounts: FinanceAccount[];
  };
}

interface FinanceAccountMutationResponse {
  success: boolean;
  data: {
    account: FinanceAccount;
  };
}

interface LedgerEntry {
  id: string;
  direction: 'credit' | 'debit';
  amount: number;
  balance_after: number;
  source_type: string;
  effective_date: string;
  description?: string | null;
}

interface FinanceSummaryResponse {
  success: boolean;
  data: {
    summary: {
      total_company_funds: number;
      active_accounts_count: number;
      bank_accounts_total: number;
      momo_accounts_total: number;
      cash_accounts_total: number;
      accounts: FinanceAccount[];
    };
  };
}

interface AccountFormState {
  account_name: string;
  account_type: FinanceAccountType;
  provider_name: string;
  account_number: string;
  branch: string;
  opening_balance: string;
}

const initialFormState: AccountFormState = {
  account_name: '',
  account_type: 'bank',
  provider_name: '',
  account_number: '',
  branch: '',
  opening_balance: '',
};

function formatCurrency(value: number) {
  return `GHS ${value.toLocaleString()}`;
}

function formatTypeLabel(value: FinanceAccountType) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

export default function FinanceAccounts() {
  const currentRole = getActiveSessionRole(getStoredSessionUser());
  const canManage = currentRole === 'owner' || currentRole === 'admin';

  const [accounts, setAccounts] = useState<FinanceAccount[]>([]);
  const [summary, setSummary] = useState<FinanceSummaryResponse['data']['summary'] | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [pageError, setPageError] = useState('');
  const [formError, setFormError] = useState('');
  const [showModal, setShowModal] = useState(false);
  const [editingAccount, setEditingAccount] = useState<FinanceAccount | null>(null);
  const [formState, setFormState] = useState<AccountFormState>(initialFormState);
  const [historyAccount, setHistoryAccount] = useState<FinanceAccount | null>(null);
  const [ledgerEntries, setLedgerEntries] = useState<LedgerEntry[]>([]);
  const [showTransfer, setShowTransfer] = useState(false);
  const [transferForm, setTransferForm] = useState({ source_account_id: '', destination_account_id: '', amount: '', effective_date: new Date().toISOString().slice(0, 10), description: '', reference_number: '' });

  const loadAccounts = async () => {
    setIsLoading(true);
    setPageError('');

    try {
      const [accountsResponse, summaryResponse] = await Promise.all([
        apiRequest<FinanceAccountsResponse>('/finance/accounts'),
        apiRequest<FinanceSummaryResponse>('/finance/summary'),
      ]);
      setAccounts(Array.isArray(accountsResponse.data?.accounts) ? accountsResponse.data.accounts : []);
      setSummary(summaryResponse.data?.summary || null);
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setPageError(error.message);
      } else {
        setPageError('Unable to load finance accounts right now.');
      }
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (!canManage) {
      setIsLoading(false);
      return;
    }
    void loadAccounts();
  }, [canManage]);

  const groupedAccounts = useMemo(() => {
    return {
      bank: accounts.filter((account) => account.account_type === 'bank'),
      momo: accounts.filter((account) => account.account_type === 'momo'),
      cash: accounts.filter((account) => account.account_type === 'cash'),
    };
  }, [accounts]);

  const closeModal = () => {
    setShowModal(false);
    setEditingAccount(null);
    setFormError('');
    setFormState(initialFormState);
  };

  const openCreateModal = () => {
    setEditingAccount(null);
    setFormError('');
    setFormState(initialFormState);
    setShowModal(true);
  };

  const openEditModal = (account: FinanceAccount) => {
    setEditingAccount(account);
    setFormError('');
    setFormState({
      account_name: account.account_name,
      account_type: account.account_type,
      provider_name: account.provider_name || '',
      account_number: account.account_number || '',
      branch: account.branch || '',
      opening_balance: String(account.opening_balance || 0),
    });
    setShowModal(true);
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setIsSubmitting(true);
    setFormError('');

    const payload = {
      account_name: formState.account_name,
      account_type: formState.account_type,
      provider_name: formState.provider_name,
      account_number: formState.account_number,
      branch: formState.branch,
      opening_balance: Number(formState.opening_balance || 0),
    };

    try {
      if (editingAccount) {
        await apiRequest<FinanceAccountMutationResponse>(`/finance/accounts/${editingAccount.id}`, {
          method: 'PATCH',
          body: JSON.stringify({
            account_name: payload.account_name,
            account_type: payload.account_type,
            provider_name: payload.provider_name,
            account_number: payload.account_number,
            branch: payload.branch,
          }),
        });
      } else {
        await apiRequest<FinanceAccountMutationResponse>('/finance/accounts', {
          method: 'POST',
          body: JSON.stringify(payload),
        });
      }
      closeModal();
      await loadAccounts();
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setFormError(error.message);
      } else {
        setFormError('Unable to save finance account right now.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleStatusChange = async (account: FinanceAccount, status: FinanceAccountStatus) => {
    setPageError('');
    try {
      await apiRequest<FinanceAccountMutationResponse>(`/finance/accounts/${account.id}/status`, {
        method: 'PATCH',
        body: JSON.stringify({ status }),
      });
      await loadAccounts();
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setPageError(error.message);
      } else {
        setPageError('Unable to update finance account status right now.');
      }
    }
  };

  const openHistory = async (account: FinanceAccount) => {
    setHistoryAccount(account);
    try {
      const response = await apiRequest<{ data: { transactions: LedgerEntry[] } }>(`/finance/accounts/${account.id}/transactions`);
      setLedgerEntries(response.data.transactions || []);
    } catch (error) {
      setPageError(error instanceof ApiRequestError ? error.message : 'Unable to load account transactions.');
    }
  };

  const submitTransfer = async (event: React.FormEvent) => {
    event.preventDefault(); setIsSubmitting(true); setFormError('');
    try {
      await apiRequest('/finance/transfers', { method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() }, body: JSON.stringify({ ...transferForm, amount: Number(transferForm.amount) }) });
      setShowTransfer(false);
      setTransferForm({ source_account_id: '', destination_account_id: '', amount: '', effective_date: new Date().toISOString().slice(0, 10), description: '', reference_number: '' });
      await loadAccounts();
    } catch (error) {
      setFormError(error instanceof ApiRequestError ? error.message : 'Unable to post account transfer.');
    } finally { setIsSubmitting(false); }
  };

  if (!canManage) {
    return (
      <div className="p-6">
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          You do not have permission to manage Finance Accounts.
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-[#0F172A]">Finance Accounts</h1>
          <p className="mt-1 text-gray-600">
            Manage Axelera cash, MoMo, and bank treasury accounts from the immutable account ledger.
          </p>
        </div>
        <div className="flex flex-wrap gap-2"><button onClick={() => { setFormError(''); setShowTransfer(true); }} className="flex items-center gap-2 rounded-lg border px-4 py-2.5 font-medium"><ArrowRightLeft className="h-5 w-5" />Transfer</button><button
            onClick={openCreateModal}
            className="flex items-center gap-2 rounded-lg bg-[#2563EB] px-4 py-2.5 font-medium text-white transition-all hover:bg-[#1d4ed8]"
          ><Plus className="h-5 w-5" />Add Account</button></div>
      </div>

      {pageError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {pageError}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-xl border border-gray-200 bg-white p-5 md:col-span-1">
          <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-lg bg-slate-100">
            <Landmark className="h-5 w-5 text-slate-600" />
          </div>
          <div className="text-2xl font-semibold text-[#0F172A]">
            {formatCurrency(summary?.total_company_funds || 0)}
          </div>
          <div className="text-sm text-gray-600">Total Available Funds</div>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-lg bg-blue-100">
            <Building2 className="h-5 w-5 text-blue-600" />
          </div>
          <div className="text-2xl font-semibold text-[#0F172A]">
            {formatCurrency(summary?.bank_accounts_total || 0)}
          </div>
          <div className="text-sm text-gray-600">Bank Accounts</div>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-lg bg-emerald-100">
            <Wallet className="h-5 w-5 text-emerald-600" />
          </div>
          <div className="text-2xl font-semibold text-[#0F172A]">
            {formatCurrency(summary?.momo_accounts_total || 0)}
          </div>
          <div className="text-sm text-gray-600">MoMo Accounts</div>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-lg bg-amber-100">
            <Wallet className="h-5 w-5 text-amber-600" />
          </div>
          <div className="text-2xl font-semibold text-[#0F172A]">
            {formatCurrency(summary?.cash_accounts_total || 0)}
          </div>
          <div className="text-sm text-gray-600">Cash Accounts</div>
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center gap-3 rounded-xl border border-gray-200 bg-white px-6 py-16 text-gray-500">
          <Loader2 className="h-5 w-5 animate-spin" />
          <span>Loading finance accounts...</span>
        </div>
      ) : (
        <>
          {(['cash', 'momo', 'bank'] as FinanceAccountType[]).map((type) => (
            <div key={type} className="overflow-hidden rounded-xl border border-gray-200 bg-white">
              <div className="border-b border-gray-200 px-6 py-4">
                <h2 className="text-lg font-semibold text-[#0F172A]">{formatTypeLabel(type)} Accounts</h2>
                <p className="mt-1 text-sm text-gray-600">
                  {groupedAccounts[type].length} account{groupedAccounts[type].length === 1 ? '' : 's'} configured
                </p>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="border-b border-gray-200 bg-gray-50">
                    <tr>
                      <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Account</th>
                      <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Provider</th>
                      <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Account Number</th>
                      <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Opening</th>
                      <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Current</th>
                      <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Status</th>
                      <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200">
                    {groupedAccounts[type].map((account) => (
                      <tr key={account.id} className="transition-colors hover:bg-gray-50">
                        <td className="px-6 py-4">
                          <div className="font-medium text-[#0F172A]">{account.account_name}</div>
                          <div className="text-xs text-gray-500">{account.branch || 'No branch set'}</div>
                        </td>
                        <td className="px-6 py-4 text-gray-700">{account.provider_name || 'Not specified'}</td>
                        <td className="px-6 py-4 text-gray-700">{account.account_number || 'Not specified'}</td>
                        <td className="px-6 py-4 text-gray-700">{formatCurrency(account.opening_balance)}</td>
                        <td className="px-6 py-4 font-semibold text-[#0F172A]">{formatCurrency(account.current_balance)}</td>
                        <td className="px-6 py-4">
                          <span
                            className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${
                              account.status === 'active'
                                ? 'border-green-200 bg-green-100 text-green-800'
                                : 'border-gray-200 bg-gray-100 text-gray-700'
                            }`}
                          >
                            {account.status}
                          </span>
                        </td>
                        <td className="px-6 py-4">
                          <div className="flex items-center gap-2">
                            <button onClick={() => void openHistory(account)} className="rounded-lg border border-gray-300 p-2 text-gray-700" aria-label={`View ${account.account_name} transactions`}><History className="h-4 w-4" /></button>
                            <button
                              onClick={() => openEditModal(account)}
                              className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 transition-all hover:bg-gray-50"
                            >
                              Edit
                            </button>
                            <button
                              onClick={() =>
                                void handleStatusChange(account, account.status === 'active' ? 'inactive' : 'active')
                              }
                              className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-all ${
                                account.status === 'active'
                                  ? 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                                  : 'bg-green-100 text-green-700 hover:bg-green-200'
                              }`}
                            >
                              {account.status === 'active' ? 'Deactivate' : 'Activate'}
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {groupedAccounts[type].length === 0 && (
                  <div className="px-6 py-12 text-center text-gray-500">No {type} accounts created yet.</div>
                )}
              </div>
            </div>
          ))}
        </>
      )}

      {historyAccount && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"><div className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-xl bg-white p-5"><div className="flex items-center justify-between"><div><h2 className="text-xl font-semibold">{historyAccount.account_name}</h2><p className="text-sm text-gray-500">Balance {formatCurrency(historyAccount.current_balance)}</p></div><button onClick={() => setHistoryAccount(null)}><XCircle className="h-5 w-5" /></button></div><div className="mt-5 space-y-2">{ledgerEntries.map((entry) => <div key={entry.id} className="grid gap-2 rounded-lg border p-3 text-sm sm:grid-cols-[1fr_auto_auto]"><div><strong className="capitalize">{entry.source_type.replaceAll('_', ' ')}</strong><div className="text-xs text-gray-500">{entry.effective_date}{entry.description ? ` · ${entry.description}` : ''}</div></div><div className={entry.direction === 'credit' ? 'font-semibold text-green-700' : 'font-semibold text-red-700'}>{entry.direction === 'credit' ? '+' : '-'}{formatCurrency(entry.amount)}</div><div className="text-gray-600">Balance {formatCurrency(entry.balance_after)}</div></div>)}{!ledgerEntries.length && <div className="py-10 text-center text-gray-500">No transactions recorded.</div>}</div></div></div>}

      {showTransfer && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"><form onSubmit={submitTransfer} className="w-full max-w-2xl space-y-4 rounded-xl bg-white p-6"><div className="flex items-center justify-between"><h2 className="text-xl font-semibold">Transfer Between Accounts</h2><button type="button" onClick={() => setShowTransfer(false)}><XCircle className="h-5 w-5" /></button></div>{formError && <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{formError}</div>}<div className="grid gap-4 sm:grid-cols-2"><label className="text-sm">From<select required value={transferForm.source_account_id} onChange={(event) => setTransferForm((current) => ({ ...current, source_account_id: event.target.value }))} className="mt-1 min-h-11 w-full rounded-lg border px-3"><option value="">Source account...</option>{accounts.filter((item) => item.status === 'active').map((item) => <option key={item.id} value={item.id}>{item.account_name} · {formatCurrency(item.current_balance)}</option>)}</select></label><label className="text-sm">To<select required value={transferForm.destination_account_id} onChange={(event) => setTransferForm((current) => ({ ...current, destination_account_id: event.target.value }))} className="mt-1 min-h-11 w-full rounded-lg border px-3"><option value="">Destination account...</option>{accounts.filter((item) => item.status === 'active' && item.id !== transferForm.source_account_id).map((item) => <option key={item.id} value={item.id}>{item.account_name}</option>)}</select></label><label className="text-sm">Amount<input required min="0.01" step="0.01" type="number" value={transferForm.amount} onChange={(event) => setTransferForm((current) => ({ ...current, amount: event.target.value }))} className="mt-1 min-h-11 w-full rounded-lg border px-3" /></label><label className="text-sm">Effective date<input required type="date" value={transferForm.effective_date} onChange={(event) => setTransferForm((current) => ({ ...current, effective_date: event.target.value }))} className="mt-1 min-h-11 w-full rounded-lg border px-3" /></label></div><label className="block text-sm">Description<input required value={transferForm.description} onChange={(event) => setTransferForm((current) => ({ ...current, description: event.target.value }))} className="mt-1 min-h-11 w-full rounded-lg border px-3" /></label><label className="block text-sm">Reference<input value={transferForm.reference_number} onChange={(event) => setTransferForm((current) => ({ ...current, reference_number: event.target.value }))} className="mt-1 min-h-11 w-full rounded-lg border px-3" /></label><div className="flex justify-end gap-2"><button type="button" onClick={() => setShowTransfer(false)} className="rounded-lg border px-4 py-2.5">Cancel</button><button disabled={isSubmitting} className="rounded-lg bg-blue-600 px-4 py-2.5 text-white disabled:opacity-60">{isSubmitting ? 'Posting…' : 'Post Transfer'}</button></div></form></div>}

      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4">
          <div className="w-full max-w-2xl rounded-xl border border-gray-200 bg-white shadow-2xl">
            <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
              <h2 className="text-xl font-semibold text-[#0F172A]">
                {editingAccount ? 'Edit Finance Account' : 'Add Finance Account'}
              </h2>
              <button onClick={closeModal} className="rounded-lg p-2 transition-all hover:bg-gray-100">
                <XCircle className="h-5 w-5 text-gray-500" />
              </button>
            </div>

            <form onSubmit={handleSubmit} className="space-y-4 px-6 py-5">
              {formError && (
                <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                  {formError}
                </div>
              )}

              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div>
                  <label className="mb-2 block text-sm font-medium text-gray-700">Account Name</label>
                  <input
                    required
                    value={formState.account_name}
                    onChange={(event) => setFormState((current) => ({ ...current, account_name: event.target.value }))}
                    className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                  />
                </div>
                <div>
                  <label className="mb-2 block text-sm font-medium text-gray-700">Account Type</label>
                  <select
                    value={formState.account_type}
                    onChange={(event) =>
                      setFormState((current) => ({
                        ...current,
                        account_type: event.target.value as FinanceAccountType,
                      }))
                    }
                    className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                  >
                    <option value="bank">Bank</option>
                    <option value="momo">MoMo</option>
                    <option value="cash">Cash</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div>
                  <label className="mb-2 block text-sm font-medium text-gray-700">Provider Name</label>
                  <input
                    value={formState.provider_name}
                    onChange={(event) => setFormState((current) => ({ ...current, provider_name: event.target.value }))}
                    className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                  />
                </div>
                <div>
                  <label className="mb-2 block text-sm font-medium text-gray-700">Account Number</label>
                  <input
                    value={formState.account_number}
                    onChange={(event) => setFormState((current) => ({ ...current, account_number: event.target.value }))}
                    className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div>
                  <label className="mb-2 block text-sm font-medium text-gray-700">Branch</label>
                  <input
                    value={formState.branch}
                    onChange={(event) => setFormState((current) => ({ ...current, branch: event.target.value }))}
                    className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                  />
                </div>
                <div>
                  <label className="mb-2 block text-sm font-medium text-gray-700">Opening Balance</label>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    required={!editingAccount}
                    disabled={Boolean(editingAccount)}
                    value={formState.opening_balance}
                    onChange={(event) => setFormState((current) => ({ ...current, opening_balance: event.target.value }))}
                    className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB] disabled:bg-gray-100"
                  />
                </div>
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
                  {isSubmitting ? 'Saving...' : editingAccount ? 'Save Changes' : 'Create Account'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
