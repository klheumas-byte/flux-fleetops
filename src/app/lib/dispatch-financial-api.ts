import { apiRequest } from './api';

export type DispatchFinancialStatus =
  | 'pending_collection'
  | 'partially_submitted'
  | 'fully_submitted'
  | 'outstanding'
  | 'under_review'
  | 'verified'
  | 'disputed'
  | 'cancelled';
export type DispatchFinancialType = 'external_paid' | 'internal_company' | 'partner_contract' | 'complimentary';
export type DriverCompensationType = 'none' | 'fixed_tip' | 'fixed_allowance' | 'percentage_of_charge' | 'manual_amount';
export type DispatchPricingType = 'standard' | 'subsidized' | 'complimentary';

export interface DispatchFinanceSnapshot {
  snapshot_version: number;
  basis: 'estimate' | 'actual';
  pricing_type: DispatchPricingType;
  commercial_value: number;
  customer_charge: number;
  concession_value: number;
  funding_source?: { id: string; name: string; description?: string | null } | null;
  billable_distance_km: number;
  operational_distance_km: number;
  fuel: { litres: number; cost: number; price_per_litre: number; vehicle_efficiency?: { km_per_litre: number } };
  driver_compensation: { mode: 'amount' | 'percentage'; value: number; suggested_amount: number; base_amount: number; extras_amount: number; approved_amount: number; effective_percentage: number; adjustments: Array<Record<string, unknown>> };
  maintenance_reserve: { rate_percent: number; amount: number; funding_shortfall: number };
  other_direct_costs: number;
  vehicle_capital_profit_allocation: number;
  expected_company_contribution: number;
  warnings: string[];
  estimated_vs_actual?: Record<string, { estimated: number; actual: number }>;
}

export type DispatchFinancialExpenseStatus = 'pending' | 'approved' | 'rejected' | 'reimbursed' | 'cancelled';
export type DispatchFinancialIncidentStatus =
  | 'reported'
  | 'under_review'
  | 'approved'
  | 'rejected'
  | 'company_paid'
  | 'driver_liable'
  | 'shared_payment'
  | 'closed'
  | 'cancelled';
export type DispatchFinancialResponsibility =
  | 'driver_responsible'
  | 'company_responsible'
  | 'shared_responsibility'
  | 'under_investigation';

export interface DispatchFinancialSimpleUser {
  id: string;
  full_name: string;
  phone?: string | null;
  email?: string | null;
  role?: string | null;
  status?: string | null;
}

export interface DispatchFinancialSimpleVehicle {
  id: string;
  registration_number: string;
  make?: string | null;
  model?: string | null;
  vehicle_type?: string | null;
  status?: string | null;
}

export interface DispatchFinancialRecord {
  id: string;
  dispatch_financial_id?: string | null;
  dispatch_job_id: string;
  dispatch_request_id?: string | null;
  vehicle_movement_id?: string | null;
  vehicle_id?: string | null;
  driver_id?: string | null;
  approved_charge: number;
  amount_paid: number;
  dispatch_financial_type: DispatchFinancialType;
  dispatch_financial_type_is_legacy?: boolean;
  partner_organization_reference?: string | null;
  partner_billing_method?: string | null;
  driver_compensation_type: DriverCompensationType;
  driver_compensation_value: number;
  driver_compensation_amount: number;
  driver_compensation_approved_by?: string | null;
  driver_compensation_approved_at?: string | null;
  amount_collected_from_customer: number;
  amount_submitted_by_driver: number;
  outstanding_balance: number;
  expected_fuel_cost: number;
  actual_fuel_cost: number;
  estimated_other_costs: number;
  approved_expenses: number;
  company_incident_costs: number;
  driver_liability_total: number;
  company_operational_cost: number;
  expected_net_revenue: number;
  actual_net_revenue: number;
  finance_notes?: string | null;
  payment_method?: string | null;
  payment_reference?: string | null;
  submitted_by?: string | null;
  submitted_at?: string | null;
  verified_by?: string | null;
  verified_at?: string | null;
  financial_status: DispatchFinancialStatus;
  is_financially_closed: boolean;
  financial_closed_at?: string | null;
  financial_closed_by?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  last_submission?: Record<string, unknown>;
  pricing_type?: DispatchPricingType | null;
  commercial_value?: number | null;
  customer_charge?: number | null;
  concession_value?: number | null;
  funding_source_snapshot?: { id: string; name: string; description?: string | null } | null;
  maintenance_reserve_amount?: number | null;
  finance_snapshot?: DispatchFinanceSnapshot | null;
  final_finance_snapshot?: DispatchFinanceSnapshot | null;
}

export interface DispatchFinancialExpense {
  id: string;
  dispatch_financial_id: string;
  dispatch_job_id: string;
  vehicle_movement_id?: string | null;
  vehicle_id?: string | null;
  driver_id?: string | null;
  expense_type: string;
  amount: number;
  note: string;
  receipt_reference?: string | null;
  status: DispatchFinancialExpenseStatus;
  rejection_reason?: string | null;
  submitted_by?: string | null;
  submitted_at?: string | null;
  reviewed_by?: string | null;
  reviewed_at?: string | null;
}

export interface DispatchFinancialIncident {
  id: string;
  dispatch_financial_id: string;
  dispatch_job_id: string;
  vehicle_movement_id?: string | null;
  vehicle_id?: string | null;
  driver_id?: string | null;
  linked_incident_id?: string | null;
  incident_type: string;
  incident_date: string;
  incident_location: string;
  amount: number;
  responsibility_type: DispatchFinancialResponsibility;
  company_share: number;
  driver_share: number;
  final_responsible_party?: string | null;
  description: string;
  evidence_reference?: string | null;
  admin_notes?: string | null;
  status: DispatchFinancialIncidentStatus;
  rejection_reason?: string | null;
  submitted_by?: string | null;
  submitted_at?: string | null;
  reviewed_by?: string | null;
  reviewed_at?: string | null;
  linked_incident?: Record<string, unknown> | null;
}

export interface DispatchFinancialListItem extends DispatchFinancialRecord {
  vehicle?: DispatchFinancialSimpleVehicle | null;
  driver?: DispatchFinancialSimpleUser | null;
  job?: {
    id: string;
    dispatch_job_id: string;
    status: string;
    return_status?: string | null;
    dispatch_date?: string | null;
    scheduled_start_time?: string | null;
  } | null;
  movement?: {
    id: string;
    status: string;
    actual_return_time?: string | null;
  } | null;
}

export interface DispatchFinancialDetail {
  record: DispatchFinancialRecord;
  job?: Record<string, unknown> & {
    id: string;
    dispatch_job_id: string;
    status: string;
    return_status?: string | null;
    dispatch_date?: string | null;
    dispatch_time?: string | null;
    scheduled_start_time?: string | null;
    expected_return_time?: string | null;
    goods_description?: string | null;
  };
  movement?: Record<string, unknown> | null;
  vehicle?: DispatchFinancialSimpleVehicle | null;
  driver?: DispatchFinancialSimpleUser | null;
  expenses: DispatchFinancialExpense[];
  incidents: DispatchFinancialIncident[];
}

export interface DriverDispatchMoneySubmissionResponse {
  dispatch_financial_id: string | null;
  dispatch_job_id: string;
  vehicle_movement_id?: string | null;
  financial_status: DispatchFinancialStatus;
  amount_collected: number;
  amount_submitted: number;
  outstanding_balance: number;
  updated_at?: string | null;
  record: DispatchFinancialRecord;
}

export interface DispatchFinancialListResponse {
  records: DispatchFinancialListItem[];
  pagination: {
    page: number;
    page_size: number;
    total: number;
    total_pages: number;
  };
  summary: {
    dispatch_revenue: number;
    paid_dispatch_revenue: number;
    internal_dispatch_operating_costs: number;
    partner_contract_dispatches: number;
    partner_contract_revenue: number;
    partner_contract_costs: number;
    complimentary_dispatch_costs: number;
    driver_dispatch_compensation: number;
    outstanding_dispatch_payments: number;
    driver_liabilities: number;
    company_operational_costs: number;
    dispatch_profitability: number;
    incident_trends: {
      total: number;
      under_investigation: number;
      driver_responsible: number;
      company_responsible: number;
      shared: number;
    };
    most_expensive_vehicle_id?: string | null;
    revenue_by_driver_id?: string | null;
  };
  filters?: {
    q?: string | null;
    financial_status?: string | null;
  };
}

export interface DriverDispatchFinancialListResponse {
  records: DispatchFinancialListItem[];
  pagination: {
    page: number;
    page_size: number;
    total: number;
    total_pages: number;
  };
  statuses: string[];
}

interface Envelope<T> {
  success: boolean;
  data: T;
}

export async function fetchDispatchFinancials(params: {
  page?: number;
  page_size?: number;
  q?: string;
  financial_status?: string;
} = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && String(value).trim() !== '') {
      query.set(key, String(value));
    }
  });
  const response = await apiRequest<Envelope<DispatchFinancialListResponse>>(`/dispatch-financials${query.toString() ? `?${query.toString()}` : ''}`, {
    cacheTtlMs: 5000,
    dedupeKey: `dispatch-financials:${query.toString() || 'default'}`,
    componentName: 'DispatchFinancials',
    requestLabel: 'list',
    cancelGroup: 'dispatch-financials-list',
    replacePending: true,
  });
  return response.data;
}

export async function fetchDispatchFinancialOptions() {
  const response = await apiRequest<Envelope<{
    financial_statuses: string[];
    expense_types: string[];
    expense_statuses: string[];
    incident_types: string[];
    responsibility_types: string[];
    incident_statuses: string[];
  }>>('/dispatch-financials/options', {
    cacheTtlMs: 15000,
    dedupeKey: 'dispatch-financial-options',
    componentName: 'DispatchFinancials',
    requestLabel: 'options',
  });
  return response.data;
}

export async function fetchDispatchFinancialDetail(jobId: string) {
  const response = await apiRequest<Envelope<DispatchFinancialDetail>>(`/dispatch-financials/${jobId}`, {
    cacheTtlMs: 3000,
    dedupeKey: `dispatch-financial-detail:${jobId}`,
    componentName: 'DispatchFinancials',
    requestLabel: 'detail',
  });
  return response.data;
}

export async function createDispatchFinancialIncident(jobId: string, payload: Record<string, unknown>) {
  const response = await apiRequest<Envelope<DispatchFinancialDetail>>(`/dispatch-financials/${jobId}/incidents`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return response.data;
}

export async function verifyDispatchFinancial(jobId: string, payload?: { finance_notes?: string; driver_compensation_type?: DriverCompensationType; driver_compensation_value?: number }) {
  const response = await apiRequest<Envelope<DispatchFinancialDetail>>(`/dispatch-financials/${jobId}/verify`, {
    method: 'PATCH',
    body: JSON.stringify(payload || {}),
  });
  return response.data;
}

export async function previewDispatchFinance(jobId: string, payload: Record<string, unknown>) {
  const response = await apiRequest<Envelope<DispatchFinanceSnapshot>>(`/dispatch-financials/${jobId}/preview`, { method: 'POST', body: JSON.stringify(payload) });
  return response.data;
}

export async function approveDispatchFinanceSnapshot(jobId: string, payload: Record<string, unknown>) {
  const response = await apiRequest<Envelope<DispatchFinanceSnapshot>>(`/dispatch-financials/${jobId}/approve-snapshot`, { method: 'POST', headers: { 'Idempotency-Key': `dispatch-finance:${jobId}` }, body: JSON.stringify(payload) });
  return response.data;
}

export async function finalizeDispatchFinanceSnapshot(jobId: string, payload: Record<string, unknown>) {
  const response = await apiRequest<Envelope<DispatchFinanceSnapshot>>(`/dispatch-financials/${jobId}/finalize-snapshot`, { method: 'POST', body: JSON.stringify(payload) });
  return response.data;
}

export async function fetchDispatchFinanceAnalytics(params: Record<string, string | undefined> = {}) {
  const query = new URLSearchParams(); Object.entries(params).forEach(([key,value]) => { if (value) query.set(key,value); });
  const response = await apiRequest<Envelope<{ start_date?: string | null; end_date: string; summary: Record<string, any>; records: Array<Record<string, any>> }>>(`/dispatch-financials/analytics?${query.toString()}`, { cacheTtlMs: 5000, dedupeKey:`dispatch-finance-analytics:${query.toString()}` });
  return response.data;
}

export async function closeDispatchFinancial(jobId: string, payload?: { finance_notes?: string }) {
  const response = await apiRequest<Envelope<DispatchFinancialDetail>>(`/dispatch-financials/${jobId}/close`, {
    method: 'PATCH',
    body: JSON.stringify(payload || {}),
  });
  return response.data;
}

export async function reviewDispatchExpense(expenseId: string, payload: {
  status: DispatchFinancialExpenseStatus;
  rejection_reason?: string;
}) {
  const response = await apiRequest<Envelope<DispatchFinancialDetail>>(`/dispatch-financials/expenses/${expenseId}/review`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
  return response.data;
}

export async function reviewDispatchIncident(incidentId: string, payload: Record<string, unknown>) {
  const response = await apiRequest<Envelope<DispatchFinancialDetail>>(`/dispatch-financials/incidents/${incidentId}/review`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
  return response.data;
}

export async function fetchDriverDispatchFinancials(params: {
  page?: number;
  page_size?: number;
  financial_status?: string;
} = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && String(value).trim() !== '') {
      query.set(key, String(value));
    }
  });
  const response = await apiRequest<Envelope<DriverDispatchFinancialListResponse>>(`/driver/dispatch-financials${query.toString() ? `?${query.toString()}` : ''}`, {
    cacheTtlMs: 5000,
    dedupeKey: `driver-dispatch-financials:${query.toString() || 'default'}`,
    componentName: 'MyDispatchFinancials',
    requestLabel: 'list',
  });
  return response.data;
}

export async function fetchDriverDispatchFinancialDetail(jobId: string) {
  const response = await apiRequest<Envelope<DispatchFinancialDetail>>(`/driver/dispatch-financials/${jobId}`, {
    cacheTtlMs: 3000,
    dedupeKey: `driver-dispatch-financial-detail:${jobId}`,
    componentName: 'MyDispatchFinancials',
    requestLabel: 'detail',
  });
  return response.data;
}

export async function submitDriverDispatchMoney(jobId: string, payload: Record<string, unknown>) {
  const response = await apiRequest<Envelope<DriverDispatchMoneySubmissionResponse>>(`/driver/dispatch-financials/${jobId}/money`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return response.data;
}

export async function submitDriverDispatchExpense(jobId: string, payload: Record<string, unknown>) {
  const response = await apiRequest<Envelope<DispatchFinancialDetail>>(`/driver/dispatch-financials/${jobId}/expenses`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return response.data;
}

export async function submitDriverDispatchIncident(jobId: string, payload: Record<string, unknown>) {
  const response = await apiRequest<Envelope<DispatchFinancialDetail>>(`/driver/dispatch-financials/${jobId}/incidents`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return response.data;
}
