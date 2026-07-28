import { useEffect, useState } from 'react';
import { AlertTriangle } from 'lucide-react';
import { toast } from 'sonner';
import { acknowledgeMaintenanceOverride, fetchMaintenanceOverrides, type MaintenanceOverride } from '../../lib/maintenance-override-api';

export default function VehicleRestrictionsPanel({ vehicleId, driverMode = false }: { vehicleId?: string | null; driverMode?: boolean }) {
  const [rows, setRows] = useState<MaintenanceOverride[]>([]);
  const load = async () => setRows(await fetchMaintenanceOverrides({ vehicle_id: vehicleId || undefined, status: 'active' }));
  useEffect(() => { void load().catch(() => undefined); }, [vehicleId]);
  if (!rows.length) return null;
  return <div className="rounded-xl border border-amber-300 bg-amber-50 p-5"><h2 className="flex items-center gap-2 font-semibold text-amber-900"><AlertTriangle className="h-5 w-5" /> Active vehicle restrictions</h2><div className="mt-3 space-y-3">{rows.map((row) => <div key={row.id} className="rounded-lg bg-white p-4 text-sm"><div className="font-medium">{row.operational_restriction}</div><div className="mt-1 text-slate-500">Mandatory repair deadline: {new Date(row.repair_deadline).toLocaleString()}</div>{row.maximum_mileage ? <div className="text-slate-500">Maximum mileage: {row.maximum_mileage}</div> : null}{driverMode && !row.acknowledgements.length ? <button onClick={() => void acknowledgeMaintenanceOverride(row.id).then(load).then(() => toast.success('Restriction acknowledged.')).catch((error) => toast.error(error.message))} className="mt-3 rounded-lg bg-amber-600 px-3 py-2 font-medium text-white">Acknowledge restriction</button> : driverMode ? <div className="mt-2 text-xs font-medium text-green-700">Acknowledged</div> : null}</div>)}</div></div>;
}
