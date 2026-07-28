import { useEffect, useState } from 'react';
import { AlertTriangle, FileUp, MessageSquare, Send, Wrench } from 'lucide-react';
import { toast } from 'sonner';
import { apiRequest, ApiRequestError } from '../../lib/api';

export default function FleetOwnerParticipationPanel({ vehicleId, faults = [], maintenance = [], onChanged }: {
  vehicleId: string; faults?: any[]; maintenance?: any[]; onChanged: () => void;
}) {
  const [action, setAction] = useState<'request' | 'fault' | 'incident' | 'document' | 'comment'>('request');
  const [busy, setBusy] = useState(false);
  const [options, setOptions] = useState<any>({ categories: [], components: [] });
  const [form, setForm] = useState<any>({ request_type: 'maintenance', reason: '', category_id: '', component_id: '', severity: 'medium', description: '', vehicle_unsafe: false, incident_type: 'other', incident_at: new Date().toISOString().slice(0, 16), location: '', can_vehicle_move: true, third_party_involved: false, compliance_item_name: 'Insurance', policy_or_reference_number: '', issue_date: '', expiry_date: '', case_type: 'fault', case_id: '', comment: '' });

  useEffect(() => {
    if (action !== 'fault' || options.categories.length) return;
    void apiRequest<any>('/faults/options').then((response) => {
      const data = response.data || {};
      setOptions(data);
      setForm((current: any) => ({ ...current, category_id: data.categories?.[0]?.id || '', component_id: data.components?.[0]?.id || '' }));
    }).catch(() => toast.error('Fault options could not be loaded.'));
  }, [action, options.categories.length]);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault(); setBusy(true);
    try {
      if (action === 'request') {
        await apiRequest('/fleet-owner/requests', { method: 'POST', body: JSON.stringify({ vehicle_id: vehicleId, request_type: form.request_type, reason: form.reason }) });
      } else if (action === 'fault') {
        await apiRequest('/faults', { method: 'POST', body: JSON.stringify({ vehicle_id: vehicleId, category_id: form.category_id, component_id: form.component_id, severity: form.severity, description: form.description, vehicle_unsafe: form.vehicle_unsafe }) });
      } else if (action === 'incident') {
        await apiRequest('/incidents', { method: 'POST', body: JSON.stringify({ vehicle_id: vehicleId, incident_type: form.incident_type, incident_at: new Date(form.incident_at).toISOString(), location: form.location, description: form.description, can_vehicle_move: form.can_vehicle_move, third_party_involved: form.third_party_involved, attachments: [] }) });
      } else if (action === 'document') {
        await apiRequest('/preventive-maintenance/compliance/records', { method: 'POST', body: JSON.stringify({ vehicle_id: vehicleId, compliance_item_name: form.compliance_item_name, policy_or_reference_number: form.policy_or_reference_number, issue_date: form.issue_date, expiry_date: form.expiry_date, renewal_frequency: 'yearly', warning_days_before: 30, document_upload: null }) });
      } else {
        await apiRequest(`/fleet-owner/cases/${form.case_type}/${form.case_id}/comments`, { method: 'POST', body: JSON.stringify({ comment: form.comment }) });
      }
      toast.success(action === 'request' ? 'Request submitted for Admin review.' : 'Vehicle record updated.');
      setForm((current: any) => ({ ...current, reason: '', description: '', location: '', comment: '' }));
      onChanged();
    } catch (error) {
      toast.error(error instanceof ApiRequestError ? error.message : 'The action could not be completed.');
    } finally { setBusy(false); }
  };

  const cases = form.case_type === 'fault' ? faults : maintenance;
  return <section className="rounded-xl border bg-white p-4 sm:p-5">
    <h2 className="font-bold text-slate-900">Participate in vehicle care</h2>
    <p className="mt-1 text-sm text-slate-500">Report safety concerns and submit controlled requests for this linked vehicle.</p>
    <div className="mt-4 flex flex-wrap gap-2">
      {([['request', Wrench, 'Request'], ['fault', AlertTriangle, 'Fault'], ['incident', AlertTriangle, 'Incident'], ['document', FileUp, 'Document'], ['comment', MessageSquare, 'Comment']] as const).map(([id, Icon, label]) => <button key={id} type="button" onClick={() => setAction(id)} className={`inline-flex items-center gap-1 rounded-md border px-3 py-2 text-sm ${action === id ? 'border-blue-600 bg-blue-50 text-blue-700' : ''}`}><Icon className="h-4 w-4" />{label}</button>)}
    </div>
    <form onSubmit={submit} className="mt-4 grid gap-3 sm:grid-cols-2">
      {action === 'request' && <><select value={form.request_type} onChange={(e) => setForm({ ...form, request_type: e.target.value })} className="rounded-md border p-2"><option value="maintenance">Request maintenance</option><option value="vehicle_withdrawal">Request withdrawal from service</option><option value="driver_reassignment">Request driver reassignment</option></select><textarea required maxLength={1000} value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} placeholder="Reason for request" className="rounded-md border p-2 sm:col-span-2" /></>}
      {action === 'fault' && <><select required value={form.category_id} onChange={(e) => setForm({ ...form, category_id: e.target.value })} className="rounded-md border p-2">{(options.categories || []).map((item: any) => <option key={item.id} value={item.id}>{item.name}</option>)}</select><select required value={form.component_id} onChange={(e) => setForm({ ...form, component_id: e.target.value })} className="rounded-md border p-2">{(options.components || []).filter((item: any) => !form.category_id || item.category_id === form.category_id).map((item: any) => <option key={item.id} value={item.id}>{item.name}</option>)}</select><select value={form.severity} onChange={(e) => setForm({ ...form, severity: e.target.value })} className="rounded-md border p-2"><option>low</option><option>medium</option><option>high</option><option>critical</option></select><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.vehicle_unsafe} onChange={(e) => setForm({ ...form, vehicle_unsafe: e.target.checked })} />Vehicle may be unsafe</label><textarea required value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="Describe the fault" className="rounded-md border p-2 sm:col-span-2" /></>}
      {action === 'incident' && <><select value={form.incident_type} onChange={(e) => setForm({ ...form, incident_type: e.target.value })} className="rounded-md border p-2"><option value="other">Vehicle concern</option><option value="breakdown">Breakdown</option><option value="accident">Accident</option><option value="theft">Theft</option><option value="fire">Fire</option></select><input type="datetime-local" required value={form.incident_at} onChange={(e) => setForm({ ...form, incident_at: e.target.value })} className="rounded-md border p-2" /><input required value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} placeholder="Location" className="rounded-md border p-2" /><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.can_vehicle_move} onChange={(e) => setForm({ ...form, can_vehicle_move: e.target.checked })} />Vehicle can move</label><textarea required value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="Describe the incident" className="rounded-md border p-2 sm:col-span-2" /></>}
      {action === 'document' && <><input required value={form.compliance_item_name} onChange={(e) => setForm({ ...form, compliance_item_name: e.target.value })} placeholder="Document type" className="rounded-md border p-2" /><input value={form.policy_or_reference_number} onChange={(e) => setForm({ ...form, policy_or_reference_number: e.target.value })} placeholder="Reference number" className="rounded-md border p-2" /><input type="date" required value={form.issue_date} onChange={(e) => setForm({ ...form, issue_date: e.target.value })} className="rounded-md border p-2" /><input type="date" required value={form.expiry_date} onChange={(e) => setForm({ ...form, expiry_date: e.target.value })} className="rounded-md border p-2" /></>}
      {action === 'comment' && <><select value={form.case_type} onChange={(e) => setForm({ ...form, case_type: e.target.value, case_id: '' })} className="rounded-md border p-2"><option value="fault">Fault</option><option value="maintenance">Maintenance</option></select><select required value={form.case_id} onChange={(e) => setForm({ ...form, case_id: e.target.value })} className="rounded-md border p-2"><option value="">Choose case</option>{cases.map((item: any) => <option key={item.id} value={item.id}>{item.title || item.description || item.id}</option>)}</select><textarea required value={form.comment} onChange={(e) => setForm({ ...form, comment: e.target.value })} placeholder="Add comment" className="rounded-md border p-2 sm:col-span-2" /></>}
      <button disabled={busy} className="inline-flex items-center justify-center gap-2 rounded-md bg-blue-600 px-4 py-2 font-semibold text-white disabled:opacity-60 sm:col-span-2"><Send className="h-4 w-4" />{busy ? 'Submitting…' : 'Submit'}</button>
    </form>
  </section>;
}
