import {
  useEffect,
  useMemo,
  useState,
} from 'react';
import {
  Truck,
  TrendingUp,
  DollarSign,
  Users,
  Fuel,
  MapPin,
  Wrench,
  AlertTriangle,
  ArrowUp,
  ArrowDown,
  Clock,
  Calendar,
  Shield
} from 'lucide-react';
import { LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import { apiRequestSafe } from '../../lib/api';
import type { UserRole } from '../../App';
import type { BookingSummary, CustomerSummary } from '../../lib/customer-booking-api';

interface DashboardProps {
  onNavigate: (section: string) => void;
  userRole: Extract<UserRole, 'owner' | 'admin'>;
}

interface FaultSummaryRecord {
  severity: 'low' | 'medium' | 'high' | 'critical';
  status: 'reported' | 'under_review' | 'approved' | 'rejected' | 'converted_to_maintenance' | 'resolved';
}

interface FaultsResponse {
  success: boolean;
  data: {
    faults: FaultSummaryRecord[];
  };
}

interface DashboardSummaryResponse {
  success: boolean;
  data: {
    dashboard: {
      summary: {
        total_vehicles: number;
        active_vehicles: number;
        active_drivers: number;
        weekly_revenue_target: number;
        revenue_collected: number;
        outstanding_balance: number;
        fuel_spend: number;
        fuel_metric_label: string;
        net_revenue: number;
        active_trips: number;
        vehicles_due_service: number;
      };
      charts: {
        weekly_revenue: Array<{ day: string; target: number; collected: number }>;
        vehicle_profitability: Array<{ vehicle: string; revenue: number; cost: number; profit: number }>;
      };
      tables: {
        recent_collections: Array<{ id: string; driver: string; vehicle: string; amount: number; time: string; status: string }>;
        drivers_owing: Array<{ driver: string; vehicle: string; balance: number; daysOverdue: number; status: string }>;
      };
      alerts: {
        maintenance: Array<{ vehicle: string; type: string; due: string; priority: string }>;
        expiries: Array<{ vehicle: string; type: string; expiryDate: string; daysLeft: number }>;
        activity_feed: Array<{ id: string; title: string; subtitle: string; tone: string }>;
      };
    };
  };
}

function formatCurrency(value: number) {
  return `GHS ${value.toLocaleString()}`;
}

export default function Dashboard({ onNavigate, userRole }: DashboardProps) {
  const [faults, setFaults] = useState<FaultSummaryRecord[]>([]);
  const [criticalFaults, setCriticalFaults] = useState<FaultSummaryRecord[]>([]);
  const [faultError, setFaultError] = useState('');
  const [faultNotice, setFaultNotice] = useState('');
  const [bookingSummary, setBookingSummary] = useState<BookingSummary | null>(null);
  const [customerSummary, setCustomerSummary] = useState<CustomerSummary | null>(null);
  const [dashboardData, setDashboardData] = useState<DashboardSummaryResponse['data']['dashboard'] | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const loadFaultSummaries = async () => {
      const pageLoadStartedAt = performance.now();
      setIsLoading(true);
      setFaultError('');
      setFaultNotice('');
      const [queueResponse, criticalResponse, bookingResponse, customerResponse, dashboardResponse] = await Promise.all([
        apiRequestSafe<FaultsResponse>('/faults/approvals', { cacheTtlMs: 15000, fallbackData: { success: true, data: { faults: [] } } }),
        apiRequestSafe<FaultsResponse>('/faults/critical', { cacheTtlMs: 15000, fallbackData: { success: true, data: { faults: [] } } }),
        apiRequestSafe<{ data: { summary: BookingSummary } }>('/bookings/summary', { cacheTtlMs: 15000, fallbackData: { data: { summary: null as unknown as BookingSummary } } }),
        apiRequestSafe<{ data: { summary: CustomerSummary } }>('/customers/summary', { cacheTtlMs: 15000, fallbackData: { data: { summary: null as unknown as CustomerSummary } } }),
        apiRequestSafe<DashboardSummaryResponse>('/dashboard/summary', { cacheTtlMs: 15000, fallbackData: { success: true, data: { dashboard: null as unknown as DashboardSummaryResponse['data']['dashboard'] } } }),
      ]);

      setFaults(Array.isArray(queueResponse.data?.data?.faults) ? queueResponse.data.data.faults : []);
      setCriticalFaults(Array.isArray(criticalResponse.data?.data?.faults) ? criticalResponse.data.data.faults : []);
      setBookingSummary(bookingResponse.data?.data?.summary || null);
      setCustomerSummary(customerResponse.data?.data?.summary || null);
      setDashboardData(dashboardResponse.data?.data?.dashboard || null);

      const coreFailures = [queueResponse, criticalResponse].filter((result) => !result.ok);
      if (coreFailures.length === 2) {
        setFaultError(coreFailures[0].error || 'Unable to load dashboard insights right now.');
      } else {
        const unavailableSections: string[] = [];
        if (!queueResponse.ok) unavailableSections.push('fault approvals');
        if (!criticalResponse.ok) unavailableSections.push('critical faults');
        if (!bookingResponse.ok) unavailableSections.push('booking summary');
        if (!customerResponse.ok) unavailableSections.push('CRM summary');
        if (!dashboardResponse.ok) unavailableSections.push('operations summary');
        if (unavailableSections.length > 0) {
          setFaultNotice(`Some sections are temporarily unavailable: ${unavailableSections.join(', ')}.`);
        }
      }
      console.info('[Flux Performance] Admin dashboard loaded', {
        durationMs: Number((performance.now() - pageLoadStartedAt).toFixed(2)),
      });
      setIsLoading(false);
  };

  useEffect(() => {
    void loadFaultSummaries();
  }, []);

  const faultMetrics = useMemo(() => {
    const pendingApprovals = faults.filter((fault) => ['reported', 'under_review'].includes(fault.status)).length;
    const pendingCritical = criticalFaults.filter((fault) => ['reported', 'under_review'].includes(fault.status)).length;
    return {
      pendingApprovals,
      criticalFaults: criticalFaults.length,
      pendingCritical,
    };
  }, [criticalFaults, faults]);

  const kpiCards = useMemo(() => {
    const summary = dashboardData?.summary;
    return [
      { label: 'Total Vehicles', value: String(summary?.total_vehicles ?? 0), trend: 'neutral', icon: Truck, color: 'bg-blue-500' },
      { label: 'Active Vehicles', value: String(summary?.active_vehicles ?? 0), trend: 'neutral', icon: Truck, color: 'bg-green-500' },
      { label: 'Active Drivers', value: String(summary?.active_drivers ?? 0), trend: 'neutral', icon: Users, color: 'bg-blue-500' },
      { label: 'Weekly Revenue Target', value: formatCurrency(summary?.weekly_revenue_target ?? 0), trend: 'neutral', icon: TrendingUp, color: 'bg-amber-500' },
      { label: 'Revenue Collected', value: formatCurrency(summary?.revenue_collected ?? 0), trend: 'neutral', icon: DollarSign, color: 'bg-green-500' },
      { label: 'Outstanding Balances', value: formatCurrency(summary?.outstanding_balance ?? 0), trend: 'neutral', icon: DollarSign, color: 'bg-red-500' },
      { label: summary?.fuel_metric_label || 'Driver Fuel Spend', value: formatCurrency(summary?.fuel_spend ?? 0), trend: 'neutral', icon: Fuel, color: 'bg-amber-500' },
      { label: 'Net Revenue', value: formatCurrency(summary?.net_revenue ?? 0), trend: 'neutral', icon: TrendingUp, color: 'bg-green-500' },
      { label: 'Active Trips', value: String(summary?.active_trips ?? 0), trend: 'neutral', icon: MapPin, color: 'bg-blue-500' },
      { label: 'Vehicles Due Service', value: String(summary?.vehicles_due_service ?? 0), trend: 'alert', icon: Wrench, color: 'bg-red-500' },
    ];
  }, [dashboardData]);

  const revenueData = dashboardData?.charts.weekly_revenue || [];
  const vehicleProfitability = dashboardData?.charts.vehicle_profitability || [];
  const recentCollections = dashboardData?.tables.recent_collections || [];
  const driversOwing = dashboardData?.tables.drivers_owing || [];
  const maintenanceAlerts = dashboardData?.alerts.maintenance || [];
  const upcomingExpiries = dashboardData?.alerts.expiries || [];
  const activityFeed = dashboardData?.alerts.activity_feed || [];

  return (
    <div className="p-6 space-y-6">
      {/* Page Header */}
      <div>
        <h1 className="text-2xl font-semibold text-gray-900">{userRole === 'owner' ? 'Owner Dashboard' : 'Admin Dashboard'}</h1>
        <p className="text-gray-500 mt-1">Welcome back! Here's what's happening with your fleet today.</p>
      </div>

      {faultError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <span>{faultError}</span>
            <button
              onClick={() => void loadFaultSummaries()}
              className="rounded-lg border border-red-200 bg-white px-3 py-2 text-xs font-medium text-red-700 hover:bg-red-100"
            >
              Retry
            </button>
          </div>
        </div>
      )}

      {faultNotice && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          {faultNotice}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        {isLoading
          ? Array.from({ length: 4 }).map((_, index) => (
              <div key={index} className="rounded-xl border border-gray-200 bg-white p-5">
                <div className="mb-3 h-11 w-11 animate-pulse rounded-xl bg-gray-100" />
                <div className="h-4 w-32 animate-pulse rounded bg-gray-100" />
                <div className="mt-4 h-10 w-20 animate-pulse rounded bg-gray-100" />
              </div>
            ))
          : null}
        {!isLoading && (
          <>
        <button
          onClick={() => onNavigate('customers')}
          className="rounded-xl border border-blue-200 bg-white p-5 text-left transition-all hover:border-blue-300 hover:shadow-sm"
        >
          <div className="mb-3 flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-blue-100 text-blue-600">
              <Users className="h-5 w-5" />
            </div>
            <div>
              <div className="text-sm font-semibold text-[#0F172A]">
                Total Customers
              </div>
              <div className="text-xs text-gray-500">
                CRM records across riders, leads, and strategic contacts
              </div>
            </div>
          </div>
          <div className="text-3xl font-semibold text-[#0F172A]">
            {customerSummary?.total_customers ?? bookingSummary?.total_customers ?? 0}
          </div>
        </button>

        <button
          onClick={() => onNavigate('customers')}
          className="rounded-xl border border-emerald-200 bg-white p-5 text-left transition-all hover:border-emerald-300 hover:shadow-sm"
        >
          <div className="mb-3 flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-emerald-100 text-emerald-600">
              <Calendar className="h-5 w-5" />
            </div>
            <div>
              <div className="text-sm font-semibold text-[#0F172A]">
                Business Leads
              </div>
              <div className="text-xs text-gray-500">
                Warm pipeline contacts with transport or business potential
              </div>
            </div>
          </div>
          <div className="text-3xl font-semibold text-[#0F172A]">
            {customerSummary?.total_business_leads ?? 0}
          </div>
        </button>

        <button
          onClick={() => onNavigate('customers')}
          className="rounded-xl border border-amber-200 bg-white p-5 text-left transition-all hover:border-amber-300 hover:shadow-sm"
        >
          <div className="mb-3 flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-amber-100 text-amber-600">
              <Clock className="h-5 w-5" />
            </div>
            <div>
              <div className="text-sm font-semibold text-[#0F172A]">Follow-Ups Due Today</div>
              <div className="text-xs text-gray-500">Relationship and lead conversations to action today</div>
            </div>
          </div>
          <div className="text-3xl font-semibold text-[#0F172A]">{customerSummary?.follow_ups_due_today ?? 0}</div>
        </button>

        <button
          onClick={() => onNavigate('customers')}
          className="rounded-xl border border-red-200 bg-white p-5 text-left transition-all hover:border-red-300 hover:shadow-sm"
        >
          <div className="mb-3 flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-red-100 text-red-600">
              <AlertTriangle className="h-5 w-5" />
            </div>
            <div>
              <div className="text-sm font-semibold text-[#0F172A]">Follow-Ups Overdue</div>
              <div className="text-xs text-gray-500">
                High-risk CRM conversations that have slipped past their due date
              </div>
            </div>
          </div>
          <div className="text-3xl font-semibold text-[#0F172A]">{customerSummary?.follow_ups_overdue ?? 0}</div>
        </button>
          </>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-5">
        {(userRole === 'owner'
          ? [
              { label: 'Total Future Bookings', value: bookingSummary?.total_future_bookings ?? 0, icon: Calendar, tint: 'border-blue-200 bg-blue-50 text-blue-700' },
              { label: 'Driver Schedules', value: bookingSummary?.driver_schedules ?? 0, icon: Truck, tint: 'border-cyan-200 bg-cyan-50 text-cyan-700' },
              { label: 'VIP Bookings', value: bookingSummary?.vip_bookings ?? 0, icon: Shield, tint: 'border-purple-200 bg-purple-50 text-purple-700' },
              { label: 'Strategic Meetings', value: bookingSummary?.strategic_meetings ?? 0, icon: Clock, tint: 'border-amber-200 bg-amber-50 text-amber-700' },
              { label: 'Follow-Up Completion Rate', value: `${bookingSummary?.follow_up_completion_rate ?? 0}%`, icon: AlertTriangle, tint: 'border-emerald-200 bg-emerald-50 text-emerald-700' },
            ]
          : [
              { label: 'Total Scheduled Bookings', value: bookingSummary?.total_scheduled_bookings ?? 0, icon: Calendar, tint: 'border-blue-200 bg-blue-50 text-blue-700' },
              { label: 'Bookings Awaiting Acknowledgement', value: bookingSummary?.pending_acknowledgement ?? 0, icon: Clock, tint: 'border-amber-200 bg-amber-50 text-amber-700' },
              { label: 'Upcoming Corporate Bookings', value: bookingSummary?.upcoming_corporate_bookings ?? 0, icon: Truck, tint: 'border-purple-200 bg-purple-50 text-purple-700' },
              { label: 'Overdue Follow-Ups', value: customerSummary?.follow_ups_overdue ?? 0, icon: Shield, tint: 'border-emerald-200 bg-emerald-50 text-emerald-700' },
              { label: 'Missed Bookings', value: bookingSummary?.missed_bookings ?? 0, icon: AlertTriangle, tint: 'border-red-200 bg-red-50 text-red-700' },
            ]).map((card) => {
          const Icon = card.icon;
          return (
            <button
              key={card.label}
              onClick={() => onNavigate('customers')}
              className="rounded-xl border bg-white p-5 text-left transition-all hover:shadow-sm"
            >
              <div className={`mb-3 inline-flex h-11 w-11 items-center justify-center rounded-xl border ${card.tint}`}>
                <Icon className="h-5 w-5" />
              </div>
              <div className="text-sm font-semibold text-[#0F172A]">{card.label}</div>
              <div className="mt-2 text-3xl font-semibold text-[#0F172A]">{card.value}</div>
            </button>
          );
        })}
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        <button
          onClick={() => onNavigate('customers')}
          className="rounded-xl border border-purple-200 bg-white p-5 text-left transition-all hover:border-purple-300 hover:shadow-sm"
        >
          <div className="text-sm font-semibold text-[#0F172A]">Strategic Contacts</div>
          <div className="mt-1 text-xs text-gray-500">High-opportunity relationships with long-term value</div>
          <div className="mt-4 text-3xl font-semibold text-[#0F172A]">{customerSummary?.total_strategic_contacts ?? 0}</div>
        </button>
        <button
          onClick={() => onNavigate('customers')}
          className="rounded-xl border border-indigo-200 bg-white p-5 text-left transition-all hover:border-indigo-300 hover:shadow-sm"
        >
          <div className="text-sm font-semibold text-[#0F172A]">Investors</div>
          <div className="mt-1 text-xs text-gray-500">Contacts flagged with investor relationship potential</div>
          <div className="mt-4 text-3xl font-semibold text-[#0F172A]">{customerSummary?.total_investors ?? 0}</div>
        </button>
        <button
          onClick={() => onNavigate('customers')}
          className="rounded-xl border border-cyan-200 bg-white p-5 text-left transition-all hover:border-cyan-300 hover:shadow-sm"
        >
          <div className="text-sm font-semibold text-[#0F172A]">Gatekeepers</div>
          <div className="mt-1 text-xs text-gray-500">Industry connectors and access points worth nurturing</div>
          <div className="mt-4 text-3xl font-semibold text-[#0F172A]">{customerSummary?.total_gatekeepers ?? 0}</div>
        </button>
        <button
          onClick={() => onNavigate('customers')}
          className="rounded-xl border border-emerald-200 bg-white p-5 text-left transition-all hover:border-emerald-300 hover:shadow-sm"
        >
          <div className="text-sm font-semibold text-[#0F172A]">Lead Conversion Rate</div>
          <div className="mt-1 text-xs text-gray-500">Converted leads as a share of the current business pipeline</div>
          <div className="mt-4 text-3xl font-semibold text-[#0F172A]">{customerSummary?.lead_conversion_rate ?? 0}%</div>
        </button>
      </div>

      {/* KPI Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
        {kpiCards.map((kpi, index) => {
          const Icon = kpi.icon;
          return (
            <div key={index} className="bg-white rounded-lg border border-gray-200 p-5 hover:shadow-md transition-shadow">
              <div className="flex items-start justify-between mb-3">
                <div className={`w-10 h-10 ${kpi.color} rounded-lg flex items-center justify-center`}>
                  <Icon className="w-5 h-5 text-white" />
                </div>
                {kpi.trend === 'up' && (
                  <div className="flex items-center gap-1 text-[#10B981] text-xs font-medium">
                    <ArrowUp className="w-3 h-3" />
                    {kpi.change}
                  </div>
                )}
                {kpi.trend === 'down' && (
                  <div className="flex items-center gap-1 text-[#10B981] text-xs font-medium">
                    <ArrowDown className="w-3 h-3" />
                    {kpi.change}
                  </div>
                )}
                {kpi.trend === 'alert' && (
                  <div className="flex items-center gap-1 text-[#EF4444] text-xs font-medium">
                    <AlertTriangle className="w-3 h-3" />
                    {kpi.change}
                  </div>
                )}
              </div>
              <div className="text-2xl font-semibold text-gray-900 mb-1">{kpi.value}</div>
              <div className="text-sm text-gray-500">{kpi.label}</div>
            </div>
          );
        })}
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Revenue vs Target */}
        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">Revenue vs Target</h3>
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={revenueData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="day" stroke="#6b7280" />
              <YAxis stroke="#6b7280" />
              <Tooltip />
              <Legend />
              <Line key="target-line" type="monotone" dataKey="target" stroke="#F59E0B" strokeWidth={2} name="Target" />
              <Line key="collected-line" type="monotone" dataKey="collected" stroke="#10B981" strokeWidth={2} name="Collected" />
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* Vehicle Profitability */}
        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">Top Vehicle Profitability</h3>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={vehicleProfitability}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="vehicle" stroke="#6b7280" />
              <YAxis stroke="#6b7280" />
              <Tooltip />
              <Legend />
              <Bar key="revenue-bar" dataKey="revenue" fill="#2563EB" name="Revenue" />
              <Bar key="cost-bar" dataKey="cost" fill="#EF4444" name="Cost" />
              <Bar key="profit-bar" dataKey="profit" fill="#10B981" name="Profit" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Tables Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Recent Collections */}
        <div className="bg-white rounded-lg border border-gray-200">
          <div className="p-6 border-b border-gray-200">
            <h3 className="text-lg font-semibold text-gray-900">Recent Collections</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Driver</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Vehicle</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Amount</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Time</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {recentCollections.map((collection) => (
                  <tr key={collection.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4 text-sm text-gray-900">{collection.driver}</td>
                    <td className="px-6 py-4 text-sm text-gray-600">{collection.vehicle}</td>
                    <td className="px-6 py-4 text-sm font-medium text-gray-900">GH₵ {collection.amount}</td>
                    <td className="px-6 py-4 text-sm text-gray-500">{collection.time}</td>
                    <td className="px-6 py-4">
                      <span className={`px-2 py-1 rounded-full text-xs font-medium ${
                        collection.status === 'completed'
                          ? 'bg-green-100 text-green-800'
                          : 'bg-yellow-100 text-yellow-800'
                      }`}>
                        {collection.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Drivers Owing */}
        <div className="bg-white rounded-lg border border-gray-200">
          <div className="p-6 border-b border-gray-200">
            <h3 className="text-lg font-semibold text-gray-900">Drivers Owing</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Driver</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Vehicle</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Balance</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Days</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {driversOwing.map((driver, index) => (
                  <tr key={index} className="hover:bg-gray-50">
                    <td className="px-6 py-4 text-sm text-gray-900">{driver.driver}</td>
                    <td className="px-6 py-4 text-sm text-gray-600">{driver.vehicle}</td>
                    <td className="px-6 py-4 text-sm font-medium text-gray-900">GH₵ {driver.balance}</td>
                    <td className="px-6 py-4 text-sm text-gray-500">{driver.daysOverdue}d</td>
                    <td className="px-6 py-4">
                      <span className={`px-2 py-1 rounded-full text-xs font-medium ${
                        driver.status === 'overdue'
                          ? 'bg-red-100 text-red-800'
                          : 'bg-yellow-100 text-yellow-800'
                      }`}>
                        {driver.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Widgets Row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Maintenance Alerts */}
        <div className="bg-white rounded-lg border border-gray-200">
          <div className="p-6 border-b border-gray-200">
            <h3 className="text-lg font-semibold text-gray-900">Maintenance Alerts</h3>
          </div>
          <div className="p-4 space-y-3">
            {maintenanceAlerts.map((alert, index) => (
              <div key={index} className="flex items-start gap-3 p-3 bg-gray-50 rounded-lg">
                <div className={`w-2 h-2 rounded-full mt-2 ${
                  alert.priority === 'critical' ? 'bg-red-500' :
                  alert.priority === 'high' ? 'bg-orange-500' :
                  alert.priority === 'medium' ? 'bg-yellow-500' : 'bg-blue-500'
                }`}></div>
                <div className="flex-1">
                  <div className="text-sm font-medium text-gray-900">{alert.vehicle}</div>
                  <div className="text-xs text-gray-600">{alert.type}</div>
                  <div className="text-xs text-gray-500 mt-1">Due: {alert.due}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Upcoming Expiries */}
        <div className="bg-white rounded-lg border border-gray-200">
          <div className="p-6 border-b border-gray-200">
            <h3 className="text-lg font-semibold text-gray-900">Upcoming Expiries</h3>
          </div>
          <div className="p-4 space-y-3">
            {upcomingExpiries.map((expiry, index) => (
              <div key={index} className="flex items-start gap-3 p-3 bg-gray-50 rounded-lg">
                <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
                  expiry.daysLeft <= 7 ? 'bg-red-100' : 'bg-amber-100'
                }`}>
                  {expiry.type === 'Insurance' ? (
                    <Shield className={`w-5 h-5 ${expiry.daysLeft <= 7 ? 'text-red-600' : 'text-amber-600'}`} />
                  ) : (
                    <Calendar className={`w-5 h-5 ${expiry.daysLeft <= 7 ? 'text-red-600' : 'text-amber-600'}`} />
                  )}
                </div>
                <div className="flex-1">
                  <div className="text-sm font-medium text-gray-900">{expiry.vehicle}</div>
                  <div className="text-xs text-gray-600">{expiry.type}</div>
                  <div className="text-xs text-gray-500 mt-1">{expiry.daysLeft} days left</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Fleet Activity Feed */}
        <div className="bg-white rounded-lg border border-gray-200">
          <div className="p-6 border-b border-gray-200">
            <h3 className="text-lg font-semibold text-gray-900">Fleet Activity Feed</h3>
          </div>
          <div className="p-4 space-y-4">
            {activityFeed.length > 0 ? (
              activityFeed.map((item) => (
                <div key={item.id} className="flex gap-3">
                  <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${
                    item.tone === 'green'
                      ? 'bg-green-100'
                      : item.tone === 'amber'
                        ? 'bg-amber-100'
                        : item.tone === 'red'
                          ? 'bg-red-100'
                          : 'bg-blue-100'
                  }`}>
                    {item.tone === 'green' ? (
                      <TrendingUp className="w-4 h-4 text-green-600" />
                    ) : item.tone === 'amber' ? (
                      <Fuel className="w-4 h-4 text-amber-600" />
                    ) : item.tone === 'red' ? (
                      <AlertTriangle className="w-4 h-4 text-red-600" />
                    ) : (
                      <Users className="w-4 h-4 text-blue-600" />
                    )}
                  </div>
                  <div className="flex-1">
                    <p className="text-sm text-gray-900">{item.title}</p>
                    <p className="text-xs text-gray-500">{item.subtitle}</p>
                  </div>
                </div>
              ))
            ) : (
              <div className="text-sm text-gray-500">No recent fleet activity found.</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
