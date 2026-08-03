import { ArrowRight, Bell, ClipboardList, PackageCheck, Receipt, ShieldCheck, Truck, Users, Wrench } from 'lucide-react';
import type { SessionUser } from '../../lib/auth-session';

const ICONS = [ClipboardList, Truck, Users, PackageCheck, Wrench, Receipt, Bell, ShieldCheck];
export default function RoleDashboard({ user, onNavigate }: { user: SessionUser; onNavigate: (page: string) => void }) {
  const menus: Record<string, { label: string; page: string }[]> = {
    system_administrator: [{label:'Users',page:'users'},{label:'Roles & Permissions',page:'roles-permissions'},{label:'Branches',page:'branches'},{label:'System Settings',page:'settings'},{label:'Audit Logs',page:'audit-logs'}],
    operations_administrator: [{label:'Delivery Scheduler',page:'smart-living-deliveries'},{label:'Daily Delivery Runs',page:'smart-living-deliveries'},{label:'Vehicles',page:'vehicles'},{label:'Drivers',page:'drivers'},{label:'Maintenance',page:'maintenance'},{label:'Operational Reports',page:'reports'}],
    operations_manager: [{label:'Delivery Scheduler',page:'smart-living-deliveries'},{label:'Daily Delivery Runs',page:'smart-living-deliveries'},{label:'Drivers',page:'drivers'},{label:'Vehicles',page:'vehicles'},{label:'Maintenance',page:'maintenance'},{label:'Notifications',page:'notifications'}],
    field_agent: [{label:"Today's Deliveries",page:'smart-living-deliveries'},{label:'Upcoming Deliveries',page:'smart-living-deliveries'},{label:'Notifications',page:'notifications'},{label:'Customer Notes',page:'smart-living-deliveries'}],
    issuing_receiving_officer: [{label:'Upcoming Loading Schedule',page:'smart-living-deliveries'},{label:'Items Waiting for Issue',page:'smart-living-deliveries'},{label:'Drivers Waiting',page:'smart-living-deliveries'},{label:'Item History',page:'smart-living-deliveries'}],
    branch_manager: [{label:'Incoming Stock',page:'stock-transfers'},{label:'Notifications',page:'notifications'}],
    branch_warehouse_coordinator: [{label:'Incoming Stock',page:'stock-transfers'}],
    finance_officer: [{label:'Operational Expenses',page:'expenses'},{label:'Fuel',page:'fuel'},{label:'Repairs',page:'expenses'},{label:'Reports',page:'reports'}],
  };
  const activeWorkspace = String(user.selected_workspace || user.role);
  const items = menus[activeWorkspace] || menus.operations_administrator;
  return <div className="space-y-6 p-4 sm:p-6"><div className="rounded-2xl bg-gradient-to-r from-slate-900 to-blue-900 p-6 text-white"><div className="text-sm text-blue-200">{user.branch || 'All branches'}</div><h1 className="mt-1 text-2xl font-semibold">Welcome, {user.full_name}</h1><p className="mt-2 text-sm text-slate-300">{user.role_name || String(user.role).replaceAll('_',' ')}</p></div><div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{items.map((item,index)=>{const Icon=ICONS[index%ICONS.length]; return <button key={item.label} onClick={()=>onNavigate(item.page)} className="group flex items-center gap-4 rounded-xl border bg-white p-5 text-left shadow-sm hover:border-blue-300"><span className="rounded-lg bg-blue-50 p-3 text-blue-600"><Icon className="h-5 w-5" /></span><span className="flex-1 font-medium text-slate-800">{item.label}</span><ArrowRight className="h-4 w-4 text-slate-400 group-hover:text-blue-600" /></button>})}</div></div>;
}
