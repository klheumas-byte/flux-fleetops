import { Component, useEffect, useMemo, useRef, useState, type ErrorInfo, type ReactNode } from 'react';
import {
  Briefcase,
  Calendar,
  Clock,
  Loader2,
  MapPin,
  Pencil,
  Phone,
  Plus,
  Save,
  Star,
  UserPlus,
  Users,
} from 'lucide-react';
import {
  ApiRequestError,
} from '../../lib/api';
import {
  createBooking,
  createCustomer,
  createCustomerContact,
  createCustomerNote,
  createCustomerOpportunity,
  fetchBookingOptions,
  fetchBookings,
  fetchCustomerById,
  fetchCustomerContacts,
  fetchCustomerNotes,
  fetchCustomerOptions,
  fetchCustomerOpportunities,
  fetchCustomers,
  type BookingOptionsResponse,
  type BookingRecord,
  type CustomerContactRecord,
  type CustomerNoteRecord,
  type BookingSummary,
  type CustomerOpportunityRecord,
  type CustomerOptionsResponse,
  type CustomerRecord,
  type CustomerSummary,
  type CustomerTimelineEntry,
  updateCustomerContact,
  updateCustomerOpportunity,
  updateCustomerRelationship,
  updateBooking,
  updateCustomer,
} from '../../lib/customer-booking-api';
import { clearDriverQuickActionIntent, peekDriverQuickActionIntent } from '../../lib/driver-quick-actions';
import { useDebouncedValue } from '../../lib/use-debounced-value';
import { usePageToastFeedback } from '../../lib/use-page-toast-feedback';
import { SearchableSelect, type SearchableSelectOption } from '../ui/searchable-select';

interface CustomerWorkspaceProps {
  portal: 'admin' | 'owner' | 'driver';
}

interface CustomerWorkspaceBoundaryState {
  hasError: boolean;
}

class CustomerWorkspaceErrorBoundary extends Component<{ children: ReactNode }, CustomerWorkspaceBoundaryState> {
  state: CustomerWorkspaceBoundaryState = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Customer workspace crashed', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="rounded-2xl border border-amber-200 bg-amber-50 px-6 py-10 text-center text-sm text-amber-900">
          Customer details are temporarily unavailable. The customer list is still available, and you can reload to try again.
        </div>
      );
    }

    return this.props.children;
  }
}

function buildMasterDataSelectOptions(
  items: Array<{ id: string; name: string; description?: string | null }> | undefined,
  currentValue?: string | null,
): SearchableSelectOption[] {
  const options = (items || []).map((item) => ({
    value: item.id,
    label: item.name,
    description: item.description || null,
  }));
  if (currentValue && !options.some((option) => option.label === currentValue || option.value === currentValue)) {
    options.push({
      value: currentValue,
      label: currentValue,
      description: 'Legacy value',
    });
  }
  return options;
}

function buildStringValueOptions(
  items: Array<{ id?: string; name?: string; value?: string; label?: string; description?: string | null }> | undefined,
  currentValue?: string | null,
): SearchableSelectOption[] {
  const options = (items || []).map((item) => ({
    value: item.value || item.name || '',
    label: item.label || item.name || '',
    description: item.description || null,
  })).filter((item) => item.value && item.label);
  if (currentValue && !options.some((option) => option.value === currentValue || option.label === currentValue)) {
    options.push({
      value: currentValue,
      label: currentValue,
      description: 'Legacy value',
    });
  }
  return options;
}

function buildFallbackStringOptions(values: string[], currentValue?: string | null): SearchableSelectOption[] {
  return buildStringValueOptions(
    values.map((value) => ({ value, label: value })),
    currentValue,
  );
}

function firstOptionValue(options: SearchableSelectOption[]): string {
  return options[0]?.value || '';
}

function preferredOptionValue(options: SearchableSelectOption[], preferredLabel: string): string {
  return options.find((option) => option.label === preferredLabel)?.value || firstOptionValue(options);
}

function formatOptionalCount(value?: number | null) {
  return typeof value === 'number' ? String(value) : '-';
}

const occupationEmptyLabel = 'No occupations found. Add occupations in Master Data.';
const positionTitleEmptyLabel = 'No position titles found. Add position titles in Master Data.';
const opportunityTypeEmptyLabel = 'No opportunity types found. Add potential services in Master Data.';
const fallbackOccupationValues = [
  'Driver',
  'Teacher',
  'Student',
  'Accountant',
  'Engineer',
  'Pastor',
  'Business Owner',
  'Entrepreneur',
  'Consultant',
  'Administrator',
  'Customer Service Professional',
  'Operations Professional',
  'Finance Professional',
  'Procurement Professional',
];
const fallbackPositionTitleValues = [
  'CEO',
  'Managing Director',
  'Operations Manager',
  'Finance Officer',
  'Procurement Officer',
  'Customer Service Officer',
  'Client Experience Officer',
  'Account Manager',
  'Branch Supervisor',
  'Team Lead',
  'Executive Assistant',
  'Project Coordinator',
  'Head Teacher',
  'Class Representative',
];

const weekdayOptions = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const defaultBookingStatuses = ['Scheduled', 'Acknowledged', 'Confirmed', 'En Route', 'Picked Up', 'In Progress', 'Completed', 'Cancelled', 'Missed'];
const defaultBookingPriorities = ['Low', 'Medium', 'High', 'Critical'];
const defaultBookingTypes = ['Customer Booking', 'Personal Reminder', 'Follow-Up Reminder'];
const defaultRecurrenceTypes = ['Daily', 'Weekly', 'Monthly', 'Custom'];

function isoDateFromValue(value?: string | null) {
  if (!value) {
    return null;
  }
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return value;
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }
  return parsed.toISOString().slice(0, 10);
}

function startOfDay(value: Date) {
  const next = new Date(value);
  next.setHours(0, 0, 0, 0);
  return next;
}

function normalizeText(value?: string | null) {
  return String(value || '').trim().toLowerCase();
}

function sortCountEntries<T extends { count: number }>(entries: T[]) {
  return [...entries].sort((left, right) => right.count - left.count || JSON.stringify(left).localeCompare(JSON.stringify(right)));
}

function buildLocalBookingSummary(customers: CustomerRecord[], bookings: BookingRecord[]): BookingSummary {
  const now = new Date();
  const today = now.toISOString().slice(0, 10);
  const activeStatuses = new Set(['Scheduled', 'Acknowledged', 'Confirmed', 'En Route', 'Picked Up', 'In Progress']);
  const inProgressStatuses = new Set(['Acknowledged', 'Confirmed', 'En Route', 'Picked Up', 'In Progress']);
  const completedStatuses = new Set(['Completed']);
  const skippedStatuses = new Set(['Completed', 'Cancelled', 'Missed']);
  const bookingsByStatus: Record<string, number> = {};
  const recurringCustomers = new Set<string>();
  const driverSchedules = new Set<string>();
  const recentCustomers = customers.filter((customer) => {
    const createdAt = customer.created_at ? new Date(customer.created_at) : null;
    return createdAt && !Number.isNaN(createdAt.getTime()) && createdAt >= new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
  }).length;
  const growthMap = new Map<string, number>();

  for (let offset = 6; offset >= 0; offset -= 1) {
    const day = new Date(now);
    day.setDate(now.getDate() - offset);
    growthMap.set(day.toISOString().slice(0, 10), 0);
  }

  customers.forEach((customer) => {
    const createdDay = isoDateFromValue(customer.created_at);
    if (createdDay && growthMap.has(createdDay)) {
      growthMap.set(createdDay, (growthMap.get(createdDay) || 0) + 1);
    }
  });

  let upcomingBookings = 0;
  let missedBookings = 0;
  let todaySchedule = 0;
  let upcomingPickups = 0;
  let totalScheduledBookings = 0;
  let pendingAcknowledgement = 0;
  let inProgressBookings = 0;
  let completedToday = 0;
  let overdueReminders = 0;
  let followUpsDueToday = 0;
  let upcomingCorporateBookings = 0;
  let totalFutureBookings = 0;
  let vipBookings = 0;
  let strategicMeetings = 0;
  let followUpTotal = 0;
  let followUpCompleted = 0;

  bookings.forEach((booking) => {
    const status = booking.status || 'Unknown';
    bookingsByStatus[status] = (bookingsByStatus[status] || 0) + 1;

    if (booking.is_recurring_template && booking.customer_id) {
      recurringCustomers.add(booking.customer_id);
    }

    const pickupAt = booking.pickup_at ? new Date(booking.pickup_at) : null;
    const pickupDay = isoDateFromValue(booking.pickup_at || booking.pickup_date || booking.reminder_date);
    const bookingType = normalizeText(booking.booking_type);
    const isFollowUp = bookingType.includes('follow-up');
    const isReminder = bookingType.includes('reminder');
    const isCorporate = bookingType.includes('corporate') || bookingType.includes('company');
    const isVip = bookingType.includes('vip');
    const isStrategic = bookingType.includes('strategic');

    if (!booking.is_recurring_template && activeStatuses.has(status)) {
      upcomingBookings += 1;
      totalScheduledBookings += 1;
    }
    if (status === 'Missed') {
      missedBookings += 1;
    }
    if (pickupDay === today && !booking.is_recurring_template && activeStatuses.has(status)) {
      todaySchedule += 1;
    }
    if (!booking.is_recurring_template && pickupAt && !Number.isNaN(pickupAt.getTime()) && pickupAt >= now) {
      upcomingPickups += 1;
      totalFutureBookings += 1;
      if (booking.driver_id) {
        driverSchedules.add(booking.driver_id);
      }
      if (isCorporate) {
        upcomingCorporateBookings += 1;
      }
      if (isVip) {
        vipBookings += 1;
      }
      if (isStrategic) {
        strategicMeetings += 1;
      }
    }
    if (status === 'Scheduled') {
      pendingAcknowledgement += 1;
    }
    if (inProgressStatuses.has(status)) {
      inProgressBookings += 1;
    }
    if (completedStatuses.has(status) && isoDateFromValue(booking.completed_at || booking.pickup_at) === today) {
      completedToday += 1;
    }
    if ((isReminder || isFollowUp) && pickupAt && !Number.isNaN(pickupAt.getTime()) && pickupAt < now && !skippedStatuses.has(status)) {
      overdueReminders += 1;
    }
    if (isFollowUp) {
      followUpTotal += 1;
      if (pickupDay === today && !skippedStatuses.has(status)) {
        followUpsDueToday += 1;
      }
      if (completedStatuses.has(status)) {
        followUpCompleted += 1;
      }
    }
  });

  return {
    upcoming_bookings: upcomingBookings,
    missed_bookings: missedBookings,
    active_recurring_customers: recurringCustomers.size,
    total_customers: customers.length,
    total_recurring_customers: recurringCustomers.size,
    today_schedule: todaySchedule,
    upcoming_pickups: upcomingPickups,
    recent_customers: recentCustomers,
    scheduled_today: todaySchedule,
    total_scheduled_bookings: totalScheduledBookings,
    pending_acknowledgement: pendingAcknowledgement,
    in_progress_bookings: inProgressBookings,
    completed_today: completedToday,
    overdue_reminders: overdueReminders,
    follow_ups_due_today: followUpsDueToday,
    upcoming_corporate_bookings: upcomingCorporateBookings,
    total_future_bookings: totalFutureBookings,
    vip_bookings: vipBookings,
    strategic_meetings: strategicMeetings,
    driver_schedules: driverSchedules.size,
    follow_up_completion_rate: followUpTotal ? Math.round((followUpCompleted / followUpTotal) * 100) : 0,
    bookings_by_status: bookingsByStatus,
    customer_growth_trend: Array.from(growthMap.entries()).map(([day, value]) => ({
      label: new Date(`${day}T00:00:00`).toLocaleDateString(undefined, { weekday: 'short' }),
      value,
    })),
  };
}

function buildLocalCustomerSummary(
  allCustomers: CustomerRecord[],
  scopedCustomers: CustomerRecord[],
  customerOptions: CustomerOptionsResponse | null,
): CustomerSummary {
  const today = new Date();
  const todayIso = today.toISOString().slice(0, 10);
  const weekStart = startOfDay(new Date(today.getFullYear(), today.getMonth(), today.getDate() - 6));
  const monthStart = startOfDay(new Date(today.getFullYear(), today.getMonth(), 1));
  const creatorCounts = new Map<string, CustomerSummary['customers_by_creator'][number]>();
  const sourceCounts = new Map<string, CustomerSummary['customers_by_source'][number]>();
  const driverCounts = new Map<string, CustomerSummary['customers_by_driver'][number]>();
  const growthMap = new Map<string, number>();

  for (let offset = 6; offset >= 0; offset -= 1) {
    const day = new Date(today);
    day.setDate(today.getDate() - offset);
    growthMap.set(day.toISOString().slice(0, 10), 0);
  }

  let newCustomersThisWeek = 0;
  let newCustomersThisMonth = 0;
  let totalBusinessLeads = 0;
  let totalStrategicContacts = 0;
  let totalInvestors = 0;
  let totalGatekeepers = 0;
  let followUpsDueToday = 0;
  let followUpsOverdue = 0;
  let highPriorityFollowUpsDue = 0;
  let convertedLeads = 0;

  scopedCustomers.forEach((customer) => {
    const createdAt = customer.created_at ? new Date(customer.created_at) : null;
    if (createdAt && !Number.isNaN(createdAt.getTime())) {
      if (createdAt >= weekStart) {
        newCustomersThisWeek += 1;
      }
      if (createdAt >= monthStart) {
        newCustomersThisMonth += 1;
      }
      const growthKey = createdAt.toISOString().slice(0, 10);
      if (growthMap.has(growthKey)) {
        growthMap.set(growthKey, (growthMap.get(growthKey) || 0) + 1);
      }
    }

    if (customer.is_business_lead) {
      totalBusinessLeads += 1;
    }
    if (normalizeText(customer.opportunity_level) === 'strategic') {
      totalStrategicContacts += 1;
    }
    if (normalizeText(customer.relationship_category) === 'investor') {
      totalInvestors += 1;
    }
    if (
      normalizeText(customer.relationship_category) === 'gatekeeper' ||
      normalizeText(customer.network_value) === 'industry gatekeeper'
    ) {
      totalGatekeepers += 1;
    }

    const followUpDate = customer.next_follow_up_date || customer.follow_up_date || null;
    if (followUpDate) {
      if (followUpDate === todayIso) {
        followUpsDueToday += 1;
      }
      if (followUpDate < todayIso) {
        followUpsOverdue += 1;
      }
      if (normalizeText(customer.follow_up_priority) === 'high' && followUpDate <= todayIso) {
        highPriorityFollowUpsDue += 1;
      }
    }

    if (normalizeText(customer.lead_status) === 'converted') {
      convertedLeads += 1;
    }

    const creatorName = customer.created_by_name || 'Unknown';
    const creatorRole = customer.created_by_role || 'legacy';
    const creatorKey = `${creatorRole}:${creatorName}`;
    creatorCounts.set(creatorKey, {
      creator_name: creatorName,
      creator_role: creatorRole,
      creator_user_id: customer.created_by_user_id || null,
      count: (creatorCounts.get(creatorKey)?.count || 0) + 1,
    });

    const sourceValue = customer.source || 'unknown';
    const sourceLabel = customer.source_label || customer.customer_source || sourceValue;
    sourceCounts.set(sourceValue, {
      source: sourceValue,
      label: sourceLabel,
      count: (sourceCounts.get(sourceValue)?.count || 0) + 1,
    });

    const driverId = customer.preferred_driver_id || customer.assigned_driver_id || customer.created_by_driver_id || '';
    const driverName =
      customer.preferred_driver?.full_name ||
      customer.assigned_driver?.full_name ||
      (normalizeText(customer.created_by_role) === 'driver' ? customer.created_by_name || 'Driver' : 'Unassigned');
    const driverKey = driverId || driverName;
    driverCounts.set(driverKey, {
      driver_id: driverId || null,
      driver_name: driverName,
      count: (driverCounts.get(driverKey)?.count || 0) + 1,
    });
  });

  const creatorRoles = Array.from(new Set(allCustomers.map((customer) => customer.created_by_role).filter(Boolean) as string[])).sort();
  const drivers = Array.from(
    new Map(
      allCustomers
        .flatMap((customer) => {
          const entries = [];
          if (customer.preferred_driver) {
            entries.push([customer.preferred_driver.id, customer.preferred_driver] as const);
          }
          if (customer.assigned_driver) {
            entries.push([customer.assigned_driver.id, customer.assigned_driver] as const);
          }
          if (normalizeText(customer.created_by_role) === 'driver' && customer.created_by_user) {
            entries.push([customer.created_by_user.id, customer.created_by_user] as const);
          }
          return entries;
        }),
    ).values(),
  );
  const customerCategories = Array.from(
    new Map(
      allCustomers
        .filter((customer) => customer.customer_category_id && customer.customer_category)
        .map((customer) => [customer.customer_category_id!, { id: customer.customer_category_id!, name: customer.customer_category }]),
    ).values(),
  ).sort((left, right) => left.name.localeCompare(right.name));
  const sources = Array.from(
    new Map(
      allCustomers
        .filter((customer) => customer.source)
        .map((customer) => [customer.source!, { value: customer.source!, label: customer.source_label || customer.customer_source || customer.source! }]),
    ).values(),
  ).sort((left, right) => left.label.localeCompare(right.label));

  return {
    total_customers: scopedCustomers.length,
    new_customers_this_week: newCustomersThisWeek,
    new_customers_this_month: newCustomersThisMonth,
    total_business_leads: totalBusinessLeads,
    total_strategic_contacts: totalStrategicContacts,
    total_investors: totalInvestors,
    total_gatekeepers: totalGatekeepers,
    follow_ups_due_today: followUpsDueToday,
    follow_ups_overdue: followUpsOverdue,
    high_priority_follow_ups_due: highPriorityFollowUpsDue,
    lead_conversion_rate: totalBusinessLeads ? Math.round((convertedLeads / totalBusinessLeads) * 100) : 0,
    customers_by_creator: sortCountEntries(Array.from(creatorCounts.values())),
    customers_by_driver: sortCountEntries(Array.from(driverCounts.values())),
    customers_by_source: sortCountEntries(Array.from(sourceCounts.values())),
    top_customer_generators: sortCountEntries(Array.from(creatorCounts.values())).slice(0, 5),
    follow_up_due_customers: scopedCustomers
      .filter((customer) => {
        const followUpDate = customer.next_follow_up_date || customer.follow_up_date || null;
        return Boolean(followUpDate && followUpDate <= todayIso);
      })
      .slice(0, 10)
      .map((customer) => ({
        id: customer.id,
        full_name: customer.full_name,
        phone_number: customer.phone_number,
        follow_up_date: customer.next_follow_up_date || customer.follow_up_date || null,
        follow_up_priority: customer.follow_up_priority || null,
        follow_up_status_label: customer.follow_up_status_label || null,
        lead_status: customer.lead_status || null,
        relationship_category: customer.relationship_category || null,
      })),
    customer_growth_trend: Array.from(growthMap.entries()).map(([day, value]) => ({
      label: new Date(`${day}T00:00:00`).toLocaleDateString(undefined, { weekday: 'short' }),
      value,
    })),
    available_filters: {
      creator_roles: creatorRoles.length ? creatorRoles : customerOptions?.creator_roles || [],
      drivers: drivers.length ? drivers : customerOptions?.drivers || [],
      customer_categories: customerCategories.length ? customerCategories : [],
      sources: sources.length ? sources : customerOptions?.source_options || [],
    },
    applied_filters: {},
  };
}

function formatDateTime(value?: string | null) {
  if (!value) return 'Not available';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

function formatDate(value?: string | null) {
  if (!value) return 'Not available';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleDateString();
}

function formatCurrency(value?: number | null) {
  return `GHS ${(value || 0).toLocaleString()}`;
}

interface CustomerFormState {
  full_name: string;
  phone_number: string;
  alternate_phone: string;
  email_address: string;
  date_of_birth: string;
  occupation: string;
  organization_name: string;
  position_title: string;
  pickup_location: string;
  destination_location: string;
  preferred_pickup_location: string;
  preferred_dropoff_location: string;
  residential_area: string;
  work_area: string;
  source: string;
  customer_category_id: string;
  customer_source_id: string;
  organization_type_id: string;
  industry_id: string;
  relationship_category_id: string;
  opportunity_level_id: string;
  network_value_id: string;
  is_transport_customer: boolean;
  is_business_lead: boolean;
  lead_status_id: string;
  potential_service_id: string;
  lead_value_estimate: string;
  follow_up_date: string;
  next_follow_up_date: string;
  follow_up_priority: string;
  preferred_driver_id: string;
  notes: string;
  relationship_notes: string;
  lead_notes: string;
  important_notes: string;
  referred_by: string;
  company_name: string;
  status: string;
}

interface BookingFormState {
  customer_id: string;
  driver_id: string;
  vehicle_id: string;
  booking_type: string;
  title: string;
  description: string;
  pickup_date: string;
  pickup_time: string;
  reminder_date: string;
  reminder_time: string;
  pickup_location: string;
  destination: string;
  expected_fare: string;
  priority: string;
  notes: string;
  status: string;
  recurrence_type: string;
  recurrence_frequency: string;
  recurrence_days: string[];
  monthly_week_of_month: string;
  monthly_day_of_week: string;
  custom_rule_text: string;
  recurrence_end_date: string;
}

interface RelationshipFormState {
  industry_id: string;
  company_or_institution_name: string;
  branch_or_department: string;
  position_or_role: string;
  relationship_role_id: string;
  relationship_category_id: string;
  lead_status_id: string;
  customer_source_id: string;
  source: string;
  influence_level_id: string;
  government_sector_id: string;
  organization_type_id: string;
  network_value_id: string;
  opportunity_level_id: string;
  potential_service_id: string;
  relationship_notes: string;
}

interface OpportunityFormState {
  id?: string | null;
  opportunity_type_id: string;
  specific_product_or_service: string;
  estimated_budget: string;
  opportunity_stage_id: string;
  probability: string;
  expected_purchase_date: string;
  follow_up_date: string;
  notes: string;
  status: string;
}

interface ContactFormState {
  id?: string | null;
  contact_name: string;
  phone: string;
  email: string;
  position_or_role: string;
  relationship_role_id: string;
  notes: string;
}

type CustomerProfileTab =
  | 'overview'
  | 'relationship'
  | 'opportunities'
  | 'contacts'
  | 'trips'
  | 'notes';

type CustomerFormField = keyof CustomerFormState;

const emptyCustomerForm: CustomerFormState = {
  full_name: '',
  phone_number: '',
  alternate_phone: '',
  email_address: '',
  date_of_birth: '',
  occupation: '',
  organization_name: '',
  position_title: '',
  pickup_location: '',
  destination_location: '',
  preferred_pickup_location: '',
  preferred_dropoff_location: '',
  residential_area: '',
  work_area: '',
  source: '',
  customer_category_id: '',
  customer_source_id: '',
  organization_type_id: '',
  industry_id: '',
  relationship_category_id: '',
  opportunity_level_id: '',
  network_value_id: '',
  is_transport_customer: true,
  is_business_lead: false,
  lead_status_id: '',
  potential_service_id: '',
  lead_value_estimate: '',
  follow_up_date: '',
  next_follow_up_date: '',
  follow_up_priority: 'medium',
  preferred_driver_id: '',
  notes: '',
  relationship_notes: '',
  lead_notes: '',
  important_notes: '',
  referred_by: '',
  company_name: '',
  status: 'active',
};

const emptyBookingForm: BookingFormState = {
  customer_id: '',
  driver_id: '',
  vehicle_id: '',
  booking_type: 'Customer Booking',
  title: '',
  description: '',
  pickup_date: '',
  pickup_time: '',
  reminder_date: '',
  reminder_time: '',
  pickup_location: '',
  destination: '',
  expected_fare: '',
  priority: 'Medium',
  notes: '',
  status: 'Scheduled',
  recurrence_type: '',
  recurrence_frequency: '1',
  recurrence_days: [],
  monthly_week_of_month: '',
  monthly_day_of_week: '',
  custom_rule_text: '',
  recurrence_end_date: '',
};

const emptyRelationshipForm: RelationshipFormState = {
  industry_id: '',
  company_or_institution_name: '',
  branch_or_department: '',
  position_or_role: '',
  relationship_role_id: '',
  relationship_category_id: '',
  lead_status_id: '',
  customer_source_id: '',
  source: '',
  influence_level_id: '',
  government_sector_id: '',
  organization_type_id: '',
  network_value_id: '',
  opportunity_level_id: '',
  potential_service_id: '',
  relationship_notes: '',
};

const emptyOpportunityForm: OpportunityFormState = {
  id: null,
  opportunity_type_id: '',
  specific_product_or_service: '',
  estimated_budget: '',
  opportunity_stage_id: '',
  probability: '',
  expected_purchase_date: '',
  follow_up_date: '',
  notes: '',
  status: 'open',
};

const emptyContactForm: ContactFormState = {
  id: null,
  contact_name: '',
  phone: '',
  email: '',
  position_or_role: '',
  relationship_role_id: '',
  notes: '',
};

const reminderBookingTypes = new Set([
  'Follow-Up Reminder',
  'Personal Reminder',
  'Maintenance Reminder',
  'Insurance Renewal Reminder',
  'Vehicle Inspection Reminder',
]);

const followUpBookingTypes = new Set(['Follow-Up Reminder']);

const customerFieldNameMap: Record<string, CustomerFormField> = {
  full_name: 'full_name',
  phone_number: 'phone_number',
  alternate_phone: 'alternate_phone',
  email_address: 'email_address',
  date_of_birth: 'date_of_birth',
  occupation: 'occupation',
  organization_name: 'organization_name',
  position_title: 'position_title',
  pickup_location: 'pickup_location',
  destination_location: 'destination_location',
  preferred_pickup_location: 'preferred_pickup_location',
  preferred_dropoff_location: 'preferred_dropoff_location',
  residential_area: 'residential_area',
  work_area: 'work_area',
  source: 'source',
  customer_category: 'customer_category_id',
  customer_source: 'customer_source_id',
  organization_type: 'organization_type_id',
  industry: 'industry_id',
  relationship_category: 'relationship_category_id',
  opportunity_level: 'opportunity_level_id',
  network_value: 'network_value_id',
  lead_status: 'lead_status_id',
  potential_service: 'potential_service_id',
  lead_value_estimate: 'lead_value_estimate',
  follow_up_date: 'follow_up_date',
  next_follow_up_date: 'next_follow_up_date',
  follow_up_priority: 'follow_up_priority',
  preferred_driver_id: 'preferred_driver_id',
  notes: 'notes',
  relationship_notes: 'relationship_notes',
  lead_notes: 'lead_notes',
  important_notes: 'important_notes',
  referred_by: 'referred_by',
  company_name: 'company_name',
  status: 'status',
};

const customerFieldLabelMap: Partial<Record<CustomerFormField, string>> = {
  full_name: 'Full name is required.',
  phone_number: 'Please enter a valid phone number.',
  alternate_phone: 'Please enter a valid phone number.',
  email_address: 'Please enter a valid email address.',
  residential_area: 'Please enter a location or area.',
  customer_category_id: 'Please select a customer category.',
  customer_source_id: 'Please select a customer source.',
  organization_type_id: 'Please select an organization type.',
  industry_id: 'Please select an industry.',
  relationship_category_id: 'Please select a relationship category.',
  opportunity_level_id: 'Please select an opportunity level.',
  network_value_id: 'Please select a network value.',
  lead_status_id: 'Please select a lead status.',
  potential_service_id: 'Please select a potential service.',
  preferred_driver_id: 'Please select a driver.',
  follow_up_priority: 'Please select a follow-up priority.',
  status: 'Please select a status.',
  source: 'Please select a customer source.',
};

function isReminderBookingType(bookingType: string) {
  return reminderBookingTypes.has(bookingType);
}

function isCompletedBookingStatus(status?: string | null) {
  return (status || '').trim().toLowerCase() === 'completed';
}

function BookingStatusBadge({ status }: { status: string }) {
  const colorMap: Record<string, string> = {
    Scheduled: 'bg-blue-100 text-blue-700',
    Acknowledged: 'bg-cyan-100 text-cyan-700',
    Confirmed: 'bg-cyan-100 text-cyan-700',
    'En Route': 'bg-amber-100 text-amber-700',
    'In Progress': 'bg-amber-100 text-amber-700',
    'Picked Up': 'bg-emerald-100 text-emerald-700',
    Completed: 'bg-slate-100 text-slate-700',
    Cancelled: 'bg-rose-100 text-rose-700',
    Missed: 'bg-red-100 text-red-700',
  };

  return (
    <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${colorMap[status] || 'bg-gray-100 text-gray-700'}`}>
      {status}
    </span>
  );
}

function Modal({
  title,
  subtitle,
  children,
  onClose,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-2 sm:p-4">
      <div className="flex max-h-[90vh] w-[95%] max-w-[600px] flex-col overflow-hidden rounded-2xl bg-white shadow-2xl md:max-w-4xl">
        <div className="sticky top-0 z-10 flex items-start justify-between border-b border-gray-200 bg-white px-4 py-4 sm:px-6">
          <div>
            <h2 className="text-xl font-semibold text-[#0F172A]">{title}</h2>
            <p className="mt-1 text-sm text-gray-500">{subtitle}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg px-3 py-2 text-sm font-medium text-gray-500 hover:bg-gray-100"
          >
            Close
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-6">{children}</div>
      </div>
    </div>
  );
}

function getErrorMessage(error: unknown, fallback: string) {
  if (error instanceof ApiRequestError) {
    return error.message;
  }
  return fallback;
}

function getCustomerFieldClass(hasError: boolean, options: { multiline?: boolean } = {}) {
  const { multiline = false } = options;
  const base = multiline
    ? 'w-full rounded-xl border px-4 py-3 text-sm focus:outline-none focus:ring-2'
    : 'w-full rounded-xl border px-4 py-2.5 text-sm focus:outline-none focus:ring-2';

  return hasError
    ? `${base} border-red-300 bg-red-50 focus:border-red-500 focus:ring-red-100`
    : `${base} border-gray-300 focus:border-[#2563EB] focus:ring-blue-100`;
}

function normalizeCustomerFormError(error: ApiRequestError) {
  const fieldErrors: Partial<Record<CustomerFormField, string>> = {};
  const duplicateError = error.errors.find((item) => item?.code === 'duplicate_customer');

  if (duplicateError) {
    const matches = Array.isArray(duplicateError.matches) ? duplicateError.matches : [];
    if (matches.includes('phone_number')) {
      fieldErrors.phone_number = 'Customer already exists with this phone number.';
    }
    if (matches.includes('email_address')) {
      fieldErrors.email_address = 'Customer already exists with this email address.';
    }
    return {
      formError: 'Customer already exists. View existing customer or update existing record.',
      fieldErrors,
      duplicateCustomer: (duplicateError.existing_customer as CustomerRecord | undefined) || null,
    };
  }

  const lowerMessage = error.message.toLowerCase();
  if (lowerMessage.includes('valid phone_number') || lowerMessage.includes('valid phone number')) {
    fieldErrors.phone_number = 'Please enter a valid phone number.';
  }
  if (lowerMessage.includes('alternate_phone')) {
    fieldErrors.alternate_phone = 'Please enter a valid phone number.';
  }
  if (lowerMessage.includes('valid email')) {
    fieldErrors.email_address = 'Please enter a valid email address.';
  }

  const requiredMatch = error.message.match(/^([a-z_]+) is required\./i);
  if (requiredMatch) {
    const mappedField = customerFieldNameMap[requiredMatch[1].toLowerCase()];
    if (mappedField) {
      fieldErrors[mappedField] = customerFieldLabelMap[mappedField] || 'This field is required.';
    }
  }

  const invalidMatch = error.message.match(/^Invalid ([a-z_]+)\./i);
  if (invalidMatch) {
    const mappedField = customerFieldNameMap[invalidMatch[1].toLowerCase()];
    if (mappedField) {
      fieldErrors[mappedField] = customerFieldLabelMap[mappedField] || 'Please correct this field.';
    }
  }

  const formError =
    error.status >= 500
      ? 'We could not save this customer because of a database or server issue. Please try again.'
      : lowerMessage.includes('valid phone_number') || lowerMessage.includes('valid phone number')
        ? 'Please enter a valid phone number.'
        : lowerMessage.includes('valid email')
          ? 'Please enter a valid email address.'
          : error.message || 'Unable to save that customer right now.';

  return {
    formError,
    fieldErrors,
    duplicateCustomer: null,
  };
}

function CustomerWorkspaceContent({ portal }: CustomerWorkspaceProps) {
  const [customers, setCustomers] = useState<CustomerRecord[]>([]);
  const [bookings, setBookings] = useState<BookingRecord[]>([]);
  const [customerOptions, setCustomerOptions] = useState<CustomerOptionsResponse | null>(null);
  const [isLoadingCustomerOptions, setIsLoadingCustomerOptions] = useState(false);
  const [bookingOptions, setBookingOptions] = useState<BookingOptionsResponse | null>(null);
  const [selectedCustomerId, setSelectedCustomerId] = useState<string | null>(null);
  const [selectedCustomerProfile, setSelectedCustomerProfile] = useState<CustomerRecord | null>(null);
  const [isLoadingCustomerProfile, setIsLoadingCustomerProfile] = useState(false);
  const [activeProfileTab, setActiveProfileTab] = useState<CustomerProfileTab>('overview');
  const [relationshipForm, setRelationshipForm] = useState<RelationshipFormState>(emptyRelationshipForm);
  const [isSavingRelationship, setIsSavingRelationship] = useState(false);
  const [opportunities, setOpportunities] = useState<CustomerOpportunityRecord[]>([]);
  const [isLoadingOpportunities, setIsLoadingOpportunities] = useState(false);
  const [showOpportunityForm, setShowOpportunityForm] = useState(false);
  const [opportunityForm, setOpportunityForm] = useState<OpportunityFormState>(emptyOpportunityForm);
  const [isSavingOpportunity, setIsSavingOpportunity] = useState(false);
  const [contacts, setContacts] = useState<CustomerContactRecord[]>([]);
  const [isLoadingContacts, setIsLoadingContacts] = useState(false);
  const [showContactForm, setShowContactForm] = useState(false);
  const [contactForm, setContactForm] = useState<ContactFormState>(emptyContactForm);
  const [isSavingContact, setIsSavingContact] = useState(false);
  const [customerNotes, setCustomerNotes] = useState<CustomerNoteRecord[]>([]);
  const [customerTimeline, setCustomerTimeline] = useState<CustomerTimelineEntry[]>([]);
  const [isLoadingNotes, setIsLoadingNotes] = useState(false);
  const [newNote, setNewNote] = useState('');
  const [isSavingNote, setIsSavingNote] = useState(false);
  const [recentlyCreatedCustomerId, setRecentlyCreatedCustomerId] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const debouncedSearch = useDebouncedValue(search, 250);
  const [isLoading, setIsLoading] = useState(true);
  const [isBookingDataLoading, setIsBookingDataLoading] = useState(true);
  const [pageError, setPageError] = useState('');
  const [pageNotice, setPageNotice] = useState('');
  const [loadedOpportunitiesCustomerId, setLoadedOpportunitiesCustomerId] = useState<string | null>(null);
  const [loadedContactsCustomerId, setLoadedContactsCustomerId] = useState<string | null>(null);
  const [opportunitiesLoadError, setOpportunitiesLoadError] = useState('');
  const [contactsLoadError, setContactsLoadError] = useState('');
  const [bookingLoadError, setBookingLoadError] = useState('');
  const [duplicateCustomer, setDuplicateCustomer] = useState<CustomerRecord | null>(null);
  const [customerFormError, setCustomerFormError] = useState('');
  const [customerFieldErrors, setCustomerFieldErrors] = useState<Partial<Record<CustomerFormField, string>>>({});
  const [showCustomerModal, setShowCustomerModal] = useState(false);
  const [showBookingModal, setShowBookingModal] = useState(false);
  const [editingCustomer, setEditingCustomer] = useState<CustomerRecord | null>(null);
  const [customerForm, setCustomerForm] = useState<CustomerFormState>(emptyCustomerForm);
  const [bookingForm, setBookingForm] = useState<BookingFormState>(emptyBookingForm);
  const [isSavingCustomer, setIsSavingCustomer] = useState(false);
  const [isSavingBooking, setIsSavingBooking] = useState(false);
  const [bookingQueueFilter, setBookingQueueFilter] = useState('All');
  const [filterDateFrom, setFilterDateFrom] = useState('');
  const [filterDateTo, setFilterDateTo] = useState('');
  const [filterCreatorRole, setFilterCreatorRole] = useState('');
  const [filterDriverId, setFilterDriverId] = useState('');
  const [filterCustomerCategoryId, setFilterCustomerCategoryId] = useState('');
  const [filterSource, setFilterSource] = useState('');
  const customerOptionsRequestRef = useRef<Promise<CustomerOptionsResponse> | null>(null);
  const customerOptionsWithDriversRequestRef = useRef<Promise<CustomerOptionsResponse> | null>(null);
  const bookingOptionsRequestRef = useRef<Promise<BookingOptionsResponse> | null>(null);
  usePageToastFeedback(pageError, pageNotice);
  const canEditProfileIntelligence = portal !== 'driver';
  const canAddCustomerNotes = true;

  const clearCustomerFormErrors = () => {
    setCustomerFormError('');
    setCustomerFieldErrors({});
    setDuplicateCustomer(null);
  };

  const updateCustomerField = <T extends CustomerFormField>(field: T, value: CustomerFormState[T]) => {
    setCustomerForm((current) => ({
      ...current,
      [field]: value,
    }));
    setCustomerFieldErrors((current) => {
      if (!current[field]) {
        return current;
      }
      const next = { ...current };
      delete next[field];
      return next;
    });
    setCustomerFormError((current) => {
      if (!current) {
        return current;
      }
      return Object.keys(customerFieldErrors).length <= 1 && customerFieldErrors[field] ? '' : current;
    });
  };

  const closeCustomerModal = () => {
    clearCustomerFormErrors();
    setShowCustomerModal(false);
  };

  const loadWorkspace = async () => {
    setIsLoading(true);
    setIsBookingDataLoading(true);
    setPageError('');
    setPageNotice('');
    setBookingLoadError('');
    setDuplicateCustomer(null);
    const bookingsPromise = fetchBookings()
      .then((bookingData) => {
        setBookings(bookingData);
        return { ok: true as const, bookingData };
      })
      .catch((error) => {
        setBookings([]);
        const message = getErrorMessage(error, 'Scheduled bookings are temporarily unavailable.');
        setBookingLoadError(message);
        return { ok: false as const, error, message };
      })
      .finally(() => {
        setIsBookingDataLoading(false);
      });

    try {
      const customerData = await fetchCustomers();
      setCustomers(customerData);
      setSelectedCustomerId((current) => {
        if (current && customerData.some((customer) => customer.id === current)) {
          return current;
        }
        return customerData[0]?.id || null;
      });
    } catch (error) {
      setCustomers([]);
      setSelectedCustomerId(null);
      setPageError(getErrorMessage(error, 'Unable to load customer management right now.'));
    } finally {
      setIsLoading(false);
    }

    const bookingsResult = await bookingsPromise;
    if (!bookingsResult.ok) {
      setPageNotice('Scheduled bookings are temporarily unavailable. Customer records are still shown.');
    }
  };

  useEffect(() => {
    void loadWorkspace();
  }, []);

  const selectedCustomer = useMemo(
    () => customers.find((customer) => customer.id === selectedCustomerId) || null,
    [customers, selectedCustomerId],
  );
  const profileCustomer = selectedCustomerProfile && selectedCustomerProfile.id === selectedCustomerId
    ? selectedCustomerProfile
    : null;
  const selectedCustomerUpcomingBookings = Array.isArray(profileCustomer?.upcoming_bookings) ? profileCustomer.upcoming_bookings : [];
  const selectedCustomerCompletedBookings = Array.isArray(profileCustomer?.completed_bookings) ? profileCustomer.completed_bookings : [];
  const selectedCustomerMissedBookings = Array.isArray(profileCustomer?.missed_bookings) ? profileCustomer.missed_bookings : [];
  const selectedCustomerRideHistory = Array.isArray(profileCustomer?.ride_history) ? profileCustomer.ride_history : [];
  const selectedCustomerRecurringSchedule = Array.isArray(profileCustomer?.recurring_schedule) ? profileCustomer.recurring_schedule : [];
  const selectedCustomerFollowUpHistory = Array.isArray(profileCustomer?.follow_up_history) ? profileCustomer.follow_up_history : [];

  useEffect(() => {
    if (!selectedCustomerId) {
      setSelectedCustomerProfile(null);
      setShowOpportunityForm(false);
      setShowContactForm(false);
      setNewNote('');
      return;
    }
    setShowOpportunityForm(false);
    setOpportunityForm(emptyOpportunityForm);
    setShowContactForm(false);
    setContactForm(emptyContactForm);
    setNewNote('');
    setOpportunities([]);
    setContacts([]);
    setLoadedOpportunitiesCustomerId(null);
    setLoadedContactsCustomerId(null);
    setOpportunitiesLoadError('');
    setContactsLoadError('');
    setCustomerNotes([]);
    setCustomerTimeline([]);
    void loadCustomerProfile(selectedCustomerId).catch((error) => {
      setPageError(getErrorMessage(error, 'Unable to load this customer profile right now.'));
    });
  }, [selectedCustomerId]);

  useEffect(() => {
    if (!selectedCustomerId) {
      return;
    }
    if (
      (activeProfileTab === 'relationship' || activeProfileTab === 'opportunities' || activeProfileTab === 'contacts')
      && !customerOptions
      && !isLoadingCustomerOptions
    ) {
      void ensureCustomerOptionsLoaded().catch((error) => {
        setPageError(getErrorMessage(error, 'Unable to load customer setup options right now.'));
      });
    }
    if (activeProfileTab === 'opportunities' && loadedOpportunitiesCustomerId !== selectedCustomerId && !isLoadingOpportunities) {
      void loadCustomerOpportunities(selectedCustomerId).catch((error) => {
        setOpportunitiesLoadError(getErrorMessage(error, 'Unable to load customer opportunities right now.'));
      });
    }
    if (activeProfileTab === 'contacts' && loadedContactsCustomerId !== selectedCustomerId && !isLoadingContacts) {
      void loadCustomerContacts(selectedCustomerId).catch((error) => {
        setContactsLoadError(getErrorMessage(error, 'Unable to load customer contacts right now.'));
      });
    }
    if (activeProfileTab === 'notes' && !customerTimeline.length && !isLoadingNotes) {
      void loadCustomerNotes(selectedCustomerId).catch((error) => {
        setPageError(getErrorMessage(error, 'Unable to load customer notes right now.'));
      });
    }
  }, [activeProfileTab, selectedCustomerId, loadedOpportunitiesCustomerId, loadedContactsCustomerId, customerTimeline.length, isLoadingOpportunities, isLoadingContacts, isLoadingNotes, customerOptions, isLoadingCustomerOptions]);

  useEffect(() => {
    if (!showCustomerModal || !editingCustomer) {
      return;
    }
    if (loadedOpportunitiesCustomerId !== editingCustomer.id && !isLoadingOpportunities) {
      void loadCustomerOpportunities(editingCustomer.id).catch((error) => {
        setOpportunitiesLoadError(getErrorMessage(error, 'Unable to load customer opportunities right now.'));
      });
    }
    if (loadedContactsCustomerId !== editingCustomer.id && !isLoadingContacts) {
      void loadCustomerContacts(editingCustomer.id).catch((error) => {
        setContactsLoadError(getErrorMessage(error, 'Unable to load customer contacts right now.'));
      });
    }
  }, [showCustomerModal, editingCustomer, loadedOpportunitiesCustomerId, loadedContactsCustomerId, isLoadingOpportunities, isLoadingContacts]);

  const ensureCustomerOptionsLoaded = async (includeDrivers = false) => {
    if (customerOptions && (!includeDrivers || (customerOptions.drivers || []).length > 0)) {
      return customerOptions;
    }
    const requestRef = includeDrivers ? customerOptionsWithDriversRequestRef : customerOptionsRequestRef;
    if (!requestRef.current) {
      setIsLoadingCustomerOptions(true);
      requestRef.current = fetchCustomerOptions({ includeDrivers })
        .then((response) => {
          setCustomerOptions((current) => {
            if (!current) {
              return response;
            }
            return {
              ...current,
              ...response,
              drivers: response.drivers?.length ? response.drivers : current.drivers,
            };
          });
          return response;
        })
        .catch((error) => {
          setPageNotice((current) =>
            current
              ? `${current} Customer setup options are temporarily unavailable.`
              : 'Customer setup options are temporarily unavailable.',
          );
          throw error;
        })
        .finally(() => {
          setIsLoadingCustomerOptions(false);
          if (includeDrivers) {
            customerOptionsWithDriversRequestRef.current = null;
          } else {
            customerOptionsRequestRef.current = null;
          }
        });
    }
    return requestRef.current;
  };

  const ensureBookingOptionsLoaded = async () => {
    if (bookingOptions) {
      return bookingOptions;
    }
    if (!bookingOptionsRequestRef.current) {
      bookingOptionsRequestRef.current = fetchBookingOptions()
        .then((response) => {
          setBookingOptions(response);
          return response;
        })
        .catch((error) => {
          setPageNotice((current) =>
            current
              ? `${current} Booking setup options are temporarily unavailable.`
              : 'Booking setup options are temporarily unavailable.',
          );
          throw error;
        })
        .finally(() => {
          bookingOptionsRequestRef.current = null;
        });
    }
    return bookingOptionsRequestRef.current;
  };

  const loadCustomerProfile = async (customerId: string) => {
    setIsLoadingCustomerProfile(true);
    try {
      const customer = await fetchCustomerById(customerId);
      setSelectedCustomerProfile(customer);
      setRelationshipForm({
        industry_id: customer.industry_id || '',
        company_or_institution_name: customer.organization_name || customer.company_name || '',
        branch_or_department: customer.branch_or_department || '',
        position_or_role: customer.position_title || '',
        relationship_role_id: customer.relationship_role_id || '',
        relationship_category_id: customer.relationship_category_id || '',
        lead_status_id: customer.lead_status_id || '',
        customer_source_id: customer.customer_source_id || '',
        source: customer.source || '',
        influence_level_id: customer.influence_level_id || '',
        government_sector_id: customer.government_sector_id || '',
        organization_type_id: customer.organization_type_id || '',
        network_value_id: customer.network_value_id || '',
        opportunity_level_id: customer.opportunity_level_id || '',
        potential_service_id: customer.potential_service_id || '',
        relationship_notes: customer.relationship_notes || '',
      });
    } finally {
      setIsLoadingCustomerProfile(false);
    }
  };

  const loadCustomerOpportunities = async (customerId: string) => {
    setIsLoadingOpportunities(true);
    setOpportunitiesLoadError('');
    try {
      setOpportunities(await fetchCustomerOpportunities(customerId));
      setLoadedOpportunitiesCustomerId(customerId);
    } catch (error) {
      setOpportunities([]);
      setLoadedOpportunitiesCustomerId(customerId);
      throw error;
    } finally {
      setIsLoadingOpportunities(false);
    }
  };

  const loadCustomerContacts = async (customerId: string) => {
    setIsLoadingContacts(true);
    setContactsLoadError('');
    try {
      setContacts(await fetchCustomerContacts(customerId));
      setLoadedContactsCustomerId(customerId);
    } catch (error) {
      setContacts([]);
      setLoadedContactsCustomerId(customerId);
      throw error;
    } finally {
      setIsLoadingContacts(false);
    }
  };

  const loadCustomerNotes = async (customerId: string) => {
    setIsLoadingNotes(true);
    try {
      const data = await fetchCustomerNotes(customerId);
      setCustomerNotes(data.notes);
      setCustomerTimeline(data.timeline);
    } finally {
      setIsLoadingNotes(false);
    }
  };

  const summaryScopedCustomers = useMemo(
    () =>
      customers.filter((customer) =>
        (!filterCreatorRole || customer.created_by_role === filterCreatorRole)
        && (!filterSource || customer.source === filterSource)
        && (!filterCustomerCategoryId || customer.customer_category_id === filterCustomerCategoryId)
        && (!filterDriverId || customer.preferred_driver_id === filterDriverId || customer.created_by_driver_id === filterDriverId)
        && (!filterDateFrom || !customer.created_at || new Date(customer.created_at) >= new Date(filterDateFrom))
        && (!filterDateTo || !customer.created_at || new Date(customer.created_at) <= new Date(`${filterDateTo}T23:59:59`)),
      ),
    [customers, filterCreatorRole, filterSource, filterCustomerCategoryId, filterDriverId, filterDateFrom, filterDateTo],
  );

  const summary: BookingSummary = useMemo(
    () => buildLocalBookingSummary(customers, bookings),
    [customers, bookings],
  );

  const customerSummary: CustomerSummary = useMemo(() => {
    const nextSummary = buildLocalCustomerSummary(customers, summaryScopedCustomers, customerOptions);
    return {
      ...nextSummary,
      applied_filters: {
        date_from: filterDateFrom || null,
        date_to: filterDateTo || null,
        creator_role: filterCreatorRole || null,
        driver_id: filterDriverId || null,
        customer_category_id: filterCustomerCategoryId || null,
        source: filterSource || null,
      },
    };
  }, [
    customerOptions,
    customers,
    filterCreatorRole,
    filterCustomerCategoryId,
    filterDateFrom,
    filterDateTo,
    filterDriverId,
    filterSource,
    summaryScopedCustomers,
  ]);

  const customerCategorySelectOptions = useMemo(
    () => buildMasterDataSelectOptions(customerOptions?.customer_category_items),
    [customerOptions?.customer_category_items],
  );
  const customerSourceSelectOptions = useMemo(
    () => buildMasterDataSelectOptions(customerOptions?.customer_source_items),
    [customerOptions?.customer_source_items],
  );
  const sourceSelectOptions = useMemo(
    () => buildStringValueOptions(customerOptions?.source_options, editingCustomer?.source || undefined),
    [customerOptions?.source_options, editingCustomer?.source],
  );
  const organizationTypeSelectOptions = useMemo(
    () => buildMasterDataSelectOptions(customerOptions?.organization_type_items),
    [customerOptions?.organization_type_items],
  );
  const industrySelectOptions = useMemo(
    () => buildMasterDataSelectOptions(customerOptions?.industry_items),
    [customerOptions?.industry_items],
  );
  const governmentSectorSelectOptions = useMemo(
    () => buildMasterDataSelectOptions(customerOptions?.government_sector_items),
    [customerOptions?.government_sector_items],
  );
  const relationshipCategorySelectOptions = useMemo(
    () => buildMasterDataSelectOptions(customerOptions?.relationship_category_items),
    [customerOptions?.relationship_category_items],
  );
  const relationshipRoleSelectOptions = useMemo(
    () => buildMasterDataSelectOptions(customerOptions?.relationship_role_items),
    [customerOptions?.relationship_role_items],
  );
  const opportunityLevelSelectOptions = useMemo(
    () => buildMasterDataSelectOptions(customerOptions?.opportunity_level_items),
    [customerOptions?.opportunity_level_items],
  );
  const opportunityStageSelectOptions = useMemo(
    () => buildMasterDataSelectOptions(customerOptions?.opportunity_stage_items),
    [customerOptions?.opportunity_stage_items],
  );
  const networkValueSelectOptions = useMemo(
    () => buildMasterDataSelectOptions(customerOptions?.network_value_items),
    [customerOptions?.network_value_items],
  );
  const influenceLevelSelectOptions = useMemo(
    () => buildMasterDataSelectOptions(customerOptions?.influence_level_items),
    [customerOptions?.influence_level_items],
  );
  const leadStatusSelectOptions = useMemo(
    () => buildMasterDataSelectOptions(customerOptions?.lead_status_items),
    [customerOptions?.lead_status_items],
  );
  const occupationFieldOptions = useMemo(
    () =>
      (customerOptions?.occupation_items || []).length
        ? buildStringValueOptions(customerOptions?.occupation_items)
        : buildFallbackStringOptions(fallbackOccupationValues),
    [customerOptions?.occupation_items],
  );
  const positionTitleFieldOptions = useMemo(
    () =>
      (customerOptions?.position_title_items || []).length
        ? buildStringValueOptions(customerOptions?.position_title_items)
        : buildFallbackStringOptions(fallbackPositionTitleValues),
    [customerOptions?.position_title_items],
  );
  const potentialServiceSelectOptions = useMemo(
    () => buildMasterDataSelectOptions(customerOptions?.potential_service_items),
    [customerOptions?.potential_service_items],
  );
  const opportunityTypeSelectOptions = useMemo(
    () =>
      buildMasterDataSelectOptions(
        (customerOptions?.opportunity_type_items || []).length
          ? customerOptions?.opportunity_type_items
          : customerOptions?.potential_service_items,
      ),
    [customerOptions?.opportunity_type_items, customerOptions?.potential_service_items],
  );
  const buildOpportunityFormDefaults = (): OpportunityFormState => ({
    ...emptyOpportunityForm,
    opportunity_type_id: preferredOptionValue(opportunityTypeSelectOptions, 'Fleet Service'),
    opportunity_stage_id: preferredOptionValue(opportunityStageSelectOptions, 'New'),
  });
  const profileDisplayCustomer = profileCustomer || selectedCustomer;

  const filteredCustomers = useMemo(
    () =>
      customers.filter((customer) =>
        [customer.full_name, customer.phone_number, customer.email_address, customer.organization_name, customer.company_name]
          .filter(Boolean)
          .some((value) => value?.toLowerCase().includes(debouncedSearch.toLowerCase()))
        && (!filterCreatorRole || customer.created_by_role === filterCreatorRole)
        && (!filterSource || customer.source === filterSource)
        && (!filterCustomerCategoryId || customer.customer_category_id === filterCustomerCategoryId)
        && (!filterDriverId || customer.preferred_driver_id === filterDriverId || customer.created_by_driver_id === filterDriverId)
        && (!filterDateFrom || !customer.created_at || new Date(customer.created_at) >= new Date(filterDateFrom))
        && (!filterDateTo || !customer.created_at || new Date(customer.created_at) <= new Date(`${filterDateTo}T23:59:59`)),
      ),
    [customers, debouncedSearch, filterCreatorRole, filterCustomerCategoryId, filterDateFrom, filterDateTo, filterDriverId, filterSource],
  );

  const upcomingBookings = useMemo(
    () =>
      bookings
        .filter((booking) => ['Scheduled', 'Acknowledged', 'En Route', 'Picked Up', 'Confirmed', 'In Progress'].includes(booking.status) && !booking.is_recurring_template)
        .sort((left, right) => (left.pickup_at || '').localeCompare(right.pickup_at || '')),
    [bookings],
  );

  const bookingQueueFilters = useMemo(
    () => ['All', 'Pending Acknowledgement', 'Acknowledged', 'En Route', 'Picked Up', 'Completed', 'Cancelled', 'Missed'],
    [],
  );

  const filteredBookingQueue = useMemo(() => {
    if (bookingQueueFilter === 'All') {
      return bookings
        .filter((booking) => !booking.is_recurring_template)
        .sort((left, right) => (left.pickup_at || '').localeCompare(right.pickup_at || ''));
    }
    if (bookingQueueFilter === 'Pending Acknowledgement') {
      return upcomingBookings.filter((booking) => booking.status === 'Scheduled');
    }
    return bookings.filter((booking) => booking.status === bookingQueueFilter && !booking.is_recurring_template);
  }, [bookingQueueFilter, bookings, upcomingBookings]);

  const recurringTemplates = useMemo(
    () => bookings.filter((booking) => booking.is_recurring_template),
    [bookings],
  );

  const metrics = useMemo(
    () =>
      portal === 'driver'
        ? {
            primary: [
              { label: 'My Customers', value: customers.length, icon: Users, tint: 'bg-blue-100 text-blue-700' },
              {
                label: 'Today Schedule',
                value: isBookingDataLoading ? '...' : summary?.scheduled_today || 0,
                icon: Calendar,
                tint: 'bg-blue-100 text-blue-700',
              },
              {
                label: 'Overdue Reminders',
                value: isBookingDataLoading ? '...' : summary?.overdue_reminders || customerSummary?.follow_ups_overdue || 0,
                icon: Clock,
                tint: 'bg-rose-100 text-rose-700',
              },
              {
                label: 'Follow-Ups Due',
                value: isBookingDataLoading ? '...' : summary?.follow_ups_due_today || customerSummary?.follow_ups_due_today || 0,
                icon: Star,
                tint: 'bg-amber-100 text-amber-700',
              },
            ],
          }
        : {
            primary: [
              { label: 'Total Customers', value: customerSummary?.total_customers || customers.length, icon: Users, tint: 'bg-blue-100 text-blue-700' },
              {
                label: 'New This Week',
                value: customerSummary?.new_customers_this_week || 0,
                icon: Calendar,
                tint: 'bg-emerald-100 text-emerald-700',
              },
              {
                label: 'New This Month',
                value: customerSummary?.new_customers_this_month || 0,
                icon: Calendar,
                tint: 'bg-cyan-100 text-cyan-700',
              },
              {
                label: 'Follow-Ups Due Today',
                value: customerSummary?.follow_ups_due_today || 0,
                icon: Calendar,
                tint: 'bg-amber-100 text-amber-700',
              },
            ],
            secondary: [
              { label: 'Business Leads', value: customerSummary?.total_business_leads || 0, icon: Briefcase, tint: 'bg-purple-100 text-purple-700' },
              { label: 'Strategic Contacts', value: customerSummary?.total_strategic_contacts || 0, icon: Star, tint: 'bg-cyan-100 text-cyan-700' },
              { label: 'Investors', value: customerSummary?.total_investors || 0, icon: Users, tint: 'bg-indigo-100 text-indigo-700' },
              { label: 'Gatekeepers', value: customerSummary?.total_gatekeepers || 0, icon: MapPin, tint: 'bg-slate-100 text-slate-700' },
              { label: 'Overdue Follow-Ups', value: customerSummary?.follow_ups_overdue || 0, icon: Clock, tint: 'bg-rose-100 text-rose-700' },
              {
                label: 'Lead Conversion',
                value: `${customerSummary?.lead_conversion_rate || 0}%`,
                icon: Briefcase,
                tint: 'bg-emerald-100 text-emerald-700',
              },
            ],
          },
    [customers.length, customerSummary, isBookingDataLoading, portal, summary, upcomingBookings.length],
  );

  const openCreateCustomer = async () => {
    clearCustomerFormErrors();
    setPageError('');
    const options = await ensureCustomerOptionsLoaded(false).catch(() => null);
    if (!options) {
      return;
    }
    setEditingCustomer(null);
    setCustomerForm({
      ...emptyCustomerForm,
      source: firstOptionValue(buildStringValueOptions(options.source_options)),
      customer_category_id: options.customer_category_items?.[0]?.id || '',
      follow_up_priority: options.follow_up_priorities?.[1] || 'medium',
      lead_status_id: options.lead_status_items?.[0]?.id || '',
    });
    setShowCustomerModal(true);
  };

  const openEditCustomer = async (customer: CustomerRecord) => {
    clearCustomerFormErrors();
    setPageError('');
    const options = await ensureCustomerOptionsLoaded(true).catch(() => null);
    setSelectedCustomerId(customer.id);
    setEditingCustomer(customer);
    setCustomerForm({
      full_name: customer.full_name || '',
      phone_number: customer.phone_number || '',
      alternate_phone: customer.alternate_phone || '',
      email_address: customer.email_address || '',
      date_of_birth: customer.date_of_birth || '',
      occupation: customer.occupation || '',
      organization_name: customer.organization_name || customer.company_name || '',
      position_title: customer.position_title || '',
      pickup_location: customer.pickup_location || '',
      destination_location: customer.destination_location || '',
      preferred_pickup_location: customer.preferred_pickup_location || '',
      preferred_dropoff_location: customer.preferred_dropoff_location || '',
      residential_area: customer.residential_area || '',
      work_area: customer.work_area || '',
      source: customer.source || firstOptionValue(buildStringValueOptions(options?.source_options, customer.customer_source || customer.source || undefined)),
      customer_category_id: customer.customer_category_id || '',
      customer_source_id: customer.customer_source_id || '',
      organization_type_id: customer.organization_type_id || '',
      industry_id: customer.industry_id || '',
      relationship_category_id: customer.relationship_category_id || '',
      opportunity_level_id: customer.opportunity_level_id || '',
      network_value_id: customer.network_value_id || '',
      is_transport_customer: customer.is_transport_customer ?? true,
      is_business_lead: customer.is_business_lead ?? false,
      lead_status_id: customer.lead_status_id || '',
      potential_service_id: customer.potential_service_id || '',
      lead_value_estimate:
        customer.lead_value_estimate !== null && customer.lead_value_estimate !== undefined
          ? String(customer.lead_value_estimate)
          : '',
      follow_up_date: customer.follow_up_date || '',
      next_follow_up_date: customer.next_follow_up_date || '',
      follow_up_priority: customer.follow_up_priority || 'medium',
      preferred_driver_id: customer.preferred_driver_id || '',
      notes: customer.notes || '',
      relationship_notes: customer.relationship_notes || '',
      lead_notes: customer.lead_notes || '',
      important_notes: customer.important_notes || '',
      referred_by: customer.referred_by || '',
      company_name: customer.organization_name || customer.company_name || '',
      status: customer.status || 'active',
    });
    setShowCustomerModal(true);
  };

  const openCreateBooking = async () => {
    const options = await ensureBookingOptionsLoaded().catch(() => null);
    if (!options) {
      return;
    }
    setBookingForm({
      ...emptyBookingForm,
      customer_id: selectedCustomer?.id || '',
      driver_id: selectedCustomer?.preferred_driver_id || '',
      pickup_location:
        selectedCustomer?.preferred_pickup_location || selectedCustomer?.pickup_location || '',
      destination:
        selectedCustomer?.preferred_dropoff_location || selectedCustomer?.destination_location || '',
      booking_type: options.booking_types?.[0] || 'Customer Booking',
      title: '',
      description: '',
      priority: options.priorities?.[1] || 'Medium',
      status: options.statuses?.[0] || 'Scheduled',
    });
    setShowBookingModal(true);
  };

  const openCreateReminder = async () => {
    const options = await ensureBookingOptionsLoaded().catch(() => null);
    if (!options) {
      return;
    }
    setBookingForm({
      ...emptyBookingForm,
      customer_id: selectedCustomer?.id || '',
      driver_id: portal === 'driver' ? options.drivers?.[0]?.id || '' : selectedCustomer?.preferred_driver_id || '',
      booking_type: 'Personal Reminder',
      title: '',
      description: '',
      priority: options.priorities?.[1] || 'Medium',
      status: 'Scheduled',
    });
    setShowBookingModal(true);
  };

  const openCreateFollowUpBooking = async () => {
    const options = await ensureBookingOptionsLoaded().catch(() => null);
    if (!options) {
      return;
    }
    setBookingForm({
      ...emptyBookingForm,
      customer_id: selectedCustomer?.id || '',
      driver_id: selectedCustomer?.preferred_driver_id || '',
      booking_type: 'Follow-Up Reminder',
      title: selectedCustomer ? `Follow up with ${selectedCustomer.full_name}` : '',
      description: '',
      priority: options.priorities?.[2] || 'High',
      status: 'Scheduled',
    });
    setShowBookingModal(true);
  };

  const handleSaveCustomer = async () => {
    setIsSavingCustomer(true);
    setPageError('');
    clearCustomerFormErrors();
    try {
      if (!editingCustomer && !customerForm.residential_area.trim()) {
        setCustomerFieldErrors({ residential_area: customerFieldLabelMap.residential_area || 'This field is required.' });
        setCustomerFormError('Please complete the required customer details.');
        return;
      }
      const payload: Record<string, unknown> = {
        ...customerForm,
        organization_name: customerForm.organization_name || undefined,
        company_name: customerForm.organization_name || undefined,
        assigned_driver_id: customerForm.preferred_driver_id || undefined,
      };
      if (customerForm.lead_value_estimate === '') {
        payload.lead_value_estimate = null;
      } else {
        payload.lead_value_estimate = Number(customerForm.lead_value_estimate);
      }
      const savedCustomer = editingCustomer
        ? await updateCustomer(editingCustomer.id, payload)
        : await createCustomer(payload);
      closeCustomerModal();
      setCustomers((current) => {
        if (editingCustomer) {
          return current.map((customer) => (customer.id === savedCustomer.id ? savedCustomer : customer));
        }
        return [savedCustomer, ...current];
      });
      setSelectedCustomerId(savedCustomer.id);
      setSelectedCustomerProfile(savedCustomer);
      setActiveProfileTab('overview');
      setRecentlyCreatedCustomerId(editingCustomer ? null : savedCustomer.id);
      setPageNotice(editingCustomer ? 'Customer profile updated.' : 'Customer added successfully.');
    } catch (error) {
      if (error instanceof ApiRequestError) {
        const normalized = normalizeCustomerFormError(error);
        setCustomerFormError(normalized.formError);
        setCustomerFieldErrors(normalized.fieldErrors);
        setDuplicateCustomer(normalized.duplicateCustomer);
      } else {
        setCustomerFormError('We could not save this customer right now. Please try again.');
      }
    } finally {
      setIsSavingCustomer(false);
    }
  };

  const handleSaveBooking = async () => {
    setIsSavingBooking(true);
    setPageError('');
    try {
      const isReminder = isReminderBookingType(bookingForm.booking_type);
      const payload: Record<string, unknown> = {
        customer_id: bookingForm.customer_id || undefined,
        driver_id: bookingForm.driver_id || undefined,
        vehicle_id: bookingForm.vehicle_id || undefined,
        booking_type: bookingForm.booking_type,
        title: bookingForm.title || undefined,
        description: bookingForm.description || undefined,
        pickup_date: (isReminder ? bookingForm.reminder_date : bookingForm.pickup_date) || bookingForm.pickup_date,
        pickup_time: (isReminder ? bookingForm.reminder_time : bookingForm.pickup_time) || bookingForm.pickup_time,
        reminder_date: bookingForm.reminder_date || bookingForm.pickup_date || undefined,
        reminder_time: bookingForm.reminder_time || bookingForm.pickup_time || undefined,
        pickup_location: bookingForm.pickup_location || undefined,
        destination: bookingForm.destination || undefined,
        priority: bookingForm.priority,
        notes: bookingForm.notes || undefined,
        status: bookingForm.status,
      };
      if (bookingForm.expected_fare) {
        payload.expected_fare = Number(bookingForm.expected_fare);
      }
      if (bookingForm.recurrence_type) {
        payload.recurrence_type = bookingForm.recurrence_type;
        payload.recurrence_frequency = Number(bookingForm.recurrence_frequency || 1);
        payload.recurrence_days = bookingForm.recurrence_days;
        payload.monthly_week_of_month = bookingForm.monthly_week_of_month
          ? Number(bookingForm.monthly_week_of_month)
          : undefined;
        payload.monthly_day_of_week = bookingForm.monthly_day_of_week || undefined;
        payload.custom_rule_text = bookingForm.custom_rule_text || undefined;
        payload.recurrence_end_date = bookingForm.recurrence_end_date || undefined;
      }

      const savedBooking = await createBooking(payload);
      setBookings((current) => [savedBooking, ...current]);
      setShowBookingModal(false);
      await loadWorkspace();
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setPageError(error.message);
      } else {
        setPageError('Unable to schedule that booking right now.');
      }
    } finally {
      setIsSavingBooking(false);
    }
  };

  const handleBookingStatusChange = async (bookingId: string, status: string) => {
    const existingBooking = bookings.find((booking) => booking.id === bookingId);
    if (isCompletedBookingStatus(existingBooking?.status) && isCompletedBookingStatus(status)) {
      setPageError('');
      setPageNotice('This booking has already been completed.');
      return;
    }

    try {
      const updated = await updateBooking(bookingId, { status });
      setBookings((current) => current.map((booking) => (booking.id === bookingId ? updated : booking)));
      await loadWorkspace();
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setPageError(error.message);
      } else {
        setPageError('Unable to update that booking right now.');
      }
    }
  };

  const handleCompleteFollowUp = async () => {
    if (!selectedCustomer) {
      return;
    }
    try {
      const updated = await updateCustomer(selectedCustomer.id, {
        mark_follow_up_completed: true,
        follow_up_completion_note: `Completed from ${portal} portal`,
      });
      setCustomers((current) => current.map((customer) => (customer.id === updated.id ? updated : customer)));
      setSelectedCustomerProfile(updated);
      setPageNotice('Follow-up marked as completed.');
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setPageError(error.message);
      } else {
        setPageError('Unable to complete that follow-up right now.');
      }
    }
  };

  const handleSaveRelationship = async () => {
    if (!profileCustomer || !canEditProfileIntelligence) {
      return;
    }
    setIsSavingRelationship(true);
    setPageError('');
    try {
      const updated = await updateCustomerRelationship(profileCustomer.id, relationshipForm);
      setSelectedCustomerProfile(updated);
      setCustomers((current) => current.map((customer) => (customer.id === updated.id ? { ...customer, ...updated } : customer)));
      setPageNotice('Relationship details updated.');
    } catch (error) {
      setPageError(getErrorMessage(error, 'Unable to update relationship details right now.'));
    } finally {
      setIsSavingRelationship(false);
    }
  };

  const handleSaveOpportunity = async () => {
    if (!profileCustomer || !canEditProfileIntelligence) {
      return;
    }
    setIsSavingOpportunity(true);
    setPageError('');
    try {
      const payload = {
        opportunity_type_id: opportunityForm.opportunity_type_id || opportunityTypeSelectOptions[0]?.value || undefined,
        specific_product_or_service: opportunityForm.specific_product_or_service || undefined,
        estimated_budget: opportunityForm.estimated_budget ? Number(opportunityForm.estimated_budget) : null,
        opportunity_stage_id: opportunityForm.opportunity_stage_id || opportunityStageSelectOptions[0]?.value || undefined,
        probability: opportunityForm.probability ? Number(opportunityForm.probability) : null,
        expected_purchase_date: opportunityForm.expected_purchase_date || undefined,
        follow_up_date: opportunityForm.follow_up_date || undefined,
        notes: opportunityForm.notes || undefined,
        status: opportunityForm.status || undefined,
      };
      const saved = opportunityForm.id
        ? await updateCustomerOpportunity(profileCustomer.id, opportunityForm.id, payload)
        : await createCustomerOpportunity(profileCustomer.id, payload);
      setOpportunities((current) => {
        if (opportunityForm.id) {
          return current.map((item) => (item.id === saved.id ? saved : item));
        }
        return [saved, ...current];
      });
      setOpportunityForm(buildOpportunityFormDefaults());
      setShowOpportunityForm(false);
      setPageNotice(opportunityForm.id ? 'Opportunity updated.' : 'Opportunity added.');
    } catch (error) {
      setPageError(getErrorMessage(error, 'Unable to save this opportunity right now.'));
    } finally {
      setIsSavingOpportunity(false);
    }
  };

  const handleSaveContact = async () => {
    if (!profileCustomer || !canEditProfileIntelligence) {
      return;
    }
    setIsSavingContact(true);
    setPageError('');
    try {
      const payload = {
        contact_name: contactForm.contact_name,
        phone: contactForm.phone || undefined,
        email: contactForm.email || undefined,
        position_or_role: contactForm.position_or_role || undefined,
        relationship_role_id: contactForm.relationship_role_id || undefined,
        notes: contactForm.notes || undefined,
      };
      const saved = contactForm.id
        ? await updateCustomerContact(profileCustomer.id, contactForm.id, payload)
        : await createCustomerContact(profileCustomer.id, payload);
      setContacts((current) => {
        if (contactForm.id) {
          return current.map((item) => (item.id === saved.id ? saved : item));
        }
        return [saved, ...current];
      });
      setContactForm(emptyContactForm);
      setShowContactForm(false);
      setPageNotice(contactForm.id ? 'Contact updated.' : 'Contact added.');
    } catch (error) {
      setPageError(getErrorMessage(error, 'Unable to save this contact right now.'));
    } finally {
      setIsSavingContact(false);
    }
  };

  const handleAddNote = async () => {
    if (!profileCustomer || !canAddCustomerNotes || !newNote.trim()) {
      return;
    }
    setIsSavingNote(true);
    setPageError('');
    try {
      await createCustomerNote(profileCustomer.id, { note: newNote });
      setNewNote('');
      await loadCustomerNotes(profileCustomer.id);
      setPageNotice('Note added.');
    } catch (error) {
      setPageError(getErrorMessage(error, 'Unable to add this note right now.'));
    } finally {
      setIsSavingNote(false);
    }
  };

  const title = portal === 'driver' ? 'My Customers, Leads & Follow-Ups' : 'Customer CRM & Scheduled Bookings';
  const subtitle =
    portal === 'driver'
      ? 'Track assigned customers, follow-ups, recurring riders, and relationship notes.'
      : 'Manage customer profiles, business leads, strategic contacts, future bookings, and ride history.';
  const bookingTypeIsReminder = isReminderBookingType(bookingForm.booking_type);
  const bookingTypeIsFollowUp = followUpBookingTypes.has(bookingForm.booking_type);

  useEffect(() => {
    if (portal !== 'driver' || isLoading) {
      return;
    }
    const quickActionIntent = peekDriverQuickActionIntent();
    if (!quickActionIntent) {
      return;
    }
    if (quickActionIntent === 'create_booking') {
      clearDriverQuickActionIntent();
      void openCreateBooking();
      return;
    }
    if (quickActionIntent === 'create_reminder') {
      clearDriverQuickActionIntent();
      void openCreateReminder();
      return;
    }
    if (quickActionIntent === 'schedule_follow_up') {
      clearDriverQuickActionIntent();
      void openCreateFollowUpBooking();
    }
  }, [isLoading, portal, bookingOptions, selectedCustomerId]);

  if (isLoading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center gap-3 text-gray-500">
        <Loader2 className="h-5 w-5 animate-spin" />
        <span>Loading customer workspace...</span>
      </div>
    );
  }

  return (
    <div className="max-w-full space-y-6 overflow-x-hidden p-4 md:p-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0">
          <h1 className="break-words text-2xl font-semibold text-[#0F172A]">{title}</h1>
          <p className="mt-1 text-sm text-gray-500">{subtitle}</p>
        </div>
        <div className="flex w-full flex-col gap-3 sm:w-auto sm:flex-row">
          <button
            type="button"
            onClick={() => void openCreateCustomer()}
            className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-gray-200 bg-white px-4 py-2.5 text-sm font-medium text-[#0F172A] hover:bg-gray-50 sm:w-auto"
          >
            <UserPlus className="h-4 w-4" />
            Add Customer
          </button>
          <button
            type="button"
            onClick={() => void openCreateBooking()}
            className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-[#2563EB] px-4 py-2.5 text-sm font-medium text-white hover:bg-[#1d4ed8] sm:w-auto"
          >
            <Plus className="h-4 w-4" />
            Schedule Booking
          </button>
          <button
            type="button"
            onClick={() => void openCreateReminder()}
            className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-purple-200 bg-purple-50 px-4 py-2.5 text-sm font-medium text-purple-700 hover:bg-purple-100 sm:w-auto"
          >
            <Clock className="h-4 w-4" />
            Create Reminder
          </button>
          <button
            type="button"
            onClick={() => void openCreateFollowUpBooking()}
            className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm font-medium text-amber-700 hover:bg-amber-100 sm:w-auto"
          >
            <Calendar className="h-4 w-4" />
            Schedule Follow-Up
          </button>
        </div>
      </div>

      {recentlyCreatedCustomerId && (
        <div className="rounded-2xl border border-blue-200 bg-blue-50 px-4 py-4">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <div className="text-sm font-semibold text-[#0F172A]">Customer saved successfully.</div>
              <p className="mt-1 text-sm text-gray-600">You can open the full profile now or add another customer right away.</p>
            </div>
            <div className="flex flex-col gap-2 sm:flex-row">
              <button
                type="button"
                onClick={() => {
                  setSelectedCustomerId(recentlyCreatedCustomerId);
                  setActiveProfileTab('overview');
                  setRecentlyCreatedCustomerId(null);
                }}
                className="rounded-xl bg-[#2563EB] px-4 py-2.5 text-sm font-medium text-white hover:bg-[#1d4ed8]"
              >
                View Profile
              </button>
              <button
                type="button"
                onClick={() => {
                  setRecentlyCreatedCustomerId(null);
                  void openCreateCustomer();
                }}
                className="rounded-xl border border-gray-300 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                Add Another Customer
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        {metrics.primary.map((card) => {
          const Icon = card.icon;
          return (
            <div key={card.label} className="rounded-2xl border border-gray-200 bg-white p-5">
              <div className={`mb-4 flex h-12 w-12 items-center justify-center rounded-xl ${card.tint}`}>
                <Icon className="h-5 w-5" />
              </div>
              <div className="text-3xl font-semibold text-[#0F172A]">{card.value}</div>
              <div className="mt-1 text-sm text-gray-500">{card.label}</div>
            </div>
          );
        })}
      </div>

      {'secondary' in metrics && metrics.secondary && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          {metrics.secondary.map((card) => {
            const Icon = card.icon;
            return (
              <div key={card.label} className="rounded-2xl border border-gray-200 bg-white p-5">
                <div className={`mb-4 flex h-12 w-12 items-center justify-center rounded-xl ${card.tint}`}>
                  <Icon className="h-5 w-5" />
                </div>
                <div className="text-3xl font-semibold text-[#0F172A]">{card.value}</div>
                <div className="mt-1 text-sm text-gray-500">{card.label}</div>
              </div>
            );
          })}
        </div>
      )}

      <div className="rounded-2xl border border-gray-200 bg-white p-4">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <h3 className="text-lg font-semibold text-[#0F172A]">Customer Analytics Filters</h3>
            <p className="text-sm text-gray-500">Filter the creator, driver, category, source, and date view without leaving the workspace.</p>
          </div>
        </div>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-6">
          <input
            type="date"
            value={filterDateFrom}
            onChange={(event) => setFilterDateFrom(event.target.value)}
            className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm"
          />
          <input
            type="date"
            value={filterDateTo}
            onChange={(event) => setFilterDateTo(event.target.value)}
            className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm"
          />
          <select value={filterCreatorRole} onChange={(event) => setFilterCreatorRole(event.target.value)} className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm">
            <option value="">All Creator Roles</option>
            {(customerSummary?.available_filters?.creator_roles || customerOptions?.creator_roles || []).map((role) => (
              <option key={role} value={role}>
                {role}
              </option>
            ))}
          </select>
          <select value={filterDriverId} onChange={(event) => setFilterDriverId(event.target.value)} className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm">
            <option value="">All Drivers</option>
            {(customerSummary?.available_filters?.drivers || customerOptions?.drivers || []).map((driver) => (
              <option key={driver.id} value={driver.id}>
                {driver.full_name}
              </option>
            ))}
          </select>
          <select value={filterCustomerCategoryId} onChange={(event) => setFilterCustomerCategoryId(event.target.value)} className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm">
            <option value="">All Categories</option>
            {(customerSummary?.available_filters?.customer_categories || []).map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
            {!customerSummary?.available_filters?.customer_categories?.length &&
              (customerOptions?.customer_category_items || []).map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
          </select>
          <select value={filterSource} onChange={(event) => setFilterSource(event.target.value)} className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm">
            <option value="">All Sources</option>
            {(customerSummary?.available_filters?.sources || customerOptions?.source_options || []).map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {portal !== 'driver' && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <section className="rounded-2xl border border-gray-200 bg-white p-5">
            <h3 className="text-lg font-semibold text-[#0F172A]">Customer Analytics</h3>
            <div className="mt-4 grid grid-cols-2 gap-4">
              <div className="rounded-xl bg-gray-50 p-4">
                <div className="text-sm text-gray-500">New This Week</div>
                <div className="mt-1 text-2xl font-semibold text-[#0F172A]">{customerSummary?.new_customers_this_week || 0}</div>
              </div>
              <div className="rounded-xl bg-gray-50 p-4">
                <div className="text-sm text-gray-500">New This Month</div>
                <div className="mt-1 text-2xl font-semibold text-[#0F172A]">{customerSummary?.new_customers_this_month || 0}</div>
              </div>
            </div>
            <div className="mt-5 space-y-3 text-sm">
              <div>
                <div className="mb-2 font-medium text-[#0F172A]">Top Customer Generators</div>
                {(customerSummary?.top_customer_generators || []).slice(0, 5).map((entry) => (
                  <div key={`${entry.creator_role}-${entry.creator_name}`} className="flex items-center justify-between rounded-lg bg-gray-50 px-3 py-2">
                    <span>{entry.creator_name} <span className="text-xs text-gray-500">({entry.creator_role})</span></span>
                    <span className="font-semibold text-[#0F172A]">{entry.count}</span>
                  </div>
                ))}
              </div>
              <div>
                <div className="mb-2 font-medium text-[#0F172A]">Customers By Source</div>
                {(customerSummary?.customers_by_source || []).slice(0, 5).map((entry) => (
                  <div key={entry.source} className="flex items-center justify-between rounded-lg bg-gray-50 px-3 py-2">
                    <span>{entry.label}</span>
                    <span className="font-semibold text-[#0F172A]">{entry.count}</span>
                  </div>
                ))}
              </div>
            </div>
          </section>

          <section className="rounded-2xl border border-gray-200 bg-white p-5">
            <h3 className="text-lg font-semibold text-[#0F172A]">Creator And Driver Breakdown</h3>
            <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
              <div>
                <div className="mb-2 text-sm font-medium text-[#0F172A]">Customers By Creator</div>
                {(customerSummary?.customers_by_creator || []).slice(0, 5).map((entry) => (
                  <div key={`${entry.creator_role}-${entry.creator_name}-creator`} className="flex items-center justify-between rounded-lg bg-gray-50 px-3 py-2 text-sm">
                    <span>{entry.creator_name}</span>
                    <span className="font-semibold text-[#0F172A]">{entry.count}</span>
                  </div>
                ))}
              </div>
              <div>
                <div className="mb-2 text-sm font-medium text-[#0F172A]">Customers By Driver</div>
                {(customerSummary?.customers_by_driver || []).slice(0, 5).map((entry) => (
                  <div key={`${entry.driver_id || entry.driver_name}-driver`} className="flex items-center justify-between rounded-lg bg-gray-50 px-3 py-2 text-sm">
                    <span>{entry.driver_name}</span>
                    <span className="font-semibold text-[#0F172A]">{entry.count}</span>
                  </div>
                ))}
              </div>
            </div>
          </section>
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
        <div className="overflow-hidden rounded-2xl border border-gray-200 bg-white">
          <div className="border-b border-gray-200 p-4">
            <div className="mb-3 flex items-center justify-between gap-3 text-xs text-gray-500">
              <span>{filteredCustomers.length} records</span>
              <span>{customers.length} total</span>
            </div>
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search by name, phone, or organization"
              className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm focus:border-[#2563EB] focus:outline-none focus:ring-2 focus:ring-blue-100"
            />
          </div>
          <div className="max-h-[820px] overflow-y-auto">
            {filteredCustomers.map((customer) => (
              <button
                type="button"
                key={customer.id}
                onClick={() => setSelectedCustomerId(customer.id)}
                className={`w-full border-b border-gray-100 px-4 py-4 text-left transition-all hover:bg-gray-50 ${
                  selectedCustomerId === customer.id ? 'bg-blue-50' : 'bg-white'
                }`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold text-[#0F172A]">{customer.full_name}</div>
                    <div className="mt-1 flex items-center gap-2 text-xs text-gray-500">
                      <Phone className="h-3.5 w-3.5" />
                      <span>{customer.phone_number}</span>
                    </div>
                    <div className="mt-2 flex flex-wrap gap-2">
                      <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-700">
                        {customer.customer_category}
                      </span>
                      {customer.source_label && (
                        <span className="rounded-full bg-cyan-100 px-2.5 py-1 text-xs text-cyan-700">
                          {customer.source_label}
                        </span>
                      )}
                      {customer.relationship_category && (
                        <span className="rounded-full bg-purple-100 px-2.5 py-1 text-xs text-purple-700">
                          {customer.relationship_category}
                        </span>
                      )}
                      {customer.lead_status && (
                        <span className="rounded-full bg-amber-100 px-2.5 py-1 text-xs text-amber-700">
                          {customer.lead_status}
                        </span>
                      )}
                      <span className="rounded-full bg-green-100 px-2.5 py-1 text-xs text-green-700">
                        {customer.status}
                      </span>
                    </div>
                  </div>
                  <div className="text-right text-xs text-gray-500">
                  <div>{formatOptionalCount(customer.total_rides)} rides</div>
                  <div className="mt-1">{formatOptionalCount(customer.upcoming_bookings_count)} upcoming</div>
                  <div className="mt-1">{formatOptionalCount(customer.completed_bookings_count)} completed</div>
                  <div className="mt-1">{formatOptionalCount(customer.missed_bookings_count)} missed</div>
                  {customer.active_follow_up_date && (
                    <div className="mt-1">{customer.follow_up_status_label}</div>
                  )}
                  </div>
                </div>
              </button>
            ))}
            {!filteredCustomers.length && (
              <div className="p-8 text-center text-sm text-gray-500">No matching records found.</div>
            )}
          </div>
        </div>

        <div className="space-y-6">
          {selectedCustomer ? (
            <>
              <div className="rounded-2xl bg-gradient-to-r from-[#0F172A] to-[#1e40af] p-6 text-white">
                <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                  <div className="space-y-3">
                    <div>
                      <h2 className="text-2xl font-semibold">{profileDisplayCustomer?.full_name || selectedCustomer.full_name}</h2>
                      <p className="mt-1 text-sm text-blue-100">
                        {profileDisplayCustomer?.occupation || 'Customer profile'}
                        {(profileDisplayCustomer?.organization_name || profileDisplayCustomer?.company_name) ? ` - ${profileDisplayCustomer?.organization_name || profileDisplayCustomer?.company_name}` : ''}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-2 text-sm text-blue-100">
                      <span className="inline-flex items-center gap-1 rounded-lg bg-white/10 px-3 py-1.5">
                        <Phone className="h-4 w-4" />
                        {profileDisplayCustomer?.phone_number || selectedCustomer.phone_number}
                      </span>
                      <span className="inline-flex items-center gap-1 rounded-lg bg-white/10 px-3 py-1.5">
                        <MapPin className="h-4 w-4" />
                        {profileDisplayCustomer?.residential_area || selectedCustomer.residential_area || 'Location not set'}
                      </span>
                      <span className="inline-flex items-center gap-1 rounded-lg bg-white/10 px-3 py-1.5">
                        <Briefcase className="h-4 w-4" />
                        {profileDisplayCustomer?.customer_category || selectedCustomer.customer_category}
                      </span>
                    </div>
                    <div className="mt-2 text-xs text-gray-200">
                      Created by {profileDisplayCustomer?.created_by_name || selectedCustomer.created_by_name || 'Unknown / Legacy Record'}
                      {(profileDisplayCustomer?.created_by_role || selectedCustomer.created_by_role) ? ` (${profileDisplayCustomer?.created_by_role || selectedCustomer.created_by_role})` : ''}
                    </div>
                  </div>
                  <div className="flex flex-col gap-2 sm:flex-row">
                    <button
                      type="button"
                      onClick={() => {
                        setActiveProfileTab('overview');
                        void loadCustomerProfile(selectedCustomer.id);
                      }}
                      className="inline-flex items-center justify-center gap-2 rounded-xl bg-white/15 px-4 py-2.5 text-sm font-medium text-white hover:bg-white/25"
                    >
                      View Profile
                    </button>
                    <button
                      type="button"
                      onClick={() => void openEditCustomer(profileDisplayCustomer || selectedCustomer)}
                      className="inline-flex items-center justify-center gap-2 rounded-xl bg-white/15 px-4 py-2.5 text-sm font-medium text-white hover:bg-white/25"
                    >
                      <Pencil className="h-4 w-4" />
                      Edit Basic Info
                    </button>
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-6">
                {[
                  { label: 'Total Rides', value: profileDisplayCustomer?.total_rides || 0 },
                  { label: 'Total Bookings', value: profileDisplayCustomer?.total_bookings || 0 },
                  { label: 'Upcoming', value: profileDisplayCustomer?.upcoming_bookings_count || 0 },
                  { label: 'Completed', value: profileDisplayCustomer?.completed_bookings_count || 0 },
                  { label: 'Missed', value: profileDisplayCustomer?.missed_bookings_count || 0 },
                  { label: 'Follow-Up', value: profileDisplayCustomer?.active_follow_up_date ? formatDate(profileDisplayCustomer.active_follow_up_date) : 'Not scheduled' },
                ].map((item) => (
                  <div key={item.label} className="rounded-2xl border border-gray-200 bg-white p-4">
                    <div className="text-xs font-medium uppercase tracking-wide text-gray-500">{item.label}</div>
                    <div className="mt-2 text-lg font-semibold text-[#0F172A]">{item.value}</div>
                  </div>
                ))}
              </div>

              <div className="flex flex-wrap gap-2 rounded-2xl border border-gray-200 bg-white p-3">
                {[
                  ['overview', 'Overview'],
                  ['relationship', 'Relationship Details'],
                  ['opportunities', 'Opportunities'],
                  ['contacts', 'Additional Contacts'],
                  ['trips', 'Trips / Bookings'],
                  ['notes', 'Notes / Timeline'],
                ].map(([id, label]) => (
                  <button
                    type="button"
                    key={id}
                    onClick={() => setActiveProfileTab(id as CustomerProfileTab)}
                    className={`rounded-xl px-4 py-2 text-sm font-medium ${
                      activeProfileTab === id ? 'bg-[#2563EB] text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>

              {isLoadingCustomerProfile && !profileCustomer ? (
                <div className="rounded-2xl border border-gray-200 bg-white px-6 py-12 text-center text-sm text-gray-500">
                  Loading customer profile...
                </div>
              ) : null}

              {activeProfileTab === 'overview' && profileDisplayCustomer && (
                <section className="rounded-2xl border border-gray-200 bg-white p-5">
                  <div className="flex items-center justify-between">
                    <h3 className="text-lg font-semibold text-[#0F172A]">Overview</h3>
                    <button
                      type="button"
                      onClick={() => void openEditCustomer(profileDisplayCustomer)}
                      className="rounded-lg border border-gray-300 px-3 py-2 text-xs font-medium text-gray-700 hover:bg-gray-50"
                    >
                      Edit Basic Info
                    </button>
                  </div>
                  <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
                    {[
                      ['Customer Name', profileDisplayCustomer.full_name],
                      ['Phone', profileDisplayCustomer.phone_number],
                      ['Location', profileDisplayCustomer.residential_area || 'Not set'],
                      ['Organization / Business Name', profileDisplayCustomer.organization_name || profileDisplayCustomer.company_name || 'Not set'],
                      ['Customer Type / Category', profileDisplayCustomer.customer_category || 'Not set'],
                      ['Email', profileDisplayCustomer.email_address || 'Not set'],
                      ['Status', profileDisplayCustomer.status || 'Not set'],
                      ['Created By', profileDisplayCustomer.created_by_name || 'Unknown / Legacy Record'],
                      ['Created Date', formatDate(profileDisplayCustomer.created_at)],
                    ].map(([label, value]) => (
                      <div key={label} className="rounded-xl bg-gray-50 p-4">
                        <div className="text-xs font-medium uppercase tracking-wide text-gray-500">{label}</div>
                        <div className="mt-2 text-sm text-[#0F172A]">{value}</div>
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {activeProfileTab === 'relationship' && profileDisplayCustomer && (
                <section className="rounded-2xl border border-gray-200 bg-white p-5">
                  <div className="flex items-center justify-between">
                    <h3 className="text-lg font-semibold text-[#0F172A]">Relationship Details</h3>
                    {canEditProfileIntelligence && (
                      <button
                        type="button"
                        onClick={() => void handleSaveRelationship()}
                        disabled={isSavingRelationship}
                        className="rounded-lg bg-[#2563EB] px-4 py-2 text-sm font-medium text-white hover:bg-[#1d4ed8] disabled:opacity-60"
                      >
                        {isSavingRelationship ? 'Saving...' : 'Save Relationship'}
                      </button>
                    )}
                  </div>
                  {isLoadingCustomerOptions && !customerOptions ? (
                    <div className="mt-4 rounded-xl bg-gray-50 px-4 py-6 text-sm text-gray-500">Loading relationship options...</div>
                  ) : null}
                  <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
                    <SearchableSelect value={relationshipForm.industry_id} onChange={(value) => setRelationshipForm((current) => ({ ...current, industry_id: value }))} options={industrySelectOptions} placeholder="Select industry" searchPlaceholder="Search industries..." emptyLabel="No industries found." allowClear clearLabel="No industry" disabled={!canEditProfileIntelligence} />
                    <SearchableSelect value={relationshipForm.government_sector_id} onChange={(value) => setRelationshipForm((current) => ({ ...current, government_sector_id: value }))} options={governmentSectorSelectOptions} placeholder="Select government sector" searchPlaceholder="Search government sectors..." emptyLabel="No government sectors found." allowClear clearLabel="No government sector" disabled={!canEditProfileIntelligence} />
                    <input value={relationshipForm.company_or_institution_name} onChange={(event) => setRelationshipForm((current) => ({ ...current, company_or_institution_name: event.target.value }))} placeholder="Company or institution name" disabled={!canEditProfileIntelligence} className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm disabled:cursor-not-allowed disabled:bg-gray-50 disabled:text-gray-500" />
                    <input value={relationshipForm.branch_or_department} onChange={(event) => setRelationshipForm((current) => ({ ...current, branch_or_department: event.target.value }))} placeholder="Branch or department" disabled={!canEditProfileIntelligence} className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm disabled:cursor-not-allowed disabled:bg-gray-50 disabled:text-gray-500" />
                    <SearchableSelect value={relationshipForm.customer_source_id} onChange={(value) => setRelationshipForm((current) => ({ ...current, customer_source_id: value }))} options={customerSourceSelectOptions} placeholder="Select customer source" searchPlaceholder="Search customer sources..." emptyLabel="No customer sources found." allowClear clearLabel="No customer source" disabled={!canEditProfileIntelligence} />
                    <SearchableSelect value={relationshipForm.source} onChange={(value) => setRelationshipForm((current) => ({ ...current, source: value }))} options={sourceSelectOptions} placeholder="Select source" searchPlaceholder="Search sources..." emptyLabel="No sources found." allowClear clearLabel="No source" disabled={!canEditProfileIntelligence} />
                    <SearchableSelect value={relationshipForm.relationship_category_id} onChange={(value) => setRelationshipForm((current) => ({ ...current, relationship_category_id: value }))} options={relationshipCategorySelectOptions} placeholder="Select relationship category" searchPlaceholder="Search relationship categories..." emptyLabel="No relationship categories found." allowClear clearLabel="No relationship category" disabled={!canEditProfileIntelligence} />
                    <SearchableSelect value={relationshipForm.relationship_role_id} onChange={(value) => setRelationshipForm((current) => ({ ...current, relationship_role_id: value }))} options={relationshipRoleSelectOptions} placeholder="Select relationship role" searchPlaceholder="Search relationship roles..." emptyLabel="No relationship roles found." allowClear clearLabel="No relationship role" disabled={!canEditProfileIntelligence} />
                    <SearchableSelect value={relationshipForm.lead_status_id} onChange={(value) => setRelationshipForm((current) => ({ ...current, lead_status_id: value }))} options={leadStatusSelectOptions} placeholder="Select lead status" searchPlaceholder="Search lead statuses..." emptyLabel="No lead statuses found." allowClear clearLabel="No lead status" disabled={!canEditProfileIntelligence} />
                    <SearchableSelect value={relationshipForm.influence_level_id} onChange={(value) => setRelationshipForm((current) => ({ ...current, influence_level_id: value }))} options={influenceLevelSelectOptions} placeholder="Select influence level" searchPlaceholder="Search influence levels..." emptyLabel="No influence levels found." allowClear clearLabel="No influence level" disabled={!canEditProfileIntelligence} />
                    <SearchableSelect value={relationshipForm.organization_type_id} onChange={(value) => setRelationshipForm((current) => ({ ...current, organization_type_id: value }))} options={organizationTypeSelectOptions} placeholder="Select organization type" searchPlaceholder="Search organization types..." emptyLabel="No organization types found." allowClear clearLabel="No organization type" disabled={!canEditProfileIntelligence} />
                    <SearchableSelect value={relationshipForm.opportunity_level_id} onChange={(value) => setRelationshipForm((current) => ({ ...current, opportunity_level_id: value }))} options={opportunityLevelSelectOptions} placeholder="Select opportunity level" searchPlaceholder="Search opportunity levels..." emptyLabel="No opportunity levels found." allowClear clearLabel="No opportunity level" disabled={!canEditProfileIntelligence} />
                    <SearchableSelect value={relationshipForm.network_value_id} onChange={(value) => setRelationshipForm((current) => ({ ...current, network_value_id: value }))} options={networkValueSelectOptions} placeholder="Select network value" searchPlaceholder="Search network values..." emptyLabel="No network values found." allowClear clearLabel="No network value" disabled={!canEditProfileIntelligence} />
                    <SearchableSelect value={relationshipForm.potential_service_id} onChange={(value) => setRelationshipForm((current) => ({ ...current, potential_service_id: value }))} options={potentialServiceSelectOptions} placeholder="Select potential service" searchPlaceholder="Search potential services..." emptyLabel="No potential services found." allowClear clearLabel="No potential service" disabled={!canEditProfileIntelligence} />
                    <SearchableSelect value={relationshipForm.position_or_role} onChange={(value) => setRelationshipForm((current) => ({ ...current, position_or_role: value }))} options={buildStringValueOptions(positionTitleFieldOptions, relationshipForm.position_or_role)} placeholder="Select position or role" searchPlaceholder="Search positions or roles..." emptyLabel={positionTitleEmptyLabel} allowClear clearLabel="No position" disabled={!canEditProfileIntelligence} />
                    <textarea value={relationshipForm.relationship_notes} onChange={(event) => setRelationshipForm((current) => ({ ...current, relationship_notes: event.target.value }))} rows={4} placeholder="Relationship notes" disabled={!canEditProfileIntelligence} className="md:col-span-2 w-full rounded-xl border border-gray-300 px-4 py-3 text-sm disabled:cursor-not-allowed disabled:bg-gray-50 disabled:text-gray-500" />
                  </div>
                </section>
              )}

              {activeProfileTab === 'opportunities' && profileDisplayCustomer && (
                <section className="rounded-2xl border border-gray-200 bg-white p-5">
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="text-lg font-semibold text-[#0F172A]">Opportunities</h3>
                      <p className="mt-1 text-sm text-gray-500">Track products, services, estimated value, stage, and follow-up for this customer.</p>
                    </div>
                    {canEditProfileIntelligence && (
                      <button type="button" onClick={() => { setOpportunityForm(buildOpportunityFormDefaults()); setShowOpportunityForm((current) => !current); }} className="rounded-lg bg-[#2563EB] px-4 py-2 text-sm font-medium text-white hover:bg-[#1d4ed8]">Add Opportunity</button>
                    )}
                  </div>
                  {isLoadingCustomerOptions && !customerOptions && !showOpportunityForm ? (
                    <div className="mt-4 rounded-xl bg-gray-50 px-4 py-6 text-sm text-gray-500">Loading opportunity options...</div>
                  ) : null}
                  {showOpportunityForm && canEditProfileIntelligence && (
                    <div className="mt-4 grid grid-cols-1 gap-4 rounded-xl border border-gray-200 p-4 md:grid-cols-2">
                      <SearchableSelect value={opportunityForm.opportunity_type_id} onChange={(value) => setOpportunityForm((current) => ({ ...current, opportunity_type_id: value }))} options={opportunityTypeSelectOptions} placeholder="Select opportunity type" searchPlaceholder="Search opportunity types..." emptyLabel={opportunityTypeEmptyLabel} />
                      <SearchableSelect value={opportunityForm.opportunity_stage_id} onChange={(value) => setOpportunityForm((current) => ({ ...current, opportunity_stage_id: value }))} options={opportunityStageSelectOptions} placeholder="Select opportunity stage" searchPlaceholder="Search opportunity stages..." emptyLabel="No opportunity stages found. Add stages in Master Data." allowClear clearLabel="No stage" />
                      <input value={opportunityForm.specific_product_or_service} onChange={(event) => setOpportunityForm((current) => ({ ...current, specific_product_or_service: event.target.value }))} placeholder="Specific product or service" className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm" />
                      <input type="number" min="0" value={opportunityForm.estimated_budget} onChange={(event) => setOpportunityForm((current) => ({ ...current, estimated_budget: event.target.value }))} placeholder="Estimated budget" className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm" />
                      <input type="number" min="0" max="100" value={opportunityForm.probability} onChange={(event) => setOpportunityForm((current) => ({ ...current, probability: event.target.value }))} placeholder="Probability %" className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm" />
                      <input value={opportunityForm.status} onChange={(event) => setOpportunityForm((current) => ({ ...current, status: event.target.value }))} placeholder="Status" className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm" />
                      <input type="date" value={opportunityForm.expected_purchase_date} onChange={(event) => setOpportunityForm((current) => ({ ...current, expected_purchase_date: event.target.value }))} className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm" />
                      <input type="date" value={opportunityForm.follow_up_date} onChange={(event) => setOpportunityForm((current) => ({ ...current, follow_up_date: event.target.value }))} className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm" />
                      <textarea value={opportunityForm.notes} onChange={(event) => setOpportunityForm((current) => ({ ...current, notes: event.target.value }))} rows={3} placeholder="Notes" className="md:col-span-2 w-full rounded-xl border border-gray-300 px-4 py-3 text-sm" />
                      <div className="md:col-span-2 flex justify-end gap-2">
                        <button type="button" onClick={() => { setShowOpportunityForm(false); setOpportunityForm(buildOpportunityFormDefaults()); }} className="rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50">Cancel</button>
                        <button type="button" onClick={() => void handleSaveOpportunity()} disabled={isSavingOpportunity} className="rounded-lg bg-[#2563EB] px-3 py-2 text-sm text-white hover:bg-[#1d4ed8] disabled:opacity-60">{isSavingOpportunity ? 'Saving...' : opportunityForm.id ? 'Update Opportunity' : 'Save Opportunity'}</button>
                      </div>
                    </div>
                  )}
                  <div className="mt-4 space-y-3">
                    {isLoadingOpportunities ? (
                      <div className="rounded-xl bg-gray-50 px-4 py-6 text-sm text-gray-500">Loading opportunities...</div>
                    ) : opportunitiesLoadError ? (
                      <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-6 text-sm text-amber-800">{opportunitiesLoadError}</div>
                    ) : opportunities.length ? opportunities.map((opportunity) => (
                      <div key={opportunity.id} className="rounded-xl border border-gray-200 p-4">
                        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                          <div>
                            <div className="text-sm font-semibold text-[#0F172A]">{opportunity.opportunity_type || 'Opportunity'}</div>
                            <div className="mt-1 text-xs text-gray-500">{opportunity.specific_product_or_service || 'No product/service specified'}</div>
                            <div className="mt-2 text-xs text-gray-500">{opportunity.opportunity_stage || 'No stage'}{opportunity.estimated_budget ? ` • ${formatCurrency(opportunity.estimated_budget)}` : ''}</div>
                          </div>
                          {canEditProfileIntelligence && (
                            <button type="button" onClick={() => { setOpportunityForm({ id: opportunity.id, opportunity_type_id: opportunity.opportunity_type_id || '', specific_product_or_service: opportunity.specific_product_or_service || '', estimated_budget: opportunity.estimated_budget ? String(opportunity.estimated_budget) : '', opportunity_stage_id: opportunity.opportunity_stage_id || '', probability: opportunity.probability ? String(opportunity.probability) : '', expected_purchase_date: opportunity.expected_purchase_date || '', follow_up_date: opportunity.follow_up_date || '', notes: opportunity.notes || '', status: opportunity.status || 'open' }); setShowOpportunityForm(true); }} className="rounded-lg border border-gray-300 px-3 py-2 text-xs font-medium text-gray-700 hover:bg-gray-50">Edit</button>
                          )}
                        </div>
                      </div>
                    )) : (
                      <div className="rounded-xl bg-gray-50 px-4 py-6 text-sm text-gray-500">No opportunities yet.</div>
                    )}
                  </div>
                </section>
              )}

              {activeProfileTab === 'contacts' && profileDisplayCustomer && (
                <section className="rounded-2xl border border-gray-200 bg-white p-5">
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="text-lg font-semibold text-[#0F172A]">Additional Contacts</h3>
                      <p className="mt-1 text-sm text-gray-500">Add separate people linked to this customer. This is different from the customer&apos;s alternate phone number.</p>
                    </div>
                    {canEditProfileIntelligence && (
                      <button type="button" onClick={() => { setContactForm(emptyContactForm); setShowContactForm((current) => !current); }} className="rounded-lg bg-[#2563EB] px-4 py-2 text-sm font-medium text-white hover:bg-[#1d4ed8]">Add Contact</button>
                    )}
                  </div>
                  {isLoadingCustomerOptions && !customerOptions && !showContactForm ? (
                    <div className="mt-4 rounded-xl bg-gray-50 px-4 py-6 text-sm text-gray-500">Loading contact options...</div>
                  ) : null}
                  {showContactForm && canEditProfileIntelligence && (
                    <div className="mt-4 grid grid-cols-1 gap-4 rounded-xl border border-gray-200 p-4 md:grid-cols-2">
                      <input value={contactForm.contact_name} onChange={(event) => setContactForm((current) => ({ ...current, contact_name: event.target.value }))} placeholder="Contact name" className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm" />
                      <SearchableSelect value={contactForm.position_or_role} onChange={(value) => setContactForm((current) => ({ ...current, position_or_role: value }))} options={buildStringValueOptions(positionTitleFieldOptions, contactForm.position_or_role)} placeholder="Select position or role" searchPlaceholder="Search positions or roles..." emptyLabel={positionTitleEmptyLabel} allowClear clearLabel="No position" />
                      <input value={contactForm.phone} onChange={(event) => setContactForm((current) => ({ ...current, phone: event.target.value }))} placeholder="Phone" className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm" />
                      <input type="email" value={contactForm.email} onChange={(event) => setContactForm((current) => ({ ...current, email: event.target.value }))} placeholder="Email" className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm" />
                      <SearchableSelect value={contactForm.relationship_role_id} onChange={(value) => setContactForm((current) => ({ ...current, relationship_role_id: value }))} options={relationshipRoleSelectOptions} placeholder="Select relationship role" searchPlaceholder="Search relationship roles..." emptyLabel="No relationship roles found." allowClear clearLabel="No relationship role" />
                      <textarea value={contactForm.notes} onChange={(event) => setContactForm((current) => ({ ...current, notes: event.target.value }))} rows={3} placeholder="Notes" className="w-full rounded-xl border border-gray-300 px-4 py-3 text-sm" />
                      <div className="md:col-span-2 flex justify-end gap-2">
                        <button type="button" onClick={() => { setShowContactForm(false); setContactForm(emptyContactForm); }} className="rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50">Cancel</button>
                        <button type="button" onClick={() => void handleSaveContact()} disabled={isSavingContact} className="rounded-lg bg-[#2563EB] px-3 py-2 text-sm text-white hover:bg-[#1d4ed8] disabled:opacity-60">{isSavingContact ? 'Saving...' : contactForm.id ? 'Update Contact' : 'Save Contact'}</button>
                      </div>
                    </div>
                  )}
                  <div className="mt-4 space-y-3">
                    {isLoadingContacts ? (
                      <div className="rounded-xl bg-gray-50 px-4 py-6 text-sm text-gray-500">Loading contacts...</div>
                    ) : contactsLoadError ? (
                      <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-6 text-sm text-amber-800">{contactsLoadError}</div>
                    ) : contacts.length ? contacts.map((contact) => (
                      <div key={contact.id} className="rounded-xl border border-gray-200 p-4">
                        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                          <div>
                            <div className="text-sm font-semibold text-[#0F172A]">{contact.contact_name}</div>
                            <div className="mt-1 text-xs text-gray-500">{contact.position_or_role || 'No position'}{contact.relationship_role ? ` • ${contact.relationship_role}` : ''}</div>
                            <div className="mt-1 text-xs text-gray-500">{contact.phone || 'No phone'}{contact.email ? ` • ${contact.email}` : ''}</div>
                          </div>
                          {canEditProfileIntelligence && (
                            <button type="button" onClick={() => { setContactForm({ id: contact.id, contact_name: contact.contact_name, phone: contact.phone || '', email: contact.email || '', position_or_role: contact.position_or_role || '', relationship_role_id: contact.relationship_role_id || '', notes: contact.notes || '' }); setShowContactForm(true); }} className="rounded-lg border border-gray-300 px-3 py-2 text-xs font-medium text-gray-700 hover:bg-gray-50">Edit</button>
                          )}
                        </div>
                      </div>
                    )) : (
                      <div className="rounded-xl bg-gray-50 px-4 py-6 text-sm text-gray-500">No additional contacts yet.</div>
                    )}
                  </div>
                </section>
              )}

              {activeProfileTab === 'trips' && profileDisplayCustomer && (
                <div className="grid grid-cols-1 gap-6 2xl:grid-cols-[1.2fr_1fr]">
                  <section className="rounded-2xl border border-gray-200 bg-white">
                    <div className="flex items-center justify-between border-b border-gray-200 px-5 py-4">
                      <h3 className="text-lg font-semibold text-[#0F172A]">Trips / Bookings</h3>
                      <div className="flex gap-2">
                        <button type="button" onClick={openCreateBooking} className="rounded-lg bg-[#2563EB] px-3 py-2 text-xs font-medium text-white hover:bg-[#1d4ed8]">Add Booking</button>
                        <button type="button" onClick={openCreateFollowUpBooking} className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-700 hover:bg-amber-100">Add Follow-Up</button>
                      </div>
                    </div>
                    <div className="space-y-4 p-5">
                      {selectedCustomerUpcomingBookings.length ? selectedCustomerUpcomingBookings.map((booking) => (
                        <div key={booking.id} className="rounded-xl border border-gray-200 p-4">
                          <div className="text-sm font-semibold text-[#0F172A]">{booking.title || booking.booking_type}</div>
                          <div className="mt-1 text-xs text-gray-500">{formatDateTime(booking.pickup_at)} • {booking.pickup_location} to {booking.destination}</div>
                        </div>
                      )) : <div className="rounded-xl bg-gray-50 px-4 py-6 text-sm text-gray-500">No upcoming bookings for this customer yet.</div>}
                      {selectedCustomerRideHistory.length ? selectedCustomerRideHistory.map((ride) => (
                        <div key={ride.id} className="rounded-xl border border-gray-200 p-4">
                          <div className="flex items-center justify-between gap-3">
                            <div>
                              <div className="text-sm font-semibold text-[#0F172A]">{ride.pickup_location} to {ride.destination}</div>
                              <div className="mt-1 text-xs text-gray-500">{formatDateTime(ride.end_time || ride.start_time || ride.scheduled_time)}</div>
                            </div>
                            <BookingStatusBadge status={ride.status} />
                          </div>
                        </div>
                      )) : <div className="rounded-xl bg-gray-50 px-4 py-6 text-sm text-gray-500">No completed ride history has been recorded yet.</div>}
                    </div>
                  </section>
                  <section className="space-y-6">
                    <div className="rounded-2xl border border-gray-200 bg-white p-5">
                      <h3 className="text-lg font-semibold text-[#0F172A]">Recurring Schedule</h3>
                      <div className="mt-4 space-y-3">
                        {selectedCustomerRecurringSchedule.length ? selectedCustomerRecurringSchedule.map((booking) => (
                          <div key={booking.id} className="rounded-xl bg-blue-50 p-4">
                            <div className="text-sm font-semibold text-[#0F172A]">{booking.booking_type}</div>
                            <div className="mt-1 text-xs text-gray-600">{booking.recurrence_type} every {booking.recurrence_frequency}</div>
                          </div>
                        )) : <div className="rounded-xl bg-gray-50 px-4 py-6 text-sm text-gray-500">No recurring pickup schedule for this customer yet.</div>}
                      </div>
                    </div>
                    <div className="rounded-2xl border border-gray-200 bg-white p-5">
                      <h3 className="text-lg font-semibold text-[#0F172A]">Follow-Up</h3>
                      <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
                        {[
                          ['Current Follow-Up', profileDisplayCustomer.active_follow_up_date ? formatDate(profileDisplayCustomer.active_follow_up_date) : 'Not scheduled'],
                          ['Priority', profileDisplayCustomer.follow_up_priority || 'Not set'],
                          ['Status', profileDisplayCustomer.follow_up_status_label || 'No follow-up scheduled'],
                          ['Next Planned Follow-Up', profileDisplayCustomer.next_follow_up_date ? formatDate(profileDisplayCustomer.next_follow_up_date) : 'Not set'],
                        ].map(([label, value]) => (
                          <div key={label} className="rounded-xl bg-gray-50 p-4">
                            <div className="text-xs font-medium uppercase tracking-wide text-gray-500">{label}</div>
                            <div className="mt-2 text-sm text-[#0F172A]">{value}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                  </section>
                </div>
              )}

              {activeProfileTab === 'notes' && profileDisplayCustomer && (
                <div className="grid grid-cols-1 gap-6 2xl:grid-cols-[0.9fr_1.1fr]">
                  <section className="rounded-2xl border border-gray-200 bg-white p-5">
                    <div className="flex items-center justify-between">
                      <h3 className="text-lg font-semibold text-[#0F172A]">Notes</h3>
                    </div>
                    <textarea value={newNote} onChange={(event) => setNewNote(event.target.value)} rows={4} placeholder="Add a note for this customer" className="mt-4 w-full rounded-xl border border-gray-300 px-4 py-3 text-sm" />
                    <div className="mt-3 flex justify-end">
                      <button type="button" onClick={() => void handleAddNote()} disabled={isSavingNote || !newNote.trim()} className="rounded-lg bg-[#2563EB] px-4 py-2 text-sm font-medium text-white hover:bg-[#1d4ed8] disabled:opacity-60">{isSavingNote ? 'Saving...' : 'Add Note'}</button>
                    </div>
                    <div className="mt-4 space-y-3">
                      {isLoadingNotes ? <div className="rounded-xl bg-gray-50 px-4 py-6 text-sm text-gray-500">Loading notes...</div> : customerNotes.length ? customerNotes.map((note) => (
                        <div key={note.id} className="rounded-xl border border-gray-200 p-4">
                          <div className="text-xs text-gray-500">{note.created_by_name || 'Unknown'} • {formatDateTime(note.created_at)}</div>
                          <div className="mt-2 text-sm text-[#0F172A]">{note.note}</div>
                        </div>
                      )) : <div className="rounded-xl bg-gray-50 px-4 py-6 text-sm text-gray-500">No notes yet.</div>}
                    </div>
                  </section>
                  <section className="rounded-2xl border border-gray-200 bg-white p-5">
                    <h3 className="text-lg font-semibold text-[#0F172A]">Timeline</h3>
                    <div className="mt-4 space-y-3">
                      {isLoadingNotes ? <div className="rounded-xl bg-gray-50 px-4 py-6 text-sm text-gray-500">Loading timeline...</div> : customerTimeline.length ? customerTimeline.map((entry) => (
                        <div key={entry.id} className="rounded-xl border border-gray-200 p-4">
                          <div className="text-xs font-medium uppercase tracking-wide text-gray-500">{entry.type === 'note' ? 'Note' : entry.action || 'Activity'}</div>
                          <div className="mt-1 text-xs text-gray-500">{formatDateTime(entry.at)}{entry.author ? ` • ${entry.author}` : ''}</div>
                          <div className="mt-2 text-sm text-[#0F172A]">{entry.text || 'Activity logged.'}</div>
                        </div>
                      )) : <div className="rounded-xl bg-gray-50 px-4 py-6 text-sm text-gray-500">No timeline activity yet.</div>}
                    </div>
                  </section>
                </div>
              )}
            </>
          ) : (
            <div className="rounded-2xl border border-dashed border-gray-300 bg-white px-6 py-16 text-center text-gray-500">
              Select a customer to see their CRM profile, ride history, and upcoming bookings.
            </div>
          )}

          <section className="rounded-2xl border border-gray-200 bg-white">
            <div className="border-b border-gray-200 px-5 py-4">
              <h3 className="text-lg font-semibold text-[#0F172A]">Fleet Booking Queue</h3>
            </div>
            <div className="grid grid-cols-1 gap-3 border-b border-gray-200 px-5 py-4 sm:grid-cols-2 xl:grid-cols-5">
              {[
                { label: 'Scheduled Today', value: isBookingDataLoading ? '...' : summary?.scheduled_today ?? upcomingBookings.length },
                { label: 'Pending Acknowledgement', value: isBookingDataLoading ? '...' : summary?.pending_acknowledgement ?? 0 },
                { label: 'In Progress Bookings', value: isBookingDataLoading ? '...' : summary?.in_progress_bookings ?? 0 },
                { label: 'Completed Today', value: isBookingDataLoading ? '...' : summary?.completed_today ?? 0 },
                { label: 'Missed Bookings', value: isBookingDataLoading ? '...' : summary?.missed_bookings ?? 0 },
              ].map((card) => (
                <div key={card.label} className="rounded-xl bg-gray-50 px-4 py-3">
                  <div className="text-xs font-medium uppercase tracking-wide text-gray-500">{card.label}</div>
                  <div className="mt-1 text-2xl font-semibold text-[#0F172A]">{card.value}</div>
                </div>
              ))}
            </div>
            <div className="flex flex-wrap gap-2 px-5 py-4">
              {bookingQueueFilters.map((filter) => (
                <button
                  key={filter}
                  type="button"
                  onClick={() => setBookingQueueFilter(filter)}
                  className={`rounded-full border px-3 py-1.5 text-xs font-medium transition ${
                    bookingQueueFilter === filter
                      ? 'border-[#2563EB] bg-[#2563EB] text-white'
                      : 'border-gray-200 bg-white text-gray-600 hover:bg-gray-50'
                  }`}
                >
                  {filter}
                </button>
              ))}
            </div>
            <div className="grid grid-cols-1 gap-4 p-5 xl:grid-cols-2">
              <div className="space-y-3">
                <div className="text-sm font-medium text-gray-500">{bookingQueueFilter} Bookings</div>
                {isBookingDataLoading ? (
                  <div className="rounded-xl bg-gray-50 px-4 py-6 text-sm text-gray-500">
                    Loading fleet booking queue...
                  </div>
                ) : bookingLoadError ? (
                  <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-6 text-sm text-amber-800">
                    {bookingLoadError}
                  </div>
                ) : filteredBookingQueue.slice(0, 8).map((booking) => (
                  <div key={booking.id} className="rounded-xl border border-gray-200 p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="text-sm font-semibold text-[#0F172A]">
                          {booking.customer?.full_name || 'Customer'} - {booking.pickup_time}
                        </div>
                        <div className="mt-1 text-xs text-gray-500">
                          {booking.pickup_date} - {booking.pickup_location} to {booking.destination}
                        </div>
                        {booking.customer?.phone_number ? (
                          <div className="mt-2 text-xs text-gray-500">Phone: {booking.customer.phone_number}</div>
                        ) : null}
                        {booking.issue_type ? (
                          <div className="mt-2 text-xs text-amber-700">
                            Issue: {booking.issue_type}
                            {booking.issue_note ? ` - ${booking.issue_note}` : ''}
                          </div>
                        ) : null}
                        {booking.completion_note ? (
                          <div className="mt-2 text-xs text-emerald-700">Completion note: {booking.completion_note}</div>
                        ) : null}
                      </div>
                      <BookingStatusBadge status={booking.status} />
                    </div>
                  </div>
                ))}
                {!isBookingDataLoading && !bookingLoadError && !filteredBookingQueue.length && (
                  <div className="rounded-xl bg-gray-50 px-4 py-6 text-sm text-gray-500">
                    No bookings match this filter right now.
                  </div>
                )}
              </div>

              <div className="space-y-3">
                <div className="text-sm font-medium text-gray-500">Recurring Templates</div>
                {!isBookingDataLoading && recurringTemplates.slice(0, 8).map((booking) => (
                  <div key={booking.id} className="rounded-xl border border-gray-200 p-4">
                    <div className="text-sm font-semibold text-[#0F172A]">
                      {booking.customer?.full_name || 'Customer'} - {booking.recurrence_type}
                    </div>
                    <div className="mt-1 text-xs text-gray-500">
                      Every {booking.recurrence_frequency} - {booking.recurrence_days?.join(', ') || booking.monthly_day_of_week || 'Pattern saved'}
                    </div>
                    <div className="mt-2 text-xs text-gray-500">
                      {booking.pickup_time} - {booking.pickup_location} to {booking.destination}
                    </div>
                  </div>
                ))}
                {isBookingDataLoading ? (
                  <div className="rounded-xl bg-gray-50 px-4 py-6 text-sm text-gray-500">
                    Loading recurring templates...
                  </div>
                ) : !recurringTemplates.length && (
                  <div className="rounded-xl bg-gray-50 px-4 py-6 text-sm text-gray-500">
                    No recurring booking templates have been created yet.
                  </div>
                )}
              </div>
            </div>
          </section>
        </div>
      </div>

      {showCustomerModal && (
        <Modal
          title={editingCustomer ? 'Update Customer Profile' : 'Create Customer'}
          subtitle="Capture the rider details, relationship context, and CRM fields that matter over time."
          onClose={closeCustomerModal}
        >
          {customerFormError && (
            <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <span>{customerFormError}</span>
                {duplicateCustomer && (
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => {
                        setSelectedCustomerId(duplicateCustomer.id);
                        closeCustomerModal();
                      }}
                      className="rounded-lg border border-red-200 bg-white px-3 py-2 text-xs font-medium text-red-700 hover:bg-red-100"
                    >
                      View Existing
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setSelectedCustomerId(duplicateCustomer.id);
                        void openEditCustomer(duplicateCustomer);
                      }}
                      className="rounded-lg bg-red-700 px-3 py-2 text-xs font-medium text-white hover:bg-red-800"
                    >
                      Update Existing
                    </button>
                  </div>
                )}
              </div>
            </div>
          )}
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Customer Name</span>
              <input
                value={customerForm.full_name}
                onChange={(event) => updateCustomerField('full_name', event.target.value)}
                className={getCustomerFieldClass(Boolean(customerFieldErrors.full_name))}
              />
              {customerFieldErrors.full_name && <p className="text-xs text-red-600">{customerFieldErrors.full_name}</p>}
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Phone Number</span>
              <input
                value={customerForm.phone_number}
                onChange={(event) => updateCustomerField('phone_number', event.target.value)}
                className={getCustomerFieldClass(Boolean(customerFieldErrors.phone_number))}
              />
              {customerFieldErrors.phone_number && <p className="text-xs text-red-600">{customerFieldErrors.phone_number}</p>}
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Location / Area</span>
              <input
                value={customerForm.residential_area}
                onChange={(event) => updateCustomerField('residential_area', event.target.value)}
                className={getCustomerFieldClass(Boolean(customerFieldErrors.residential_area))}
              />
              {customerFieldErrors.residential_area && <p className="text-xs text-red-600">{customerFieldErrors.residential_area}</p>}
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Customer Type</span>
              <SearchableSelect
                value={customerForm.customer_category_id}
                onChange={(value) => updateCustomerField('customer_category_id', value)}
                options={customerCategorySelectOptions}
                placeholder="Select customer type"
                searchPlaceholder="Search customer types..."
                emptyLabel="No customer types found."
                triggerClassName={getCustomerFieldClass(Boolean(customerFieldErrors.customer_category_id))}
              />
              {customerFieldErrors.customer_category_id && <p className="text-xs text-red-600">{customerFieldErrors.customer_category_id}</p>}
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Organization / Business Name</span>
              <input
                value={customerForm.organization_name}
                onChange={(event) => updateCustomerField('organization_name', event.target.value)}
                className={getCustomerFieldClass(Boolean(customerFieldErrors.organization_name))}
              />
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Email</span>
              <input
                type="email"
                value={customerForm.email_address}
                onChange={(event) => updateCustomerField('email_address', event.target.value)}
                className={getCustomerFieldClass(Boolean(customerFieldErrors.email_address))}
              />
              {customerFieldErrors.email_address && <p className="text-xs text-red-600">{customerFieldErrors.email_address}</p>}
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Alternative Phone</span>
              <input
                value={customerForm.alternate_phone}
                onChange={(event) => updateCustomerField('alternate_phone', event.target.value)}
                className={getCustomerFieldClass(Boolean(customerFieldErrors.alternate_phone))}
              />
              {customerFieldErrors.alternate_phone && <p className="text-xs text-red-600">{customerFieldErrors.alternate_phone}</p>}
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Occupation</span>
              <SearchableSelect
                value={customerForm.occupation}
                onChange={(value) => updateCustomerField('occupation', value)}
                options={buildStringValueOptions(occupationFieldOptions, customerForm.occupation)}
                placeholder="Select occupation"
                searchPlaceholder="Search occupations..."
                emptyLabel={occupationEmptyLabel}
                allowClear
                clearLabel="No occupation"
                triggerClassName={getCustomerFieldClass(Boolean(customerFieldErrors.occupation))}
              />
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Source</span>
              <SearchableSelect
                value={customerForm.source}
                onChange={(value) => updateCustomerField('source', value)}
                options={sourceSelectOptions}
                placeholder="Select source"
                searchPlaceholder="Search sources..."
                emptyLabel="No sources found."
                allowClear
                clearLabel="No source"
                triggerClassName={getCustomerFieldClass(Boolean(customerFieldErrors.source))}
              />
              {customerFieldErrors.source && <p className="text-xs text-red-600">{customerFieldErrors.source}</p>}
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Customer Source</span>
              <SearchableSelect
                value={customerForm.customer_source_id}
                onChange={(value) => updateCustomerField('customer_source_id', value)}
                options={customerSourceSelectOptions}
                placeholder="Select customer source"
                searchPlaceholder="Search customer sources..."
                emptyLabel="No customer sources found."
                allowClear
                clearLabel="No customer source"
                triggerClassName={getCustomerFieldClass(Boolean(customerFieldErrors.customer_source_id))}
              />
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Position / Title</span>
              <SearchableSelect
                value={customerForm.position_title}
                onChange={(value) => updateCustomerField('position_title', value)}
                options={buildStringValueOptions(positionTitleFieldOptions, customerForm.position_title)}
                placeholder="Select position or title"
                searchPlaceholder="Search positions or titles..."
                emptyLabel={positionTitleEmptyLabel}
                allowClear
                clearLabel="No position"
                triggerClassName={getCustomerFieldClass(Boolean(customerFieldErrors.position_title))}
              />
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Organization Type</span>
              <SearchableSelect
                value={customerForm.organization_type_id}
                onChange={(value) => updateCustomerField('organization_type_id', value)}
                options={organizationTypeSelectOptions}
                placeholder="Select organization type"
                searchPlaceholder="Search organization types..."
                emptyLabel="No organization types found."
                allowClear
                clearLabel="No organization type"
                triggerClassName={getCustomerFieldClass(Boolean(customerFieldErrors.organization_type_id))}
              />
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Industry</span>
              <SearchableSelect
                value={customerForm.industry_id}
                onChange={(value) => updateCustomerField('industry_id', value)}
                options={industrySelectOptions}
                placeholder="Select industry"
                searchPlaceholder="Search industries..."
                emptyLabel="No industries found."
                allowClear
                clearLabel="No industry"
                triggerClassName={getCustomerFieldClass(Boolean(customerFieldErrors.industry_id))}
              />
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Relationship Category</span>
              <SearchableSelect
                value={customerForm.relationship_category_id}
                onChange={(value) => updateCustomerField('relationship_category_id', value)}
                options={relationshipCategorySelectOptions}
                placeholder="Select relationship category"
                searchPlaceholder="Search relationship categories..."
                emptyLabel="No relationship categories found."
                allowClear
                clearLabel="No relationship category"
                triggerClassName={getCustomerFieldClass(Boolean(customerFieldErrors.relationship_category_id))}
              />
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Opportunity Level</span>
              <SearchableSelect
                value={customerForm.opportunity_level_id}
                onChange={(value) => updateCustomerField('opportunity_level_id', value)}
                options={opportunityLevelSelectOptions}
                placeholder="Select opportunity level"
                searchPlaceholder="Search opportunity levels..."
                emptyLabel="No opportunity levels found."
                allowClear
                clearLabel="No opportunity level"
                triggerClassName={getCustomerFieldClass(Boolean(customerFieldErrors.opportunity_level_id))}
              />
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Network Value</span>
              <SearchableSelect
                value={customerForm.network_value_id}
                onChange={(value) => updateCustomerField('network_value_id', value)}
                options={networkValueSelectOptions}
                placeholder="Select network value"
                searchPlaceholder="Search network values..."
                emptyLabel="No network values found."
                allowClear
                clearLabel="No network value"
                triggerClassName={getCustomerFieldClass(Boolean(customerFieldErrors.network_value_id))}
              />
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Lead Status</span>
              <SearchableSelect
                value={customerForm.lead_status_id}
                onChange={(value) => updateCustomerField('lead_status_id', value)}
                options={leadStatusSelectOptions}
                placeholder="Select lead status"
                searchPlaceholder="Search lead statuses..."
                emptyLabel="No lead statuses found."
                allowClear
                clearLabel="No lead status"
                triggerClassName={getCustomerFieldClass(Boolean(customerFieldErrors.lead_status_id))}
              />
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Potential Service</span>
              <SearchableSelect
                value={customerForm.potential_service_id}
                onChange={(value) => updateCustomerField('potential_service_id', value)}
                options={potentialServiceSelectOptions}
                placeholder="Select potential service"
                searchPlaceholder="Search potential services..."
                emptyLabel="No potential services found."
                allowClear
                clearLabel="No potential service"
                triggerClassName={getCustomerFieldClass(Boolean(customerFieldErrors.potential_service_id))}
              />
            </label>

            {editingCustomer && (
              <>
                <label className="space-y-2">
                  <span className="text-sm font-medium text-[#0F172A]">Preferred Driver</span>
                  <SearchableSelect
                    value={customerForm.preferred_driver_id}
                    onChange={(value) => updateCustomerField('preferred_driver_id', value)}
                    options={(customerOptions?.drivers || []).map((driver) => ({ value: driver.id, label: driver.full_name }))}
                    placeholder="Select driver"
                    searchPlaceholder="Search drivers..."
                    emptyLabel="No drivers found."
                    allowClear
                    clearLabel="No preferred driver"
                    triggerClassName={getCustomerFieldClass(Boolean(customerFieldErrors.preferred_driver_id))}
                  />
                </label>

                <label className="space-y-2">
                  <span className="text-sm font-medium text-[#0F172A]">Status</span>
                  <SearchableSelect
                    value={customerForm.status}
                    onChange={(value) => updateCustomerField('status', value)}
                    options={(customerOptions?.statuses || ['active', 'inactive']).map((status) => ({ value: status, label: status }))}
                    placeholder="Select status"
                    searchPlaceholder="Search statuses..."
                    emptyLabel="No statuses found."
                    triggerClassName={getCustomerFieldClass(Boolean(customerFieldErrors.status))}
                  />
                </label>
              </>
            )}
          </div>

          <div className="mt-4 grid grid-cols-1 gap-4">
            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Notes</span>
              <textarea
                rows={3}
                value={customerForm.notes}
                onChange={(event) => updateCustomerField('notes', event.target.value)}
                className={getCustomerFieldClass(Boolean(customerFieldErrors.notes), { multiline: true })}
              />
            </label>
          </div>

          {editingCustomer && (
            <div className="mt-8 space-y-6 border-t border-gray-200 pt-6">
              <div className="flex flex-wrap gap-2 rounded-2xl border border-gray-200 bg-gray-50 p-3">
                {[
                  ['overview', 'Overview'],
                  ['relationship', 'Relationship Details'],
                  ['opportunities', 'Opportunities'],
                  ['contacts', 'Additional Contacts'],
                  ['trips', 'Trips / Bookings'],
                  ['notes', 'Notes / Timeline'],
                ].map(([id, label]) => (
                  <button
                    key={id}
                    type="button"
                    onClick={() => {
                      closeCustomerModal();
                      setActiveProfileTab(id as CustomerProfileTab);
                    }}
                    className={`rounded-xl px-4 py-2 text-sm font-medium ${
                      activeProfileTab === id ? 'bg-[#2563EB] text-white' : 'bg-white text-gray-700 hover:bg-gray-100'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>

              <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
                <section className="rounded-2xl border border-gray-200 bg-white p-5">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <h3 className="text-lg font-semibold text-[#0F172A]">Opportunities</h3>
                      <p className="mt-1 text-sm text-gray-500">Add and manage opportunities for this customer directly from the profile.</p>
                    </div>
                      <button
                        type="button"
                        onClick={() => {
                          setOpportunityForm(buildOpportunityFormDefaults());
                          setShowOpportunityForm((current) => !current);
                        }}
                        className="rounded-lg bg-[#2563EB] px-4 py-2 text-sm font-medium text-white hover:bg-[#1d4ed8]"
                    >
                      Add Opportunity
                    </button>
                  </div>
                  {showOpportunityForm && (
                    <div className="mt-4 grid grid-cols-1 gap-4 rounded-xl border border-gray-200 p-4 md:grid-cols-2">
                      <SearchableSelect value={opportunityForm.opportunity_type_id} onChange={(value) => setOpportunityForm((current) => ({ ...current, opportunity_type_id: value }))} options={opportunityTypeSelectOptions} placeholder="Opportunity Type" searchPlaceholder="Search opportunity types..." emptyLabel={opportunityTypeEmptyLabel} />
                      <SearchableSelect value={opportunityForm.opportunity_stage_id} onChange={(value) => setOpportunityForm((current) => ({ ...current, opportunity_stage_id: value }))} options={opportunityStageSelectOptions} placeholder="Opportunity Stage" searchPlaceholder="Search opportunity stages..." emptyLabel="No opportunity stages found. Add stages in Master Data." allowClear clearLabel="No stage" />
                      <input value={opportunityForm.specific_product_or_service} onChange={(event) => setOpportunityForm((current) => ({ ...current, specific_product_or_service: event.target.value }))} placeholder="Specific Product / Service" className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm" />
                      <input type="number" min="0" value={opportunityForm.estimated_budget} onChange={(event) => setOpportunityForm((current) => ({ ...current, estimated_budget: event.target.value }))} placeholder="Estimated Budget" className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm" />
                      <input type="number" min="0" max="100" value={opportunityForm.probability} onChange={(event) => setOpportunityForm((current) => ({ ...current, probability: event.target.value }))} placeholder="Probability" className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm" />
                      <input value={opportunityForm.status} onChange={(event) => setOpportunityForm((current) => ({ ...current, status: event.target.value }))} placeholder="Status" className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm" />
                      <input type="date" value={opportunityForm.expected_purchase_date} onChange={(event) => setOpportunityForm((current) => ({ ...current, expected_purchase_date: event.target.value }))} className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm" />
                      <input type="date" value={opportunityForm.follow_up_date} onChange={(event) => setOpportunityForm((current) => ({ ...current, follow_up_date: event.target.value }))} className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm" />
                      <textarea value={opportunityForm.notes} onChange={(event) => setOpportunityForm((current) => ({ ...current, notes: event.target.value }))} rows={3} placeholder="Notes" className="md:col-span-2 w-full rounded-xl border border-gray-300 px-4 py-3 text-sm" />
                      <div className="md:col-span-2 flex justify-end gap-2">
                        <button type="button" onClick={() => { setShowOpportunityForm(false); setOpportunityForm(buildOpportunityFormDefaults()); }} className="rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50">Cancel</button>
                        <button type="button" onClick={() => void handleSaveOpportunity()} disabled={isSavingOpportunity} className="rounded-lg bg-[#2563EB] px-3 py-2 text-sm text-white hover:bg-[#1d4ed8] disabled:opacity-60">{isSavingOpportunity ? 'Saving...' : opportunityForm.id ? 'Update Opportunity' : 'Save Opportunity'}</button>
                      </div>
                    </div>
                  )}
                  <div className="mt-4 space-y-3">
                    {isLoadingOpportunities ? (
                      <div className="rounded-xl bg-gray-50 px-4 py-6 text-sm text-gray-500">Loading opportunities...</div>
                    ) : opportunitiesLoadError ? (
                      <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-6 text-sm text-amber-800">{opportunitiesLoadError}</div>
                    ) : opportunities.length ? opportunities.map((opportunity) => (
                      <div key={opportunity.id} className="rounded-xl border border-gray-200 p-4">
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <div className="text-sm font-semibold text-[#0F172A]">{opportunity.opportunity_type || 'Opportunity'}</div>
                            <div className="mt-1 text-xs text-gray-500">{opportunity.specific_product_or_service || 'No product/service specified'}</div>
                            <div className="mt-2 text-xs text-gray-500">{opportunity.opportunity_stage || 'No stage'}{opportunity.estimated_budget ? ` • ${formatCurrency(opportunity.estimated_budget)}` : ''}</div>
                          </div>
                          <button type="button" onClick={() => { setOpportunityForm({ id: opportunity.id, opportunity_type_id: opportunity.opportunity_type_id || '', specific_product_or_service: opportunity.specific_product_or_service || '', estimated_budget: opportunity.estimated_budget ? String(opportunity.estimated_budget) : '', opportunity_stage_id: opportunity.opportunity_stage_id || '', probability: opportunity.probability ? String(opportunity.probability) : '', expected_purchase_date: opportunity.expected_purchase_date || '', follow_up_date: opportunity.follow_up_date || '', notes: opportunity.notes || '', status: opportunity.status || 'open' }); setShowOpportunityForm(true); }} className="rounded-lg border border-gray-300 px-3 py-2 text-xs font-medium text-gray-700 hover:bg-gray-50">Edit</button>
                        </div>
                      </div>
                    )) : (
                      <div className="rounded-xl bg-gray-50 px-4 py-6 text-sm text-gray-500">No opportunities yet.</div>
                    )}
                  </div>
                </section>

                <section className="rounded-2xl border border-gray-200 bg-white p-5">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <h3 className="text-lg font-semibold text-[#0F172A]">Additional Contacts</h3>
                      <p className="mt-1 text-sm text-gray-500">This is separate from the customer&apos;s alternative phone number.</p>
                    </div>
                    <button
                      type="button"
                      onClick={() => {
                        setContactForm(emptyContactForm);
                        setShowContactForm((current) => !current);
                      }}
                      className="rounded-lg bg-[#2563EB] px-4 py-2 text-sm font-medium text-white hover:bg-[#1d4ed8]"
                    >
                      Add Contact
                    </button>
                  </div>
                  {showContactForm && (
                    <div className="mt-4 grid grid-cols-1 gap-4 rounded-xl border border-gray-200 p-4 md:grid-cols-2">
                      <input value={contactForm.contact_name} onChange={(event) => setContactForm((current) => ({ ...current, contact_name: event.target.value }))} placeholder="Contact Name" className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm" />
                      <SearchableSelect value={contactForm.position_or_role} onChange={(value) => setContactForm((current) => ({ ...current, position_or_role: value }))} options={buildStringValueOptions(positionTitleFieldOptions, contactForm.position_or_role)} placeholder="Position / Role" searchPlaceholder="Search positions or roles..." emptyLabel={positionTitleEmptyLabel} allowClear clearLabel="No position" />
                      <input value={contactForm.phone} onChange={(event) => setContactForm((current) => ({ ...current, phone: event.target.value }))} placeholder="Phone" className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm" />
                      <input type="email" value={contactForm.email} onChange={(event) => setContactForm((current) => ({ ...current, email: event.target.value }))} placeholder="Email" className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm" />
                      <SearchableSelect value={contactForm.relationship_role_id} onChange={(value) => setContactForm((current) => ({ ...current, relationship_role_id: value }))} options={relationshipRoleSelectOptions} placeholder="Relationship Role" searchPlaceholder="Search relationship roles..." emptyLabel="No relationship roles found." allowClear clearLabel="No relationship role" />
                      <textarea value={contactForm.notes} onChange={(event) => setContactForm((current) => ({ ...current, notes: event.target.value }))} rows={3} placeholder="Notes" className="w-full rounded-xl border border-gray-300 px-4 py-3 text-sm" />
                      <div className="md:col-span-2 flex justify-end gap-2">
                        <button type="button" onClick={() => { setShowContactForm(false); setContactForm(emptyContactForm); }} className="rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50">Cancel</button>
                        <button type="button" onClick={() => void handleSaveContact()} disabled={isSavingContact} className="rounded-lg bg-[#2563EB] px-3 py-2 text-sm text-white hover:bg-[#1d4ed8] disabled:opacity-60">{isSavingContact ? 'Saving...' : contactForm.id ? 'Update Contact' : 'Save Contact'}</button>
                      </div>
                    </div>
                  )}
                  <div className="mt-4 space-y-3">
                    {isLoadingContacts ? (
                      <div className="rounded-xl bg-gray-50 px-4 py-6 text-sm text-gray-500">Loading contacts...</div>
                    ) : contactsLoadError ? (
                      <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-6 text-sm text-amber-800">{contactsLoadError}</div>
                    ) : contacts.length ? contacts.map((contact) => (
                      <div key={contact.id} className="rounded-xl border border-gray-200 p-4">
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <div className="text-sm font-semibold text-[#0F172A]">{contact.contact_name}</div>
                            <div className="mt-1 text-xs text-gray-500">{contact.position_or_role || 'No position'}{contact.relationship_role ? ` • ${contact.relationship_role}` : ''}</div>
                            <div className="mt-1 text-xs text-gray-500">{contact.phone || 'No phone'}{contact.email ? ` • ${contact.email}` : ''}</div>
                          </div>
                          <button type="button" onClick={() => { setContactForm({ id: contact.id, contact_name: contact.contact_name, phone: contact.phone || '', email: contact.email || '', position_or_role: contact.position_or_role || '', relationship_role_id: contact.relationship_role_id || '', notes: contact.notes || '' }); setShowContactForm(true); }} className="rounded-lg border border-gray-300 px-3 py-2 text-xs font-medium text-gray-700 hover:bg-gray-50">Edit</button>
                        </div>
                      </div>
                    )) : (
                      <div className="rounded-xl bg-gray-50 px-4 py-6 text-sm text-gray-500">No additional contacts yet.</div>
                    )}
                  </div>
                </section>
              </div>
            </div>
          )}

          <div className="sticky bottom-0 mt-6 flex justify-end border-t border-gray-200 bg-white pt-4">
            <button
              type="button"
              onClick={() => void handleSaveCustomer()}
              disabled={isSavingCustomer}
              className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-[#2563EB] px-4 py-2.5 text-sm font-medium text-white disabled:opacity-60 sm:w-auto"
            >
              {isSavingCustomer ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              {editingCustomer ? 'Save Customer' : 'Create Customer'}
            </button>
          </div>
        </Modal>
      )}

      {showBookingModal && (
        <Modal
          title={bookingTypeIsReminder ? 'Create Reminder' : 'Schedule Booking'}
          subtitle="Create bookings, recurring schedules, and reminder activities without leaving the CRM workflow."
          onClose={() => setShowBookingModal(false)}
        >
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Customer</span>
              <SearchableSelect
                value={bookingForm.customer_id}
                onChange={(value) => setBookingForm((current) => ({ ...current, customer_id: value }))}
                options={customers.map((customer) => ({
                  value: customer.id,
                  label: customer.full_name,
                  description: [customer.phone_number, customer.organization_name || customer.company_name || customer.residential_area].filter(Boolean).join(' • '),
                }))}
                placeholder="Select customer"
                searchPlaceholder="Search customers..."
                emptyLabel="No customers found."
                triggerClassName="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm"
              />
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Booking Type</span>
              <select
                value={bookingForm.booking_type}
                onChange={(event) => setBookingForm((current) => ({ ...current, booking_type: event.target.value }))}
                className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm"
              >
                {(bookingOptions?.booking_types || defaultBookingTypes).map((type) => (
                  <option key={type} value={type}>
                    {type}
                  </option>
                ))}
              </select>
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">{bookingTypeIsReminder ? 'Reminder Title' : 'Title'}</span>
              <input
                value={bookingForm.title}
                onChange={(event) => setBookingForm((current) => ({ ...current, title: event.target.value }))}
                placeholder={bookingTypeIsFollowUp ? 'Follow up with customer' : 'Optional title'}
                className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm"
              />
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Priority</span>
              <select
                value={bookingForm.priority}
                onChange={(event) => setBookingForm((current) => ({ ...current, priority: event.target.value }))}
                className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm"
              >
                {(bookingOptions?.priorities || defaultBookingPriorities).map((priority) => (
                  <option key={priority} value={priority}>
                    {priority}
                  </option>
                ))}
              </select>
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Driver</span>
              <SearchableSelect
                value={bookingForm.driver_id}
                onChange={(value) => setBookingForm((current) => ({ ...current, driver_id: value }))}
                options={(bookingOptions?.drivers || []).map((driver) => ({
                  value: driver.id,
                  label: driver.full_name,
                  description: driver.role,
                }))}
                placeholder="Assign later"
                searchPlaceholder="Search drivers..."
                emptyLabel="No drivers found."
                allowClear
                clearLabel="Assign later"
                triggerClassName="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm"
              />
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Vehicle</span>
              <SearchableSelect
                value={bookingForm.vehicle_id}
                onChange={(value) => setBookingForm((current) => ({ ...current, vehicle_id: value }))}
                options={(bookingOptions?.vehicles || []).map((vehicle) => ({
                  value: vehicle.id,
                  label: vehicle.registration_number,
                  description: [vehicle.make, vehicle.model, vehicle.vehicle_type].filter(Boolean).join(' • '),
                }))}
                placeholder="Assign later"
                searchPlaceholder="Search vehicles..."
                emptyLabel="No vehicles found."
                allowClear
                clearLabel="Assign later"
                triggerClassName="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm"
              />
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">{bookingTypeIsReminder ? 'Reminder Date' : 'Pickup Date'}</span>
              <input
                type="date"
                value={bookingTypeIsReminder ? bookingForm.reminder_date : bookingForm.pickup_date}
                onChange={(event) =>
                  setBookingForm((current) => ({
                    ...current,
                    pickup_date: event.target.value,
                    reminder_date: event.target.value,
                  }))
                }
                className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm"
              />
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">{bookingTypeIsReminder ? 'Reminder Time' : 'Pickup Time'}</span>
              <input
                type="time"
                value={bookingTypeIsReminder ? bookingForm.reminder_time : bookingForm.pickup_time}
                onChange={(event) =>
                  setBookingForm((current) => ({
                    ...current,
                    pickup_time: event.target.value,
                    reminder_time: event.target.value,
                  }))
                }
                className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm"
              />
            </label>

            {!bookingTypeIsReminder && (
              <>
                <label className="space-y-2">
                  <span className="text-sm font-medium text-[#0F172A]">Pickup Location</span>
                  <input
                    value={bookingForm.pickup_location}
                    onChange={(event) => setBookingForm((current) => ({ ...current, pickup_location: event.target.value }))}
                    className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm"
                  />
                </label>

                <label className="space-y-2">
                  <span className="text-sm font-medium text-[#0F172A]">Destination</span>
                  <input
                    value={bookingForm.destination}
                    onChange={(event) => setBookingForm((current) => ({ ...current, destination: event.target.value }))}
                    className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm"
                  />
                </label>
              </>
            )}

            {bookingTypeIsReminder && (
              <label className="space-y-2 md:col-span-2">
                <span className="text-sm font-medium text-[#0F172A]">Description</span>
                <textarea
                  rows={3}
                  value={bookingForm.description}
                  onChange={(event) => setBookingForm((current) => ({ ...current, description: event.target.value }))}
                  className="w-full rounded-xl border border-gray-300 px-4 py-3 text-sm"
                />
              </label>
            )}

            {!bookingTypeIsReminder && (
              <label className="space-y-2">
                <span className="text-sm font-medium text-[#0F172A]">Expected Fare</span>
                <input
                  type="number"
                  min="0"
                  value={bookingForm.expected_fare}
                  onChange={(event) => setBookingForm((current) => ({ ...current, expected_fare: event.target.value }))}
                  className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm"
                />
              </label>
            )}

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Status</span>
              <select
                value={bookingForm.status}
                onChange={(event) => setBookingForm((current) => ({ ...current, status: event.target.value }))}
                className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm"
              >
                {(bookingOptions?.statuses || defaultBookingStatuses).map((status) => (
                  <option key={status} value={status}>
                    {status}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="mt-4 rounded-2xl border border-gray-200 bg-gray-50 p-4">
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <label className="space-y-2">
                <span className="text-sm font-medium text-[#0F172A]">Recurrence Type</span>
                <select
                  value={bookingForm.recurrence_type}
                  onChange={(event) => setBookingForm((current) => ({ ...current, recurrence_type: event.target.value }))}
                  className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm"
                >
                  <option value="">One Time</option>
                  {(bookingOptions?.recurrence_types || defaultRecurrenceTypes).map((type) => (
                    type !== 'One Time' ? (
                    <option key={type} value={type}>
                      {type}
                    </option>
                    ) : null
                  ))}
                </select>
              </label>

              <label className="space-y-2">
                <span className="text-sm font-medium text-[#0F172A]">Frequency</span>
                <input
                  type="number"
                  min="1"
                  value={bookingForm.recurrence_frequency}
                  onChange={(event) => setBookingForm((current) => ({ ...current, recurrence_frequency: event.target.value }))}
                  className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm"
                />
              </label>

              <div className="space-y-2 md:col-span-2">
                <span className="text-sm font-medium text-[#0F172A]">Weekly / Custom Days</span>
                <div className="flex flex-wrap gap-2">
                  {weekdayOptions.map((day) => {
                    const isSelected = bookingForm.recurrence_days.includes(day);
                    return (
                      <button
                        key={day}
                        type="button"
                        onClick={() =>
                          setBookingForm((current) => ({
                            ...current,
                            recurrence_days: isSelected
                              ? current.recurrence_days.filter((value) => value !== day)
                              : [...current.recurrence_days, day],
                          }))
                        }
                        className={`rounded-full px-3 py-1.5 text-xs font-medium ${
                          isSelected ? 'bg-[#2563EB] text-white' : 'bg-white text-gray-700'
                        } border border-gray-300`}
                      >
                        {day}
                      </button>
                    );
                  })}
                </div>
              </div>

              <label className="space-y-2">
                <span className="text-sm font-medium text-[#0F172A]">Monthly Week</span>
                <input
                  type="number"
                  min="1"
                  max="5"
                  value={bookingForm.monthly_week_of_month}
                  onChange={(event) => setBookingForm((current) => ({ ...current, monthly_week_of_month: event.target.value }))}
                  className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm"
                />
              </label>

              <label className="space-y-2">
                <span className="text-sm font-medium text-[#0F172A]">Monthly Day</span>
                <select
                  value={bookingForm.monthly_day_of_week}
                  onChange={(event) => setBookingForm((current) => ({ ...current, monthly_day_of_week: event.target.value }))}
                  className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm"
                >
                  <option value="">Select weekday</option>
                  {weekdayOptions.map((day) => (
                    <option key={day} value={day}>
                      {day}
                    </option>
                  ))}
                </select>
              </label>

              <label className="space-y-2 md:col-span-2">
                <span className="text-sm font-medium text-[#0F172A]">Custom Rule Text</span>
                <input
                  value={bookingForm.custom_rule_text}
                  onChange={(event) => setBookingForm((current) => ({ ...current, custom_rule_text: event.target.value }))}
                  placeholder="Example: Every Sunday 7AM"
                  className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm"
                />
              </label>

              <label className="space-y-2">
                <span className="text-sm font-medium text-[#0F172A]">Recurrence End Date</span>
                <input
                  type="date"
                  value={bookingForm.recurrence_end_date}
                  onChange={(event) => setBookingForm((current) => ({ ...current, recurrence_end_date: event.target.value }))}
                  className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm"
                />
              </label>
            </div>
          </div>

          <label className="mt-4 block space-y-2">
            <span className="text-sm font-medium text-[#0F172A]">Notes</span>
            <textarea
              rows={3}
              value={bookingForm.notes}
              onChange={(event) => setBookingForm((current) => ({ ...current, notes: event.target.value }))}
              className="w-full rounded-xl border border-gray-300 px-4 py-3 text-sm"
            />
          </label>

          <div className="sticky bottom-0 mt-6 flex justify-end border-t border-gray-200 bg-white pt-4">
            <button
              type="button"
              onClick={() => void handleSaveBooking()}
              disabled={isSavingBooking}
              className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-[#2563EB] px-4 py-2.5 text-sm font-medium text-white disabled:opacity-60 sm:w-auto"
            >
              {isSavingBooking ? <Loader2 className="h-4 w-4 animate-spin" /> : <Calendar className="h-4 w-4" />}
              {bookingTypeIsReminder ? 'Save Reminder' : 'Schedule Booking'}
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}

export default function CustomerWorkspace(props: CustomerWorkspaceProps) {
  return (
    <CustomerWorkspaceErrorBoundary>
      <CustomerWorkspaceContent {...props} />
    </CustomerWorkspaceErrorBoundary>
  );
}
