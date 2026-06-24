import { useEffect, useMemo, useState } from 'react';
import {
  Calendar,
  Download,
  FileText,
  Filter,
  Fuel,
  Loader2,
  MapPin,
  Printer,
  RefreshCw,
  Target,
  Truck,
  Users,
  UsersRound,
  Wrench,
  DollarSign,
} from 'lucide-react';
import { apiRequest, ApiRequestError } from '../../lib/api';

type ReportCategory = 'revenue' | 'drivers' | 'vehicles' | 'trips' | 'fuel' | 'maintenance' | 'customers';

interface UserSummary {
  id: string;
  full_name: string;
  phone?: string | null;
  role: 'owner' | 'admin' | 'driver';
}

interface VehicleOption {
  id: string;
  registration_number: string;
  status?: string | null;
}

interface ValidationSummary {
  total_records: number;
  total_amount: number;
  last_updated: string | null;
  active_filters: string[];
}

interface ReportSection<T = Record<string, unknown>> {
  records: T[];
  validation: ValidationSummary;
  [key: string]: unknown;
}

interface ReportsResponse {
  success: boolean;
  data: {
    generated_by: UserSummary | null;
    generated_at: string;
    filters: {
      date_from: string | null;
      date_to: string | null;
      driver_id: string | null;
      vehicle_id: string | null;
      branch: string | null;
      creator_role?: string | null;
      customer_category_id?: string | null;
      source?: string | null;
    };
    available_filters: {
      drivers: UserSummary[];
      vehicles: VehicleOption[];
      branches: string[];
      creator_roles?: string[];
      customer_categories?: string[];
      customer_category_items?: Array<{ id: string; name: string }>;
      sources?: string[];
    };
    reports: {
      collections: ReportSection;
      deposits: ReportSection;
      expenses: ReportSection;
      fuel: ReportSection & { total_litres?: number };
      maintenance: ReportSection;
      faults: ReportSection;
      customers: ReportSection;
      bookings: ReportSection & { status_breakdown?: Record<string, number> };
      trip_logs: ReportSection & {
        trips_by_platform?: Array<{ label: string; count: number }>;
        trips_by_purpose?: Array<{ label: string; count: number }>;
      };
      driver_performance: ReportSection;
      vehicle_performance: ReportSection;
      vehicle_economics: {
        validation: ValidationSummary;
        message?: string;
        total_fleet_investment?: number;
        total_recovered?: number;
        remaining_recovery_balance?: number;
        net_fleet_profit?: number;
        vehicles?: Array<{
          id: string;
          registration_number: string;
          economics?: {
            investment?: { total_vehicle_investment?: number };
            recovery?: {
              amount_recovered?: number;
              remaining_balance?: number;
              recovery_percentage?: number;
              status?: string;
              estimated_break_even_date?: string;
              recovery_status?: string;
            };
            profitability?: {
              gross_revenue?: number;
              operating_costs?: number;
              company_vehicle_costs?: number;
              net_profit?: number;
            };
            health?: { score?: number };
          };
        }>;
      };
    };
  };
}

const reportCategories: Array<{
  id: ReportCategory;
  label: string;
  icon: typeof DollarSign;
  color: string;
}> = [
  { id: 'revenue', label: 'Revenue Reports', icon: DollarSign, color: 'bg-green-100 text-green-700 border-green-200' },
  { id: 'drivers', label: 'Driver Reports', icon: Users, color: 'bg-blue-100 text-blue-700 border-blue-200' },
  { id: 'vehicles', label: 'Vehicle Reports', icon: Truck, color: 'bg-purple-100 text-purple-700 border-purple-200' },
  { id: 'trips', label: 'Trip Reports', icon: MapPin, color: 'bg-indigo-100 text-indigo-700 border-indigo-200' },
  { id: 'fuel', label: 'Fuel Reports', icon: Fuel, color: 'bg-amber-100 text-amber-700 border-amber-200' },
  { id: 'maintenance', label: 'Maintenance Reports', icon: Wrench, color: 'bg-red-100 text-red-700 border-red-200' },
  { id: 'customers', label: 'Customer Reports', icon: UsersRound, color: 'bg-pink-100 text-pink-700 border-pink-200' },
];

function formatCurrency(value: number) {
  return `GHS ${Number(value || 0).toLocaleString()}`;
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return 'No timestamp';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
}

function formatDate(value: string | null | undefined) {
  if (!value) return 'No date';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString();
}

function getDateRange(range: string) {
  const today = new Date();
  const end = today.toISOString().slice(0, 10);
  if (range === 'all-time') {
    return { date_from: '', date_to: '' };
  }
  if (range === 'this-year') {
    return { date_from: `${today.getFullYear()}-01-01`, date_to: end };
  }
  const offset = range === 'last-90-days' ? 89 : 29;
  const start = new Date(today);
  start.setDate(today.getDate() - offset);
  return {
    date_from: start.toISOString().slice(0, 10),
    date_to: end,
  };
}

function combineValidationSummaries(...validations: Array<ValidationSummary | undefined>): ValidationSummary {
  const available = validations.filter(Boolean) as ValidationSummary[];
  const timestamps = available
    .map((item) => (item.last_updated ? new Date(item.last_updated).getTime() : 0))
    .filter((value) => value > 0);
  return {
    total_records: available.reduce((sum, item) => sum + item.total_records, 0),
    total_amount: Number(available.reduce((sum, item) => sum + item.total_amount, 0).toFixed(2)),
    last_updated: timestamps.length ? new Date(Math.max(...timestamps)).toISOString() : null,
    active_filters: available[0]?.active_filters || ['All records'],
  };
}

const DEFAULT_VALIDATION: ValidationSummary = {
  total_records: 0,
  total_amount: 0,
  last_updated: null,
  active_filters: ['All records'],
};

function createEmptySection<T = Record<string, unknown>>() {
  return {
    records: [] as T[],
    validation: DEFAULT_VALIDATION,
    message: 'No records found for this report.',
  };
}

function createEmptyVehicleEconomics() {
  return {
    validation: DEFAULT_VALIDATION,
    message: 'No records found for this report.',
    total_fleet_investment: 0,
    total_recovered: 0,
    remaining_recovery_balance: 0,
    net_fleet_profit: 0,
    vehicles: [] as NonNullable<ReportsResponse['data']['reports']['vehicle_economics']['vehicles']>,
  };
}

function toCsv(rows: Array<Record<string, unknown>>) {
  if (!rows.length) return '';
  const headers = Array.from(
    rows.reduce((set, row) => {
      Object.keys(row).forEach((key) => set.add(key));
      return set;
    }, new Set<string>()),
  );
  const lines = [
    headers.join(','),
    ...rows.map((row) =>
      headers
        .map((header) => {
          const value = row[header];
          const cell =
            value === null || value === undefined
              ? ''
              : typeof value === 'object'
                ? JSON.stringify(value)
                : String(value);
          return `"${cell.replace(/"/g, '""')}"`;
        })
        .join(','),
    ),
  ];
  return lines.join('\n');
}

export default function Reports() {
  const [activeCategory, setActiveCategory] = useState<ReportCategory>('revenue');
  const [dateRange, setDateRange] = useState('last-30-days');
  const [selectedDriverId, setSelectedDriverId] = useState('');
  const [selectedVehicleId, setSelectedVehicleId] = useState('');
  const [selectedBranch, setSelectedBranch] = useState('');
  const [selectedCreatorRole, setSelectedCreatorRole] = useState('');
  const [selectedCustomerCategoryId, setSelectedCustomerCategoryId] = useState('');
  const [selectedSource, setSelectedSource] = useState('');
  const [reportData, setReportData] = useState<ReportsResponse['data'] | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [pageError, setPageError] = useState('');
  const [refreshKey, setRefreshKey] = useState(0);

  const storedUser = localStorage.getItem('flux_user');
  const currentRole = storedUser ? JSON.parse(storedUser).role : null;

  useEffect(() => {
    if (currentRole === 'driver') {
      setIsLoading(false);
      return;
    }

    const loadReportData = async () => {
      const pageLoadStartedAt = performance.now();
      setIsLoading(true);
      setPageError('');
      setReportData(null);
      const range = getDateRange(dateRange);
      const params = new URLSearchParams();
      params.set('category', activeCategory);
      if (range.date_from) params.set('date_from', range.date_from);
      if (range.date_to) params.set('date_to', range.date_to);
      if (selectedDriverId) params.set('driver_id', selectedDriverId);
      if (selectedVehicleId) params.set('vehicle_id', selectedVehicleId);
      if (selectedBranch) params.set('branch', selectedBranch);
      if (selectedCreatorRole) params.set('creator_role', selectedCreatorRole);
      if (selectedCustomerCategoryId) params.set('customer_category_id', selectedCustomerCategoryId);
      if (selectedSource) params.set('source', selectedSource);

      try {
        const response = await apiRequest<ReportsResponse>(`/reports/finance?${params.toString()}`, {
          cacheTtlMs: 10000,
          timeoutMs: 20000,
        });
        setReportData(response.data);
        console.info('[Flux Performance] Reports page loaded', {
          category: activeCategory,
          durationMs: Number((performance.now() - pageLoadStartedAt).toFixed(2)),
        });
      } catch (error) {
        if (error instanceof ApiRequestError) {
          setPageError(error.message || 'Unable to load reports right now.');
        } else {
          setPageError('Unable to load reports right now.');
        }
      } finally {
        setIsLoading(false);
      }
    };

    void loadReportData();
  }, [activeCategory, currentRole, dateRange, selectedDriverId, selectedVehicleId, selectedBranch, selectedCreatorRole, selectedCustomerCategoryId, selectedSource, refreshKey]);

  const reports = useMemo(() => {
    const source = reportData?.reports;
    return {
      collections: source?.collections ?? createEmptySection(),
      deposits: source?.deposits ?? createEmptySection(),
      expenses: source?.expenses ?? createEmptySection(),
      fuel: source?.fuel ?? { ...createEmptySection(), total_litres: 0 },
      maintenance: source?.maintenance ?? createEmptySection(),
      faults: source?.faults ?? createEmptySection(),
      customers: source?.customers ?? createEmptySection(),
      bookings: source?.bookings ?? { ...createEmptySection(), status_breakdown: {} },
      trip_logs: source?.trip_logs ?? { ...createEmptySection(), trips_by_platform: [], trips_by_purpose: [] },
      driver_performance: source?.driver_performance ?? createEmptySection(),
      vehicle_performance: source?.vehicle_performance ?? createEmptySection(),
      vehicle_economics: source?.vehicle_economics ?? createEmptyVehicleEconomics(),
    };
  }, [reportData]);

  const validationSummary = useMemo(() => {
    if (activeCategory === 'revenue') {
      return combineValidationSummaries(
        reports.collections.validation,
        reports.deposits.validation,
        reports.expenses.validation,
      );
    }
    if (activeCategory === 'drivers') {
      return reports.driver_performance.validation;
    }
    if (activeCategory === 'vehicles') {
      return combineValidationSummaries(
        reports.vehicle_performance.validation,
        reports.vehicle_economics.validation,
      );
    }
    if (activeCategory === 'trips') {
      return combineValidationSummaries(reports.bookings.validation, reports.trip_logs.validation);
    }
    if (activeCategory === 'fuel') {
      return reports.fuel.validation;
    }
    if (activeCategory === 'maintenance') {
      return combineValidationSummaries(reports.maintenance.validation, reports.faults.validation);
    }
    return reports.customers.validation;
  }, [activeCategory, reports]);

  const exportRows = useMemo(() => {
    if (activeCategory === 'revenue') {
      return [
        ...reports.collections.records.map((item) => ({ report_type: 'Collection', ...item })),
        ...reports.deposits.records.map((item) => ({ report_type: 'Deposit', ...item })),
        ...reports.expenses.records.map((item) => ({ report_type: 'Expense', ...item })),
      ];
    }
    if (activeCategory === 'drivers') return reports.driver_performance.records;
    if (activeCategory === 'vehicles') {
      return [
        ...reports.vehicle_performance.records.map((item) => ({ report_type: 'Vehicle Performance', ...item })),
        ...((reports.vehicle_economics.vehicles || []).map((item) => ({
          report_type: 'Vehicle Economics',
          registration_number: item.registration_number,
          total_vehicle_investment: item.economics?.investment?.total_vehicle_investment || 0,
          amount_recovered: item.economics?.recovery?.amount_recovered || 0,
          remaining_balance: item.economics?.recovery?.remaining_balance || 0,
          recovery_percentage: item.economics?.recovery?.recovery_percentage || 0,
          recovery_status: item.economics?.recovery?.recovery_status || item.economics?.recovery?.status || 'Restricted',
          company_vehicle_costs: item.economics?.profitability?.company_vehicle_costs || 0,
          net_profit: item.economics?.profitability?.net_profit || 0,
          break_even_forecast: item.economics?.recovery?.estimated_break_even_date || 'N/A',
        })) as Array<Record<string, unknown>>),
      ];
    }
    if (activeCategory === 'trips') {
      return [
        ...reports.bookings.records.map((item) => ({ report_type: 'Booking', ...item })),
        ...reports.trip_logs.records.map((item) => ({ report_type: 'Trip Log', ...item })),
      ];
    }
    if (activeCategory === 'fuel') return reports.fuel.records;
    if (activeCategory === 'maintenance') {
      return [
        ...reports.maintenance.records.map((item) => ({ report_type: 'Maintenance', ...item })),
        ...reports.faults.records.map((item) => ({ report_type: 'Fault', ...item })),
      ];
    }
    return reports.customers.records;
  }, [activeCategory, reports]);

  const hasExportData = exportRows.length > 0;

  const handleExportExcel = () => {
    if (!hasExportData) return;
    const blob = new Blob([toCsv(exportRows)], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `flux-fleet-${activeCategory}-report.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const handleExportPDF = () => {
    if (!hasExportData) return;
    window.print();
  };

  const handlePrint = () => {
    if (!hasExportData) return;
    window.print();
  };

  if (currentRole === 'driver') {
    return (
      <div className="p-6">
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Drivers do not have access to enterprise reports.
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 overflow-x-hidden p-4 sm:p-6">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold text-[#0F172A]">Enterprise Reporting Center</h1>
          <p className="mt-1 text-sm text-gray-600">
            Verified report totals from live records across collections, bookings, fleet usage, and operating activity.
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-gray-500">
            <span>Generated by: {reportData?.generated_by?.full_name || 'System'}</span>
            <span>|</span>
            <span>Generated at: {formatDateTime(reportData?.generated_at)}</span>
          </div>
        </div>

        <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row sm:flex-wrap">
          <button
            onClick={() => setRefreshKey((current) => current + 1)}
            className="flex w-full items-center justify-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 transition-all hover:bg-gray-50 sm:w-auto"
          >
            <RefreshCw className="h-4 w-4" />
            Refresh
          </button>
          <button
            onClick={handleExportPDF}
            disabled={!hasExportData}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-red-600 px-4 py-2.5 text-sm font-medium text-white transition-all hover:bg-red-700 disabled:cursor-not-allowed disabled:bg-red-300 sm:w-auto"
          >
            <Download className="h-4 w-4" />
            PDF
          </button>
          <button
            onClick={handleExportExcel}
            disabled={!hasExportData}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-green-600 px-4 py-2.5 text-sm font-medium text-white transition-all hover:bg-green-700 disabled:cursor-not-allowed disabled:bg-green-300 sm:w-auto"
          >
            <Download className="h-4 w-4" />
            Excel
          </button>
          <button
            onClick={handlePrint}
            disabled={!hasExportData}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-gray-700 px-4 py-2.5 text-sm font-medium text-white transition-all hover:bg-gray-800 disabled:cursor-not-allowed disabled:bg-gray-300 sm:w-auto"
          >
            <Printer className="h-4 w-4" />
            Print
          </button>
        </div>
      </div>

      <div className="rounded-xl border border-gray-200 bg-white p-4 sm:p-5">
        <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-[#0F172A]">
          <Filter className="h-4 w-4" />
          Active Report Filters
        </div>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
          <select
            value={dateRange}
            onChange={(event) => setDateRange(event.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm text-gray-700"
          >
            <option value="last-30-days">Last 30 Days</option>
            <option value="last-90-days">Last 90 Days</option>
            <option value="this-year">This Year</option>
            <option value="all-time">All Time</option>
          </select>
          <select
            value={selectedDriverId}
            onChange={(event) => setSelectedDriverId(event.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm text-gray-700"
          >
            <option value="">All Drivers</option>
            {(reportData?.available_filters.drivers || []).map((driver) => (
              <option key={driver.id} value={driver.id}>
                {driver.full_name}
              </option>
            ))}
          </select>
          <select
            value={selectedVehicleId}
            onChange={(event) => setSelectedVehicleId(event.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm text-gray-700"
          >
            <option value="">All Vehicles</option>
            {(reportData?.available_filters.vehicles || []).map((vehicle) => (
              <option key={vehicle.id} value={vehicle.id}>
                {vehicle.registration_number}
              </option>
            ))}
          </select>
          <select
            value={selectedBranch}
            onChange={(event) => setSelectedBranch(event.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm text-gray-700"
          >
            <option value="">All Branches</option>
            {(reportData?.available_filters.branches || []).map((branch) => (
              <option key={branch} value={branch}>
                {branch}
              </option>
            ))}
          </select>
        </div>
        {activeCategory === 'customers' && (
          <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-3">
            <select
              value={selectedCreatorRole}
              onChange={(event) => setSelectedCreatorRole(event.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm text-gray-700"
            >
              <option value="">All Creator Roles</option>
              {(reportData?.available_filters.creator_roles || []).map((role) => (
                <option key={role} value={role}>
                  {role}
                </option>
              ))}
            </select>
            <select
              value={selectedCustomerCategoryId}
              onChange={(event) => setSelectedCustomerCategoryId(event.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm text-gray-700"
            >
              <option value="">All Customer Categories</option>
              {(reportData?.available_filters.customer_category_items || []).map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
            <select
              value={selectedSource}
              onChange={(event) => setSelectedSource(event.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm text-gray-700"
            >
              <option value="">All Sources</option>
              {(reportData?.available_filters.sources || []).map((source) => (
                <option key={source} value={source}>
                  {source}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
        {reportCategories.map((category) => {
          const Icon = category.icon;
          const isActive = activeCategory === category.id;
          return (
            <button
              key={category.id}
              onClick={() => setActiveCategory(category.id)}
              className={`rounded-xl border-2 p-4 transition-all ${
                isActive ? `${category.color} shadow-md` : 'border-gray-200 bg-white hover:border-gray-300 hover:shadow-sm'
              }`}
            >
              <div
                className={`mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-lg ${
                  isActive ? 'bg-white/60' : category.color.split(' ')[0]
                }`}
              >
                <Icon className={`h-5 w-5 ${isActive ? category.color.split(' ')[1] : ''}`} />
              </div>
              <div className="text-center text-xs font-semibold text-gray-700 sm:text-sm">{category.label}</div>
            </button>
          );
        })}
      </div>

      {pageError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{pageError}</div>
      )}

      {isLoading ? (
        <div className="space-y-6">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {Array.from({ length: 4 }).map((_, index) => (
              <div key={index} className="rounded-xl border border-gray-200 bg-white p-5">
                <div className="mb-4 h-10 w-10 animate-pulse rounded-lg bg-gray-100" />
                <div className="h-5 w-28 animate-pulse rounded bg-gray-100" />
                <div className="mt-3 h-4 w-40 animate-pulse rounded bg-gray-100" />
              </div>
            ))}
          </div>
          <div className="rounded-xl border border-gray-200 bg-white p-6">
            <div className="space-y-3">
              {Array.from({ length: 6 }).map((_, index) => (
                <div key={index} className="h-10 animate-pulse rounded bg-gray-100" />
              ))}
            </div>
          </div>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <MetricCard label="Total Records" value={validationSummary.total_records.toLocaleString()} icon={FileText} />
            <MetricCard label="Total Amount" value={formatCurrency(validationSummary.total_amount)} icon={DollarSign} />
            <MetricCard label="Last Updated" value={formatDateTime(validationSummary.last_updated)} icon={RefreshCw} />
            <MetricCard label="Active Filters" value={validationSummary.active_filters.join(' | ')} icon={Calendar} />
          </div>

          {reportData && activeCategory === 'revenue' && (
            <div className="space-y-6">
              <SectionHeader title="Collections Report" validation={reports.collections.validation} />
              <ReportTable
                emptyMessage="No records found for this filter."
                columns={['Date', 'Driver', 'Vehicle', 'Amount', 'Status', 'Method']}
                rows={reports.collections.records.map((record: any) => [
                  record.collection_date || 'No date',
                  record.driver_name || 'Unassigned',
                  record.vehicle_registration || 'Unassigned',
                  formatCurrency(record.amount || 0),
                  record.status || 'Unknown',
                  record.payment_method || 'N/A',
                ])}
              />

              <SectionHeader title="Deposits Report" validation={reports.deposits.validation} />
              <ReportTable
                emptyMessage="No records found for this filter."
                columns={['Date', 'Destination', 'Branch', 'Amount', 'Status', 'Method']}
                rows={reports.deposits.records.map((record: any) => [
                  record.deposit_date || 'No date',
                  record.destination_name || 'No destination',
                  record.branch || 'No branch',
                  formatCurrency(record.amount || 0),
                  record.status || 'Unknown',
                  record.deposit_method || 'N/A',
                ])}
              />

              <SectionHeader title="Expenses Report" validation={reports.expenses.validation} />
              <ReportTable
                emptyMessage="No records found for this filter."
                columns={['Date', 'Title', 'Category', 'Driver', 'Vehicle', 'Amount', 'Status']}
                rows={reports.expenses.records.map((record: any) => [
                  record.expense_date || 'No date',
                  record.expense_title || 'Untitled',
                  record.expense_category || 'Uncategorized',
                  record.driver_name || 'N/A',
                  record.vehicle_registration || 'N/A',
                  formatCurrency(record.amount || 0),
                  record.status || 'Unknown',
                ])}
              />
            </div>
          )}

          {reportData && activeCategory === 'drivers' && (
            <div className="space-y-6">
              <SectionHeader title="Driver Performance Report" validation={reports.driver_performance.validation} />
              <ReportTable
                emptyMessage="No records found for this filter."
                columns={['Driver', 'Vehicle', 'Collected', 'Achievement %', 'Fuel Score', 'Critical Faults', 'Maintenance Days Lost']}
                rows={reports.driver_performance.records.map((record: any) => [
                  record.driver?.full_name || 'Unknown Driver',
                  record.vehicle?.registration_number || 'Unassigned',
                  formatCurrency(record.amount_collected || 0),
                  `${record.target_achievement_percentage || 0}%`,
                  `${record.fuel_efficiency_score || 0}`,
                  `${record.number_of_critical_faults || 0}`,
                  `${record.maintenance_days_lost || 0}`,
                ])}
              />
            </div>
          )}

          {reportData && activeCategory === 'vehicles' && (
            <div className="space-y-6">
              <SectionHeader title="Vehicle Performance Report" validation={reports.vehicle_performance.validation} />
              <ReportTable
                emptyMessage="No records found for this filter."
                columns={['Vehicle', 'Status', 'Trips', 'Active Days', 'Idle Days', 'Utilization %']}
                rows={reports.vehicle_performance.records.map((record: any) => [
                  record.registration_number || 'Unknown Vehicle',
                  record.status || 'Unknown',
                  `${record.trip_count || 0}`,
                  `${record.active_days || 0}`,
                  `${record.idle_days || 0}`,
                  `${record.utilization_percentage || 0}%`,
                ])}
              />

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
                <MetricCard label="Fleet Investment" value={formatCurrency(reports.vehicle_economics.total_fleet_investment || 0)} icon={DollarSign} />
                <MetricCard label="Recovered" value={formatCurrency(reports.vehicle_economics.total_recovered || 0)} icon={Target} />
                <MetricCard label="Remaining Balance" value={formatCurrency(reports.vehicle_economics.remaining_recovery_balance || 0)} icon={RefreshCw} />
                <MetricCard label="Net Fleet Profit" value={formatCurrency(reports.vehicle_economics.net_fleet_profit || 0)} icon={Truck} />
              </div>

              <SectionHeader
                title="Vehicle Economics Report"
                validation={reports.vehicle_economics.validation}
                description={reports.vehicle_economics.message}
              />
              <ReportTable
                emptyMessage="No records found for this filter."
                columns={['Vehicle', 'Total Investment', 'Amount Recovered', 'Remaining Balance', 'Recovery %', 'Recovery Status', 'Company Vehicle Costs', 'Net Vehicle Profit', 'Break-Even Forecast']}
                rows={(reports.vehicle_economics.vehicles || []).map((vehicle) => [
                  vehicle.registration_number || 'Unknown Vehicle',
                  formatCurrency(vehicle.economics?.investment?.total_vehicle_investment || 0),
                  formatCurrency(vehicle.economics?.recovery?.amount_recovered || 0),
                  formatCurrency(vehicle.economics?.recovery?.remaining_balance || 0),
                  `${vehicle.economics?.recovery?.recovery_percentage || 0}%`,
                  vehicle.economics?.recovery?.recovery_status || vehicle.economics?.recovery?.status || 'Restricted',
                  formatCurrency(vehicle.economics?.profitability?.company_vehicle_costs || 0),
                  formatCurrency(vehicle.economics?.profitability?.net_profit || 0),
                  formatDate(vehicle.economics?.recovery?.estimated_break_even_date),
                ])}
              />
            </div>
          )}

          {reportData && activeCategory === 'trips' && (
            <div className="space-y-6">
              <SectionHeader title="Booking Report" validation={reports.bookings.validation} />
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
                {Object.entries(reports.bookings.status_breakdown || {}).map(([status, count]) => (
                  <div key={status} className="rounded-xl border border-gray-200 bg-white p-4">
                    <div className="text-sm text-gray-500">{status}</div>
                    <div className="mt-2 text-2xl font-semibold text-[#0F172A]">{count}</div>
                  </div>
                ))}
              </div>
              <ReportTable
                emptyMessage="No records found for this filter."
                columns={['Booking ID', 'Pickup Time', 'Type', 'Driver', 'Vehicle', 'Expected Fare', 'Status']}
                rows={reports.bookings.records.map((record: any) => [
                  record.booking_id || 'No ID',
                  formatDateTime(record.pickup_at),
                  record.booking_type || 'N/A',
                  record.driver_name || 'Unassigned',
                  record.vehicle_registration || 'Unassigned',
                  formatCurrency(record.expected_fare || 0),
                  record.status || 'Unknown',
                ])}
              />

              <SectionHeader title="Trip Log Report" validation={reports.trip_logs.validation} />
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <MiniListCard title="Trips By Platform" items={reports.trip_logs.trips_by_platform || []} />
                <MiniListCard title="Trips By Purpose" items={reports.trip_logs.trips_by_purpose || []} />
              </div>
              <ReportTable
                emptyMessage="No records found for this filter."
                columns={['Trip ID', 'Date', 'Platform', 'Purpose', 'Driver', 'Vehicle', 'Route', 'Status']}
                rows={reports.trip_logs.records.map((record: any) => [
                  record.trip_id || 'No ID',
                  record.trip_date || 'No date',
                  record.trip_source || 'N/A',
                  record.trip_purpose || 'N/A',
                  record.driver_name || 'Unassigned',
                  record.vehicle_registration || 'Unassigned',
                  `${record.pickup_area || 'Unknown'} -> ${record.destination_area || 'Unknown'}`,
                  record.status || 'Unknown',
                ])}
              />
            </div>
          )}

          {reportData && activeCategory === 'fuel' && (
            <div className="space-y-6">
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
                <MetricCard label="Fuel Records" value={reports.fuel.validation.total_records.toLocaleString()} icon={Fuel} />
                <MetricCard label="Fuel Spend" value={formatCurrency(reports.fuel.validation.total_amount)} icon={DollarSign} />
                <MetricCard label="Total Litres" value={(reports.fuel.total_litres || 0).toLocaleString()} icon={Target} />
                <MetricCard label="Last Updated" value={formatDateTime(reports.fuel.validation.last_updated)} icon={RefreshCw} />
              </div>
              <SectionHeader title="Fuel Report" validation={reports.fuel.validation} />
              <ReportTable
                emptyMessage="No records found for this filter."
                columns={['Date', 'Driver', 'Vehicle', 'Fuel Type', 'Litres', 'Amount', 'Status']}
                rows={reports.fuel.records.map((record: any) => [
                  record.fuel_date || 'No date',
                  record.driver_name || 'Unassigned',
                  record.vehicle_registration || 'Unassigned',
                  record.fuel_type || 'N/A',
                  `${record.litres || 0}`,
                  formatCurrency(record.amount || 0),
                  record.status || 'Unknown',
                ])}
              />
            </div>
          )}

          {reportData && activeCategory === 'maintenance' && (
            <div className="space-y-6">
              <SectionHeader title="Maintenance Report" validation={reports.maintenance.validation} />
              <ReportTable
                emptyMessage="No records found for this filter."
                columns={['Reference Date', 'Title', 'Type', 'Driver', 'Vehicle', 'Cost', 'Status']}
                rows={reports.maintenance.records.map((record: any) => [
                  record.reference_date || 'No date',
                  record.title || 'Untitled',
                  record.maintenance_type || 'N/A',
                  record.driver_name || 'N/A',
                  record.vehicle_registration || 'N/A',
                  formatCurrency(record.actual_cost || 0),
                  record.status || 'Unknown',
                ])}
              />

              <SectionHeader title="Fault Report" validation={reports.faults.validation} />
              <ReportTable
                emptyMessage="No records found for this filter."
                columns={['Reported At', 'Severity', 'Driver', 'Vehicle', 'Status', 'Description']}
                rows={reports.faults.records.map((record: any) => [
                  formatDateTime(record.reported_at),
                  record.severity || 'N/A',
                  record.driver_name || 'N/A',
                  record.vehicle_registration || 'N/A',
                  record.status || 'Unknown',
                  record.description || 'No description',
                ])}
              />
            </div>
          )}

          {reportData && activeCategory === 'customers' && (
            <div className="space-y-6">
              <SectionHeader title="Customer Report" validation={reports.customers.validation} />
              <ReportTable
                emptyMessage="No records found for this filter."
                columns={['Customer', 'Phone', 'Category', 'Creator', 'Role', 'Source', 'Relationship', 'Lead Status', 'Lead Value', 'Created']}
                rows={reports.customers.records.map((record: any) => [
                  record.full_name || 'Unnamed Customer',
                  record.phone_number || 'No phone',
                  record.customer_category || 'N/A',
                  record.creator_name || 'Unknown / Legacy Record',
                  record.creator_role || 'legacy',
                  record.source || 'other',
                  record.relationship_category || 'N/A',
                  record.lead_status || 'N/A',
                  formatCurrency(record.lead_value_estimate || 0),
                  formatDate(record.created_at),
                ])}
              />
            </div>
          )}
        </>
      )}
    </div>
  );
}

function MetricCard({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: string;
  icon: typeof DollarSign;
}) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5">
      <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-lg bg-blue-100">
        <Icon className="h-5 w-5 text-blue-600" />
      </div>
      <div className="break-words text-base font-semibold text-[#0F172A] sm:text-lg">{value}</div>
      <div className="mt-1 text-sm text-gray-600">{label}</div>
    </div>
  );
}

function SectionHeader({
  title,
  validation,
  description,
}: {
  title: string;
  validation: ValidationSummary;
  description?: string;
}) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold text-[#0F172A]">{title}</h2>
          {description && <p className="mt-1 text-sm text-gray-600">{description}</p>}
        </div>
        <div className="grid grid-cols-1 gap-2 text-sm text-gray-600 sm:grid-cols-3 lg:text-right">
          <div>Total Records: <span className="font-medium text-[#0F172A]">{validation.total_records}</span></div>
          <div>Total Amount: <span className="font-medium text-[#0F172A]">{formatCurrency(validation.total_amount)}</span></div>
          <div>Last Updated: <span className="font-medium text-[#0F172A]">{formatDateTime(validation.last_updated)}</span></div>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        {validation.active_filters.map((filter) => (
          <span key={filter} className="rounded-full bg-gray-100 px-3 py-1 text-xs font-medium text-gray-600">
            {filter}
          </span>
        ))}
      </div>
    </div>
  );
}

function ReportTable({
  columns,
  rows,
  emptyMessage,
}: {
  columns: string[];
  rows: string[][];
  emptyMessage: string;
}) {
  if (!rows.length) {
    return (
      <div className="rounded-xl border border-gray-200 bg-white px-6 py-12 text-center text-gray-500">
        {emptyMessage}
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px]">
          <thead className="border-b border-gray-200 bg-gray-50">
            <tr>
              {columns.map((column) => (
                <th key={column} className="px-4 py-3 text-left text-xs font-semibold uppercase text-gray-700">
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {rows.map((row, rowIndex) => (
              <tr key={`${row[0] || 'row'}-${rowIndex}`} className="hover:bg-gray-50">
                {row.map((cell, cellIndex) => (
                  <td key={`${rowIndex}-${cellIndex}`} className="px-4 py-3 align-top text-sm text-gray-700">
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function MiniListCard({
  title,
  items,
}: {
  title: string;
  items: Array<{ label: string; count: number }>;
}) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5">
      <h3 className="text-base font-semibold text-[#0F172A]">{title}</h3>
      {items.length === 0 ? (
        <div className="mt-6 text-sm text-gray-500">No records found for this filter.</div>
      ) : (
        <div className="mt-4 space-y-3">
          {items.map((item) => (
            <div key={item.label} className="flex items-center justify-between text-sm">
              <span className="text-gray-600">{item.label}</span>
              <span className="font-medium text-[#0F172A]">{item.count}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
