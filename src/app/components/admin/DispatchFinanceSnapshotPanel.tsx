import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, Loader2, Plus, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { apiRequest } from '../../lib/api';
import {
  approveDispatchFinanceSnapshot,
  finalizeDispatchFinanceSnapshot,
  previewDispatchFinance,
  type DispatchFinanceSnapshot,
  type DispatchFinancialDetail,
  type DispatchPricingType,
} from '../../lib/dispatch-financial-api';

type Props = { detail: DispatchFinancialDetail; onChanged: () => Promise<void> };
type Adjustment = { category: string; reason: string; mode: 'amount' | 'percentage'; value: string };
const money = (value?: number | null) => `GHS ${Number(value || 0).toLocaleString()}`;

export default function DispatchFinanceSnapshotPanel({ detail, onChanged }: Props) {
  const jobId = detail.job?.id || detail.record.dispatch_job_id;
  const approved = detail.record.finance_snapshot || null;
  const finalSnapshot = detail.record.final_finance_snapshot || null;
  const [sources, setSources] = useState<Array<{ id: string; name: string }>>([]);
  const [pricingType, setPricingType] = useState<DispatchPricingType>(approved?.pricing_type || 'standard');
  const [commercial, setCommercial] = useState(String(approved?.commercial_value ?? detail.record.approved_charge ?? 0));
  const [charge, setCharge] = useState(String(approved?.customer_charge ?? detail.record.approved_charge ?? 0));
  const [fundingSourceId, setFundingSourceId] = useState(approved?.funding_source?.id || '');
  const [fundingDescription, setFundingDescription] = useState(approved?.funding_source?.description || '');
  const [billableKm, setBillableKm] = useState(String(approved?.billable_distance_km ?? 0));
  const [operationalKm, setOperationalKm] = useState(String(approved?.operational_distance_km ?? 0));
  const [compMode, setCompMode] = useState<'amount' | 'percentage'>(approved?.driver_compensation.mode || 'amount');
  const [compValue, setCompValue] = useState(String(approved?.driver_compensation.value ?? 0));
  const [suggested, setSuggested] = useState(String(approved?.driver_compensation.suggested_amount ?? 0));
  const [otherCosts, setOtherCosts] = useState(String(approved?.other_direct_costs ?? 0));
  const [actualFuelCost, setActualFuelCost] = useState('');
  const [durationMinutes, setDurationMinutes] = useState('');
  const [actualStops, setActualStops] = useState('');
  const [waitingMinutes, setWaitingMinutes] = useState('');
  const [journeyNotes, setJourneyNotes] = useState('');
  const [adjustments, setAdjustments] = useState<Adjustment[]>([]);
  const [preview, setPreview] = useState<DispatchFinanceSnapshot | null>(approved);
  const [busy, setBusy] = useState('');
  const [overrideReason, setOverrideReason] = useState('');

  useEffect(() => {
    apiRequest<{ data: { funding_sources: Array<{ id: string; name: string }> } }>('/finance/funding-sources')
      .then((response) => setSources(response.data.funding_sources || []))
      .catch(() => setSources([]));
  }, []);

  useEffect(() => {
    if (pricingType === 'complimentary') setCharge('0');
    if (pricingType === 'standard') setCharge(commercial);
  }, [pricingType, commercial]);

  const payload = useMemo(() => ({
    pricing_type: pricingType, commercial_value: Number(commercial || 0), customer_charge: Number(charge || 0),
    funding_source_id: fundingSourceId || undefined, funding_source_description: fundingDescription || undefined,
    billable_distance_km: Number(billableKm || 0), operational_distance_km: Number(operationalKm || 0),
    driver_compensation_mode: compMode, driver_compensation_value: Number(compValue || 0),
    suggested_driver_compensation: Number(suggested || 0), driver_adjustments: adjustments.map((item) => ({ ...item, value: Number(item.value || 0) })),
    other_direct_costs: Number(otherCosts || 0), pricing_override: Boolean(overrideReason), pricing_override_reason: overrideReason || undefined,
  }), [pricingType, commercial, charge, fundingSourceId, fundingDescription, billableKm, operationalKm, compMode, compValue, suggested, adjustments, otherCosts, overrideReason]);

  const execute = async (kind: 'preview' | 'approve' | 'finalize') => {
    setBusy(kind);
    try {
      const result = kind === 'preview' ? await previewDispatchFinance(jobId, payload)
        : kind === 'approve' ? await approveDispatchFinanceSnapshot(jobId, payload)
        : await finalizeDispatchFinanceSnapshot(jobId, {
            actual_billable_distance_km: Number(billableKm || 0), actual_operational_distance_km: Number(operationalKm || 0),
            actual_fuel_cost: actualFuelCost === '' ? undefined : Number(actualFuelCost),
            driver_compensation_mode: compMode, driver_compensation_value: Number(compValue || 0), driver_adjustments: payload.driver_adjustments,
            suggested_driver_compensation: Number(suggested || 0), actual_other_direct_costs: Number(otherCosts || 0),
            journey_evidence: { duration_minutes:Number(durationMinutes||0), stops:Number(actualStops||0), waiting_minutes:Number(waitingMinutes||0), notes:journeyNotes||undefined },
          });
      setPreview(result);
      toast.success(kind === 'preview' ? 'Finance preview updated.' : kind === 'approve' ? 'Immutable finance snapshot approved.' : 'Actual finance confirmed.');
      if (kind !== 'preview') await onChanged();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Unable to update dispatch finance.');
    } finally { setBusy(''); }
  };

  const selectedSource = sources.find((item) => item.id === fundingSourceId);
  const disabled = Boolean(approved && !finalSnapshot);
  return <section className="rounded-xl border border-blue-200 bg-blue-50/40 p-4">
    <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
      <div><h3 className="font-semibold text-slate-900">Dispatch Finance Snapshot</h3><p className="text-xs text-slate-600">Revenue, cash collection, driver entitlement, and submission remain separate.</p></div>
      {approved && <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-3 py-1 text-xs text-emerald-800"><CheckCircle2 className="h-3.5 w-3.5"/>Estimate locked</span>}
    </div>
    <fieldset disabled={Boolean(finalSnapshot)} className="grid gap-3 md:grid-cols-3 disabled:opacity-70">
      <label className="text-xs">Pricing Type<select className="mt-1 w-full rounded-lg border p-2" value={pricingType} onChange={(e) => setPricingType(e.target.value as DispatchPricingType)}><option value="standard">Standard</option><option value="subsidized">Subsidized</option><option value="complimentary">Complimentary</option></select></label>
      <Field label="Commercial Value" value={commercial} setValue={setCommercial}/><Field label="Customer Charge" value={charge} setValue={setCharge}/>
      {pricingType !== 'standard' && <><label className="text-xs">Funding Source<select required className="mt-1 w-full rounded-lg border p-2" value={fundingSourceId} onChange={(e) => setFundingSourceId(e.target.value)}><option value="">Select source</option>{sources.map((source) => <option key={source.id} value={source.id}>{source.name}</option>)}</select></label>{selectedSource?.name.toLowerCase() === 'other' && <label className="text-xs">Describe Other<input className="mt-1 w-full rounded-lg border p-2" value={fundingDescription} onChange={(e) => setFundingDescription(e.target.value)}/></label>}</>}
      <Field label="Billable Distance (km)" value={billableKm} setValue={setBillableKm}/><Field label="Operational Distance (km)" value={operationalKm} setValue={setOperationalKm}/>
      <label className="text-xs">Compensation Mode<select className="mt-1 w-full rounded-lg border p-2" value={compMode} onChange={(e) => setCompMode(e.target.value as 'amount'|'percentage')}><option value="amount">Amount</option><option value="percentage">Percentage</option></select></label>
      <Field label={compMode === 'percentage' ? 'Compensation (%)' : 'Compensation Amount'} value={compValue} setValue={setCompValue}/><Field label="Suggested Amount" value={suggested} setValue={setSuggested}/><Field label="Other Direct Costs" value={otherCosts} setValue={setOtherCosts}/>
      {approved && !finalSnapshot && <><Field label="Actual Fuel Cost (optional)" value={actualFuelCost} setValue={setActualFuelCost}/><Field label="Actual Duration (minutes)" value={durationMinutes} setValue={setDurationMinutes}/><Field label="Actual Stops" value={actualStops} setValue={setActualStops}/><Field label="Waiting (minutes)" value={waitingMinutes} setValue={setWaitingMinutes}/><label className="text-xs md:col-span-2">Journey Evidence / Additional Work<input className="mt-1 w-full rounded-lg border p-2" value={journeyNotes} onChange={(e)=>setJourneyNotes(e.target.value)}/></label></>}
    </fieldset>
    {!approved && <div className="mt-4 rounded-lg border bg-white p-3"><div className="flex items-center justify-between"><span className="text-sm font-medium">Driver extras</span><button type="button" onClick={() => setAdjustments((rows) => [...rows, { category: 'loading', reason: '', mode: 'amount', value: '0' }])} className="inline-flex items-center gap-1 text-xs text-blue-700"><Plus className="h-3.5 w-3.5"/>Add</button></div>{adjustments.map((item, index) => <div key={index} className="mt-2 grid gap-2 md:grid-cols-5"><select className="rounded border p-2 text-xs" value={item.category} onChange={(e) => setAdjustments((rows) => rows.map((row,i) => i===index?{...row,category:e.target.value}:row))}>{['loading','offloading','waiting','extra_stops','difficult_load','special_duty','other'].map((v)=><option key={v} value={v}>{v.replace('_',' ')}</option>)}</select><select className="rounded border p-2 text-xs" value={item.mode} onChange={(e) => setAdjustments((rows) => rows.map((row,i) => i===index?{...row,mode:e.target.value as Adjustment['mode']}:row))}><option value="amount">Amount</option><option value="percentage">Percentage</option></select><input className="rounded border p-2 text-xs" type="number" min="0" value={item.value} onChange={(e)=>setAdjustments((rows)=>rows.map((row,i)=>i===index?{...row,value:e.target.value}:row))}/><input className="rounded border p-2 text-xs md:col-span-1" placeholder="Required reason" value={item.reason} onChange={(e)=>setAdjustments((rows)=>rows.map((row,i)=>i===index?{...row,reason:e.target.value}:row))}/><button type="button" onClick={()=>setAdjustments((rows)=>rows.filter((_r,i)=>i!==index))}><Trash2 className="h-4 w-4 text-red-600"/></button></div>)}</div>}
    {preview && <div className="mt-4 grid gap-2 rounded-lg bg-white p-4 text-sm sm:grid-cols-2 lg:grid-cols-4"><Metric label="Commercial Value" value={money(preview.commercial_value)}/><Metric label="Customer Charge" value={money(preview.customer_charge)}/><Metric label="Concession / Funding" value={money(preview.concession_value)}/><Metric label="Fuel" value={money(preview.fuel.cost)}/><Metric label="Driver Compensation" value={money(preview.driver_compensation.approved_amount)}/><Metric label={`Maintenance (${preview.maintenance_reserve.rate_percent}%)`} value={money(preview.maintenance_reserve.amount)}/><Metric label="Capital / Profit" value={money(preview.vehicle_capital_profit_allocation)}/><Metric label="Company Contribution" value={money(preview.expected_company_contribution)}/>{preview.warnings.map((warning)=><div key={warning} className="col-span-full flex gap-2 rounded bg-amber-50 p-2 text-amber-800"><AlertTriangle className="h-4 w-4 shrink-0"/>{warning}</div>)}</div>}
    {preview?.expected_company_contribution !== undefined && preview.expected_company_contribution < 0 && !approved && <label className="mt-3 block text-xs">Authorized override reason<input className="mt-1 w-full rounded-lg border p-2" value={overrideReason} onChange={(e)=>setOverrideReason(e.target.value)}/></label>}
    <div className="mt-4 flex justify-end gap-2">{!approved && <><Action busy={busy==='preview'} onClick={()=>execute('preview')} label="Preview" secondary/><Action busy={busy==='approve'} onClick={()=>execute('approve')} label="Approve Snapshot"/></>}{disabled && <Action busy={busy==='finalize'} onClick={()=>execute('finalize')} label="Confirm Actuals"/>}</div>
  </section>;
}

function Field({label,value,setValue}:{label:string;value:string;setValue:(value:string)=>void}) { return <label className="text-xs">{label}<input type="number" min="0" step="0.01" className="mt-1 w-full rounded-lg border p-2" value={value} onChange={(e)=>setValue(e.target.value)}/></label>; }
function Metric({label,value}:{label:string;value:string}) { return <div><div className="text-xs text-slate-500">{label}</div><div className="font-semibold">{value}</div></div>; }
function Action({busy,onClick,label,secondary=false}:{busy:boolean;onClick:()=>void;label:string;secondary?:boolean}) { return <button type="button" disabled={busy} onClick={onClick} className={`inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm disabled:opacity-60 ${secondary?'border bg-white':'bg-blue-600 text-white'}`}>{busy&&<Loader2 className="h-4 w-4 animate-spin"/>}{label}</button>; }
