import { useEffect, useMemo, useState } from 'react';
import {
  ArrowLeft, Bell, Car, CircleDollarSign, LogOut, Route, ShieldAlert,
  Target, UserRound, Wrench,
} from 'lucide-react';
import { toast } from 'sonner';
import type { SessionUser } from '../../lib/auth-session';
import {
  fetchFleetOwnerDashboard,
  fetchFleetOwnerVehicle,
  type FleetOwnerDashboardData,
} from '../../lib/fleet-owner-api';
import VehicleRestrictionsPanel from '../shared/VehicleRestrictionsPanel';
import KpiGrid, { compactKpiCardClass } from '../shared/KpiGrid';
import FleetOwnerParticipationPanel from './FleetOwnerParticipationPanel';
import WorkspaceSwitcher from '../shared/WorkspaceSwitcher';

const money = new Intl.NumberFormat('en-GH', { style: 'currency', currency: 'GHS' });
const today = new Date().toISOString().slice(0, 10);
const weekAgo = new Date(Date.now() - 6 * 86400000).toISOString().slice(0, 10);

export default function FleetOwnerPortal({
  currentUser,
  onLogout,
}: {
  currentUser: SessionUser;
  onLogout: () => void;
}) {
  const [data, setData] = useState<FleetOwnerDashboardData | null>(null);
  const [detail, setDetail] = useState<Record<string, any> | null>(null);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({ start_date: weekAgo, end_date: today, vehicle_id: '' });

  const setPreset = (days: number) => {
    setFilters((current) => ({
      ...current,
      start_date: new Date(Date.now() - (days - 1) * 86400000).toISOString().slice(0, 10),
      end_date: today,
    }));
  };

  const load = async () => {
    setLoading(true);
    try {
      setData(await fetchFleetOwnerDashboard(filters));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not load Fleet Owner dashboard.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, []);

  const openVehicle = async (vehicleId: string) => {
    try {
      setDetail(await fetchFleetOwnerVehicle(vehicleId, filters));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not load vehicle.');
    }
  };

  const cards = useMemo(() => data ? [
    ['Linked vehicles', data.summary.total_linked_vehicles, Car],
    ['Available', data.summary.available_vehicles, Car],
    ['Active / in operation', data.summary.active_vehicles, Route],
    ['Maintenance / fault', data.summary.maintenance_or_fault_vehicles, Wrench],
    ['Period collections', money.format(data.summary.period_company_collections), CircleDollarSign],
    ['Target achievement', `${data.summary.weekly_target_achievement_percent}%`, Target],
    ['Completed trips', data.summary.trips_completed, Route],
    ['Open faults', data.summary.open_faults, ShieldAlert],
  ] : [], [data]);

  if (detail) {
    const vehicle = detail.vehicle || {};
    const profitability = detail.profitability?.totals || {};
    return (
      <div className="min-h-screen bg-slate-50">
        <PortalHeader user={currentUser} onLogout={onLogout} />
        <main className="mx-auto max-w-7xl space-y-6 p-4 md:p-8">
          <button className="flex items-center gap-2 text-sm font-medium text-blue-700" onClick={() => setDetail(null)}>
            <ArrowLeft className="h-4 w-4" /> Back to fleet
          </button>
          <div>
            <p className="text-sm font-medium text-blue-700">Read-only vehicle view</p>
            <h1 className="text-3xl font-bold text-slate-900">{vehicle.registration_number}</h1>
            <p className="text-slate-500">{vehicle.make} {vehicle.model} · {vehicle.status}</p>
          </div>
          <KpiGrid className="xl:grid-cols-4">
            <Metric label="Gross revenue" value={money.format(profitability.gross_revenue || 0)} />
            <Metric label="Recorded cost" value={money.format(profitability.total_recorded_operating_cost || 0)} />
            <Metric label="Net profitability" value={money.format(profitability.net_profitability || 0)} />
            <Metric label="Current driver" value={detail.current_driver?.full_name || 'Unassigned'} />
          </KpiGrid>
          <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
            {detail.profitability?.by_vehicle?.[vehicle.id]?.data_note}
          </p>
          <VehicleRestrictionsPanel vehicleId={vehicle.id} />
          <FleetOwnerParticipationPanel vehicleId={vehicle.id} faults={detail.faults} maintenance={detail.maintenance} onChanged={() => void openVehicle(vehicle.id)} />
          <section className="grid gap-5 lg:grid-cols-2">
            <DataPanel title="Allocation history" rows={detail.allocation_history} fields={['driver', 'start_date', 'end_date', 'status']} />
            <DataPanel title="Company collections" rows={detail.collections} fields={['collection_date', 'amount', 'status']} />
            <DataPanel title="Trips" rows={detail.trips} fields={['trip_date', 'pickup_area', 'destination_area', 'status']} />
            <DataPanel title="Fuel logs" rows={detail.fuel_logs} fields={['fuel_date', 'litres', 'amount', 'status']} />
            <DataPanel title="Maintenance" rows={detail.maintenance} fields={['title', 'start_date', 'actual_cost', 'status']} />
            <DataPanel title="Faults" rows={detail.faults} fields={['severity', 'description', 'status', 'reported_at']} />
            <DataPanel title="Documents & expiry" rows={detail.documents} fields={['type', 'expiry_date']} />
            <DataPanel title="Ownership history" rows={detail.ownership_history} fields={['ownership_type', 'effective_at']} />
          </section>
        </main>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <PortalHeader user={currentUser} onLogout={onLogout} />
      <main className="mx-auto max-w-7xl space-y-7 p-4 md:p-8">
        <div>
          <p className="text-sm font-semibold text-blue-700">Fleet Owner Portal</p>
          <h1 className="text-3xl font-bold text-slate-900">Your fleet at a glance</h1>
          <p className="mt-1 text-slate-500">Operational and financial records for linked vehicles only.</p>
        </div>
        <section className="flex flex-wrap items-end gap-3 rounded-xl border bg-white p-4">
          <div className="flex gap-2">
            <button type="button" onClick={() => setPreset(1)} className="rounded-md border px-3 py-2 text-sm">Daily</button>
            <button type="button" onClick={() => setPreset(7)} className="rounded-md border px-3 py-2 text-sm">Weekly</button>
            <button type="button" onClick={() => setPreset(30)} className="rounded-md border px-3 py-2 text-sm">Monthly</button>
          </div>
          <label className="text-sm text-slate-600">From<input type="date" value={filters.start_date} onChange={(e) => setFilters({ ...filters, start_date: e.target.value })} className="mt-1 block rounded-md border px-3 py-2" /></label>
          <label className="text-sm text-slate-600">To<input type="date" value={filters.end_date} onChange={(e) => setFilters({ ...filters, end_date: e.target.value })} className="mt-1 block rounded-md border px-3 py-2" /></label>
          <label className="min-w-56 text-sm text-slate-600">Vehicle<select value={filters.vehicle_id} onChange={(e) => setFilters({ ...filters, vehicle_id: e.target.value })} className="mt-1 block w-full rounded-md border px-3 py-2"><option value="">All linked vehicles</option>{data?.vehicles.map((item) => <option key={item.id} value={item.id}>{item.registration_number}</option>)}</select></label>
          <button onClick={() => void load()} className="rounded-md bg-blue-600 px-5 py-2 text-sm font-semibold text-white">Apply</button>
        </section>
        {loading ? <p className="text-slate-500">Loading authoritative fleet records…</p> : data && <>
          <KpiGrid className="xl:grid-cols-4">
            {cards.map(([label, value, Icon]: any) => <div key={label} className={compactKpiCardClass}><Icon className="mb-2 text-blue-600" /><p className="text-xs text-slate-500 sm:text-sm">{label}</p><p className="mt-1 truncate text-xl font-bold text-slate-900 sm:text-2xl">{value}</p></div>)}
          </KpiGrid>
          <section className="grid gap-5 lg:grid-cols-3">
            <div className="rounded-xl border bg-white p-5 lg:col-span-2">
              <h2 className="mb-4 text-lg font-bold">Linked vehicles</h2>
              <div className="divide-y">{data.vehicles.map((vehicle) => {
                const driver = data.current_drivers.find((item) => item.vehicle_id === vehicle.id);
                return <button key={vehicle.id} onClick={() => void openVehicle(vehicle.id)} className="flex w-full items-center justify-between py-4 text-left hover:bg-slate-50"><span><span className="block font-semibold">{vehicle.registration_number}</span><span className="text-sm text-slate-500">{vehicle.make} {vehicle.model} · {driver?.driver_name || 'Unassigned'}</span></span><span className="rounded-full bg-slate-100 px-3 py-1 text-xs capitalize">{vehicle.status}</span></button>;
              })}</div>
            </div>
            <div className="rounded-xl border bg-white p-5">
              <h2 className="text-lg font-bold">Profitability summary</h2>
              <div className="mt-5 space-y-4">
                <Metric label="Gross revenue" value={money.format(data.profitability.totals.gross_revenue || 0)} />
                <Metric label="Recorded operating cost" value={money.format(data.profitability.totals.total_recorded_operating_cost || 0)} />
                <Metric label="Net profitability" value={money.format(data.profitability.totals.net_profitability || 0)} />
              </div>
            </div>
          </section>
        </>}
      </main>
    </div>
  );
}

function PortalHeader({ user, onLogout }: { user: SessionUser; onLogout: () => void }) {
  return <header className="border-b bg-slate-950 text-white"><div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 md:px-8"><div><span className="font-bold">Flux FleetOps</span><span className="ml-3 text-sm text-slate-400">Fleet Owner</span></div><div className="flex items-center gap-3"><WorkspaceSwitcher user={user} /><Bell className="h-5 w-5 text-slate-300" /><UserRound className="h-5 w-5" /><span className="hidden text-sm sm:inline">{user.full_name}</span><button onClick={onLogout} className="rounded-md p-2 hover:bg-slate-800" aria-label="Log out"><LogOut className="h-5 w-5" /></button></div></div></header>;
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return <div><p className="text-sm text-slate-500">{label}</p><p className="mt-1 text-xl font-bold text-slate-900">{value}</p></div>;
}

function DataPanel({ title, rows, fields }: { title: string; rows: any[]; fields: string[] }) {
  return <div className="rounded-xl border bg-white p-5"><h2 className="mb-4 text-lg font-bold">{title}</h2>{!rows?.length ? <p className="text-sm text-slate-500">No records for this vehicle.</p> : <div className="max-h-72 space-y-3 overflow-auto">{rows.map((row, index) => <div key={row.id || index} className="rounded-lg bg-slate-50 p-3 text-sm">{fields.map((field) => <div key={field} className="flex justify-between gap-4 py-0.5"><span className="capitalize text-slate-500">{field.replaceAll('_', ' ')}</span><span className="max-w-[65%] text-right font-medium">{typeof row[field] === 'object' ? row[field]?.full_name || '—' : row[field] ?? '—'}</span></div>)}</div>)}</div>}</div>;
}
