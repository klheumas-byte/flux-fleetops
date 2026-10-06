import { useEffect, useMemo, useState } from 'react';
import { Banknote, Loader2, Smartphone, TrendingUp, WalletCards } from 'lucide-react';
import { toast } from 'sonner';
import { fetchDriverEarnings, type DriverEarningsResponse } from '../../lib/ride-masterdata-api';

type Period = 'today' | 'week' | 'month' | 'custom';

function money(value: number) {
  return `GHS ${Number(value || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
function today() { return new Date().toISOString().slice(0, 10); }
function monthStart() { const value = new Date(); value.setDate(1); return value.toISOString().slice(0, 10); }

export default function MyEarnings() {
  const [data, setData] = useState<DriverEarningsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [period, setPeriod] = useState<Period>('month');
  const [startDate, setStartDate] = useState(monthStart());
  const [endDate, setEndDate] = useState(today());
  const [source, setSource] = useState('');
  const [paymentMethod, setPaymentMethod] = useState('');
  const [page, setPage] = useState(1);

  useEffect(() => {
    let active = true;
    setLoading(true);
    fetchDriverEarnings({
      period,
      start_date: period === 'custom' ? startDate : undefined,
      end_date: period === 'custom' ? endDate : undefined,
      source: source || undefined,
      payment_method: (paymentMethod || undefined) as 'Cash' | 'MoMo' | undefined,
      page,
      limit: 25,
    }).then((result) => { if (active) setData(result); })
      .catch((error) => { if (active) toast.error(error instanceof Error ? error.message : 'Unable to load earnings.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [period, startDate, endDate, source, paymentMethod, page]);

  const maxTrend = useMemo(() => Math.max(...(data?.trend.map((row) => row.net_earnings) || [0]), 1), [data?.trend]);
  const summary = data?.summary;
  const cards = [
    { label: 'Gross Earnings', value: summary?.gross_earnings || 0, icon: WalletCards, tone: 'bg-blue-50 text-blue-700' },
    { label: 'Platform Fees', value: summary?.platform_fees || 0, icon: TrendingUp, tone: 'bg-amber-50 text-amber-700' },
    { label: 'Net Earnings', value: summary?.net_earnings || 0, icon: Banknote, tone: 'bg-emerald-50 text-emerald-700' },
    { label: 'Cash', value: summary?.cash || 0, icon: Banknote, tone: 'bg-slate-100 text-slate-700' },
    { label: 'MoMo', value: summary?.momo || 0, icon: Smartphone, tone: 'bg-purple-50 text-purple-700' },
  ];

  return <div className="space-y-5 p-4 sm:p-6">
    <header className="rounded-2xl bg-slate-900 p-5 text-white sm:p-6">
      <h1 className="text-2xl font-semibold">My Earnings</h1>
      <p className="mt-1 max-w-3xl text-sm text-slate-300">Private earnings from your completed trip logs. These amounts never affect remittance, arrears, credit, or company finance.</p>
    </header>

    <section className="space-y-4 rounded-xl border bg-white p-4">
      <div className="flex flex-wrap gap-2">
        {(['today', 'week', 'month', 'custom'] as Period[]).map((item) => <button key={item} type="button" onClick={() => { setPeriod(item); setPage(1); }} className={`min-h-10 rounded-lg px-4 text-sm font-medium ${period === item ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'}`}>{item === 'week' ? 'This Week' : item === 'month' ? 'This Month' : item === 'custom' ? 'Custom Range' : 'Today'}</button>)}
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {period === 'custom' && <>
          <label className="text-sm text-slate-600">From<input type="date" value={startDate} max={endDate} onChange={(event) => { setStartDate(event.target.value); setPage(1); }} className="mt-1 block min-h-11 w-full rounded-lg border px-3" /></label>
          <label className="text-sm text-slate-600">To<input type="date" value={endDate} min={startDate} onChange={(event) => { setEndDate(event.target.value); setPage(1); }} className="mt-1 block min-h-11 w-full rounded-lg border px-3" /></label>
        </>}
        <label className="text-sm text-slate-600">Platform<select value={source} onChange={(event) => { setSource(event.target.value); setPage(1); }} className="mt-1 block min-h-11 w-full rounded-lg border px-3"><option value="">All platforms</option>{data?.filters.sources.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
        <label className="text-sm text-slate-600">Payment method<select value={paymentMethod} onChange={(event) => { setPaymentMethod(event.target.value); setPage(1); }} className="mt-1 block min-h-11 w-full rounded-lg border px-3"><option value="">Cash &amp; MoMo</option><option value="Cash">Cash</option><option value="MoMo">MoMo</option></select></label>
      </div>
    </section>

    <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
      {cards.map(({ label, value, icon: Icon, tone }) => <article key={label} className="rounded-xl border bg-white p-4"><div className={`inline-flex rounded-lg p-2 ${tone}`}><Icon className="h-5 w-5" /></div><div className="mt-3 text-sm text-slate-500">{label}</div><div className="mt-1 text-xl font-semibold text-slate-900">{money(value)}</div></article>)}
    </section>

    <section className="rounded-xl border bg-white p-4 sm:p-5">
      <div className="flex items-center justify-between"><h2 className="font-semibold text-slate-900">Earnings trend</h2><span className="text-xs text-slate-500">{summary?.trip_count || 0} completed trips</span></div>
      {loading ? <div className="flex h-44 items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-blue-600" /></div> : data?.trend.length ? <div className="mt-5 flex h-44 items-end gap-2 overflow-x-auto pb-6">
        {data.trend.map((row) => <div key={row.date} className="flex min-w-14 flex-1 flex-col items-center justify-end gap-1"><span className="text-[10px] text-slate-500">{money(row.net_earnings)}</span><div title={`${row.date}: ${money(row.net_earnings)} net`} className="w-full max-w-16 rounded-t bg-blue-500" style={{ height: `${Math.max(5, (Math.max(row.net_earnings, 0) / maxTrend) * 110)}px` }} /><span className="whitespace-nowrap text-[10px] text-slate-500">{row.date.slice(5)}</span></div>)}
      </div> : <div className="flex h-44 items-center justify-center text-sm text-slate-500">No completed trips with an Amount Charged in this period.</div>}
    </section>

    <section className="overflow-hidden rounded-xl border bg-white">
      <div className="border-b px-4 py-4 sm:px-5"><h2 className="font-semibold text-slate-900">Earnings transactions</h2><p className="text-xs text-slate-500">One row per trip; no separate finance entry is created.</p></div>
      <div className="hidden overflow-x-auto md:block"><table className="w-full min-w-[850px] text-sm"><thead className="bg-slate-50 text-left text-slate-600"><tr>{['Trip / Date', 'Platform', 'Payment', 'Gross', 'Fee', 'Net', 'Route'].map((label) => <th key={label} className="px-4 py-3 font-medium">{label}</th>)}</tr></thead><tbody className="divide-y">{data?.transactions.map((row) => <tr key={row.id}><td className="px-4 py-3"><div className="font-medium">{row.trip_id || 'Trip'}</div><div className="text-xs text-slate-500">{row.trip_date}{row.end_time ? ` · ${row.end_time}` : ''}</div></td><td className="px-4 py-3">{row.source || 'Not specified'}</td><td className="px-4 py-3">{row.payment_method || 'Not specified'}</td><td className="px-4 py-3">{money(row.gross_earnings)}</td><td className="px-4 py-3 text-amber-700">{money(row.platform_fee)}</td><td className="px-4 py-3 font-semibold text-emerald-700">{money(row.net_earnings)}</td><td className="max-w-56 truncate px-4 py-3 text-slate-600">{row.pickup_area || '—'} → {row.destination_area || '—'}</td></tr>)}</tbody></table></div>
      <div className="divide-y md:hidden">{data?.transactions.map((row) => <article key={row.id} className="space-y-3 p-4"><div className="flex items-start justify-between gap-3"><div><div className="font-medium">{row.trip_id || 'Trip'}</div><div className="text-xs text-slate-500">{row.trip_date}{row.end_time ? ` · ${row.end_time}` : ''}</div></div><div className="font-semibold text-emerald-700">{money(row.net_earnings)}</div></div><div className="grid grid-cols-2 gap-2 text-xs"><div><span className="text-slate-500">Platform</span><strong className="block">{row.source || 'Not specified'}</strong></div><div><span className="text-slate-500">Payment</span><strong className="block">{row.payment_method || 'Not specified'}</strong></div><div><span className="text-slate-500">Gross</span><strong className="block">{money(row.gross_earnings)}</strong></div><div><span className="text-slate-500">Platform fee</span><strong className="block">{money(row.platform_fee)}</strong></div></div></article>)}</div>
      {!loading && !data?.transactions.length && <div className="p-10 text-center text-sm text-slate-500">No earnings transactions match these filters.</div>}
      {data && data.pagination.total_pages > 1 && <div className="flex items-center justify-between border-t px-4 py-3 text-sm"><button disabled={!data.pagination.has_prev} onClick={() => setPage((value) => Math.max(value - 1, 1))} className="rounded-lg border px-3 py-2 disabled:opacity-40">Previous</button><span>Page {data.pagination.page} of {data.pagination.total_pages}</span><button disabled={!data.pagination.has_next} onClick={() => setPage((value) => value + 1)} className="rounded-lg border px-3 py-2 disabled:opacity-40">Next</button></div>}
    </section>
  </div>;
}
