import { useEffect, useMemo, useState } from 'react';
import { Download, Pencil, Plus, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import {
  deletePrivateFinanceEntry, downloadPrivateFinance, fetchPrivateFinance,
  fetchPrivateFinanceSummary, savePrivateFinanceEntry,
  type PrivateFinanceEntry, type PrivateFinancePlatform, type PrivateFinanceSummary,
} from '../../lib/private-finance-api';

const platforms: PrivateFinancePlatform[] = ['bolt', 'uber', 'yango', 'indrive', 'other', 'multiple'];
const moneyFields = [
  ['cash_sales', 'Cash sales'], ['digital_sales', 'Mobile-money / digital sales'], ['other_sales', 'Other sales'],
  ['platform_fees', 'Platform fees / commission'], ['fuel_paid_personally', 'Fuel paid personally'],
  ['parking', 'Parking'], ['tolls', 'Tolls'], ['washing', 'Washing'],
  ['repairs_paid_personally', 'Repairs paid personally'], ['other_expenses', 'Other expenses'],
] as const;
const blankForm = Object.fromEntries(moneyFields.map(([key]) => [key, ''])) as Record<string, string>;

function money(value: number) { return `GHS ${Number(value || 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}`; }
function monthStart() { const value = new Date(); value.setDate(1); return value.toISOString().slice(0, 10); }

export default function MyEarnings() {
  const [records, setRecords] = useState<PrivateFinanceEntry[]>([]);
  const [summary, setSummary] = useState<PrivateFinanceSummary | null>(null);
  const [filters, setFilters] = useState({ start_date: monthStart(), end_date: new Date().toISOString().slice(0, 10), platform: '', period: 'daily' });
  const [editing, setEditing] = useState<PrivateFinanceEntry | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ date: new Date().toISOString().slice(0, 10), platform: 'bolt', ...blankForm, notes: '' });

  const load = async () => {
    const requestFilters = { ...filters, platform: filters.platform || undefined };
    const [list, totals] = await Promise.all([fetchPrivateFinance(requestFilters), fetchPrivateFinanceSummary(requestFilters)]);
    setRecords(list.records); setSummary(totals);
  };
  useEffect(() => { void load().catch((error) => toast.error(error.message)); }, [filters.start_date, filters.end_date, filters.platform, filters.period]);

  const calculated = useMemo(() => {
    const value = (key: string) => Number(form[key] || 0);
    const gross = value('cash_sales') + value('digital_sales') + value('other_sales');
    const expenses = value('fuel_paid_personally') + value('parking') + value('tolls') + value('washing') + value('repairs_paid_personally') + value('other_expenses');
    return { gross, expenses, net: gross - value('platform_fees') - expenses };
  }, [form]);

  const openCreate = () => { setEditing(null); setForm({ date: new Date().toISOString().slice(0, 10), platform: 'bolt', ...blankForm, notes: '' }); setShowForm(true); };
  const openEdit = (entry: PrivateFinanceEntry) => {
    setEditing(entry);
    setForm({ date: entry.date, platform: entry.platform, ...Object.fromEntries(moneyFields.map(([key]) => [key, String(entry[key] || '')])), notes: entry.notes || '' });
    setShowForm(true);
  };
  const submit = async (event: React.FormEvent) => {
    event.preventDefault(); setBusy(true);
    try {
      const payload = { ...form, ...Object.fromEntries(moneyFields.map(([key]) => [key, Number(form[key] || 0)])) };
      await savePrivateFinanceEntry(payload, editing?.id); setShowForm(false); await load(); toast.success(editing ? 'Entry updated.' : 'Entry saved privately.');
    } catch (error) { toast.error(error instanceof Error ? error.message : 'Could not save entry.'); }
    finally { setBusy(false); }
  };
  const remove = async (entry: PrivateFinanceEntry) => {
    if (!window.confirm(`Delete the private earnings entry for ${entry.date}?`)) return;
    try { await deletePrivateFinanceEntry(entry.id); await load(); toast.success('Entry deleted.'); }
    catch (error) { toast.error(error instanceof Error ? error.message : 'Could not delete entry.'); }
  };

  return <div className="space-y-6 p-4 sm:p-6">
    <div className="rounded-xl bg-slate-900 p-6 text-white"><div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between"><div><h1 className="text-2xl font-semibold">My Earnings</h1><p className="mt-1 text-sm text-slate-300">Your private ride-platform ledger. These figures are never included in company or fleet reports.</p></div><div className="flex gap-2"><button onClick={() => void downloadPrivateFinance({ ...filters, platform: filters.platform || undefined })} className="flex items-center gap-2 rounded-lg border border-slate-600 px-4 py-2"><Download className="h-4 w-4" /> Export</button><button onClick={openCreate} className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2"><Plus className="h-4 w-4" /> Add entry</button></div></div></div>
    <div className="grid gap-3 rounded-xl border bg-white p-4 md:grid-cols-4"><input type="date" value={filters.start_date} onChange={(e) => setFilters({ ...filters, start_date: e.target.value })} className="rounded-lg border p-2"/><input type="date" value={filters.end_date} onChange={(e) => setFilters({ ...filters, end_date: e.target.value })} className="rounded-lg border p-2"/><select value={filters.platform} onChange={(e) => setFilters({ ...filters, platform: e.target.value })} className="rounded-lg border p-2"><option value="">All platforms</option>{platforms.map((item) => <option key={item} value={item}>{item}</option>)}</select><select value={filters.period} onChange={(e) => setFilters({ ...filters, period: e.target.value })} className="rounded-lg border p-2"><option value="daily">Daily trend</option><option value="weekly">Weekly trend</option><option value="monthly">Monthly trend</option></select></div>
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{[['Gross sales', summary?.gross_sales || 0], ['Platform deductions', summary?.total_platform_deductions || 0], ['Personal expenses', summary?.total_personal_expenses || 0], ['Net earnings', summary?.driver_net_earnings || 0]].map(([label, value]) => <div key={String(label)} className="rounded-xl border bg-white p-5"><div className="text-sm text-slate-500">{label}</div><div className="mt-2 text-2xl font-semibold">{money(Number(value))}</div></div>)}</div>
    {summary?.trend?.length ? <div className="rounded-xl border bg-white p-5"><h2 className="font-semibold">Earnings trend</h2><div className="mt-4 flex h-36 items-end gap-2 overflow-x-auto">{summary.trend.map((row) => { const max = Math.max(...summary.trend.map((item) => Math.max(item.net_earnings, 0)), 1); return <div key={row.period} className="flex min-w-14 flex-1 flex-col items-center gap-1"><div title={money(row.net_earnings)} className="w-full rounded-t bg-blue-500" style={{ height: `${Math.max(4, (Math.max(row.net_earnings, 0) / max) * 100)}px` }} /><span className="text-xs text-slate-500">{row.period}</span></div>; })}</div></div> : null}
    <div className="overflow-hidden rounded-xl border bg-white"><div className="overflow-x-auto"><table className="w-full min-w-[760px] text-sm"><thead className="bg-slate-50"><tr>{['Date', 'Platform', 'Gross', 'Deductions', 'Expenses', 'Net', ''].map((item) => <th key={item} className="px-4 py-3 text-left">{item}</th>)}</tr></thead><tbody className="divide-y">{records.map((entry) => <tr key={entry.id}><td className="px-4 py-3">{entry.date}</td><td className="px-4 py-3 capitalize">{entry.platform}</td><td className="px-4 py-3">{money(entry.gross_sales)}</td><td className="px-4 py-3">{money(entry.total_platform_deductions)}</td><td className="px-4 py-3">{money(entry.total_personal_expenses)}</td><td className="px-4 py-3 font-semibold">{money(entry.driver_net_earnings)}</td><td className="px-4 py-3"><div className="flex gap-2"><button onClick={() => openEdit(entry)} aria-label="Edit entry"><Pencil className="h-4 w-4" /></button><button onClick={() => void remove(entry)} aria-label="Delete entry" className="text-red-600"><Trash2 className="h-4 w-4" /></button></div></td></tr>)}</tbody></table>{!records.length && <div className="p-10 text-center text-slate-500">No private earnings entries for this period.</div>}</div></div>
    {showForm && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"><form onSubmit={submit} className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-xl bg-white p-6"><div className="flex items-center justify-between"><h2 className="text-xl font-semibold">{editing ? 'Edit earnings entry' : 'Add earnings entry'}</h2><button type="button" onClick={() => setShowForm(false)}>Close</button></div><div className="mt-5 grid gap-4 sm:grid-cols-2"><label className="text-sm">Date<input required type="date" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} className="mt-1 w-full rounded-lg border p-2" /></label><label className="text-sm">Platform<select value={form.platform} onChange={(e) => setForm({ ...form, platform: e.target.value })} className="mt-1 w-full rounded-lg border p-2">{platforms.map((item) => <option key={item}>{item}</option>)}</select></label>{moneyFields.map(([key, label]) => <label key={key} className="text-sm">{label}<input min="0" step="0.01" type="number" value={form[key]} onChange={(e) => setForm({ ...form, [key]: e.target.value })} className="mt-1 w-full rounded-lg border p-2" /></label>)}</div><label className="mt-4 block text-sm">Notes<textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} className="mt-1 w-full rounded-lg border p-2" rows={3} /></label><div className="mt-4 grid gap-2 rounded-lg bg-slate-50 p-4 text-sm sm:grid-cols-3"><span>Gross: <b>{money(calculated.gross)}</b></span><span>Expenses: <b>{money(calculated.expenses)}</b></span><span>Net: <b>{money(calculated.net)}</b></span></div><div className="mt-5 flex justify-end gap-2"><button type="button" onClick={() => setShowForm(false)} className="rounded-lg border px-4 py-2">Cancel</button><button disabled={busy} className="rounded-lg bg-blue-600 px-4 py-2 text-white disabled:opacity-50">{busy ? 'Saving…' : 'Save privately'}</button></div></form></div>}
  </div>;
}
