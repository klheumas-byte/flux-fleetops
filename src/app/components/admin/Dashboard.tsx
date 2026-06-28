import {
  useEffect,
  useMemo,
  useRef,
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
    fleetInvestmentSummary?: Record<string, unknown>;
    operationsSummary?: Record<string, unknown>;
    revenueSummary?: Record<string, unknown>;
    incidentsClaimsSummary?: Record<string, unknown>;
    complianceSummary?: Record<string, unknown>;
    maintenanceSummary?: Record<string, unknown>;
    supportingLookups?: Record<string, unknown>;
    warnings?: string[];
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
      fleet_economics_summary?: {
        total_managed_fleet?: number;
        total_active_vehicles?: number;
        total_managed_fleet_value?: number;
        total_fleet_investment: number;
        total_capital_recovered: number;
        outstanding_capital: number;
        fleet_roi_percent: number;
        total_revenue_collected: number;
        net_revenue: number;
        portfolio_breakdown?: Array<{
          asset_owner_name: string;
          asset_owner_type?: string | null;
          vehicle_count: number;
          fleet_value: number;
          capital_basis_for_recovery: number;
          revenue_generated: number;
          net_profit: number;
          capital_recovered: number;
          outstanding_capital: number;
          roi_percent: number;
        }>;
        top_vehicle_profitability?: {
          vehicle_id?: string | null;
          vehicle: string;
          registration_number?: string | null;
          net_profit: number;
          gross_revenue: number;
          roi_percent: number;
        };
      };
      fleet_risk_summary?: {
        vehicles_due_service: number;
        open_incidents: number;
        open_claims: number;
        expired_compliance_count: number;
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
      warnings?: string[];
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
  const [selectedAssetOwnerGroup, setSelectedAssetOwnerGroup] = useState('all');
  const hasLoadedRef = useRef(false);

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

      const unauthorizedResponses = [
        queueResponse,
        criticalResponse,
        bookingResponse,
        customerResponse,
        dashboardResponse,
      ].filter((result) => result.status === 401);
      if (unauthorizedResponses.length > 0) {
        setIsLoading(false);
        return;
      }

      setFaults(Array.isArray(queueResponse.data?.data?.faults) ? queueResponse.data.data.faults : []);
      setCriticalFaults(Array.isArray(criticalResponse.data?.data?.faults) ? criticalResponse.data.data.faults : []);
      setBookingSummary(bookingResponse.data?.data?.summary || null);
      setCustomerSummary(customerResponse.data?.data?.summary || null);
      setDashboardData(dashboardResponse.data?.data?.dashboard || null);
      const dashboardWarnings = Array.isArray(dashboardResponse.data?.data?.warnings)
        ? dashboardResponse.data.data.warnings
        : Array.isArray(dashboardResponse.data?.data?.dashboard?.warnings)
        ? dashboardResponse.data.data.dashboard.warnings
        : [];
      const dashboardRequestFailed = !dashboardResponse.ok;

      const coreFailures = [queueResponse, criticalResponse].filter((result) => !result.ok);
      if (coreFailures.length === 2) {
        setFaultError(coreFailures[0].error || 'Unable to load dashboard insights right now.');
      } else {
        if (dashboardRequestFailed) {
          setFaultNotice(dashboardResponse.error || 'Some dashboard sections are temporarily unavailable.');
        } else if (dashboardWarnings.length > 0) {
          setFaultNotice(`Some sections are temporarily unavailable: ${dashboardWarnings.join(', ')}.`);
        }
      }
      console.info('[Flux Performance] Admin dashboard loaded', {
        durationMs: Number((performance.now() - pageLoadStartedAt).toFixed(2)),
      });
      setIsLoading(false);
  };

  useEffect(() => {
    if (hasLoadedRef.current) {
      return;
    }
    hasLoadedRef.current = true;
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
  const fleetEconomicsSummary = dashboardData?.fleet_economics_summary;
  const fleetRiskSummary = dashboardData?.fleet_risk_summary;
  const portfolioBreakdown = fleetEconomicsSummary?.portfolio_breakdown || [];
  const ownerGroupLabel = (entry: NonNullable<typeof portfolioBreakdown>[number]) => {
    const ownerName = (entry.asset_owner_name || '').toLowerCase();
    const ownerType = (entry.asset_owner_type || '').toLowerCase();
    if (ownerName.includes('axelera') || ownerType.includes('axelera')) return 'axelera';
    if (ownerName.includes('smart living')) return 'smart-living';
    if (ownerType.includes('investor')) return 'investors';
    if (ownerType.includes('partner')) return 'partners';
    return 'external';
  };
  const filteredPortfolioBreakdown = useMemo(() => {
    if (selectedAssetOwnerGroup === 'all') {
      return portfolioBreakdown;
    }
    return portfolioBreakdown.filter((entry) => ownerGroupLabel(entry) === selectedAssetOwnerGroup);
  }, [portfolioBreakdown, selectedAssetOwnerGroup]);
  const filteredPortfolioSummary = useMemo(() => {
    if (selectedAssetOwnerGroup === 'all') {
      return {
        totalManagedFleet: fleetEconomicsSummary?.total_managed_fleet ?? 0,
        totalManagedFleetValue: fleetEconomicsSummary?.total_managed_fleet_value ?? 0,
        totalFleetInvestment: fleetEconomicsSummary?.total_fleet_investment ?? 0,
        totalCapitalRecovered: fleetEconomicsSummary?.total_capital_recovered ?? 0,
        outstandingCapital: fleetEconomicsSummary?.outstanding_capital ?? 0,
        fleetRoiPercent: fleetEconomicsSummary?.fleet_roi_percent ?? 0,
      };
    }
    const totalFleetInvestment = filteredPortfolioBreakdown.reduce((sum, entry) => sum + (entry.capital_basis_for_recovery || 0), 0);
    const totalCapitalRecovered = filteredPortfolioBreakdown.reduce((sum, entry) => sum + (entry.capital_recovered || 0), 0);
    const outstandingCapital = filteredPortfolioBreakdown.reduce((sum, entry) => sum + (entry.outstanding_capital || 0), 0);
    const totalManagedFleetValue = filteredPortfolioBreakdown.reduce((sum, entry) => sum + (entry.fleet_value || 0), 0);
    const totalManagedFleet = filteredPortfolioBreakdown.reduce((sum, entry) => sum + (entry.vehicle_count || 0), 0);
    const netProfit = filteredPortfolioBreakdown.reduce((sum, entry) => sum + (entry.net_profit || 0), 0);
    return {
      totalManagedFleet,
      totalManagedFleetValue,
      totalFleetInvestment,
      totalCapitalRecovered,
      outstandingCapital,
      fleetRoiPercent: totalFleetInvestment > 0 ? Number(((netProfit / totalFleetInvestment) * 100).toFixed(2)) : 0,
    };
  }, [filteredPortfolioBreakdown, fleetEconomicsSummary, selectedAssetOwnerGroup]);
  const ownerFleetOverviewCards = useMemo(() => {
    if (userRole !== 'owner') {
      return [];
    }

    return [
      {
        label: 'Managed Fleet Value',
        value: formatCurrency(filteredPortfolioSummary.totalManagedFleetValue),
        helper: 'Current estimated value of managed fleet assets',
        icon: Truck,
        color: 'bg-indigo-500',
      },
      {
        label: 'Fleet Investment',
        value: formatCurrency(filteredPortfolioSummary.totalFleetInvestment),
        helper: 'Total capital deployed across the fleet',
        icon: DollarSign,
        color: 'bg-slate-500',
      },
      {
        label: 'Capital Recovered',
        value: formatCurrency(filteredPortfolioSummary.totalCapitalRecovered),
        helper: 'Capital recovered from fleet operations',
        icon: TrendingUp,
        color: 'bg-green-500',
      },
      {
        label: 'Outstanding Capital',
        value: formatCurrency(filteredPortfolioSummary.outstandingCapital),
        helper: 'Remaining fleet capital still to recover',
        icon: AlertTriangle,
        color: 'bg-amber-500',
      },
      {
        label: 'Fleet ROI',
        value: `${filteredPortfolioSummary.fleetRoiPercent.toLocaleString()}%`,
        helper: 'Fleet-wide return on investment',
        icon: ArrowUp,
        color: 'bg-blue-500',
      },
      {
        label: 'Open Incidents / Claims',
        value: `${fleetRiskSummary?.open_incidents ?? 0} / ${fleetRiskSummary?.open_claims ?? 0}`,
        helper: 'Active incidents and insurance claims',
        icon: Shield,
        color: 'bg-rose-500',
      },
      {
        label: 'Expired Compliance',
        value: String(fleetRiskSummary?.expired_compliance_count ?? 0),
        helper: 'Compliance records already expired',
        icon: Calendar,
        color: 'bg-red-500',
      },
    ];
  }, [filteredPortfolioSummary, fleetRiskSummary, userRole]);
  const topVehicleProfitabilitySummary = fleetEconomicsSummary?.top_vehicle_profitability;

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

      {userRole === 'owner' && (
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="mb-5 flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h2 className="text-lg font-semibold text-[#0F172A]">Fleet Investment & Risk Overview</h2>
              <p className="mt-1 text-sm text-gray-600">
                Capital recovery, ROI, and operational risk from fleet economics, incidents, and compliance modules.
              </p>
            </div>
            <div className="flex flex-col gap-3 sm:items-end">
              <select
                value={selectedAssetOwnerGroup}
                onChange={(event) => setSelectedAssetOwnerGroup(event.target.value)}
                className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-700"
              >
                <option value="all">All Asset Owners</option>
                <option value="axelera">Axelera</option>
                <option value="smart-living">Smart Living</option>
                <option value="external">External Owners</option>
                <option value="investors">Investors</option>
                <option value="partners">Partners</option>
              </select>
              <div className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-600">
                <div>Managed Vehicles: <span className="font-medium text-[#0F172A]">{filteredPortfolioSummary.totalManagedFleet}</span></div>
                <div className="mt-1">Revenue Collected: <span className="font-medium text-[#0F172A]">{formatCurrency(fleetEconomicsSummary?.total_revenue_collected ?? 0)}</span></div>
                <div className="mt-1">Net Revenue: <span className="font-medium text-[#0F172A]">{formatCurrency(fleetEconomicsSummary?.net_revenue ?? 0)}</span></div>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {ownerFleetOverviewCards.map((card) => {
              const Icon = card.icon;
              return (
                <div key={card.label} className="rounded-xl border border-gray-200 bg-white p-5">
                  <div className="mb-3 flex items-start justify-between gap-3">
                    <div className={`flex h-11 w-11 items-center justify-center rounded-xl ${card.color}`}>
                      <Icon className="h-5 w-5 text-white" />
                    </div>
                    {card.label === 'Open Incidents / Claims' ? (
                      <button
                        type="button"
                        onClick={() => onNavigate('incidents')}
                        className="text-xs font-medium text-[#2563EB] hover:text-[#1d4ed8]"
                      >
                        View incidents
                      </button>
                    ) : null}
                  </div>
                  <div className="text-sm font-semibold text-[#0F172A]">{card.label}</div>
                  <div className="mt-2 text-3xl font-semibold text-[#0F172A]">{card.value}</div>
                  <div className="mt-2 text-xs text-gray-500">{card.helper}</div>
                </div>
              );
            })}
          </div>

          <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
            <div className="rounded-xl border border-gray-200 bg-gray-50 p-4">
              <div className="text-sm font-semibold text-[#0F172A]">Top Vehicle Profitability</div>
              <div className="mt-2 text-2xl font-semibold text-[#0F172A]">
                {topVehicleProfitabilitySummary?.vehicle || 'No vehicle data yet'}
              </div>
              <div className="mt-2 flex flex-wrap gap-4 text-sm text-gray-600">
                <span>Net Profit: <span className="font-medium text-[#0F172A]">{formatCurrency(topVehicleProfitabilitySummary?.net_profit ?? 0)}</span></span>
                <span>ROI: <span className="font-medium text-[#0F172A]">{(topVehicleProfitabilitySummary?.roi_percent ?? 0).toLocaleString()}%</span></span>
              </div>
            </div>
            <div className="rounded-xl border border-gray-200 bg-gray-50 p-4">
              <div className="text-sm font-semibold text-[#0F172A]">Operational Risk Snapshot</div>
              <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-3 text-sm text-gray-600">
                <div>Due Service: <span className="font-medium text-[#0F172A]">{fleetRiskSummary?.vehicles_due_service ?? dashboardData?.summary.vehicles_due_service ?? 0}</span></div>
                <div>Open Incidents: <span className="font-medium text-[#0F172A]">{fleetRiskSummary?.open_incidents ?? 0}</span></div>
                <div>Open Claims: <span className="font-medium text-[#0F172A]">{fleetRiskSummary?.open_claims ?? 0}</span></div>
              </div>
            </div>
          </div>

          <div className="mt-4 rounded-xl border border-gray-200 bg-white">
            <div className="border-b border-gray-200 px-4 py-3">
              <h3 className="text-sm font-semibold text-[#0F172A]">Fleet Portfolio Breakdown</h3>
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200 text-sm">
                <thead className="bg-gray-50">
                  <tr>
                    {['Asset Owner', 'Ownership Type', 'Vehicles', 'Fleet Value', 'Revenue', 'Net Profit', 'ROI', 'Capital Recovered', 'Outstanding Capital'].map((header) => (
                      <th key={header} className="px-4 py-3 text-left font-semibold text-gray-600">
                        {header}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {filteredPortfolioBreakdown.length > 0 ? (
                    filteredPortfolioBreakdown.map((entry) => (
                      <tr key={`${entry.asset_owner_name}-${entry.asset_owner_type || 'owner'}`}>
                        <td className="px-4 py-3 text-gray-900">{entry.asset_owner_name}</td>
                        <td className="px-4 py-3 text-gray-600">{entry.asset_owner_type || 'Unspecified'}</td>
                        <td className="px-4 py-3 text-gray-600">{entry.vehicle_count}</td>
                        <td className="px-4 py-3 text-gray-600">{formatCurrency(entry.fleet_value || 0)}</td>
                        <td className="px-4 py-3 text-gray-600">{formatCurrency(entry.revenue_generated || 0)}</td>
                        <td className="px-4 py-3 text-gray-600">{formatCurrency(entry.net_profit || 0)}</td>
                        <td className="px-4 py-3 text-gray-600">{entry.roi_percent || 0}%</td>
                        <td className="px-4 py-3 text-gray-600">{formatCurrency(entry.capital_recovered || 0)}</td>
                        <td className="px-4 py-3 text-gray-600">{formatCurrency(entry.outstanding_capital || 0)}</td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={9} className="px-4 py-8 text-center text-gray-500">
                        No portfolio records found for this owner filter.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
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
