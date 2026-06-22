import { apiRequest } from './api';
import type { RideRecord } from './ride-masterdata-api';

export interface UserSummary {
  id: string;
  full_name: string;
  role: string;
  status: string;
}

export interface VehicleSummary {
  id: string;
  registration_number: string;
  vehicle_type?: string | null;
  make?: string | null;
  model?: string | null;
}

export interface BookingRecord {
  id: string;
  booking_id: string;
  customer_id: string;
  driver_id?: string | null;
  vehicle_id?: string | null;
  booking_type: string;
  pickup_date: string;
  pickup_time: string;
  pickup_location: string;
  destination: string;
  expected_fare?: number | null;
  title?: string | null;
  description?: string | null;
  notes?: string | null;
  status: string;
  priority?: string | null;
  assigned_to?: string | null;
  completed_by?: string | null;
  reminder_date?: string | null;
  reminder_time?: string | null;
  reminder_sent: boolean;
  reminder_flags?: Record<string, string>;
  created_by: string;
  created_at?: string | null;
  updated_at?: string | null;
  source_booking_id?: string | null;
  is_recurring_template: boolean;
  generated_from_recurring: boolean;
  recurrence_type?: string | null;
  recurrence_frequency?: number | null;
  recurrence_days?: string[];
  monthly_week_of_month?: number | null;
  monthly_day_of_week?: string | null;
  custom_rule_text?: string | null;
  recurrence_end_date?: string | null;
  pickup_at?: string | null;
  acknowledged_by?: string | null;
  acknowledged_at?: string | null;
  en_route_at?: string | null;
  picked_up_at?: string | null;
  completed_at?: string | null;
  completion_note?: string | null;
  issue_type?: string | null;
  issue_note?: string | null;
  issue_reported_at?: string | null;
  trip_log_id?: string | null;
  activity_kind?: string | null;
  activity_color?: string | null;
  is_overdue?: boolean;
  is_personal_reminder?: boolean;
  is_follow_up_reminder?: boolean;
  is_company_event?: boolean;
  issue_history?: Array<{
    issue_type?: string | null;
    issue_note?: string | null;
    reported_at?: string | null;
    reported_by?: string | null;
  }>;
  customer?: CustomerRecord | null;
  driver?: UserSummary | null;
  vehicle?: VehicleSummary | null;
}

export interface CustomerRecord {
  id: string;
  customer_id: string;
  full_name: string;
  phone_number: string;
  alternate_phone?: string | null;
  email_address?: string | null;
  date_of_birth?: string | null;
  occupation?: string | null;
  organization_name?: string | null;
  position_title?: string | null;
  customer_category: string;
  customer_category_id?: string | null;
  pickup_location?: string | null;
  destination_location?: string | null;
  residential_area?: string | null;
  work_area?: string | null;
  preferred_pickup_location?: string | null;
  preferred_dropoff_location?: string | null;
  customer_source_id?: string | null;
  customer_source?: string | null;
  organization_type_id?: string | null;
  organization_type?: string | null;
  industry_id?: string | null;
  industry?: string | null;
  referred_by?: string | null;
  relationship_category_id?: string | null;
  relationship_category?: string | null;
  opportunity_level_id?: string | null;
  opportunity_level?: string | null;
  network_value_id?: string | null;
  network_value?: string | null;
  is_transport_customer?: boolean;
  is_business_lead?: boolean;
  lead_status_id?: string | null;
  lead_status?: string | null;
  potential_service_id?: string | null;
  potential_service?: string | null;
  lead_value_estimate?: number | null;
  follow_up_date?: string | null;
  next_follow_up_date?: string | null;
  follow_up_priority?: string | null;
  follow_up_completed_at?: string | null;
  preferred_driver_id?: string | null;
  assigned_driver_id?: string | null;
  notes?: string | null;
  relationship_notes?: string | null;
  lead_notes?: string | null;
  important_notes?: string | null;
  company_name?: string | null;
  company_industry?: string | null;
  status: 'active' | 'inactive';
  created_by: string;
  created_by_user_id?: string | null;
  created_by_name?: string | null;
  created_by_role?: string | null;
  created_by_driver_id?: string | null;
  source?: string | null;
  source_label?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  preferred_driver?: UserSummary | null;
  assigned_driver?: UserSummary | null;
  created_by_user?: UserSummary | null;
  total_rides?: number;
  total_bookings?: number;
  last_ride_date?: string | null;
  upcoming_bookings_count?: number;
  completed_bookings_count?: number;
  missed_bookings_count?: number;
  ride_frequency?: string;
  ride_history?: RideRecord[];
  upcoming_bookings?: BookingRecord[];
  completed_bookings?: BookingRecord[];
  missed_bookings?: BookingRecord[];
  recurring_schedule?: BookingRecord[];
  active_follow_up_date?: string | null;
  is_follow_up_due_today?: boolean;
  is_follow_up_overdue?: boolean;
  is_high_priority_follow_up?: boolean;
  follow_up_status_label?: string;
  follow_up_history?: Array<{
    action: string;
    date?: string | null;
    next_follow_up_date?: string | null;
    priority?: string | null;
    note?: string | null;
    at?: string | null;
    by?: string | null;
  }>;
  profile_summary?: {
    full_name: string;
    phone_number: string;
    occupation?: string | null;
    position?: string | null;
    organization?: string | null;
    category: string;
    relationship_category?: string | null;
    opportunity_level?: string | null;
    network_value?: string | null;
    lead_status?: string | null;
    preferred_driver?: UserSummary | null;
    total_rides?: number;
    last_ride_date?: string | null;
    upcoming_bookings?: number;
    completed_bookings?: number;
    missed_bookings?: number;
    follow_up_date?: string | null;
  };
}

export interface MasterDataOption {
  id: string;
  data_type: string;
  name: string;
  active: boolean;
  archived?: boolean;
  admin_editable?: boolean;
}

export interface CustomerOptionsResponse {
  drivers: UserSummary[];
  customer_categories: string[];
  customer_category_items: MasterDataOption[];
  customer_sources: string[];
  customer_source_items: MasterDataOption[];
  company_industries: string[];
  industry_items: MasterDataOption[];
  organization_types: string[];
  organization_type_items: MasterDataOption[];
  relationship_category_items: MasterDataOption[];
  opportunity_level_items: MasterDataOption[];
  network_value_items: MasterDataOption[];
  lead_status_items: MasterDataOption[];
  potential_service_items: MasterDataOption[];
  follow_up_priorities: string[];
  statuses: string[];
  source_options?: Array<{ value: string; label: string }>;
  creator_roles?: string[];
}

export interface BookingOptionsResponse {
  customers: CustomerRecord[];
  drivers: UserSummary[];
  vehicles: VehicleSummary[];
  booking_types: string[];
  statuses: string[];
  recurrence_types: string[];
  priorities?: string[];
}

export interface CalendarEntry {
  booking: BookingRecord;
  time: string;
  customer: string;
  pickup: string;
  destination: string;
  status: string;
  color?: string;
  is_overdue?: boolean;
}

export interface BookingSummary {
  upcoming_bookings: number;
  missed_bookings: number;
  active_recurring_customers: number;
  total_customers: number;
  total_recurring_customers: number;
  today_schedule: number;
  upcoming_pickups: number;
  recent_customers: number;
  scheduled_today: number;
  pending_acknowledgement: number;
  in_progress_bookings: number;
  completed_today: number;
  total_scheduled_bookings?: number;
  overdue_reminders?: number;
  follow_ups_due_today?: number;
  upcoming_corporate_bookings?: number;
  total_future_bookings?: number;
  vip_bookings?: number;
  strategic_meetings?: number;
  driver_schedules?: number;
  follow_up_completion_rate?: number;
  bookings_by_status: Record<string, number>;
  customer_growth_trend: Array<{ label: string; value: number }>;
}

export interface CustomerSummary {
  total_customers: number;
  new_customers_this_week: number;
  new_customers_this_month: number;
  total_business_leads: number;
  total_strategic_contacts: number;
  total_investors: number;
  total_gatekeepers: number;
  follow_ups_due_today: number;
  follow_ups_overdue: number;
  high_priority_follow_ups_due: number;
  lead_conversion_rate: number;
  customers_by_creator: Array<{
    creator_name: string;
    creator_role: string;
    creator_user_id?: string | null;
    count: number;
  }>;
  customers_by_driver: Array<{
    driver_id?: string | null;
    driver_name: string;
    count: number;
  }>;
  customers_by_source: Array<{
    source: string;
    label: string;
    count: number;
  }>;
  top_customer_generators: Array<{
    creator_name: string;
    creator_role: string;
    creator_user_id?: string | null;
    count: number;
  }>;
  follow_up_due_customers: Array<{
    id: string;
    full_name: string;
    phone_number: string;
    follow_up_date?: string | null;
    follow_up_priority?: string | null;
    follow_up_status_label?: string | null;
    lead_status?: string | null;
    relationship_category?: string | null;
  }>;
  customer_growth_trend: Array<{ label: string; value: number }>;
  available_filters?: {
    creator_roles: string[];
    drivers: UserSummary[];
    customer_categories: Array<{ id: string; name: string }>;
    sources: Array<{ value: string; label: string }>;
  };
  applied_filters?: {
    date_from?: string | null;
    date_to?: string | null;
    creator_role?: string | null;
    driver_id?: string | null;
    customer_category_id?: string | null;
    source?: string | null;
  };
}

function ensureArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

function ensureObject<T extends object>(value: unknown, fallback: T): T {
  return value && typeof value === 'object' ? ({ ...fallback, ...(value as Partial<T>) } as T) : fallback;
}

function normalizeCustomerOptions(value: unknown): CustomerOptionsResponse {
  const normalized = ensureObject<CustomerOptionsResponse>(value, {
    drivers: [],
    customer_categories: [],
    customer_category_items: [],
    customer_sources: [],
    customer_source_items: [],
    company_industries: [],
    industry_items: [],
    organization_types: [],
    organization_type_items: [],
    relationship_category_items: [],
    opportunity_level_items: [],
    network_value_items: [],
    lead_status_items: [],
    potential_service_items: [],
    follow_up_priorities: [],
    statuses: [],
    source_options: [],
    creator_roles: [],
  });

  return {
    ...normalized,
    drivers: ensureArray<UserSummary>(normalized.drivers),
    customer_categories: ensureArray<string>(normalized.customer_categories),
    customer_category_items: ensureArray<MasterDataOption>(normalized.customer_category_items),
    customer_sources: ensureArray<string>(normalized.customer_sources),
    customer_source_items: ensureArray<MasterDataOption>(normalized.customer_source_items),
    company_industries: ensureArray<string>(normalized.company_industries),
    industry_items: ensureArray<MasterDataOption>(normalized.industry_items),
    organization_types: ensureArray<string>(normalized.organization_types),
    organization_type_items: ensureArray<MasterDataOption>(normalized.organization_type_items),
    relationship_category_items: ensureArray<MasterDataOption>(normalized.relationship_category_items),
    opportunity_level_items: ensureArray<MasterDataOption>(normalized.opportunity_level_items),
    network_value_items: ensureArray<MasterDataOption>(normalized.network_value_items),
    lead_status_items: ensureArray<MasterDataOption>(normalized.lead_status_items),
    potential_service_items: ensureArray<MasterDataOption>(normalized.potential_service_items),
    follow_up_priorities: ensureArray<string>(normalized.follow_up_priorities),
    statuses: ensureArray<string>(normalized.statuses),
    source_options: ensureArray<{ value: string; label: string }>(normalized.source_options),
    creator_roles: ensureArray<string>(normalized.creator_roles),
  };
}

function normalizeBookingOptions(value: unknown): BookingOptionsResponse {
  const normalized = ensureObject<BookingOptionsResponse>(value, {
    customers: [],
    drivers: [],
    vehicles: [],
    booking_types: [],
    statuses: [],
    recurrence_types: [],
    priorities: [],
  });

  return {
    ...normalized,
    customers: ensureArray<CustomerRecord>(normalized.customers),
    drivers: ensureArray<UserSummary>(normalized.drivers),
    vehicles: ensureArray<VehicleSummary>(normalized.vehicles),
    booking_types: ensureArray<string>(normalized.booking_types),
    statuses: ensureArray<string>(normalized.statuses),
    recurrence_types: ensureArray<string>(normalized.recurrence_types),
    priorities: ensureArray<string>(normalized.priorities),
  };
}

const emptyBookingSummary: BookingSummary = {
  upcoming_bookings: 0,
  missed_bookings: 0,
  active_recurring_customers: 0,
  total_customers: 0,
  total_recurring_customers: 0,
  today_schedule: 0,
  upcoming_pickups: 0,
  recent_customers: 0,
  scheduled_today: 0,
  pending_acknowledgement: 0,
  in_progress_bookings: 0,
  completed_today: 0,
  bookings_by_status: {},
  total_scheduled_bookings: 0,
  overdue_reminders: 0,
  follow_ups_due_today: 0,
  upcoming_corporate_bookings: 0,
  total_future_bookings: 0,
  vip_bookings: 0,
  strategic_meetings: 0,
  driver_schedules: 0,
  follow_up_completion_rate: 0,
  customer_growth_trend: [],
};

const emptyCustomerSummary: CustomerSummary = {
  total_customers: 0,
  new_customers_this_week: 0,
  new_customers_this_month: 0,
  total_business_leads: 0,
  total_strategic_contacts: 0,
  total_investors: 0,
  total_gatekeepers: 0,
  follow_ups_due_today: 0,
  follow_ups_overdue: 0,
  high_priority_follow_ups_due: 0,
  lead_conversion_rate: 0,
  customers_by_creator: [],
  customers_by_driver: [],
  customers_by_source: [],
  top_customer_generators: [],
  follow_up_due_customers: [],
  customer_growth_trend: [],
  available_filters: {
    creator_roles: [],
    drivers: [],
    customer_categories: [],
    sources: [],
  },
  applied_filters: {},
};

function normalizeCustomerSummary(value: unknown): CustomerSummary {
  const normalized = ensureObject<CustomerSummary>(value, emptyCustomerSummary);
  const availableFilters = ensureObject<NonNullable<CustomerSummary['available_filters']>>(
    normalized.available_filters,
    emptyCustomerSummary.available_filters!,
  );
  const appliedFilters = ensureObject<NonNullable<CustomerSummary['applied_filters']>>(
    normalized.applied_filters,
    emptyCustomerSummary.applied_filters!,
  );

  return {
    ...normalized,
    customers_by_creator: ensureArray<CustomerSummary['customers_by_creator'][number]>(normalized.customers_by_creator),
    customers_by_driver: ensureArray<CustomerSummary['customers_by_driver'][number]>(normalized.customers_by_driver),
    customers_by_source: ensureArray<CustomerSummary['customers_by_source'][number]>(normalized.customers_by_source),
    top_customer_generators: ensureArray<CustomerSummary['top_customer_generators'][number]>(normalized.top_customer_generators),
    follow_up_due_customers: ensureArray<CustomerSummary['follow_up_due_customers'][number]>(normalized.follow_up_due_customers),
    customer_growth_trend: ensureArray<{ label: string; value: number }>(normalized.customer_growth_trend),
    available_filters: {
      creator_roles: ensureArray<string>(availableFilters.creator_roles),
      drivers: ensureArray<UserSummary>(availableFilters.drivers),
      customer_categories: ensureArray<{ id: string; name: string }>(availableFilters.customer_categories),
      sources: ensureArray<{ value: string; label: string }>(availableFilters.sources),
    },
    applied_filters: {
      date_from: appliedFilters.date_from ?? null,
      date_to: appliedFilters.date_to ?? null,
      creator_role: appliedFilters.creator_role ?? null,
      driver_id: appliedFilters.driver_id ?? null,
      customer_category_id: appliedFilters.customer_category_id ?? null,
      source: appliedFilters.source ?? null,
    },
  };
}

export async function fetchCustomers() {
  const response = await apiRequest<{ data: { customers: CustomerRecord[] } }>('/customers');
  return ensureArray<CustomerRecord>(response?.data?.customers);
}

export async function createCustomer(payload: Record<string, unknown>) {
  const response = await apiRequest<{ data: { customer: CustomerRecord } }>('/customers', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return response.data.customer;
}

export async function updateCustomer(customerId: string, payload: Record<string, unknown>) {
  const response = await apiRequest<{ data: { customer: CustomerRecord } }>(`/customers/${customerId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
  return response.data.customer;
}

export async function fetchCustomerOptions() {
  const response = await apiRequest<{ data: CustomerOptionsResponse }>('/customers/options');
  return normalizeCustomerOptions(response?.data);
}

function toQueryString(filters: Record<string, string | undefined | null>) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value) {
      params.set(key, value);
    }
  });
  const query = params.toString();
  return query ? `?${query}` : '';
}

export async function fetchCustomerSummary(filters: {
  date_from?: string;
  date_to?: string;
  creator_role?: string;
  driver_id?: string;
  customer_category_id?: string;
  source?: string;
} = {}) {
  const response = await apiRequest<{ data: { summary: CustomerSummary } }>(`/customers/summary${toQueryString(filters)}`);
  return normalizeCustomerSummary(response?.data?.summary);
}

export async function fetchBookings() {
  const response = await apiRequest<{ data: { bookings: BookingRecord[] } }>('/bookings');
  return ensureArray<BookingRecord>(response?.data?.bookings);
}

export async function createBooking(payload: Record<string, unknown>) {
  const response = await apiRequest<{ data: { booking: BookingRecord } }>('/bookings', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return response.data.booking;
}

export async function updateBooking(bookingId: string, payload: Record<string, unknown>) {
  const response = await apiRequest<{ data: { booking: BookingRecord } }>(`/bookings/${bookingId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
  return response.data.booking;
}

async function patchBookingAction(bookingId: string, action: string, payload?: Record<string, unknown>) {
  const response = await apiRequest<{ data: { booking: BookingRecord } }>(`/bookings/${bookingId}/${action}`, {
    method: 'PATCH',
    body: JSON.stringify(payload || {}),
  });
  return response.data.booking;
}

export async function acknowledgeBooking(bookingId: string) {
  return patchBookingAction(bookingId, 'acknowledge');
}

export async function startBookingPickup(bookingId: string) {
  return patchBookingAction(bookingId, 'start-pickup');
}

export async function markBookingPickedUp(bookingId: string) {
  return patchBookingAction(bookingId, 'picked-up');
}

export async function completeBookingAction(
  bookingId: string,
  payload: { completion_note?: string; create_trip_log?: boolean },
) {
  return patchBookingAction(bookingId, 'complete', payload);
}

export async function reportBookingIssue(
  bookingId: string,
  payload: { issue_type: string; issue_note?: string },
) {
  return patchBookingAction(bookingId, 'report-issue', payload);
}

export async function fetchBookingOptions() {
  const response = await apiRequest<{ data: BookingOptionsResponse }>('/bookings/options');
  return normalizeBookingOptions(response?.data);
}

export async function fetchCalendar(view: 'today' | 'tomorrow' | 'this-week' | 'upcoming' | 'overdue' | 'completed') {
  const response = await apiRequest<{ data: { view: string; entries: CalendarEntry[] } }>(`/calendar?view=${view}`);
  return ensureArray<CalendarEntry>(response?.data?.entries);
}

export async function fetchBookingSummary() {
  const response = await apiRequest<{ data: { summary: BookingSummary } }>('/bookings/summary');
  return ensureObject<BookingSummary>(response?.data?.summary, emptyBookingSummary);
}
