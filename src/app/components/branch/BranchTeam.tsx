import { FormEvent, useEffect, useState, type ReactNode } from 'react';
import { KeyRound, Pencil, Plus, RefreshCw, UserCheck, UserX } from 'lucide-react';
import { toast } from 'sonner';
import {
  createBranchFieldAgent, fetchBranchTeam, resetBranchFieldAgent,
  setBranchFieldAgentStatus, submitBranchDriverRequest, updateBranchFieldAgent,
  type BranchTeam as TeamData, type TeamUser,
} from '../../lib/branch-operations-api';

const empty = { full_name:'', email:'', phone:'', username:'', password:'', license_number:'', license_class:'', license_expiry:'', notes:'' };

export default function BranchTeam() {
  const [data, setData] = useState<TeamData | null>(null);
  const [loading, setLoading] = useState(true);
  const [mode, setMode] = useState<'agent' | 'driver' | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState(empty);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    setLoading(true);
    try { setData(await fetchBranchTeam()); }
    catch (error) { toast.error(error instanceof Error ? error.message : 'Unable to load branch team.'); }
    finally { setLoading(false); }
  };
  useEffect(() => { void load(); }, []);

  const openCreate = (nextMode: 'agent' | 'driver') => { setEditingId(null); setForm(empty); setMode(nextMode); };
  const openEdit = (row: TeamUser) => {
    setEditingId(row.id);
    setForm({ ...empty, full_name:row.full_name || '', email:row.email || '', phone:row.phone || '', username:row.username || '' });
    setMode('agent');
  };
  const closeForm = () => { setMode(null); setEditingId(null); setForm(empty); };

  const submit = async (event: FormEvent) => {
    event.preventDefault(); setSaving(true);
    try {
      if (mode === 'agent' && editingId) {
        await updateBranchFieldAgent(editingId, { full_name:form.full_name, email:form.email || undefined, username:form.username || undefined, phone:form.phone });
        toast.success('Field Agent details updated.');
      } else if (mode === 'agent') {
        await createBranchFieldAgent({ full_name:form.full_name, email:form.email || undefined, username:form.username || undefined, phone:form.phone, password:form.password });
        toast.success('Field Agent created in your primary branch.');
      } else {
        await submitBranchDriverRequest({ full_name:form.full_name, email:form.email || undefined, username:form.username || undefined, phone:form.phone, password:form.password, notes:form.notes, driver_profile:{ license_number:form.license_number, license_class:form.license_class, license_expiry:form.license_expiry } });
        toast.success('Driver request submitted for HQ approval.');
      }
      closeForm(); await load();
    } catch (error) { toast.error(error instanceof Error ? error.message : 'Unable to save team member.'); }
    finally { setSaving(false); }
  };

  return <div className="space-y-6 p-4 sm:p-6">
    <header className="flex flex-wrap items-center justify-between gap-3">
      <div><h1 className="text-2xl font-semibold text-slate-900">Branch Team</h1><p className="mt-1 text-sm text-slate-500">Branch staff and company drivers currently serving your branch.</p></div>
      <div className="flex flex-wrap gap-2">
        <button onClick={() => openCreate('agent')} className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-blue-600 px-4 text-sm font-medium text-white"><Plus className="h-4 w-4"/>Field Agent</button>
        <button onClick={() => openCreate('driver')} className="min-h-11 rounded-lg border bg-white px-4 text-sm font-medium text-slate-700">Request Driver</button>
        <button onClick={() => void load()} className="min-h-11 rounded-lg border bg-white px-3" aria-label="Refresh branch team"><RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`}/></button>
      </div>
    </header>

    {mode && <form onSubmit={submit} className="grid gap-3 rounded-2xl border bg-white p-4 sm:grid-cols-2">
      <div className="sm:col-span-2"><h2 className="font-semibold text-slate-900">{mode === 'agent' ? (editingId ? 'Edit Field Agent' : 'Create Field Agent') : 'Submit Driver for Approval'}</h2><p className="text-xs text-slate-500">Role and branch are assigned automatically and cannot be changed here.</p></div>
      {(['full_name','phone','email','username',...(editingId ? [] : ['password'])] as const).map(key => <label key={key} className="text-sm capitalize text-slate-600">{key.replaceAll('_',' ')}{['full_name','phone','password'].includes(key) && ' *'}<input required={['full_name','phone','password'].includes(key)} type={key === 'password' ? 'password' : 'text'} value={form[key]} onChange={event => setForm({...form,[key]:event.target.value})} className="mt-1 min-h-11 w-full rounded-lg border px-3"/></label>)}
      {mode === 'driver' && <>{(['license_number','license_class','license_expiry'] as const).map(key => <label key={key} className="text-sm capitalize text-slate-600">{key.replaceAll('_',' ')}<input type={key === 'license_expiry' ? 'date' : 'text'} value={form[key]} onChange={event => setForm({...form,[key]:event.target.value})} className="mt-1 min-h-11 w-full rounded-lg border px-3"/></label>)}<label className="text-sm text-slate-600 sm:col-span-2">Notes<textarea value={form.notes} onChange={event => setForm({...form,notes:event.target.value})} className="mt-1 min-h-20 w-full rounded-lg border p-3"/></label></>}
      <div className="flex gap-2 sm:col-span-2"><button disabled={saving} className="min-h-11 rounded-lg bg-blue-600 px-5 text-sm font-medium text-white disabled:opacity-50">{saving ? 'Saving...' : 'Submit'}</button><button type="button" onClick={closeForm} className="min-h-11 rounded-lg border px-5 text-sm">Cancel</button></div>
    </form>}

    <div className="grid gap-5 xl:grid-cols-2">
      <TeamSection title="Field Agents" rows={data?.field_agents || []} actions={row => <>
        <button onClick={() => openEdit(row)} className="rounded-lg border p-2" title="Edit basic details"><Pencil className="h-4 w-4"/></button>
        <button onClick={async () => { try { const result=await resetBranchFieldAgent(row.id); toast.success(`Temporary password: ${result.temporary_password}`,{duration:10000}); } catch(error) { toast.error(error instanceof Error ? error.message : 'Reset failed'); } }} className="rounded-lg border p-2" title="Reset / invite access"><KeyRound className="h-4 w-4"/></button>
        <button onClick={async () => { try { await setBranchFieldAgentStatus(row.id,row.status === 'active' ? 'inactive' : 'active'); await load(); } catch(error) { toast.error(error instanceof Error ? error.message : 'Status update failed'); } }} className="rounded-lg border p-2" title={row.status === 'active' ? 'Deactivate' : 'Activate'}>{row.status === 'active' ? <UserX className="h-4 w-4"/> : <UserCheck className="h-4 w-4"/>}</button>
      </>}/>
      <TeamSection title="Drivers" rows={data?.drivers || []}/>
      <TeamSection title="Warehouse Coordinators" rows={data?.warehouse_coordinators || []}/>
    </div>
  </div>;
}

function TeamSection({title,rows,actions}:{title:string;rows:TeamUser[];actions?:(row:TeamUser)=>ReactNode}) {
  return <section className="overflow-hidden rounded-2xl border bg-white"><h2 className="border-b px-4 py-3 font-semibold text-slate-900">{title} <span className="text-sm font-normal text-slate-400">({rows.length})</span></h2><div className="divide-y">{rows.map(row => <article key={row.id} className="flex items-center gap-3 p-4"><div className="min-w-0 flex-1"><p className="truncate font-medium text-slate-900">{row.full_name}</p><p className="truncate text-xs text-slate-500">{row.phone} · {row.status}{row.temporary_assignment ? ' · Temporary assignment' : ''}{row.serving_active_delivery ? ' · Active branch delivery' : ''}{row.driver_profile?.approval_status === 'pending' ? ' · Pending approval' : ''}</p>{row.delivery_summary && <p className="mt-1 text-xs text-blue-700">Assigned {row.delivery_summary.assigned} · Upcoming {row.delivery_summary.upcoming} · Completed {row.delivery_summary.completed}</p>}</div><div className="flex gap-1">{actions?.(row)}</div></article>)}{!rows.length && <p className="p-6 text-center text-sm text-slate-500">No {title.toLowerCase()} in branch scope.</p>}</div></section>;
}
