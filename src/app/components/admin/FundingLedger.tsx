import { useEffect, useState } from 'react';
import { Loader2, Plus } from 'lucide-react';
import { apiRequest, ApiRequestError } from '../../lib/api';

interface Source { id: string; name: string; active: boolean }
interface Account { id: string; account_name: string; account_type: 'cash' | 'momo' | 'bank'; provider_name?: string | null; account_number?: string | null; status: string }
interface Contribution { id: string; amount: number; contribution_date: string; description: string; funding_source_snapshot?: { name: string }; finance_account_snapshot?: { account_name: string } }
interface Position { money_in: number; expenses_out: number; net_funding_position: number; sources: Array<{ funding_source_id: string; funding_source?: { name: string }; money_in: number; expenses_out: number; net_position: number }> }
interface ReconciliationRow { driver: { id: string; full_name: string }; gross_collections: number; amount_submitted: number; target: number; target_achievement_percentage: number; fleet_sales_funded_expenses: number; expected_cash_submission: number; outstanding_unsubmitted_amount: number; net_operating_position: number; submission_history: Array<{ id: string; collection_date: string; status: string; amount: number; submitted_amount?: number }>; expenses: Array<{ id: string; expense_date: string; expense_category: string; amount: number; funding_source_snapshot?: { name: string }; approved_by?: string }> }

const today = new Date().toISOString().slice(0, 10);
const money = (value = 0) => `GHS ${value.toLocaleString(undefined, { minimumFractionDigits: 2 })}`;
const accountLabel = (account: Account) => `${account.account_name} · ${account.account_type.toUpperCase()}${account.provider_name ? ` · ${account.provider_name}` : ''}${account.account_number ? ` · ••••${account.account_number.slice(-4)}` : ''}`;

export default function FundingLedger() {
  const [sources, setSources] = useState<Source[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [contributions, setContributions] = useState<Contribution[]>([]);
  const [position, setPosition] = useState<Position | null>(null);
  const [reconciliation, setReconciliation] = useState<ReconciliationRow[]>([]);
  const [period, setPeriod] = useState<'this_week' | 'last_week' | 'custom'>('this_week');
  const [customStart, setCustomStart] = useState(today);
  const [customEnd, setCustomEnd] = useState(today);
  const [form, setForm] = useState({ funding_source_id: '', funding_source_description: '', finance_account_id: '', amount: '', contribution_date: today, description: '', reference_number: '', notes: '' });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const load = async () => {
    setLoading(true); setError('');
    try {
      const periodQuery = period === 'custom' ? `start_date=${customStart}&end_date=${customEnd}` : `period=${period}`;
      const [sourceResponse, accountResponse, contributionResponse, positionResponse, reconciliationResponse] = await Promise.all([
        apiRequest<{ data: { funding_sources: Source[] } }>('/finance/funding-sources'),
        apiRequest<{ data: { accounts: Account[] } }>('/finance/accounts'),
        apiRequest<{ data: { contributions: Contribution[] } }>('/finance/contributions'),
        apiRequest<{ data: { position: Position } }>('/finance/funding-position'),
        apiRequest<{ data: { drivers: ReconciliationRow[] } }>(`/finance/reconciliation?${periodQuery}`),
      ]);
      const nextSources = sourceResponse.data.funding_sources || []; const nextAccounts = accountResponse.data.accounts || [];
      setSources(nextSources); setAccounts(nextAccounts); setContributions(contributionResponse.data.contributions || []); setPosition(positionResponse.data.position || null);
      setReconciliation(reconciliationResponse.data.drivers || []);
      setForm((current) => ({ ...current, funding_source_id: current.funding_source_id || nextSources[0]?.id || '', finance_account_id: current.finance_account_id || nextAccounts.find((item) => item.status === 'active')?.id || '' }));
    } catch (caught) { setError(caught instanceof ApiRequestError ? caught.message : 'Unable to load funding ledger.'); }
    finally { setLoading(false); }
  };
  useEffect(() => { void load(); }, [period, customStart, customEnd]);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault(); setSaving(true); setError(''); setSuccess('');
    try {
      await apiRequest('/finance/contributions', { method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() }, body: JSON.stringify({ ...form, amount: Number(form.amount) }) });
      setSuccess('Funding contribution recorded successfully.');
      setForm((current) => ({ ...current, amount: '', description: '', reference_number: '', notes: '', funding_source_description: '' }));
      await load();
    } catch (caught) { setError(caught instanceof ApiRequestError ? caught.message : 'Unable to record funding contribution.'); }
    finally { setSaving(false); }
  };
  const selectedSource = sources.find((item) => item.id === form.funding_source_id);

  return <div className="space-y-6 p-4 sm:p-6">
    <div><h1 className="text-2xl font-semibold text-slate-900">Funding & Source Ledger</h1><p className="text-gray-600">Record non-sales funding and report money in, expenses out, and net source position.</p></div>
    {error && <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}
    {success && <div className="rounded-lg border border-green-200 bg-green-50 p-3 text-sm text-green-700">{success}</div>}
    {loading ? <div className="flex gap-2 p-8 text-gray-500"><Loader2 className="animate-spin" /> Loading finance sources...</div> : <>
      <div className="grid gap-4 md:grid-cols-3">{[['Money In', position?.money_in], ['Expenses Out', position?.expenses_out], ['Net Funding Position', position?.net_funding_position]].map(([label, value]) => <div key={String(label)} className="rounded-xl border bg-white p-5"><div className="text-sm text-gray-500">{label}</div><div className="text-2xl font-semibold">{money(Number(value || 0))}</div></div>)}</div>
      <div className="space-y-4 rounded-xl border bg-white p-5">
        <div className="flex flex-wrap items-end justify-between gap-3"><div><h2 className="text-lg font-semibold">Driver Collection Reconciliation</h2><p className="text-sm text-gray-500">Gross collections remain unchanged; only Driver Collection-funded expenses adjust expected cash.</p></div><div className="flex flex-wrap gap-2"><select value={period} onChange={(event) => setPeriod(event.target.value as typeof period)} className="rounded-lg border p-2"><option value="this_week">This Week</option><option value="last_week">Last Week</option><option value="custom">Custom Period</option></select>{period === 'custom' && <><input type="date" value={customStart} onChange={(e) => setCustomStart(e.target.value)} className="rounded-lg border p-2" /><input type="date" value={customEnd} onChange={(e) => setCustomEnd(e.target.value)} className="rounded-lg border p-2" /></>}</div></div>
        <div className="overflow-x-auto"><table className="w-full text-sm"><thead className="bg-gray-50"><tr>{['Driver', 'Gross', 'Submitted', 'Target', 'Achievement', 'Collection-funded', 'Expected cash', 'Outstanding', 'Net'].map((item) => <th key={item} className="p-2 text-left">{item}</th>)}</tr></thead><tbody>{reconciliation.map((row) => <tr key={row.driver.id} className="border-t align-top"><td className="p-2"><details><summary className="cursor-pointer font-medium">{row.driver.full_name}</summary><div className="mt-2 min-w-80 space-y-2 text-xs"><div className="font-semibold">Submissions</div>{row.submission_history.map((item) => <div key={item.id}>{item.collection_date}: {money(item.submitted_amount ?? item.amount)} · {item.status}</div>)}<div className="pt-1 font-semibold">Expenses</div>{row.expenses.map((item) => <div key={item.id}>{item.expense_date}: {item.expense_category} · {item.funding_source_snapshot?.name || 'Legacy'} · {money(item.amount)}</div>)}</div></details></td><td className="p-2">{money(row.gross_collections)}</td><td className="p-2">{money(row.amount_submitted)}</td><td className="p-2">{money(row.target)}</td><td className="p-2">{row.target_achievement_percentage}%</td><td className="p-2">{money(row.fleet_sales_funded_expenses)}</td><td className="p-2">{money(row.expected_cash_submission)}</td><td className="p-2">{money(row.outstanding_unsubmitted_amount)}</td><td className="p-2">{money(row.net_operating_position)}</td></tr>)}</tbody></table></div>
      </div>
      <form onSubmit={submit} className="grid gap-4 rounded-xl border bg-white p-5 md:grid-cols-2">
        <h2 className="md:col-span-2 text-lg font-semibold">Record Funding Contribution</h2>
        <select required value={form.funding_source_id} onChange={(e) => setForm({ ...form, funding_source_id: e.target.value })} className="rounded-lg border p-2.5"><option value="">Funding source...</option>{sources.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select>
        <select required value={form.finance_account_id} onChange={(e) => setForm({ ...form, finance_account_id: e.target.value })} className="rounded-lg border p-2.5"><option value="">Destination treasury account...</option>{accounts.filter((item) => item.status === 'active').map((item) => <option key={item.id} value={item.id}>{accountLabel(item)}</option>)}</select>
        {selectedSource?.name.toLowerCase() === 'other' && <input required placeholder="Describe other funding source" value={form.funding_source_description} onChange={(e) => setForm({ ...form, funding_source_description: e.target.value })} className="rounded-lg border p-2.5" />}
        <input required type="number" min="0.01" step="0.01" placeholder="Amount" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} className="rounded-lg border p-2.5" />
        <input required type="date" value={form.contribution_date} onChange={(e) => setForm({ ...form, contribution_date: e.target.value })} className="rounded-lg border p-2.5" />
        <input required placeholder="Description" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} className="rounded-lg border p-2.5" />
        <input placeholder="Optional reference" value={form.reference_number} onChange={(e) => setForm({ ...form, reference_number: e.target.value })} className="rounded-lg border p-2.5" />
        <button disabled={saving} className="flex items-center justify-center gap-2 rounded-lg bg-blue-600 p-2.5 font-medium text-white disabled:opacity-60">{saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}{saving ? 'Recording...' : 'Record Contribution'}</button>
      </form>
      <div className="overflow-x-auto rounded-xl border bg-white"><table className="w-full text-sm"><thead className="bg-gray-50"><tr>{['Date', 'Source', 'Account', 'Description', 'Amount'].map((item) => <th key={item} className="p-3 text-left">{item}</th>)}</tr></thead><tbody>{contributions.map((item) => <tr key={item.id} className="border-t"><td className="p-3">{item.contribution_date}</td><td className="p-3">{item.funding_source_snapshot?.name}</td><td className="p-3">{item.finance_account_snapshot?.account_name}</td><td className="p-3">{item.description}</td><td className="p-3 font-medium">{money(item.amount)}</td></tr>)}</tbody></table></div>
    </>}
  </div>;
}
