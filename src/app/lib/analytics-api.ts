import { apiRequest } from './api';

export interface AnalyticsUserSummary {
  id: string;
  full_name: string;
  email: string;
  phone: string;
  role: 'owner' | 'admin' | 'driver';
  status: string;
}

export interface AnalyticsVehicleSummary {
  id: string;
  registration_number: string;
  vehicle_type?: string | null;
  status?: string | null;
}

export interface DriverPerformanceRecord {
  driver: AnalyticsUserSummary;
  vehicle: AnalyticsVehicleSummary | null;
  weekly_target: number;
  amount_collected: number;
  outstanding_balance: number;
  target_achievement_percentage: number;
  number_of_late_payments: number;
  payment_consistency_percentage: number;
  fuel_spend: number;
  fuel_logs_count: number;
  average_fuel_cost_per_km: number;
  fuel_efficiency_score: number;
  number_of_fault_reports: number;
  number_of_critical_faults: number;
  maintenance_days_lost: number;
  customers_generated: number;
  recurring_customers: number;
  scheduled_customers: number;
  business_leads_captured: number;
  active_assignment_status: string;
  overall_driver_score: number;
  score_breakdown: {
    target_score: number;
    payment_score: number;
    fuel_score: number;
    reliability_score: number;
    assignment_score: number;
  };
  detail: {
    active_assignment: {
      id: string;
      weekly_target: number;
      daily_target: number;
      start_date: string | null;
      end_date: string | null;
      status: string;
    } | null;
    recent_collections: Array<{
      id: string;
      collection_date: string | null;
      amount: number;
      status: string;
      is_late: boolean;
      payment_method: string | null;
    }>;
    recent_fuel_logs: Array<{
      id: string;
      fuel_date: string | null;
      amount: number;
      cost_per_km: number | null;
      status: string;
    }>;
    fault_history: Array<{
      id: string;
      reported_at: string | null;
      severity: string;
      status: string;
      description: string;
    }>;
    maintenance_summary: {
      jobs_count: number;
      days_lost: number;
    };
    recent_generated_customers: Array<{
      id: string;
      full_name: string;
      source?: string | null;
      created_at?: string | null;
    }>;
  };
}

export interface DriverLeaderboardEntry {
  rank: number;
  driver: AnalyticsUserSummary;
  vehicle: AnalyticsVehicleSummary | null;
  overall_driver_score: number;
  target_achievement_percentage: number;
  payment_consistency_percentage: number;
  fuel_efficiency_score: number;
  number_of_critical_faults: number;
  maintenance_days_lost: number;
  customers_generated: number;
  recurring_customers: number;
  scheduled_customers: number;
  business_leads_captured: number;
}

export interface DriverAnalyticsFilters {
  start_date?: string;
  end_date?: string;
  vehicle_id?: string;
  admin_id?: string;
  branch?: string;
}

interface DriverAnalyticsListResponse {
  success: boolean;
  data: {
    drivers: DriverPerformanceRecord[];
    filters: {
      start_date: string;
      end_date: string;
      vehicle_id: string | null;
      admin_id: string | null;
      branch: string | null;
    };
    available_filters: {
      vehicles: AnalyticsVehicleSummary[];
      admins: AnalyticsUserSummary[];
      branches: string[];
    };
  };
}

interface DriverAnalyticsDetailResponse {
  success: boolean;
  data: {
    driver_performance: DriverPerformanceRecord;
    filters: {
      start_date: string;
      end_date: string;
      vehicle_id: string | null;
      admin_id: string | null;
      branch: string | null;
    };
  };
}

interface DriverLeaderboardResponse {
  success: boolean;
  data: {
    leaderboard: DriverLeaderboardEntry[];
    filters: {
      start_date: string;
      end_date: string;
      vehicle_id: string | null;
      admin_id: string | null;
      branch: string | null;
    };
  };
}

function toQueryString(filters: DriverAnalyticsFilters = {}) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value) {
      params.set(key, value);
    }
  });
  const query = params.toString();
  return query ? `?${query}` : '';
}

export async function fetchDriverAnalytics(filters: DriverAnalyticsFilters = {}) {
  const response = await apiRequest<DriverAnalyticsListResponse>(
    `/analytics/drivers${toQueryString(filters)}`,
  );
  return response.data;
}

export async function fetchDriverAnalyticsDetail(driverId: string, filters: DriverAnalyticsFilters = {}) {
  const response = await apiRequest<DriverAnalyticsDetailResponse>(
    `/analytics/drivers/${driverId}${toQueryString(filters)}`,
  );
  return response.data;
}

export async function fetchDriverAnalyticsLeaderboard(filters: DriverAnalyticsFilters = {}) {
  const response = await apiRequest<DriverLeaderboardResponse>(
    `/analytics/drivers/leaderboard${toQueryString(filters)}`,
  );
  return response.data;
}
