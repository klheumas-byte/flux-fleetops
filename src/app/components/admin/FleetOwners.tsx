import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { apiRequest } from '../../lib/api';
import {
  createFleetOwnerAccount, fetchFleetOwnerAccounts, linkFleetOwnerVehicles,
  updateFleetOwnerAccount, fetchFleetOwnerParticipationRequests, reviewFleetOwnerParticipationRequest,
} from '../../lib/fleet-owner-api';

const emptyForm = { name: '', contact_name: '', email: '', phone: '', password: '', status: 'active' };

export default function FleetOwners() {
  const [owners, setOwners] = useState<Array<Record<string, any>>>([]);
  const [vehicles, setVehicles] = useState<Array<Record<string, any>>>([]);
  const [form, setForm] = useState(emptyForm);
  const [selectedOwner, setSelectedOwner] = useState('');
  const [selectedVehicles, setSelectedVehicles] = useState<string[]>([]);
  const [requests, setRequests] = useState<Array<Record<string, any>>>([]);
  const [loadError, setLoadError] = useState('');

  const load = async () => {
    setLoadError('');
    const [ownerResult, vehicleResult, requestResult] = await Promise.allSettled([
      fetchFleetOwnerAccounts(),
      apiRequest<any>('/vehicles'),
      fetchFleetOwnerParticipationRequests('pending_review'),
    ]);
    if (ownerResult.status === 'fulfilled') setOwners(ownerResult.value);
    if (vehicleResult.status === 'fulfilled') setVehicles(vehicleResult.value.data.vehicles || []);
    if (requestResult.status === 'fulfilled') setRequests(requestResult.value);
    const failures = [ownerResult, vehicleResult, requestResult].filter((result) => result.status === 'rejected');
    if (failures.length) {
      const reason = (failures[0] as PromiseRejectedResult).reason;
      const message = reason instanceof Error ? reason.message : 'Some Fleet Owner data could not be loaded.';
      setLoadError(message);
      toast.error(message);
    }
  };
  useEffect(() => { void load(); }, []);

  const create = async (event: React.FormEvent) => {
    event.preventDefault();
    try {
      await createFleetOwnerAccount(form);
      setForm(emptyForm);
      await load();
      toast.success('Fleet Owner account created.');
    } catch (error) { toast.error(error instanceof Error ? error.message : 'Could not create account.'); }
  };

  const link = async () => {
    try {
      await linkFleetOwnerVehicles(selectedOwner, selectedVehicles);
      setSelectedVehicles([]);
      await load();
      toast.success('Vehicles linked.');
    } catch (error) { toast.error(error instanceof Error ? error.message : 'Could not link vehicles.'); }
  };

  const review = async (id: string, status: 'approved' | 'rejected') => {
    try { await reviewFleetOwnerParticipationRequest(id, status); await load(); toast.success(`Request ${status}.`); }
    catch (error) { toast.error(error instanceof Error ? error.message : 'Could not review request.'); }
  };

  return <div className="space-y-6 p-4 md:p-8"><div><h1 className="text-2xl font-bold">Fleet Owners</h1><p className="text-slate-500">Manage third-party owner accounts and vehicle links.</p></div>
    {loadError && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{loadError}</div>}
    {requests.length > 0 && <section className="rounded-xl border bg-white p-5"><h2 className="mb-4 font-bold">Participation requests awaiting review</h2><div className="space-y-3">{requests.map((item) => <div key={item.id} className="flex flex-col gap-3 rounded-lg bg-slate-50 p-3 sm:flex-row sm:items-center sm:justify-between"><div><b className="capitalize">{String(item.request_type).replaceAll('_', ' ')}</b><p className="text-sm text-slate-600">{item.reason}</p><p className="text-xs text-slate-400">Vehicle {item.vehicle_id}</p></div><div className="flex gap-2"><button onClick={() => void review(item.id, 'approved')} className="rounded bg-emerald-600 px-3 py-1.5 text-sm text-white">Approve review</button><button onClick={() => void review(item.id, 'rejected')} className="rounded border border-red-300 px-3 py-1.5 text-sm text-red-700">Reject</button></div></div>)}</div></section>}
    <form onSubmit={create} className="grid gap-3 rounded-xl border bg-white p-5 md:grid-cols-3">{Object.keys(emptyForm).filter((key) => key !== 'status').map((key) => <input key={key} required value={(form as any)[key]} type={key === 'password' ? 'password' : 'text'} placeholder={key.replaceAll('_', ' ')} onChange={(e) => setForm({ ...form, [key]: e.target.value })} className="rounded-md border px-3 py-2" />)}<button className="rounded-md bg-blue-600 px-4 py-2 font-semibold text-white">Create account</button></form>
    <div className="grid gap-5 lg:grid-cols-2"><section className="rounded-xl border bg-white p-5"><h2 className="mb-4 font-bold">Accounts</h2><div className="space-y-3">{owners.map((owner) => <div key={owner.id} className="flex items-center justify-between rounded-lg bg-slate-50 p-3"><span><b className="block">{owner.name}</b><span className="text-sm text-slate-500">{owner.vehicle_count} vehicles · {owner.status}</span></span><button onClick={() => void updateFleetOwnerAccount(owner.id, { status: owner.status === 'active' ? 'inactive' : 'active' }).then(load)} className="rounded border px-3 py-1 text-sm">{owner.status === 'active' ? 'Deactivate' : 'Activate'}</button></div>)}</div></section>
    <section className="rounded-xl border bg-white p-5"><h2 className="mb-4 font-bold">Link vehicles</h2><select value={selectedOwner} onChange={(e) => setSelectedOwner(e.target.value)} className="mb-3 w-full rounded-md border px-3 py-2"><option value="">Choose Fleet Owner</option>{owners.map((owner) => <option key={owner.id} value={owner.id}>{owner.name}</option>)}</select><div className="max-h-60 space-y-2 overflow-auto">{vehicles.filter((item) => !item.fleet_owner_id || item.fleet_owner_id === selectedOwner).map((vehicle) => <label key={vehicle.id} className="flex gap-2 rounded bg-slate-50 p-2"><input type="checkbox" checked={selectedVehicles.includes(vehicle.id)} onChange={(e) => setSelectedVehicles(e.target.checked ? [...selectedVehicles, vehicle.id] : selectedVehicles.filter((id) => id !== vehicle.id))} />{vehicle.registration_number}</label>)}</div><button disabled={!selectedOwner || !selectedVehicles.length} onClick={() => void link()} className="mt-4 rounded-md bg-blue-600 px-4 py-2 font-semibold text-white disabled:opacity-40">Link selected</button></section></div>
  </div>;
}
