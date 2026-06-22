import { useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  AlertCircle,
  AlertTriangle,
  BadgePlus,
  Calendar,
  Car,
  CarFront,
  CheckCircle,
  Clock,
  Flag,
  Fuel,
  Loader2,
  MapPin,
  Navigation,
  Phone,
  Plus,
  Route,
  ShieldAlert,
  Siren,
  Target,
  Truck,
  Wallet,
  WalletCards,
  Wrench,
  X,
} from 'lucide-react';
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { toast } from 'sonner';
import {
  getAssignedVehicleLabel,
  type SessionUser,
} from '../../lib/auth-session';
import type { DriverActiveAssignment, DriverDashboardSummary } from '../../lib/driver-api';
import { apiRequestSafe } from '../../lib/api';
import type { BookingSummary } from '../../lib/customer-booking-api';
import { setDriverQuickActionIntent } from '../../lib/driver-quick-actions';
import {
  convertBookingToRide,
  createRide,
  fetchRideOptions,
  fetchRides,
  updateRide,
  type TripOptions,
  type TripRecord,
} from '../../lib/ride-masterdata-api';

interface DriverDashboardProps {
  currentUser: SessionUser | null;
  activeAssignment: DriverActiveAssignment | null;
  dashboardSummary: DriverDashboardSummary | null;
  onNavigate: (page: string) => void;
}

function formatCurrency(value: number) {
  return `GHS ${value.toLocaleString()}`;
}

function nowTimeValue() {
  return new Date().toISOString().slice(11, 16);
}

function todayValue() {
  return new Date().toISOString().slice(0, 10);
}

export default function DriverDashboard({
  currentUser,
  activeAssignment,
  dashboardSummary,
  onNavigate,
}: DriverDashboardProps) {
  const [bookingSummary, setBookingSummary] = useState<BookingSummary | null>(null);
  const [bookingSummaryError, setBookingSummaryError] = useState('');
  const [bookingSummaryNotice, setBookingSummaryNotice] = useState('');
  const [showStartTripModal, setShowStartTripModal] = useState(false);
  const [showEndTripModal, setShowEndTripModal] = useState(false);
  const [showLocationModal, setShowLocationModal] = useState(false);
  const [showEmergencyPanel, setShowEmergencyPanel] = useState(false);
  const [rideOptions, setRideOptions] = useState<TripOptions | null>(null);
  const [activeRide, setActiveRide] = useState<TripRecord | null>(null);
  const [isLoadingRideWorkspace, setIsLoadingRideWorkspace] = useState(false);
  const [isSubmittingTripAction, setIsSubmittingTripAction] = useState(false);
  const [isCapturingLocation, setIsCapturingLocation] = useState(false);
  const [locationValue, setLocationValue] = useState('');
  const [locationAccuracy, setLocationAccuracy] = useState('');
  const [startTripForm, setStartTripForm] = useState({
    booking_id: '',
    trip_date: todayValue(),
    start_time: nowTimeValue(),
    pickup_area: '',
    destination_area: '',
    odometer_start: '',
    notes: '',
  });
  const [endTripForm, setEndTripForm] = useState({
    end_time: nowTimeValue(),
    odometer_end: '',
    notes: '',
  });

  const loadBookingSummary = async () => {
    setBookingSummaryError('');
    setBookingSummaryNotice('');
    const response = await apiRequestSafe<{ data: { summary: BookingSummary } }>('/bookings/summary', {
      fallbackData: { data: { summary: null as unknown as BookingSummary } },
      cacheTtlMs: 15000,
    });
    setBookingSummary(response.data?.data?.summary || null);
    if (!response.ok) {
      setBookingSummaryError(response.error || 'Unable to load booking insights right now.');
    } else if (!response.data?.data?.summary) {
      setBookingSummaryNotice('No booking insights are available yet.');
    }
  };

  useEffect(() => {
    void loadBookingSummary();
  }, []);

  useEffect(() => {
    void loadRideWorkspace();
  }, []);

  const selectedBooking = useMemo(
    () => rideOptions?.bookings.find((booking) => booking.id === startTripForm.booking_id) || null,
    [rideOptions?.bookings, startTripForm.booking_id],
  );

  useEffect(() => {
    if (!selectedBooking) {
      return;
    }
    setStartTripForm((current) => ({
      ...current,
      pickup_area: selectedBooking.pickup_location || current.pickup_area,
      destination_area: selectedBooking.destination || current.destination_area,
      trip_date: selectedBooking.pickup_date || current.trip_date,
      start_time: selectedBooking.pickup_time || current.start_time,
    }));
  }, [selectedBooking]);

  const stats = {
    weeklyTarget: dashboardSummary?.weekly_target || 0,
    amountPaid: dashboardSummary?.approved_total_this_week || dashboardSummary?.amount_paid_this_week || 0,
    submittedTotal: dashboardSummary?.submitted_total_this_week || 0,
    outstandingBalance: dashboardSummary?.outstanding_balance || 0,
    todaysCollections: dashboardSummary?.today_collection_total || 0,
    dailyTarget: dashboardSummary?.daily_target || 0,
    achievementPercentage: dashboardSummary?.achievement_percentage || 0,
  };

  const insuranceProfile = activeAssignment?.vehicle?.insurance_profile || null;
  const insurancePhone = insuranceProfile?.claims_officer_phone || insuranceProfile?.emergency_contact || '';
  const insuranceEmail = insuranceProfile?.claims_officer_email || '';
  const insuranceOfficerName = insuranceProfile?.claims_officer_name || insuranceProfile?.insurance_company || 'Insurance support';
  const hasInsuranceContact = Boolean(insurancePhone);
  const fleetManagerPhone = '';
  const hasFleetManagerContact = Boolean(fleetManagerPhone);
  const assignedVehicleLabel = getAssignedVehicleLabel(currentUser, activeAssignment);
  const assignmentStatus = activeAssignment?.status || 'not assigned';

  const weeklyProgress = [
    { day: 'Mon', revenue: 0, trips: 0 },
    { day: 'Tue', revenue: 0, trips: 0 },
    { day: 'Wed', revenue: 0, trips: 0 },
    { day: 'Thu', revenue: 0, trips: 0 },
    { day: 'Fri', revenue: 0, trips: 0 },
    { day: 'Sat', revenue: 0, trips: 0 },
    { day: 'Sun', revenue: 0, trips: 0 },
  ];

  const loadRideWorkspace = async () => {
    setIsLoadingRideWorkspace(true);
    try {
      const [nextOptions, rides] = await Promise.all([fetchRideOptions(), fetchRides()]);
      setRideOptions(nextOptions);
      const nextActiveRide = [...rides]
        .filter((ride) => !['Completed', 'Cancelled'].includes(ride.status))
        .sort((left, right) => {
          const leftValue = new Date(left.updated_at || left.created_at || 0).getTime();
          const rightValue = new Date(right.updated_at || right.created_at || 0).getTime();
          return rightValue - leftValue;
        })[0] || null;
      setActiveRide(nextActiveRide);
      setStartTripForm((current) => ({
        ...current,
        trip_date: todayValue(),
        start_time: nowTimeValue(),
      }));
      setEndTripForm((current) => ({
        ...current,
        end_time: nowTimeValue(),
      }));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Unable to load trip actions right now.');
    } finally {
      setIsLoadingRideWorkspace(false);
    }
  };

  const routeWithIntent = (page: string, intent?: Parameters<typeof setDriverQuickActionIntent>[0]) => {
    if (intent) {
      setDriverQuickActionIntent(intent);
    }
    onNavigate(page);
  };

  const handlePhoneAction = (label: string, phoneNumber: string) => {
    if (!phoneNumber) {
      toast.error(`${label} contact is not available right now.`);
      return;
    }
    window.location.href = `tel:${phoneNumber}`;
  };

  const openStartTrip = async () => {
    if (!activeAssignment?.vehicle_id) {
      toast.error('You need an assigned vehicle before you can start a trip.');
      return;
    }
    if (activeRide) {
      toast.info(`Finish ${activeRide.trip_id} before starting another trip.`);
      return;
    }
    await loadRideWorkspace();
    setShowStartTripModal(true);
  };

  const openEndTrip = async () => {
    await loadRideWorkspace();
    if (!activeRide) {
      toast.info('There is no active trip to end right now.');
      return;
    }
    setShowEndTripModal(true);
  };

  const handleStartTrip = async () => {
    if (!activeAssignment?.vehicle_id) {
      toast.error('You need an assigned vehicle before you can start a trip.');
      return;
    }
    if (!rideOptions?.trip_sources?.[0]?.id || !rideOptions?.trip_purposes?.[0]?.id) {
      toast.error('Trip setup options are not ready yet. Please try again shortly.');
      return;
    }
    if (!startTripForm.pickup_area || !startTripForm.destination_area) {
      toast.error('Please add both pickup and destination details before starting the trip.');
      return;
    }

    setIsSubmittingTripAction(true);
    try {
      const payload = {
        driver_id: currentUser?.id || undefined,
        vehicle_id: activeAssignment.vehicle_id,
        trip_source_id: rideOptions.trip_sources[0].id,
        trip_purpose_id: rideOptions.trip_purposes[0].id,
        trip_date: startTripForm.trip_date,
        start_time: startTripForm.start_time,
        pickup_area: startTripForm.pickup_area,
        destination_area: startTripForm.destination_area,
        odometer_start: startTripForm.odometer_start ? Number(startTripForm.odometer_start) : undefined,
        notes: startTripForm.notes || undefined,
        status: 'Logged',
      };
      const trip = startTripForm.booking_id
        ? await convertBookingToRide(startTripForm.booking_id, payload)
        : await createRide(payload);
      setActiveRide(trip);
      setShowStartTripModal(false);
      toast.success(`Trip ${trip.trip_id} started successfully.`);
      await loadRideWorkspace();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Unable to start the trip right now.');
    } finally {
      setIsSubmittingTripAction(false);
    }
  };

  const handleEndTrip = async () => {
    if (!activeRide) {
      toast.info('There is no active trip to end right now.');
      return;
    }
    setIsSubmittingTripAction(true);
    try {
      const trip = await updateRide(activeRide.id, {
        end_time: endTripForm.end_time,
        odometer_end: endTripForm.odometer_end ? Number(endTripForm.odometer_end) : undefined,
        notes: endTripForm.notes || undefined,
      });
      setActiveRide(trip.status === 'Completed' ? null : trip);
      setShowEndTripModal(false);
      toast.success(`Trip ${trip.trip_id} closed successfully.`);
      await loadRideWorkspace();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Unable to end the trip right now.');
    } finally {
      setIsSubmittingTripAction(false);
    }
  };

  const handleCaptureLocation = async () => {
    if (!navigator.geolocation) {
      toast.info('Live location is not available in this browser. You can enter it manually below.');
      return;
    }
    setIsCapturingLocation(true);
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const { latitude, longitude, accuracy } = position.coords;
        setLocationValue(`${latitude.toFixed(6)}, ${longitude.toFixed(6)}`);
        setLocationAccuracy(`Accuracy ±${Math.round(accuracy)}m`);
        setIsCapturingLocation(false);
        toast.success('Current location captured.');
      },
      () => {
        setIsCapturingLocation(false);
        toast.error('We could not read your location. Please enter it manually.');
      },
      { enableHighAccuracy: true, timeout: 10000 },
    );
  };

  const submitLocationUpdate = () => {
    if (!locationValue.trim()) {
      toast.error('Please capture or enter a location before continuing.');
      return;
    }
    setShowLocationModal(false);
    toast.info('Location captured. Live dispatch sync is coming soon.');
  };

  const quickActionGroups = [
    {
      title: 'Operations',
      actions: [
        {
          label: 'Start Trip',
          description: activeRide ? `Finish ${activeRide.trip_id} before starting another trip.` : 'Create an active trip for your assigned vehicle.',
          icon: Route,
          color: 'bg-blue-600',
          disabled: Boolean(activeRide),
          onClick: () => void openStartTrip(),
        },
        {
          label: 'End Trip',
          description: activeRide ? `Close ${activeRide.trip_id} and record the end time.` : 'Available when you have an active trip.',
          icon: Flag,
          color: 'bg-slate-700',
          disabled: !activeRide,
          onClick: () => void openEndTrip(),
        },
        {
          label: 'Submit Collection',
          description: 'Open your wallet and submit this week’s collection.',
          icon: WalletCards,
          color: 'bg-emerald-600',
          onClick: () => routeWithIntent('my-wallet', 'submit_collection'),
        },
        {
          label: 'Log Fuel',
          description: 'Record a fuel purchase for your assigned vehicle.',
          icon: Fuel,
          color: 'bg-amber-500',
          onClick: () => routeWithIntent('fuel-logs', 'log_fuel'),
        },
      ],
    },
    {
      title: 'Vehicle',
      actions: [
        {
          label: 'Report Fault',
          description: 'Send a fault report with your vehicle attached.',
          icon: AlertCircle,
          color: 'bg-rose-600',
          onClick: () => onNavigate('report-fault'),
        },
        {
          label: 'Report Accident / Incident',
          description: 'Open the incident workflow with vehicle and driver details.',
          icon: AlertTriangle,
          color: 'bg-red-700',
          onClick: () => onNavigate('incidents'),
        },
        {
          label: 'Request Maintenance',
          description: 'Maintenance request handoff is not ready yet.',
          icon: Wrench,
          color: 'bg-orange-600',
          onClick: () => toast.info('This action is coming soon.'),
        },
        {
          label: 'Update Location',
          description: 'Capture your current location or enter it manually.',
          icon: MapPin,
          color: 'bg-cyan-600',
          onClick: () => setShowLocationModal(true),
        },
      ],
    },
    {
      title: 'Customers & Bookings',
      actions: [
        {
          label: 'Create Booking',
          description: 'Open the customer workspace and start a new booking.',
          icon: Plus,
          color: 'bg-blue-500',
          onClick: () => routeWithIntent('customers', 'create_booking'),
        },
        {
          label: 'Create Reminder',
          description: 'Open the customer workspace with a reminder form ready.',
          icon: Clock,
          color: 'bg-purple-500',
          onClick: () => routeWithIntent('customers', 'create_reminder'),
        },
        {
          label: 'Schedule Follow-Up',
          description: 'Open the customer workspace with a follow-up form ready.',
          icon: BadgePlus,
          color: 'bg-amber-500',
          onClick: () => routeWithIntent('customers', 'schedule_follow_up'),
        },
        {
          label: 'View Calendar',
          description: 'See your scheduled pickups and booking actions.',
          icon: Navigation,
          color: 'bg-green-500',
          onClick: () => onNavigate('calendar'),
        },
      ],
    },
    {
      title: 'Emergency',
      actions: [
        {
          label: 'Call Police',
          description: 'Use the emergency number quickly from the dashboard.',
          icon: Siren,
          color: 'bg-red-600',
          onClick: () => handlePhoneAction('Police', '191'),
        },
        {
          label: 'Call Insurance',
          description: hasInsuranceContact ? `Contact ${insuranceOfficerName}.` : 'No insurance contact found for this vehicle.',
          icon: ShieldAlert,
          color: 'bg-indigo-600',
          disabled: !hasInsuranceContact,
          onClick: () => handlePhoneAction('Insurance', insurancePhone),
        },
        {
          label: 'Call Fleet Manager',
          description: hasFleetManagerContact ? 'Contact the configured fleet manager.' : 'Fleet manager contact has not been configured.',
          icon: Phone,
          color: 'bg-slate-600',
          onClick: () => {
            if (!hasFleetManagerContact) {
              toast.info('Fleet manager contact has not been configured.');
              return;
            }
            handlePhoneAction('Fleet manager', fleetManagerPhone);
          },
        },
        {
          label: 'Emergency Support',
          description: 'See support contacts and jump into incident reporting.',
          icon: Truck,
          color: 'bg-black',
          onClick: () => setShowEmergencyPanel(true),
        },
      ],
    },
  ];

  return (
    <div className="space-y-6 p-4 sm:p-6">
      <div className="rounded-lg bg-gradient-to-r from-blue-600 to-purple-600 p-6 text-white">
        <h1 className="mb-2 text-2xl font-semibold">
          Welcome back, {currentUser?.full_name || 'Driver'}!
        </h1>
        <p className="text-blue-100">Your portal now reflects your real active assignment, vehicle, and weekly financial summary.</p>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <div className="rounded-lg bg-white/20 px-3 py-1.5 backdrop-blur-sm">
            <span className="text-sm font-medium">Vehicle: {assignedVehicleLabel}</span>
          </div>
          <div className="rounded-lg bg-white/20 px-3 py-1.5 backdrop-blur-sm">
            <span className="text-sm font-medium capitalize">Assignment: {assignmentStatus}</span>
          </div>
          <div className="flex items-center gap-1.5 rounded-lg bg-green-500/20 px-3 py-1.5 backdrop-blur-sm">
            <div className="h-2 w-2 rounded-full bg-green-400"></div>
            <span className="text-sm font-medium capitalize">{currentUser?.status || 'unknown'}</span>
          </div>
          <div className="rounded-lg bg-white/20 px-3 py-1.5 backdrop-blur-sm">
            <span className="text-sm font-medium capitalize">Role: {currentUser?.role || 'driver'}</span>
          </div>
          <div className="rounded-lg bg-white/20 px-3 py-1.5 backdrop-blur-sm">
            <span className="text-sm font-medium">
              Deadline: {dashboardSummary?.weekly_cycle?.payment_deadline || 'N/A'}
            </span>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-4">
        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-blue-100">
            <Target className="h-6 w-6 text-blue-600" />
          </div>
          <div className="mb-2 text-3xl font-semibold text-gray-900">{formatCurrency(stats.weeklyTarget)}</div>
          <div className="text-sm text-gray-600">Weekly Target</div>
          <div className="mt-2 text-xs text-gray-500">From your active assignment</div>
        </div>

        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-green-100">
            <Wallet className="h-6 w-6 text-green-600" />
          </div>
          <div className="mb-2 text-3xl font-semibold text-green-600">{formatCurrency(stats.amountPaid)}</div>
          <div className="text-sm text-gray-600">Approved Total</div>
          <div className="mt-2 text-xs text-gray-500">{dashboardSummary?.total_collections_this_week || 0} collections this week</div>
        </div>

        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-red-100">
            <AlertCircle className="h-6 w-6 text-red-600" />
          </div>
          <div className="mb-2 text-3xl font-semibold text-red-600">{formatCurrency(stats.outstandingBalance)}</div>
          <div className="text-sm text-gray-600">Outstanding Balance</div>
          <div className="mt-2 text-xs text-gray-500">Weekly target minus payments this week</div>
        </div>

        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-purple-100">
            <CarFront className="h-6 w-6 text-purple-600" />
          </div>
          <div className="mb-2 text-3xl font-semibold text-gray-900">{formatCurrency(stats.todaysCollections)}</div>
          <div className="text-sm text-gray-600">Today&apos;s Collections</div>
          <div className="mt-2 text-xs text-gray-500">0 when nothing has been recorded today</div>
        </div>
      </div>

      {bookingSummaryError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <span>{bookingSummaryError}</span>
            <button onClick={() => void loadBookingSummary()} className="rounded-lg border border-red-200 bg-white px-3 py-2 text-xs font-medium text-red-700 hover:bg-red-100">
              Retry
            </button>
          </div>
        </div>
      )}

      {bookingSummaryNotice && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          {bookingSummaryNotice}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        {[
          { label: 'Scheduled Today', value: bookingSummary?.scheduled_today ?? 0, icon: Calendar, tint: 'bg-blue-100 text-blue-600' },
          { label: 'Upcoming Bookings', value: bookingSummary?.upcoming_bookings ?? 0, icon: Navigation, tint: 'bg-emerald-100 text-emerald-600' },
          { label: 'Overdue Reminders', value: bookingSummary?.overdue_reminders ?? 0, icon: Clock, tint: 'bg-rose-100 text-rose-600' },
          { label: 'Follow-Ups Due Today', value: bookingSummary?.follow_ups_due_today ?? 0, icon: CheckCircle, tint: 'bg-amber-100 text-amber-600' },
        ].map((card) => {
          const Icon = card.icon;
          return (
            <div key={card.label} className="rounded-lg border border-gray-200 bg-white p-5">
              <div className={`mb-4 flex h-11 w-11 items-center justify-center rounded-xl ${card.tint}`}>
                <Icon className="h-5 w-5" />
              </div>
              <div className="text-3xl font-semibold text-[#0F172A]">{card.value}</div>
              <div className="mt-1 text-sm text-gray-500">{card.label}</div>
            </div>
          );
        })}
      </div>

      <div className="rounded-lg border border-gray-200 bg-white p-6">
        <div className="flex flex-col gap-2 border-b border-gray-100 pb-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h3 className="text-lg font-semibold text-gray-900">Quick Actions</h3>
            <p className="text-sm text-gray-500">Every action below opens a real workflow or gives a clear next step.</p>
          </div>
          {activeRide && (
            <div className="inline-flex items-center gap-2 rounded-full bg-emerald-50 px-3 py-1.5 text-xs font-medium text-emerald-700">
              <Car className="h-3.5 w-3.5" />
              Active trip: {activeRide.trip_id}
            </div>
          )}
        </div>
        <div className="mt-5 space-y-6">
          {quickActionGroups.map((group) => (
            <div key={group.title}>
              <div className="mb-3 text-sm font-semibold uppercase tracking-[0.16em] text-gray-500">{group.title}</div>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
                {group.actions.map((action) => {
                  const Icon = action.icon;
                  return (
                    <button
                      key={action.label}
                      type="button"
                      title={action.description}
                      onClick={action.onClick}
                      disabled={action.disabled}
                      className="flex min-h-[144px] flex-col items-start gap-3 rounded-xl border border-gray-200 bg-gray-50 p-5 text-left transition-colors hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      <div className={`flex h-11 w-11 items-center justify-center rounded-xl ${action.color}`}>
                        <Icon className="h-5 w-5 text-white" />
                      </div>
                      <div>
                        <div className="text-sm font-semibold text-gray-900">{action.label}</div>
                        <p className="mt-1 text-xs leading-5 text-gray-500">{action.description}</p>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <h3 className="mb-4 text-lg font-semibold text-gray-900">Weekly Revenue</h3>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={weeklyProgress}>
              <CartesianGrid stroke="#f0f0f0" strokeDasharray="3 3" />
              <XAxis dataKey="day" stroke="#6b7280" />
              <YAxis stroke="#6b7280" />
              <Tooltip />
              <Legend />
              <Bar dataKey="revenue" fill="#10B981" name="Revenue (GHS)" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <h3 className="mb-4 text-lg font-semibold text-gray-900">Driver Summary</h3>
          <div className="space-y-4">
            <div className="flex items-center gap-3 rounded-lg bg-gray-50 p-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-100">
                <Navigation className="h-5 w-5 text-blue-600" />
              </div>
              <div>
                <div className="text-sm font-medium text-gray-900">Logged-in Driver</div>
                <div className="text-sm text-gray-500">{currentUser?.full_name || 'Driver'}</div>
              </div>
            </div>
            <div className="flex items-center gap-3 rounded-lg bg-gray-50 p-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-green-100">
                <CheckCircle className="h-5 w-5 text-green-600" />
              </div>
              <div>
                <div className="text-sm font-medium text-gray-900">Account Status</div>
                <div className="text-sm capitalize text-gray-500">{currentUser?.status || 'unknown'}</div>
              </div>
            </div>
            <div className="flex items-center gap-3 rounded-lg bg-gray-50 p-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-purple-100">
                <Wallet className="h-5 w-5 text-purple-600" />
              </div>
              <div>
                <div className="text-sm font-medium text-gray-900">Assigned Vehicle</div>
                <div className="text-sm text-gray-500">{assignedVehicleLabel}</div>
              </div>
            </div>
            <div className="flex items-center gap-3 rounded-lg bg-gray-50 p-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-red-100">
                <Target className="h-5 w-5 text-red-600" />
              </div>
              <div>
                <div className="text-sm font-medium text-gray-900">Targets</div>
                <div className="text-sm text-gray-500">
                  Weekly {formatCurrency(stats.weeklyTarget)} / Daily {formatCurrency(stats.dailyTarget)}
                </div>
              </div>
            </div>
            <div className="flex items-center gap-3 rounded-lg bg-gray-50 p-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-amber-100">
                <CheckCircle className="h-5 w-5 text-amber-600" />
              </div>
              <div>
                <div className="text-sm font-medium text-gray-900">Week Cycle</div>
                <div className="text-sm text-gray-500">
                  Submitted {formatCurrency(stats.submittedTotal)} / Approved {formatCurrency(stats.amountPaid)}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="rounded-lg border border-gray-200 bg-white">
        <div className="border-b border-gray-200 p-6">
          <h3 className="text-lg font-semibold text-gray-900">Latest Collections</h3>
        </div>
        {dashboardSummary?.latest_collections?.length ? (
          <div className="divide-y divide-gray-200">
            {dashboardSummary.latest_collections.map((collection) => (
              <div key={collection.id} className="flex items-center justify-between gap-4 px-6 py-4">
                <div>
                  <div className="text-sm font-medium text-gray-900 capitalize">{collection.payment_method} collection</div>
                  <div className="text-xs text-gray-500">{collection.collection_date} / {collection.status}</div>
                </div>
                <div className="text-sm font-semibold text-green-600">{formatCurrency(collection.amount || 0)}</div>
              </div>
            ))}
          </div>
        ) : (
          <div className="px-6 py-10 text-center text-gray-500">No collections recorded yet for this week.</div>
        )}
      </div>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <div className="mb-4 flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-green-100">
              <Wallet className="h-5 w-5 text-green-600" />
            </div>
            <div>
              <h3 className="text-sm font-medium text-gray-600">Amount Paid This Week</h3>
              <p className="text-2xl font-semibold text-gray-900">{formatCurrency(stats.amountPaid)}</p>
            </div>
          </div>
          <div className="text-sm text-gray-500">Based on received and approved collections this week</div>
        </div>

        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <div className="mb-4 flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-purple-100">
              <Target className="h-5 w-5 text-purple-600" />
            </div>
            <div>
              <h3 className="text-sm font-medium text-gray-600">Daily Target</h3>
              <p className="text-2xl font-semibold text-gray-900">{formatCurrency(stats.dailyTarget)}</p>
            </div>
          </div>
          <div className="text-sm text-gray-500">From your active assignment</div>
        </div>

        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <div className="mb-4 flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-100">
              <CheckCircle className="h-5 w-5 text-blue-600" />
            </div>
            <div>
              <h3 className="text-sm font-medium text-gray-600">Achievement</h3>
              <p className="text-2xl font-semibold text-gray-900">{stats.achievementPercentage.toFixed(2)}%</p>
            </div>
          </div>
          <div className="text-sm text-gray-500">Weekly payment progress against target</div>
        </div>
      </div>

      {showStartTripModal && (
        <ActionModal
          title="Start Trip"
          subtitle="Create an active trip record for your assigned vehicle."
          onClose={() => setShowStartTripModal(false)}
        >
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <FieldBlock label="Assigned Vehicle">
              <div className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2.5 text-sm text-gray-700">{assignedVehicleLabel}</div>
            </FieldBlock>
            <FieldBlock label="Linked Booking">
              <select value={startTripForm.booking_id} onChange={(event) => setStartTripForm((current) => ({ ...current, booking_id: event.target.value }))} className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm">
                <option value="">No linked booking</option>
                {(rideOptions?.bookings || []).map((booking) => (
                  <option key={booking.id} value={booking.id}>
                    {booking.booking_id} - {booking.pickup_date} {booking.pickup_time}
                  </option>
                ))}
              </select>
            </FieldBlock>
            <FieldBlock label="Trip Date">
              <input type="date" value={startTripForm.trip_date} onChange={(event) => setStartTripForm((current) => ({ ...current, trip_date: event.target.value }))} className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm" />
            </FieldBlock>
            <FieldBlock label="Start Time">
              <input type="time" value={startTripForm.start_time} onChange={(event) => setStartTripForm((current) => ({ ...current, start_time: event.target.value }))} className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm" />
            </FieldBlock>
            <FieldBlock label="Pickup Area">
              <input value={startTripForm.pickup_area} onChange={(event) => setStartTripForm((current) => ({ ...current, pickup_area: event.target.value }))} placeholder="Where are you starting from?" className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm" />
            </FieldBlock>
            <FieldBlock label="Destination Area">
              <input value={startTripForm.destination_area} onChange={(event) => setStartTripForm((current) => ({ ...current, destination_area: event.target.value }))} placeholder="Where are you heading?" className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm" />
            </FieldBlock>
            <FieldBlock label="Odometer Start">
              <input type="number" value={startTripForm.odometer_start} onChange={(event) => setStartTripForm((current) => ({ ...current, odometer_start: event.target.value }))} placeholder="Optional" className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm" />
            </FieldBlock>
            <FieldBlock label="Notes">
              <textarea value={startTripForm.notes} onChange={(event) => setStartTripForm((current) => ({ ...current, notes: event.target.value }))} placeholder="Operational notes for dispatch or handover." className="min-h-[96px] w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm" />
            </FieldBlock>
          </div>
          <div className="mt-5 flex justify-end gap-3">
            <button type="button" onClick={() => setShowStartTripModal(false)} className="rounded-lg border border-gray-200 px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50">Cancel</button>
            <button type="button" onClick={() => void handleStartTrip()} disabled={isSubmittingTripAction || isLoadingRideWorkspace} className="inline-flex items-center gap-2 rounded-lg bg-[#2563EB] px-4 py-2.5 text-sm font-medium text-white hover:bg-[#1d4ed8] disabled:cursor-not-allowed disabled:opacity-70">
              {isSubmittingTripAction || isLoadingRideWorkspace ? <Loader2 className="h-4 w-4 animate-spin" /> : <Route className="h-4 w-4" />}
              {isSubmittingTripAction ? 'Starting Trip...' : 'Start Trip'}
            </button>
          </div>
        </ActionModal>
      )}

      {showEndTripModal && (
        <ActionModal
          title="End Trip"
          subtitle={activeRide ? `Close ${activeRide.trip_id} and record the final details.` : 'Close the current trip.'}
          onClose={() => setShowEndTripModal(false)}
        >
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <FieldBlock label="Active Trip">
              <div className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2.5 text-sm text-gray-700">{activeRide?.trip_id || 'No active trip'}</div>
            </FieldBlock>
            <FieldBlock label="End Time">
              <input type="time" value={endTripForm.end_time} onChange={(event) => setEndTripForm((current) => ({ ...current, end_time: event.target.value }))} className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm" />
            </FieldBlock>
            <FieldBlock label="Odometer End">
              <input type="number" value={endTripForm.odometer_end} onChange={(event) => setEndTripForm((current) => ({ ...current, odometer_end: event.target.value }))} placeholder="Optional" className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm" />
            </FieldBlock>
            <FieldBlock label="Completion Notes">
              <textarea value={endTripForm.notes} onChange={(event) => setEndTripForm((current) => ({ ...current, notes: event.target.value }))} placeholder="Add any drop-off, issue, or handover notes." className="min-h-[96px] w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm" />
            </FieldBlock>
          </div>
          <div className="mt-5 flex justify-end gap-3">
            <button type="button" onClick={() => setShowEndTripModal(false)} className="rounded-lg border border-gray-200 px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50">Cancel</button>
            <button type="button" onClick={() => void handleEndTrip()} disabled={isSubmittingTripAction} className="inline-flex items-center gap-2 rounded-lg bg-[#0F172A] px-4 py-2.5 text-sm font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-70">
              {isSubmittingTripAction ? <Loader2 className="h-4 w-4 animate-spin" /> : <Flag className="h-4 w-4" />}
              {isSubmittingTripAction ? 'Ending Trip...' : 'End Trip'}
            </button>
          </div>
        </ActionModal>
      )}

      {showLocationModal && (
        <ActionModal
          title="Update Location"
          subtitle="Capture your live location or enter it manually for operations support."
          onClose={() => setShowLocationModal(false)}
        >
          <div className="space-y-4">
            <div className="rounded-xl border border-cyan-200 bg-cyan-50 p-4 text-sm text-cyan-900">
              Share your current position with dispatch. If device location is unavailable, you can enter a landmark, address, or coordinates manually.
            </div>
            <FieldBlock label="Current Location">
              <textarea value={locationValue} onChange={(event) => setLocationValue(event.target.value)} placeholder="Example: 5.603717, -0.186964 or Spintex Road, Accra" className="min-h-[96px] w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm" />
              {locationAccuracy && <div className="mt-2 text-xs text-gray-500">{locationAccuracy}</div>}
            </FieldBlock>
          </div>
          <div className="mt-5 flex flex-col gap-3 sm:flex-row sm:justify-end">
            <button type="button" onClick={() => void handleCaptureLocation()} disabled={isCapturingLocation} className="inline-flex items-center justify-center gap-2 rounded-lg border border-cyan-200 bg-cyan-50 px-4 py-2.5 text-sm font-medium text-cyan-800 hover:bg-cyan-100 disabled:cursor-not-allowed disabled:opacity-70">
              {isCapturingLocation ? <Loader2 className="h-4 w-4 animate-spin" /> : <MapPin className="h-4 w-4" />}
              {isCapturingLocation ? 'Capturing...' : 'Use Current Location'}
            </button>
            <button type="button" onClick={submitLocationUpdate} className="rounded-lg bg-[#2563EB] px-4 py-2.5 text-sm font-medium text-white hover:bg-[#1d4ed8]">Save Location</button>
          </div>
        </ActionModal>
      )}

      {showEmergencyPanel && (
        <ActionModal
          title="Emergency Support"
          subtitle="Reach the right contact quickly and continue with the incident process."
          onClose={() => setShowEmergencyPanel(false)}
        >
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            <EmergencyCard
              title="Fleet Manager"
              detail={hasFleetManagerContact ? fleetManagerPhone : 'Fleet manager contact has not been configured.'}
              actionLabel="Call Fleet Manager"
              onClick={() => {
                if (!hasFleetManagerContact) {
                  toast.info('Fleet manager contact has not been configured.');
                  return;
                }
                handlePhoneAction('Fleet manager', fleetManagerPhone);
              }}
            />
            <EmergencyCard
              title="Insurance Contact"
              detail={hasInsuranceContact ? `${insuranceOfficerName}${insurancePhone ? ` • ${insurancePhone}` : ''}` : 'No insurance contact found for this vehicle.'}
              actionLabel="Call Insurance"
              disabled={!hasInsuranceContact}
              onClick={() => handlePhoneAction('Insurance', insurancePhone)}
            />
            <EmergencyCard
              title="Police"
              detail="Emergency line: 191"
              actionLabel="Call Police"
              onClick={() => handlePhoneAction('Police', '191')}
            />
          </div>
          <div className="mt-5 flex flex-col gap-3 sm:flex-row sm:justify-end">
            {insuranceEmail && (
              <button type="button" onClick={() => { window.location.href = `mailto:${insuranceEmail}`; }} className="rounded-lg border border-indigo-200 bg-indigo-50 px-4 py-2.5 text-sm font-medium text-indigo-800 hover:bg-indigo-100">
                Email Insurance
              </button>
            )}
            <button type="button" onClick={() => { setShowEmergencyPanel(false); onNavigate('incidents'); }} className="rounded-lg bg-[#DC2626] px-4 py-2.5 text-sm font-medium text-white hover:bg-[#B91C1C]">
              Open Incident Report
            </button>
          </div>
        </ActionModal>
      )}
    </div>
  );
}

function ActionModal({
  title,
  subtitle,
  onClose,
  children,
}: {
  title: string;
  subtitle: string;
  onClose: () => void;
  children: ReactNode;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-4">
      <div className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-2xl bg-white shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-gray-200 px-5 py-4 sm:px-6">
          <div>
            <h4 className="text-lg font-semibold text-[#0F172A]">{title}</h4>
            <p className="mt-1 text-sm text-gray-500">{subtitle}</p>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg p-2 text-gray-500 hover:bg-gray-100 hover:text-gray-700">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="px-5 py-5 sm:px-6">{children}</div>
      </div>
    </div>
  );
}

function FieldBlock({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="space-y-2">
      <span className="text-sm font-medium text-[#0F172A]">{label}</span>
      {children}
    </label>
  );
}

function EmergencyCard({
  title,
  detail,
  actionLabel,
  onClick,
  disabled,
}: {
  title: string;
  detail: string;
  actionLabel: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <div className="rounded-xl border border-gray-200 bg-gray-50 p-4">
      <div className="text-sm font-semibold text-[#0F172A]">{title}</div>
      <p className="mt-2 min-h-[48px] text-sm text-gray-500">{detail}</p>
      <button type="button" onClick={onClick} disabled={disabled} className="mt-4 w-full rounded-lg border border-gray-200 bg-white px-4 py-2.5 text-sm font-medium text-[#0F172A] hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-60">
        {actionLabel}
      </button>
    </div>
  );
}
