import { apiRequest } from './api';
import type { SessionUser } from './auth-session';

export type BranchRun = { id:string; record_type?:string; run_number?:string; delivery_date?:string; expected_time?:string; status:string; readiness?:'PLANNING_REQUIRED'|'PARTIALLY_PLANNED'|'READY'; missing_requirements?:string[]; customer?:string; products?:string[]; area?:string; field_agent?:string; field_agents?:string[]; transport_method?:'VEHICLE'|'KAYA'|'OTHER_MANUAL'; driver?:string; handler?:string; vehicle?:string; delivery_count:number };
export type BranchOverview = {
  kpis: Record<'deliveries_today'|'tomorrow'|'upcoming'|'awaiting_planning'|'scheduled'|'in_progress'|'completed'|'failed_partial'|'incoming_stock'|'open_exceptions'|'available_branch_drivers', number>;
  board: Record<'awaiting_planning'|'scheduled'|'in_progress'|'completed'|'exceptions', BranchRun[]>;
  upcoming: Record<'today'|'tomorrow'|'this_week', BranchRun[]>;
  tomorrow_summary: { total:number; ready:number; planning_required:number };
};
export type TeamUser = SessionUser & { temporary_assignment?:boolean; serving_active_delivery?:boolean; driver_request_status?:string; delivery_summary?:{assigned:number;upcoming:number;completed:number} };
export type BranchTeam = { staff:TeamUser[]; field_agents:TeamUser[]; drivers:TeamUser[]; warehouse_coordinators:TeamUser[] };
type Envelope<T> = { data:T; message?:string };

export async function fetchBranchOverview() { return (await apiRequest<Envelope<BranchOverview>>('/branch-operations/overview')).data; }
export async function fetchBranchTeam() { return (await apiRequest<Envelope<BranchTeam>>('/branch-operations/team')).data; }
export async function createBranchFieldAgent(payload:Record<string,unknown>) { return (await apiRequest<Envelope<{user:TeamUser}>>('/branch-operations/team/field-agents',{method:'POST',body:JSON.stringify(payload)})).data.user; }
export async function updateBranchFieldAgent(id:string,payload:Record<string,unknown>) { return (await apiRequest<Envelope<{user:TeamUser}>>(`/branch-operations/team/field-agents/${id}`,{method:'PATCH',body:JSON.stringify(payload)})).data.user; }
export async function setBranchFieldAgentStatus(id:string,status:'active'|'inactive') { return (await apiRequest<Envelope<{user:TeamUser}>>(`/branch-operations/team/field-agents/${id}/status`,{method:'PATCH',body:JSON.stringify({status})})).data.user; }
export async function resetBranchFieldAgent(id:string) { return (await apiRequest<Envelope<{user:TeamUser;temporary_password:string}>>(`/branch-operations/team/field-agents/${id}/reset-access`,{method:'POST',body:'{}'})).data; }
export async function submitBranchDriverRequest(payload:Record<string,unknown>) { return (await apiRequest<Envelope<{driver:TeamUser}>>('/branch-operations/team/driver-requests',{method:'POST',body:JSON.stringify(payload)})).data.driver; }
