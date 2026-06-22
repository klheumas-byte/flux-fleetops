import { apiRequest } from './api';

export interface DriverAssignedVehicle {
  id: string;
  registration_number: string;
  vehicle_type?: string | null;
  make?: string | null;
  model?: string | null;
  year?: number | null;
  color?: string | null;
  transmission?: string | null;
  fuel_type?: string | null;
  insurance_expiry?: string | null;
  insurance_profile?: {
    insurance_company?: string | null;
    policy_number?: string | null;
    insurance_type?: string | null;
    claims_officer_name?: string | null;
    claims_officer_phone?: string | null;
    claims_officer_email?: string | null;
    emergency_contact?: string | null;
    expiry_date?: string | null;
  } | null;
  roadworthy_expiry?: string | null;
}

export interface DriverActiveAssignment {
  assignment_id: string;
  driver_id: string;
  vehicle_id: string;
  weekly_target: number;
  daily_target: number;
  start_date: string | null;
  status: string;
  vehicle: DriverAssignedVehicle | null;
}

export interface DriverLatestCollection {
  id: string;
  driver_id: string;
  vehicle_id: string;
  assignment_id: string;
  amount: number;
  submitted_amount?: number | null;
  admin_received_amount?: number | null;
  collection_date: string;
  payment_method: string;
  reference_number?: string | null;
  notes?: string | null;
  driver_note?: string | null;
  admin_approval_note?: string | null;
  status: string;
  received_by_admin_id?: string | null;
  approved_by_admin_id?: string | null;
  submitted_by_driver_id?: string | null;
  rejected_by_admin_id?: string | null;
  submitted_at?: string | null;
  approved_at?: string | null;
  rejected_at?: string | null;
  rejection_reason?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface DriverDashboardSummary {
  driver_id: string;
  active_assignment: {
    id: string;
    driver_id: string;
    vehicle_id: string;
    weekly_target: number;
    daily_target: number;
    start_date: string | null;
    end_date?: string | null;
    status: string;
    assigned_by?: string | null;
    created_by?: string | null;
    created_at?: string | null;
    updated_at?: string | null;
    ended_at?: string | null;
  } | null;
  vehicle: DriverAssignedVehicle | null;
  weekly_target: number;
  daily_target: number;
  amount_paid_this_week: number;
  outstanding_balance: number;
  achievement_percentage: number;
  total_collections_this_week: number;
  latest_collections: DriverLatestCollection[];
  today_collection_total: number;
  weekly_cycle?: {
    payment_deadline?: string | null;
  } | null;
}

export interface DriverWalletLedgerEntry {
  date: string | null;
  type: string;
  description: string;
  debit: number;
  credit: number;
  balance_after: number;
  reference_id: string | null;
}

export interface DriverWeeklyCyclePayment {
  id: string | null;
  amount: number;
  submitted_amount?: number | null;
  admin_received_amount?: number | null;
  status: string;
  collection_date: string | null;
  payment_method: string | null;
  reference_number: string | null;
  driver_note?: string | null;
  admin_approval_note?: string | null;
  rejection_reason: string | null;
  is_late: boolean;
}

export interface DriverWeeklyCycle {
  cycle_key: string;
  assignment_id: string;
  week_start: string;
  week_end: string;
  payment_deadline: string;
  weekly_target: number;
  submitted_total: number;
  approved_total: number;
  outstanding_balance: number;
  achievement_percentage: number;
  status: 'open' | 'completed' | 'overdue' | string;
  payments: DriverWeeklyCyclePayment[];
}

export interface DriverWalletData {
  driver_id: string;
  active_assignment_id: string | null;
  weekly_target: number;
  daily_target: number;
  total_debits: number;
  total_credits: number;
  outstanding_balance: number;
  achievement_percentage: number;
  weekly_cycle: DriverWeeklyCycle | null;
  weekly_history: DriverWeeklyCycle[];
  ledger_entries: DriverWalletLedgerEntry[];
}

interface DriverActiveAssignmentResponse {
  success: boolean;
  message: string;
  data: {
    assignment: DriverActiveAssignment | null;
  };
}

interface DriverDashboardSummaryResponse {
  success: boolean;
  message: string;
  data: {
    summary: DriverDashboardSummary;
  };
}

interface DriverWalletResponse {
  success: boolean;
  message: string;
  data: {
    wallet: DriverWalletData;
  };
}

interface DriverPaymentSubmissionResponse {
  success: boolean;
  message: string;
  data: {
    payment: DriverLatestCollection;
  };
}

export async function fetchDriverActiveAssignment(): Promise<DriverActiveAssignment | null> {
  const response = await apiRequest<DriverActiveAssignmentResponse>('/driver/active-assignment');
  return response.data.assignment;
}

export async function fetchDriverDashboardSummary(): Promise<DriverDashboardSummary> {
  const response = await apiRequest<DriverDashboardSummaryResponse>('/driver/dashboard-summary');
  return response.data.summary;
}

export async function fetchDriverWallet(): Promise<DriverWalletData> {
  const response = await apiRequest<DriverWalletResponse>('/driver/wallet');
  return response.data.wallet;
}

export async function submitDriverPayment(payload: {
  amount: number;
  collection_date: string;
  payment_method: 'cash' | 'momo' | 'bank' | 'other';
  reference_number?: string;
  notes?: string;
}): Promise<DriverLatestCollection> {
  const response = await apiRequest<DriverPaymentSubmissionResponse>('/driver/payments', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return response.data.payment;
}
