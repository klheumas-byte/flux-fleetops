import { Component, useEffect, useMemo, useState, type ErrorInfo, type ReactNode } from 'react';
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
  fetchBookingOptions,
  fetchBookingSummary,
  fetchCustomerSummary,
  fetchBookings,
  fetchCustomerOptions,
  fetchCustomers,
  type BookingOptionsResponse,
  type BookingRecord,
  type BookingSummary,
  type CustomerOptionsResponse,
  type CustomerRecord,
  type CustomerSummary,
  updateBooking,
  updateCustomer,
} from '../../lib/customer-booking-api';
import { clearDriverQuickActionIntent, peekDriverQuickActionIntent } from '../../lib/driver-quick-actions';
import { useDebouncedValue } from '../../lib/use-debounced-value';
import { usePageToastFeedback } from '../../lib/use-page-toast-feedback';

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

const weekdayOptions = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

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
  source: 'manual_entry',
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
  const [bookingOptions, setBookingOptions] = useState<BookingOptionsResponse | null>(null);
  const [summary, setSummary] = useState<BookingSummary | null>(null);
  const [customerSummary, setCustomerSummary] = useState<CustomerSummary | null>(null);
  const [selectedCustomerId, setSelectedCustomerId] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const debouncedSearch = useDebouncedValue(search, 250);
  const [isLoading, setIsLoading] = useState(true);
  const [pageError, setPageError] = useState('');
  const [pageNotice, setPageNotice] = useState('');
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
  usePageToastFeedback(pageError, pageNotice);

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
    setPageError('');
    setPageNotice('');
    setDuplicateCustomer(null);
    try {
      const [customersResult, bookingsResult] = await Promise.allSettled([
        fetchCustomers(),
        fetchBookings(),
      ]);

      const customerData = customersResult.status === 'fulfilled' ? customersResult.value : [];
      const bookingData = bookingsResult.status === 'fulfilled' ? bookingsResult.value : [];

      setCustomers(customerData);
      setBookings(bookingData);
      setSelectedCustomerId((current) => {
        if (current && customerData.some((customer) => customer.id === current)) {
          return current;
        }
        return customerData[0]?.id || null;
      });

      const primaryLoadFailed = customersResult.status === 'rejected' && bookingsResult.status === 'rejected';
      if (primaryLoadFailed) {
        setPageError(getErrorMessage(customersResult.reason, 'Unable to load customer management right now.'));
      } else if (bookingsResult.status === 'rejected') {
        setPageNotice('Scheduled bookings are temporarily unavailable. Customer records are still shown.');
      }

      const secondaryResults = await Promise.allSettled([
        fetchCustomerOptions(),
        fetchBookingOptions(),
        fetchBookingSummary(),
        fetchCustomerSummary(),
      ]);
      const [customerOptionsResult, bookingOptionsResult, bookingSummaryResult, customerSummaryResult] = secondaryResults;

      setCustomerOptions(
        customerOptionsResult.status === 'fulfilled'
          ? customerOptionsResult.value
          : {
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
              follow_up_priorities: ['low', 'medium', 'high'],
              statuses: ['active', 'inactive'],
              source_options: [],
              creator_roles: [],
            },
      );
      setBookingOptions(
        bookingOptionsResult.status === 'fulfilled'
          ? bookingOptionsResult.value
          : {
              customers: [],
              drivers: [],
              vehicles: [],
              booking_types: [],
              statuses: [],
              recurrence_types: [],
              priorities: ['Low', 'Medium', 'High', 'Critical'],
            },
      );
      setSummary(
        bookingSummaryResult.status === 'fulfilled'
          ? bookingSummaryResult.value
          : {
              upcoming_bookings: 0,
              missed_bookings: 0,
              active_recurring_customers: 0,
              total_customers: 0,
              total_recurring_customers: 0,
              today_schedule: 0,
              upcoming_pickups: 0,
              recent_customers: 0,
              scheduled_today: 0,
              total_scheduled_bookings: 0,
              pending_acknowledgement: 0,
              in_progress_bookings: 0,
              completed_today: 0,
              overdue_reminders: 0,
              follow_ups_due_today: 0,
              upcoming_corporate_bookings: 0,
              total_future_bookings: 0,
              vip_bookings: 0,
              strategic_meetings: 0,
              driver_schedules: 0,
              follow_up_completion_rate: 0,
              bookings_by_status: {},
              customer_growth_trend: [],
            },
      );
      setCustomerSummary(
        customerSummaryResult.status === 'fulfilled'
          ? customerSummaryResult.value
          : {
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
            },
      );

      const unavailableSections: string[] = [];
      if (customerOptionsResult.status === 'rejected') unavailableSections.push('customer options');
      if (bookingOptionsResult.status === 'rejected') unavailableSections.push('booking options');
      if (bookingSummaryResult.status === 'rejected') unavailableSections.push('booking summary');
      if (customerSummaryResult.status === 'rejected') unavailableSections.push('CRM summary');
      if (unavailableSections.length > 0) {
        setPageNotice((current) =>
          current
            ? `${current} Some sections are temporarily unavailable: ${unavailableSections.join(', ')}.`
            : `Some sections are temporarily unavailable: ${unavailableSections.join(', ')}.`,
        );
      }
    } catch (error) {
      setPageError(getErrorMessage(error, 'Unable to load customer management right now.'));
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void loadWorkspace();
  }, []);

  useEffect(() => {
    const loadFilteredSummary = async () => {
      try {
        const nextSummary = await fetchCustomerSummary({
          date_from: filterDateFrom || undefined,
          date_to: filterDateTo || undefined,
          creator_role: filterCreatorRole || undefined,
          driver_id: filterDriverId || undefined,
          customer_category_id: filterCustomerCategoryId || undefined,
          source: filterSource || undefined,
        });
        setCustomerSummary(nextSummary);
      } catch {
        // Keep the existing summary visible if a filtered refresh fails.
      }
    };
    void loadFilteredSummary();
  }, [filterCustomerCategoryId, filterCreatorRole, filterDateFrom, filterDateTo, filterDriverId, filterSource]);

  const selectedCustomer = useMemo(
    () => customers.find((customer) => customer.id === selectedCustomerId) || null,
    [customers, selectedCustomerId],
  );
  const selectedCustomerUpcomingBookings = Array.isArray(selectedCustomer?.upcoming_bookings) ? selectedCustomer.upcoming_bookings : [];
  const selectedCustomerCompletedBookings = Array.isArray(selectedCustomer?.completed_bookings) ? selectedCustomer.completed_bookings : [];
  const selectedCustomerMissedBookings = Array.isArray(selectedCustomer?.missed_bookings) ? selectedCustomer.missed_bookings : [];
  const selectedCustomerRideHistory = Array.isArray(selectedCustomer?.ride_history) ? selectedCustomer.ride_history : [];
  const selectedCustomerRecurringSchedule = Array.isArray(selectedCustomer?.recurring_schedule) ? selectedCustomer.recurring_schedule : [];
  const selectedCustomerFollowUpHistory = Array.isArray(selectedCustomer?.follow_up_history) ? selectedCustomer.follow_up_history : [];

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
                value: summary?.scheduled_today || 0,
                icon: Calendar,
                tint: 'bg-blue-100 text-blue-700',
              },
              {
                label: 'Overdue Reminders',
                value: summary?.overdue_reminders || customerSummary?.follow_ups_overdue || 0,
                icon: Clock,
                tint: 'bg-rose-100 text-rose-700',
              },
              {
                label: 'Follow-Ups Due',
                value: summary?.follow_ups_due_today || customerSummary?.follow_ups_due_today || 0,
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
    [customers.length, customerSummary, portal, summary, upcomingBookings.length],
  );

  const openCreateCustomer = () => {
    clearCustomerFormErrors();
    setEditingCustomer(null);
    setCustomerForm({
      ...emptyCustomerForm,
      source: 'manual_entry',
      customer_category_id: customerOptions?.customer_category_items?.[0]?.id || '',
      follow_up_priority: customerOptions?.follow_up_priorities?.[1] || 'medium',
      lead_status_id: customerOptions?.lead_status_items?.[0]?.id || '',
    });
    setShowCustomerModal(true);
  };

  const openEditCustomer = (customer: CustomerRecord) => {
    clearCustomerFormErrors();
    setEditingCustomer(customer);
    setCustomerForm({
      full_name: customer.full_name || '',
      phone_number: customer.phone_number || '',
      alternate_phone: customer.alternate_phone || '',
      email_address: customer.email_address || '',
      date_of_birth: customer.date_of_birth || '',
      occupation: customer.occupation || '',
      organization_name: customer.organization_name || '',
      position_title: customer.position_title || '',
      pickup_location: customer.pickup_location || '',
      destination_location: customer.destination_location || '',
      preferred_pickup_location: customer.preferred_pickup_location || '',
      preferred_dropoff_location: customer.preferred_dropoff_location || '',
      residential_area: customer.residential_area || '',
      work_area: customer.work_area || '',
      source: customer.source || 'manual_entry',
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
      company_name: customer.company_name || '',
      status: customer.status || 'active',
    });
    setShowCustomerModal(true);
  };

  const openCreateBooking = () => {
    setBookingForm({
      ...emptyBookingForm,
      customer_id: selectedCustomer?.id || '',
      driver_id: selectedCustomer?.preferred_driver_id || '',
      pickup_location:
        selectedCustomer?.preferred_pickup_location || selectedCustomer?.pickup_location || '',
      destination:
        selectedCustomer?.preferred_dropoff_location || selectedCustomer?.destination_location || '',
      booking_type: bookingOptions?.booking_types?.[0] || 'Customer Booking',
      title: '',
      description: '',
      priority: bookingOptions?.priorities?.[1] || 'Medium',
      status: bookingOptions?.statuses?.[0] || 'Scheduled',
    });
    setShowBookingModal(true);
  };

  const openCreateReminder = () => {
    setBookingForm({
      ...emptyBookingForm,
      customer_id: selectedCustomer?.id || '',
      driver_id: portal === 'driver' ? bookingOptions?.drivers?.[0]?.id || '' : selectedCustomer?.preferred_driver_id || '',
      booking_type: 'Personal Reminder',
      title: '',
      description: '',
      priority: bookingOptions?.priorities?.[1] || 'Medium',
      status: 'Scheduled',
    });
    setShowBookingModal(true);
  };

  const openCreateFollowUpBooking = () => {
    setBookingForm({
      ...emptyBookingForm,
      customer_id: selectedCustomer?.id || '',
      driver_id: selectedCustomer?.preferred_driver_id || '',
      booking_type: 'Follow-Up Reminder',
      title: selectedCustomer ? `Follow up with ${selectedCustomer.full_name}` : '',
      description: '',
      priority: bookingOptions?.priorities?.[2] || 'High',
      status: 'Scheduled',
    });
    setShowBookingModal(true);
  };

  const handleSaveCustomer = async () => {
    setIsSavingCustomer(true);
    setPageError('');
    clearCustomerFormErrors();
    try {
      const payload: Record<string, unknown> = {
        ...customerForm,
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
      setSelectedCustomerId(savedCustomer.id);
      await loadWorkspace();
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
      await loadWorkspace();
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setPageError(error.message);
      } else {
        setPageError('Unable to complete that follow-up right now.');
      }
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
      openCreateBooking();
      return;
    }
    if (quickActionIntent === 'create_reminder') {
      clearDriverQuickActionIntent();
      openCreateReminder();
      return;
    }
    if (quickActionIntent === 'schedule_follow_up') {
      clearDriverQuickActionIntent();
      openCreateFollowUpBooking();
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
            onClick={openCreateCustomer}
            className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-gray-200 bg-white px-4 py-2.5 text-sm font-medium text-[#0F172A] hover:bg-gray-50 sm:w-auto"
          >
            <UserPlus className="h-4 w-4" />
            Add Customer
          </button>
          <button
            onClick={openCreateBooking}
            className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-[#2563EB] px-4 py-2.5 text-sm font-medium text-white hover:bg-[#1d4ed8] sm:w-auto"
          >
            <Plus className="h-4 w-4" />
            Schedule Booking
          </button>
          <button
            onClick={openCreateReminder}
            className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-purple-200 bg-purple-50 px-4 py-2.5 text-sm font-medium text-purple-700 hover:bg-purple-100 sm:w-auto"
          >
            <Clock className="h-4 w-4" />
            Create Reminder
          </button>
          <button
            onClick={openCreateFollowUpBooking}
            className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm font-medium text-amber-700 hover:bg-amber-100 sm:w-auto"
          >
            <Calendar className="h-4 w-4" />
            Schedule Follow-Up
          </button>
        </div>
      </div>

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
                  <div>{customer.total_rides || 0} rides</div>
                  <div className="mt-1">{customer.upcoming_bookings_count || 0} upcoming</div>
                  <div className="mt-1">{customer.completed_bookings_count || 0} completed</div>
                  <div className="mt-1">{customer.missed_bookings_count || 0} missed</div>
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
                      <h2 className="text-2xl font-semibold">{selectedCustomer.full_name}</h2>
                      <p className="mt-1 text-sm text-blue-100">
                        {selectedCustomer.occupation || 'Customer profile'}
                        {selectedCustomer.organization_name ? ` - ${selectedCustomer.organization_name}` : ''}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-2 text-sm text-blue-100">
                      <span className="inline-flex items-center gap-1 rounded-lg bg-white/10 px-3 py-1.5">
                        <Phone className="h-4 w-4" />
                        {selectedCustomer.phone_number}
                      </span>
                      <span className="inline-flex items-center gap-1 rounded-lg bg-white/10 px-3 py-1.5">
                        <MapPin className="h-4 w-4" />
                        {selectedCustomer.preferred_pickup_location || selectedCustomer.pickup_location || 'Pickup not set'}
                      </span>
                      <span className="inline-flex items-center gap-1 rounded-lg bg-white/10 px-3 py-1.5">
                        <Briefcase className="h-4 w-4" />
                        {selectedCustomer.customer_category}
                      </span>
                      {selectedCustomer.relationship_category && (
                        <span className="inline-flex items-center gap-1 rounded-lg bg-white/10 px-3 py-1.5">
                          <Star className="h-4 w-4" />
                          {selectedCustomer.relationship_category}
                        </span>
                      )}
                    </div>
                    <div className="mt-2 text-xs text-gray-500">
                      Created by {selectedCustomer?.created_by_name || 'Unknown / Legacy Record'}
                      {selectedCustomer?.created_by_role ? ` (${selectedCustomer.created_by_role})` : ''}
                    </div>
                  </div>
                  <button
                    onClick={() => openEditCustomer(selectedCustomer)}
                    className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-white/15 px-4 py-2.5 text-sm font-medium text-white hover:bg-white/25 sm:w-auto"
                  >
                    <Pencil className="h-4 w-4" />
                    Edit Profile
                  </button>
                </div>
              </div>

              <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-5">
                {[
                  { label: 'Total Rides', value: selectedCustomer.total_rides || 0 },
                  { label: 'Total Bookings', value: selectedCustomer.total_bookings || 0 },
                  { label: 'Upcoming', value: selectedCustomer.upcoming_bookings_count || 0 },
                  { label: 'Completed', value: selectedCustomer.completed_bookings_count || 0 },
                  { label: 'Missed', value: selectedCustomer.missed_bookings_count || 0 },
                  {
                    label: 'Follow-Up',
                    value: selectedCustomer.active_follow_up_date
                      ? formatDate(selectedCustomer.active_follow_up_date)
                      : 'Not scheduled',
                  },
                ].map((item) => (
                  <div key={item.label} className="rounded-2xl border border-gray-200 bg-white p-4">
                    <div className="text-xs font-medium uppercase tracking-wide text-gray-500">{item.label}</div>
                    <div className="mt-2 text-lg font-semibold text-[#0F172A]">{item.value}</div>
                  </div>
                ))}
              </div>

              <div className="grid grid-cols-1 gap-6 2xl:grid-cols-[1.3fr_1fr]">
                <div className="space-y-6">
                  <section className="rounded-2xl border border-gray-200 bg-white">
                    <div className="border-b border-gray-200 px-5 py-4">
                      <h3 className="text-lg font-semibold text-[#0F172A]">Customer Details</h3>
                    </div>
                    <div className="grid grid-cols-1 gap-4 p-5 md:grid-cols-2">
                      {[
                        ['Phone', selectedCustomer.phone_number],
                        ['Alternate Phone', selectedCustomer.alternate_phone || 'Not set'],
                        ['Occupation', selectedCustomer.occupation || 'Not set'],
                        ['Position', selectedCustomer.position_title || 'Not set'],
                        ['Organization', selectedCustomer.organization_name || selectedCustomer.company_name || 'Not set'],
                        ['Source', selectedCustomer.source_label || selectedCustomer.customer_source || 'Not set'],
                        ['Created By', selectedCustomer.created_by_name || 'Unknown / Legacy Record'],
                        ['Creator Role', selectedCustomer.created_by_role || 'legacy'],
                        ['Relationship Category', selectedCustomer.relationship_category || 'Not set'],
                        ['Opportunity Level', selectedCustomer.opportunity_level || 'Not set'],
                        ['Network Value', selectedCustomer.network_value || 'Not set'],
                        ['Lead Status', selectedCustomer.lead_status || 'Not set'],
                        ['Residential Area', selectedCustomer.residential_area || 'Not set'],
                        ['Work Area', selectedCustomer.work_area || 'Not set'],
                        ['Assigned Driver', selectedCustomer.assigned_driver?.full_name || selectedCustomer.preferred_driver?.full_name || 'Not set'],
                        ['Email', selectedCustomer.email_address || 'Not set'],
                      ].map(([label, value]) => (
                        <div key={label}>
                          <div className="text-xs font-medium uppercase tracking-wide text-gray-500">{label}</div>
                          <div className="mt-1 text-sm text-[#0F172A]">{value}</div>
                        </div>
                      ))}
                    </div>
                  </section>

                  <section className="rounded-2xl border border-gray-200 bg-white">
                    <div className="flex items-center justify-between border-b border-gray-200 px-5 py-4">
                      <h3 className="text-lg font-semibold text-[#0F172A]">Upcoming Bookings</h3>
                      <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row">
                        <button
                          onClick={openCreateBooking}
                          className="w-full rounded-lg bg-[#2563EB] px-3 py-2 text-xs font-medium text-white hover:bg-[#1d4ed8] sm:w-auto"
                        >
                          Add Booking
                        </button>
                        <button
                          onClick={openCreateFollowUpBooking}
                          className="w-full rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-700 hover:bg-amber-100 sm:w-auto"
                        >
                          Add Follow-Up
                        </button>
                      </div>
                    </div>
                    <div className="space-y-3 p-5">
                      {selectedCustomerUpcomingBookings.length ? (
                        selectedCustomerUpcomingBookings.map((booking) => (
                          <div key={booking.id} className="rounded-xl border border-gray-200 p-4">
                            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                              <div>
                                <div className="text-sm font-semibold text-[#0F172A]">{booking.booking_type}</div>
                                <div className="mt-1 text-xs text-gray-500">
                                  {formatDateTime(booking.pickup_at)} - {booking.pickup_location} to {booking.destination}
                                </div>
                              </div>
                              <div className="flex flex-wrap items-center gap-2">
                                <BookingStatusBadge status={booking.status} />
                                <select
                                  value={booking.status}
                                  onChange={(event) => void handleBookingStatusChange(booking.id, event.target.value)}
                                  disabled={isCompletedBookingStatus(booking.status)}
                                  className="rounded-lg border border-gray-300 px-3 py-2 text-xs focus:border-[#2563EB] focus:outline-none"
                                >
                                  {(bookingOptions?.statuses || []).map((status) => (
                                    <option key={status} value={status}>
                                      {status}
                                    </option>
                                  ))}
                                </select>
                              </div>
                            </div>
                          </div>
                        ))
                      ) : (
                        <div className="rounded-xl bg-gray-50 px-4 py-6 text-sm text-gray-500">
                          No upcoming bookings for this customer yet.
                        </div>
                      )}
                    </div>
                  </section>

                  <section className="rounded-2xl border border-gray-200 bg-white">
                    <div className="border-b border-gray-200 px-5 py-4">
                      <h3 className="text-lg font-semibold text-[#0F172A]">Completed & Missed Bookings</h3>
                    </div>
                    <div className="grid grid-cols-1 gap-4 p-5 lg:grid-cols-2">
                      <div className="space-y-3">
                        <div className="text-sm font-medium text-gray-500">Completed</div>
                        {selectedCustomerCompletedBookings.length ? (
                          selectedCustomerCompletedBookings.map((booking) => (
                            <div key={booking.id} className="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
                              <div className="text-sm font-semibold text-[#0F172A]">{booking.title || booking.booking_type}</div>
                              <div className="mt-1 text-xs text-gray-600">{formatDateTime(booking.completed_at || booking.pickup_at)}</div>
                              {booking.completion_note ? (
                                <div className="mt-2 text-xs text-emerald-800">Completion note: {booking.completion_note}</div>
                              ) : null}
                            </div>
                          ))
                        ) : (
                          <div className="rounded-xl bg-gray-50 px-4 py-6 text-sm text-gray-500">No completed bookings yet.</div>
                        )}
                      </div>
                      <div className="space-y-3">
                        <div className="text-sm font-medium text-gray-500">Missed</div>
                        {selectedCustomerMissedBookings.length ? (
                          selectedCustomerMissedBookings.map((booking) => (
                            <div key={booking.id} className="rounded-xl border border-red-200 bg-red-50 p-4">
                              <div className="text-sm font-semibold text-[#0F172A]">{booking.title || booking.booking_type}</div>
                              <div className="mt-1 text-xs text-gray-600">{formatDateTime(booking.pickup_at)}</div>
                            </div>
                          ))
                        ) : (
                          <div className="rounded-xl bg-gray-50 px-4 py-6 text-sm text-gray-500">No missed bookings recorded.</div>
                        )}
                      </div>
                    </div>
                  </section>

                  <section className="rounded-2xl border border-gray-200 bg-white">
                    <div className="border-b border-gray-200 px-5 py-4">
                      <h3 className="text-lg font-semibold text-[#0F172A]">Ride History</h3>
                    </div>
                    <div className="space-y-3 p-5">
                      {selectedCustomerRideHistory.length ? (
                        selectedCustomerRideHistory.map((ride) => (
                          <div key={ride.id} className="rounded-xl border border-gray-200 p-4">
                            <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
                              <div>
                                <div className="text-sm font-semibold text-[#0F172A]">
                                  {ride.pickup_location} to {ride.destination}
                                </div>
                                <div className="mt-1 text-xs text-gray-500">
                                  {formatDateTime(ride.end_time || ride.start_time || ride.scheduled_time)}
                                  {ride.driver?.full_name ? ` - ${ride.driver.full_name}` : ''}
                                </div>
                              </div>
                              <div className="flex items-center gap-3">
                                <div className="text-sm font-semibold text-emerald-700">
                                  {formatCurrency(ride.actual_fare ?? ride.estimated_fare)}
                                </div>
                                <BookingStatusBadge status={ride.status} />
                              </div>
                            </div>
                          </div>
                        ))
                      ) : (
                        <div className="rounded-xl bg-gray-50 px-4 py-6 text-sm text-gray-500">
                          No completed ride history has been recorded yet.
                        </div>
                      )}
                    </div>
                  </section>
                </div>

                <div className="space-y-6">
                  <section className="rounded-2xl border border-gray-200 bg-white">
                    <div className="border-b border-gray-200 px-5 py-4">
                      <h3 className="text-lg font-semibold text-[#0F172A]">Recurring Schedule</h3>
                    </div>
                    <div className="space-y-3 p-5">
                      {selectedCustomerRecurringSchedule.length ? (
                        selectedCustomerRecurringSchedule.map((booking) => (
                          <div key={booking.id} className="rounded-xl bg-blue-50 p-4">
                            <div className="text-sm font-semibold text-[#0F172A]">{booking.booking_type}</div>
                            <div className="mt-1 text-xs text-gray-600">
                              {booking.recurrence_type} every {booking.recurrence_frequency}
                              {booking.recurrence_days?.length ? ` - ${booking.recurrence_days.join(', ')}` : ''}
                            </div>
                            <div className="mt-2 text-xs text-gray-500">
                              {booking.pickup_time} - {booking.pickup_location} to {booking.destination}
                            </div>
                          </div>
                        ))
                      ) : (
                        <div className="rounded-xl bg-gray-50 px-4 py-6 text-sm text-gray-500">
                          No recurring pickup schedule for this customer yet.
                        </div>
                      )}
                    </div>
                  </section>

                  <section className="rounded-2xl border border-gray-200 bg-white">
                    <div className="border-b border-gray-200 px-5 py-4">
                      <h3 className="text-lg font-semibold text-[#0F172A]">Follow-Up Management</h3>
                    </div>
                    <div className="space-y-4 p-5">
                      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                        {[
                          ['Current Follow-Up', selectedCustomer.active_follow_up_date ? formatDate(selectedCustomer.active_follow_up_date) : 'Not scheduled'],
                          ['Priority', selectedCustomer.follow_up_priority || 'Not set'],
                          ['Status', selectedCustomer.follow_up_status_label || 'No follow-up scheduled'],
                          ['Next Planned Follow-Up', selectedCustomer.next_follow_up_date ? formatDate(selectedCustomer.next_follow_up_date) : 'Not set'],
                        ].map(([label, value]) => (
                          <div key={label} className="rounded-xl bg-gray-50 p-4">
                            <div className="text-xs font-medium uppercase tracking-wide text-gray-500">{label}</div>
                            <div className="mt-2 text-sm text-[#0F172A]">{value}</div>
                          </div>
                        ))}
                      </div>
                      <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap">
                        <button
                          onClick={() => openEditCustomer(selectedCustomer)}
                          className="w-full rounded-lg border border-gray-300 px-3 py-2 text-xs font-medium text-gray-700 hover:bg-gray-50 sm:w-auto"
                        >
                          Schedule Follow-Up
                        </button>
                        {selectedCustomer.active_follow_up_date && (
                          <button
                            onClick={() => void handleCompleteFollowUp()}
                            className="w-full rounded-lg bg-[#2563EB] px-3 py-2 text-xs font-medium text-white hover:bg-[#1d4ed8] sm:w-auto"
                          >
                            Mark Follow-Up Completed
                          </button>
                        )}
                      </div>
                      {selectedCustomerFollowUpHistory.slice(0, 4).map((entry, index) => (
                        <div key={`${entry.at || entry.date || 'follow-up'}-${index}`} className="rounded-xl border border-gray-200 p-4">
                          <div className="text-xs font-medium uppercase tracking-wide text-gray-500">{entry.action}</div>
                          <div className="mt-2 text-sm text-[#0F172A]">
                            {entry.date ? formatDate(entry.date) : 'No date'}
                            {entry.priority ? ` - ${entry.priority}` : ''}
                          </div>
                          {entry.note && <div className="mt-1 text-sm text-gray-600">{entry.note}</div>}
                        </div>
                      ))}
                    </div>
                  </section>

                  <section className="rounded-2xl border border-gray-200 bg-white">
                    <div className="border-b border-gray-200 px-5 py-4">
                      <h3 className="text-lg font-semibold text-[#0F172A]">Notes & Relationship Tracking</h3>
                    </div>
                    <div className="space-y-4 p-5">
                      {[
                        ['General Notes', selectedCustomer.notes || 'No general notes yet.'],
                        ['Relationship Notes', selectedCustomer.relationship_notes || 'No relationship notes yet.'],
                        ['Lead Notes', selectedCustomer.lead_notes || 'No lead notes yet.'],
                        ['Important Notes', selectedCustomer.important_notes || 'No important notes yet.'],
                        ['Referral', selectedCustomer.referred_by || 'No referral captured.'],
                      ].map(([label, value]) => (
                        <div key={label} className="rounded-xl bg-gray-50 p-4">
                          <div className="text-xs font-medium uppercase tracking-wide text-gray-500">{label}</div>
                          <div className="mt-2 text-sm text-[#0F172A]">{value}</div>
                        </div>
                      ))}
                    </div>
                  </section>

                  <section className="rounded-2xl border border-gray-200 bg-white">
                    <div className="border-b border-gray-200 px-5 py-4">
                      <h3 className="text-lg font-semibold text-[#0F172A]">Network & Business Context</h3>
                    </div>
                    <div className="space-y-3 p-5 text-sm text-[#0F172A]">
                      <div>
                        <span className="font-medium">Company:</span> {selectedCustomer.company_name || 'Not set'}
                      </div>
                      <div>
                        <span className="font-medium">Industry:</span> {selectedCustomer.company_industry || 'Not set'}
                      </div>
                      <div>
                        <span className="font-medium">Organization Type:</span> {selectedCustomer.organization_type || 'Not set'}
                      </div>
                      <div>
                        <span className="font-medium">Potential Service:</span> {selectedCustomer.potential_service || 'Not set'}
                      </div>
                      <div>
                        <span className="font-medium">Lead Value Estimate:</span>{' '}
                        {selectedCustomer.lead_value_estimate ? formatCurrency(selectedCustomer.lead_value_estimate) : 'Not set'}
                      </div>
                      <div>
                        <span className="font-medium">Transport Customer:</span> {selectedCustomer.is_transport_customer ? 'Yes' : 'No'}
                      </div>
                      <div>
                        <span className="font-medium">Business Lead:</span> {selectedCustomer.is_business_lead ? 'Yes' : 'No'}
                      </div>
                      <div>
                        <span className="font-medium">Relationship Created:</span> {formatDate(selectedCustomer.created_at)}
                      </div>
                    </div>
                  </section>
                </div>
              </div>
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
                { label: 'Scheduled Today', value: summary?.scheduled_today ?? upcomingBookings.length },
                { label: 'Pending Acknowledgement', value: summary?.pending_acknowledgement ?? 0 },
                { label: 'In Progress Bookings', value: summary?.in_progress_bookings ?? 0 },
                { label: 'Completed Today', value: summary?.completed_today ?? 0 },
                { label: 'Missed Bookings', value: summary?.missed_bookings ?? 0 },
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
                {filteredBookingQueue.slice(0, 8).map((booking) => (
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
                {!filteredBookingQueue.length && (
                  <div className="rounded-xl bg-gray-50 px-4 py-6 text-sm text-gray-500">
                    No bookings match this filter right now.
                  </div>
                )}
              </div>

              <div className="space-y-3">
                <div className="text-sm font-medium text-gray-500">Recurring Templates</div>
                {recurringTemplates.slice(0, 8).map((booking) => (
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
                {!recurringTemplates.length && (
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
                        openEditCustomer(duplicateCustomer);
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
            {[
              ['Full Name', 'full_name'],
              ['Phone Number', 'phone_number'],
              ['Alternate Phone', 'alternate_phone'],
              ['Email Address', 'email_address'],
              ['Date of Birth', 'date_of_birth'],
              ['Occupation', 'occupation'],
              ['Organization Name', 'organization_name'],
              ['Position Title', 'position_title'],
              ['Company Name', 'company_name'],
              ['Pickup Location', 'pickup_location'],
              ['Destination Location', 'destination_location'],
              ['Preferred Pickup Location', 'preferred_pickup_location'],
              ['Preferred Dropoff Location', 'preferred_dropoff_location'],
              ['Residential Area', 'residential_area'],
              ['Work Area', 'work_area'],
              ['Referred By', 'referred_by'],
            ].map(([label, fieldName]) => (
              <label key={fieldName} className="space-y-2">
                <span className="text-sm font-medium text-[#0F172A]">{label}</span>
                <input
                  type={fieldName.includes('date') ? 'date' : fieldName.includes('email') ? 'email' : 'text'}
                  value={customerForm[fieldName as keyof CustomerFormState] as string}
                  onChange={(event) => updateCustomerField(fieldName as CustomerFormField, event.target.value)}
                  className={getCustomerFieldClass(Boolean(customerFieldErrors[fieldName as CustomerFormField]))}
                />
                {customerFieldErrors[fieldName as CustomerFormField] && (
                  <p className="text-xs text-red-600">{customerFieldErrors[fieldName as CustomerFormField]}</p>
                )}
              </label>
            ))}

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Customer Category</span>
              <select
                value={customerForm.customer_category_id}
                onChange={(event) => updateCustomerField('customer_category_id', event.target.value)}
                className={getCustomerFieldClass(Boolean(customerFieldErrors.customer_category_id))}
              >
                <option value="">Select category</option>
                {(customerOptions?.customer_category_items || []).map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
              {customerFieldErrors.customer_category_id && (
                <p className="text-xs text-red-600">{customerFieldErrors.customer_category_id}</p>
              )}
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Customer Source</span>
              <select
                value={customerForm.source}
                onChange={(event) => updateCustomerField('source', event.target.value)}
                className={getCustomerFieldClass(Boolean(customerFieldErrors.source))}
              >
                <option value="">Select source</option>
                {(customerOptions?.source_options || []).map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </select>
              {customerFieldErrors.source && <p className="text-xs text-red-600">{customerFieldErrors.source}</p>}
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Organization Type</span>
              <select
                value={customerForm.organization_type_id}
                onChange={(event) => updateCustomerField('organization_type_id', event.target.value)}
                className={getCustomerFieldClass(Boolean(customerFieldErrors.organization_type_id))}
              >
                <option value="">Select organization type</option>
                {(customerOptions?.organization_type_items || []).map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
              {customerFieldErrors.organization_type_id && (
                <p className="text-xs text-red-600">{customerFieldErrors.organization_type_id}</p>
              )}
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Industry</span>
              <select
                value={customerForm.industry_id}
                onChange={(event) => updateCustomerField('industry_id', event.target.value)}
                className={getCustomerFieldClass(Boolean(customerFieldErrors.industry_id))}
              >
                <option value="">Select industry</option>
                {(customerOptions?.industry_items || []).map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
              {customerFieldErrors.industry_id && <p className="text-xs text-red-600">{customerFieldErrors.industry_id}</p>}
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Relationship Category</span>
              <select
                value={customerForm.relationship_category_id}
                onChange={(event) => updateCustomerField('relationship_category_id', event.target.value)}
                className={getCustomerFieldClass(Boolean(customerFieldErrors.relationship_category_id))}
              >
                <option value="">Select relationship category</option>
                {(customerOptions?.relationship_category_items || []).map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
              {customerFieldErrors.relationship_category_id && (
                <p className="text-xs text-red-600">{customerFieldErrors.relationship_category_id}</p>
              )}
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Opportunity Level</span>
              <select
                value={customerForm.opportunity_level_id}
                onChange={(event) => updateCustomerField('opportunity_level_id', event.target.value)}
                className={getCustomerFieldClass(Boolean(customerFieldErrors.opportunity_level_id))}
              >
                <option value="">Select opportunity level</option>
                {(customerOptions?.opportunity_level_items || []).map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
              {customerFieldErrors.opportunity_level_id && (
                <p className="text-xs text-red-600">{customerFieldErrors.opportunity_level_id}</p>
              )}
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Network Value</span>
              <select
                value={customerForm.network_value_id}
                onChange={(event) => updateCustomerField('network_value_id', event.target.value)}
                className={getCustomerFieldClass(Boolean(customerFieldErrors.network_value_id))}
              >
                <option value="">Select network value</option>
                {(customerOptions?.network_value_items || []).map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
              {customerFieldErrors.network_value_id && (
                <p className="text-xs text-red-600">{customerFieldErrors.network_value_id}</p>
              )}
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Lead Status</span>
              <select
                value={customerForm.lead_status_id}
                onChange={(event) => updateCustomerField('lead_status_id', event.target.value)}
                className={getCustomerFieldClass(Boolean(customerFieldErrors.lead_status_id))}
              >
                <option value="">Select lead status</option>
                {(customerOptions?.lead_status_items || []).map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
              {customerFieldErrors.lead_status_id && (
                <p className="text-xs text-red-600">{customerFieldErrors.lead_status_id}</p>
              )}
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Potential Service</span>
              <select
                value={customerForm.potential_service_id}
                onChange={(event) => updateCustomerField('potential_service_id', event.target.value)}
                className={getCustomerFieldClass(Boolean(customerFieldErrors.potential_service_id))}
              >
                <option value="">Select potential service</option>
                {(customerOptions?.potential_service_items || []).map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
              {customerFieldErrors.potential_service_id && (
                <p className="text-xs text-red-600">{customerFieldErrors.potential_service_id}</p>
              )}
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Lead Value Estimate</span>
              <input
                type="number"
                min="0"
                value={customerForm.lead_value_estimate}
                onChange={(event) => updateCustomerField('lead_value_estimate', event.target.value)}
                className={getCustomerFieldClass(Boolean(customerFieldErrors.lead_value_estimate))}
              />
              {customerFieldErrors.lead_value_estimate && (
                <p className="text-xs text-red-600">{customerFieldErrors.lead_value_estimate}</p>
              )}
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Follow-Up Date</span>
              <input
                type="date"
                value={customerForm.follow_up_date}
                onChange={(event) => updateCustomerField('follow_up_date', event.target.value)}
                className={getCustomerFieldClass(Boolean(customerFieldErrors.follow_up_date))}
              />
              {customerFieldErrors.follow_up_date && (
                <p className="text-xs text-red-600">{customerFieldErrors.follow_up_date}</p>
              )}
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Next Follow-Up Date</span>
              <input
                type="date"
                value={customerForm.next_follow_up_date}
                onChange={(event) => updateCustomerField('next_follow_up_date', event.target.value)}
                className={getCustomerFieldClass(Boolean(customerFieldErrors.next_follow_up_date))}
              />
              {customerFieldErrors.next_follow_up_date && (
                <p className="text-xs text-red-600">{customerFieldErrors.next_follow_up_date}</p>
              )}
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Follow-Up Priority</span>
              <select
                value={customerForm.follow_up_priority}
                onChange={(event) => updateCustomerField('follow_up_priority', event.target.value)}
                className={getCustomerFieldClass(Boolean(customerFieldErrors.follow_up_priority))}
              >
                {(customerOptions?.follow_up_priorities || []).map((priority) => (
                  <option key={priority} value={priority}>
                    {priority}
                  </option>
                ))}
              </select>
              {customerFieldErrors.follow_up_priority && (
                <p className="text-xs text-red-600">{customerFieldErrors.follow_up_priority}</p>
              )}
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Preferred Driver</span>
              <select
                value={customerForm.preferred_driver_id}
                onChange={(event) => updateCustomerField('preferred_driver_id', event.target.value)}
                className={getCustomerFieldClass(Boolean(customerFieldErrors.preferred_driver_id))}
              >
                <option value="">Select driver</option>
                {(customerOptions?.drivers || []).map((driver) => (
                  <option key={driver.id} value={driver.id}>
                    {driver.full_name}
                  </option>
                ))}
              </select>
              {customerFieldErrors.preferred_driver_id && (
                <p className="text-xs text-red-600">{customerFieldErrors.preferred_driver_id}</p>
              )}
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Status</span>
              <select
                value={customerForm.status}
                onChange={(event) => updateCustomerField('status', event.target.value)}
                className={getCustomerFieldClass(Boolean(customerFieldErrors.status))}
              >
                {(customerOptions?.statuses || []).map((status) => (
                  <option key={status} value={status}>
                    {status}
                  </option>
                ))}
              </select>
              {customerFieldErrors.status && <p className="text-xs text-red-600">{customerFieldErrors.status}</p>}
            </label>
          </div>

          <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
            <label className="flex items-center justify-between rounded-xl border border-gray-200 px-4 py-3">
              <div>
                <div className="text-sm font-medium text-[#0F172A]">Transport Customer</div>
                <div className="text-xs text-gray-500">Keep this on for active transport riders.</div>
              </div>
              <input
                type="checkbox"
                checked={customerForm.is_transport_customer}
                onChange={(event) => updateCustomerField('is_transport_customer', event.target.checked)}
                className="h-4 w-4 rounded border-gray-300 text-[#2563EB] focus:ring-[#2563EB]"
              />
            </label>

            <label className="flex items-center justify-between rounded-xl border border-gray-200 px-4 py-3">
              <div>
                <div className="text-sm font-medium text-[#0F172A]">Business Lead</div>
                <div className="text-xs text-gray-500">Use this for leads, partners, investors, and strategic contacts.</div>
              </div>
              <input
                type="checkbox"
                checked={customerForm.is_business_lead}
                onChange={(event) => updateCustomerField('is_business_lead', event.target.checked)}
                className="h-4 w-4 rounded border-gray-300 text-[#2563EB] focus:ring-[#2563EB]"
              />
            </label>
          </div>

          <div className="mt-4 grid grid-cols-1 gap-4">
            {[
              ['Notes', 'notes'],
              ['Relationship Notes', 'relationship_notes'],
              ['Lead Notes', 'lead_notes'],
              ['Important Notes', 'important_notes'],
            ].map(([label, fieldName]) => (
              <label key={fieldName} className="space-y-2">
                <span className="text-sm font-medium text-[#0F172A]">{label}</span>
                <textarea
                  rows={3}
                  value={customerForm[fieldName as keyof CustomerFormState] as string}
                  onChange={(event) => updateCustomerField(fieldName as CustomerFormField, event.target.value)}
                  className={getCustomerFieldClass(Boolean(customerFieldErrors[fieldName as CustomerFormField]), { multiline: true })}
                />
                {customerFieldErrors[fieldName as CustomerFormField] && (
                  <p className="text-xs text-red-600">{customerFieldErrors[fieldName as CustomerFormField]}</p>
                )}
              </label>
            ))}
          </div>

          <div className="sticky bottom-0 mt-6 flex justify-end border-t border-gray-200 bg-white pt-4">
            <button
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
              <select
                value={bookingForm.customer_id}
                onChange={(event) => setBookingForm((current) => ({ ...current, customer_id: event.target.value }))}
                className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm"
              >
                <option value="">Select customer</option>
                {customers.map((customer) => (
                  <option key={customer.id} value={customer.id}>
                    {customer.full_name}
                  </option>
                ))}
              </select>
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Booking Type</span>
              <select
                value={bookingForm.booking_type}
                onChange={(event) => setBookingForm((current) => ({ ...current, booking_type: event.target.value }))}
                className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm"
              >
                {(bookingOptions?.booking_types || []).map((type) => (
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
                {(bookingOptions?.priorities || ['Low', 'Medium', 'High', 'Critical']).map((priority) => (
                  <option key={priority} value={priority}>
                    {priority}
                  </option>
                ))}
              </select>
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Driver</span>
              <select
                value={bookingForm.driver_id}
                onChange={(event) => setBookingForm((current) => ({ ...current, driver_id: event.target.value }))}
                className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm"
              >
                <option value="">Assign later</option>
                {(bookingOptions?.drivers || []).map((driver) => (
                  <option key={driver.id} value={driver.id}>
                    {driver.full_name}
                  </option>
                ))}
              </select>
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-[#0F172A]">Vehicle</span>
              <select
                value={bookingForm.vehicle_id}
                onChange={(event) => setBookingForm((current) => ({ ...current, vehicle_id: event.target.value }))}
                className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm"
              >
                <option value="">Assign later</option>
                {(bookingOptions?.vehicles || []).map((vehicle) => (
                  <option key={vehicle.id} value={vehicle.id}>
                    {vehicle.registration_number}
                  </option>
                ))}
              </select>
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
                {(bookingOptions?.statuses || []).map((status) => (
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
                  {(bookingOptions?.recurrence_types || []).map((type) => (
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
