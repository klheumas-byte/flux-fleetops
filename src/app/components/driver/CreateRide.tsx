import { useEffect, useMemo, useState } from 'react';
import { Calendar, CarFront, Clock, Loader2, MapPin, Navigation, Plus, Route } from 'lucide-react';
import { ApiRequestError } from '../../lib/api';
import {
  convertBookingToRide,
  createRide,
  fetchRideOptions,
  fetchRides,
  type TripOptions,
  type TripRecord,
} from '../../lib/ride-masterdata-api';

interface TripFormState {
  booking_id: string;
  customer_id: string;
  driver_id: string;
  vehicle_id: string;
  trip_source_id: string;
  trip_purpose_id: string;
  trip_date: string;
  start_time: string;
  end_time: string;
  pickup_area: string;
  destination_area: string;
  odometer_start: string;
  odometer_end: string;
  notes: string;
  status: string;
}

const todayDate = new Date().toISOString().slice(0, 10);
const currentTime = new Date().toISOString().slice(11, 16);

const emptyTripForm: TripFormState = {
  booking_id: '',
  customer_id: '',
  driver_id: '',
  vehicle_id: '',
  trip_source_id: '',
  trip_purpose_id: '',
  trip_date: todayDate,
  start_time: currentTime,
  end_time: currentTime,
  pickup_area: '',
  destination_area: '',
  odometer_start: '',
  odometer_end: '',
  notes: '',
  status: 'Completed',
};

function formatDate(value?: string | null) {
  if (!value) return 'No date';
  const date = new Date(`${value}T00:00:00`);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString();
}

function formatTime(value?: string | null) {
  return value || 'No time';
}

export default function CreateRide() {
  const [options, setOptions] = useState<TripOptions | null>(null);
  const [rides, setRides] = useState<TripRecord[]>([]);
  const [form, setForm] = useState<TripFormState>(emptyTripForm);
  const [isLoading, setIsLoading] = useState(true);
  const [pageError, setPageError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const loadTripWorkspace = async () => {
    setIsLoading(true);
    setPageError('');
    try {
      const [nextOptions, nextRides] = await Promise.all([fetchRideOptions(), fetchRides()]);
      setOptions(nextOptions);
      setRides(nextRides);
      setForm((current) => ({
        ...current,
        trip_source_id: current.trip_source_id || nextOptions.trip_sources[0]?.id || '',
        trip_purpose_id: current.trip_purpose_id || nextOptions.trip_purposes[0]?.id || '',
      }));
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setPageError(error.message);
      } else {
        setPageError('Unable to load trip log tools right now.');
      }
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void loadTripWorkspace();
  }, []);

  const selectedBooking = useMemo(
    () => options?.bookings.find((booking) => booking.id === form.booking_id) || null,
    [form.booking_id, options?.bookings],
  );

  useEffect(() => {
    if (!selectedBooking) return;
    setForm((current) => ({
      ...current,
      customer_id: selectedBooking.customer_id,
      driver_id: selectedBooking.driver_id || current.driver_id,
      vehicle_id: selectedBooking.vehicle_id || current.vehicle_id,
      pickup_area: selectedBooking.pickup_location,
      destination_area: selectedBooking.destination,
      trip_date: selectedBooking.pickup_date || current.trip_date,
      start_time: selectedBooking.pickup_time || current.start_time,
      end_time: current.end_time || selectedBooking.pickup_time || current.start_time,
      status: 'Scheduled',
    }));
  }, [selectedBooking]);

  const recentTrips = useMemo(() => rides.slice(0, 5), [rides]);

  const handleSubmit = async () => {
    setIsSubmitting(true);
    setPageError('');
    try {
      const payload: Record<string, unknown> = {
        customer_id: form.customer_id || undefined,
        driver_id: form.driver_id || undefined,
        vehicle_id: form.vehicle_id,
        trip_source_id: form.trip_source_id,
        trip_purpose_id: form.trip_purpose_id,
        trip_date: form.trip_date,
        start_time: form.start_time || undefined,
        end_time: form.end_time || undefined,
        pickup_area: form.pickup_area,
        destination_area: form.destination_area,
        odometer_start: form.odometer_start ? Number(form.odometer_start) : undefined,
        odometer_end: form.odometer_end ? Number(form.odometer_end) : undefined,
        notes: form.notes || undefined,
        status: form.status,
      };
      if (form.booking_id) {
        await convertBookingToRide(form.booking_id, payload);
      } else {
        await createRide(payload);
      }
      setForm({
        ...emptyTripForm,
        trip_source_id: options?.trip_sources[0]?.id || '',
        trip_purpose_id: options?.trip_purposes[0]?.id || '',
      });
      await loadTripWorkspace();
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setPageError(error.message);
      } else {
        setPageError('Unable to save this trip log right now.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center gap-3 text-gray-500">
        <Loader2 className="h-5 w-5 animate-spin" />
        <span>Loading trip workspace...</span>
      </div>
    );
  }

  return (
    <div className="space-y-6 bg-[#F8FAFC] p-4 md:p-6">
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[1.1fr_0.9fr]">
        <div className="rounded-2xl border border-gray-200 bg-white">
          <div className="border-b border-gray-200 bg-gradient-to-r from-[#0F172A] to-[#1e293b] px-6 py-5 text-white">
            <h1 className="text-2xl font-semibold">Log Trip</h1>
            <p className="mt-1 text-sm text-gray-300">
              Record platform usage, customer activity, and vehicle movement without fare tracking.
            </p>
          </div>

          <div className="space-y-5 p-6">
            {pageError && (
              <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                {pageError}
              </div>
            )}

            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <label className="space-y-2">
                <span className="text-sm font-medium text-[#0F172A]">Convert Scheduled Booking</span>
                <select
                  value={form.booking_id}
                  onChange={(event) => setForm((current) => ({ ...current, booking_id: event.target.value }))}
                  className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm"
                >
                  <option value="">Log without booking</option>
                  {(options?.bookings || []).map((booking) => (
                    <option key={booking.id} value={booking.id}>
                      {booking.booking_id} - {booking.pickup_date} {booking.pickup_time}
                    </option>
                  ))}
                </select>
              </label>

              <label className="space-y-2">
                <span className="text-sm font-medium text-[#0F172A]">Customer</span>
                <select
                  value={form.customer_id}
                  onChange={(event) => setForm((current) => ({ ...current, customer_id: event.target.value }))}
                  className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm"
                >
                  <option value="">Optional customer</option>
                  {(options?.customers || []).map((customer) => (
                    <option key={customer.id} value={customer.id}>
                      {customer.full_name}
                    </option>
                  ))}
                </select>
              </label>

              <label className="space-y-2">
                <span className="text-sm font-medium text-[#0F172A]">Trip Source</span>
                <select
                  value={form.trip_source_id}
                  onChange={(event) => setForm((current) => ({ ...current, trip_source_id: event.target.value }))}
                  className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm"
                >
                  {(options?.trip_sources || []).map((source) => (
                    <option key={source.id} value={source.id}>
                      {source.name}
                    </option>
                  ))}
                </select>
              </label>

              <label className="space-y-2">
                <span className="text-sm font-medium text-[#0F172A]">Trip Purpose</span>
                <select
                  value={form.trip_purpose_id}
                  onChange={(event) => setForm((current) => ({ ...current, trip_purpose_id: event.target.value }))}
                  className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm"
                >
                  {(options?.trip_purposes || []).map((purpose) => (
                    <option key={purpose.id} value={purpose.id}>
                      {purpose.name}
                    </option>
                  ))}
                </select>
              </label>

              <label className="space-y-2">
                <span className="text-sm font-medium text-[#0F172A]">Driver</span>
                <select
                  value={form.driver_id}
                  onChange={(event) => setForm((current) => ({ ...current, driver_id: event.target.value }))}
                  className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm"
                >
                  <option value="">Auto-assign to me</option>
                  {(options?.drivers || []).map((driver) => (
                    <option key={driver.id} value={driver.id}>
                      {driver.full_name}
                    </option>
                  ))}
                </select>
              </label>

              <label className="space-y-2">
                <span className="text-sm font-medium text-[#0F172A]">Vehicle</span>
                <select
                  value={form.vehicle_id}
                  onChange={(event) => setForm((current) => ({ ...current, vehicle_id: event.target.value }))}
                  className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm"
                >
                  <option value="">Select vehicle</option>
                  {(options?.vehicles || []).map((vehicle) => (
                    <option key={vehicle.id} value={vehicle.id}>
                      {vehicle.registration_number}
                    </option>
                  ))}
                </select>
              </label>

              <label className="space-y-2">
                <span className="text-sm font-medium text-[#0F172A]">Trip Date</span>
                <input
                  type="date"
                  value={form.trip_date}
                  onChange={(event) => setForm((current) => ({ ...current, trip_date: event.target.value }))}
                  className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm"
                />
              </label>

              <label className="space-y-2">
                <span className="text-sm font-medium text-[#0F172A]">Status</span>
                <select
                  value={form.status}
                  onChange={(event) => setForm((current) => ({ ...current, status: event.target.value }))}
                  className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm"
                >
                  {(options?.statuses || []).map((status) => (
                    <option key={status} value={status}>
                      {status}
                    </option>
                  ))}
                </select>
              </label>

              <label className="space-y-2">
                <span className="text-sm font-medium text-[#0F172A]">Start Time</span>
                <input
                  type="time"
                  value={form.start_time}
                  onChange={(event) => setForm((current) => ({ ...current, start_time: event.target.value }))}
                  className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm"
                />
              </label>

              <label className="space-y-2">
                <span className="text-sm font-medium text-[#0F172A]">End Time</span>
                <input
                  type="time"
                  value={form.end_time}
                  onChange={(event) => setForm((current) => ({ ...current, end_time: event.target.value }))}
                  className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm"
                />
              </label>

              <label className="space-y-2 md:col-span-2">
                <span className="text-sm font-medium text-[#0F172A]">Pickup Area</span>
                <input
                  value={form.pickup_area}
                  onChange={(event) => setForm((current) => ({ ...current, pickup_area: event.target.value }))}
                  className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm"
                />
              </label>

              <label className="space-y-2 md:col-span-2">
                <span className="text-sm font-medium text-[#0F172A]">Destination Area</span>
                <input
                  value={form.destination_area}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, destination_area: event.target.value }))
                  }
                  className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm"
                />
              </label>

              <label className="space-y-2">
                <span className="text-sm font-medium text-[#0F172A]">Odometer Start</span>
                <input
                  type="number"
                  min="0"
                  value={form.odometer_start}
                  onChange={(event) => setForm((current) => ({ ...current, odometer_start: event.target.value }))}
                  className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm"
                />
              </label>

              <label className="space-y-2">
                <span className="text-sm font-medium text-[#0F172A]">Odometer End</span>
                <input
                  type="number"
                  min="0"
                  value={form.odometer_end}
                  onChange={(event) => setForm((current) => ({ ...current, odometer_end: event.target.value }))}
                  className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm"
                />
              </label>

              <label className="space-y-2 md:col-span-2">
                <span className="text-sm font-medium text-[#0F172A]">Notes</span>
                <textarea
                  rows={3}
                  value={form.notes}
                  onChange={(event) => setForm((current) => ({ ...current, notes: event.target.value }))}
                  className="w-full rounded-xl border border-gray-300 px-4 py-3 text-sm"
                />
              </label>
            </div>

            <button
              onClick={() => void handleSubmit()}
              disabled={isSubmitting}
              className="inline-flex items-center gap-2 rounded-xl bg-[#2563EB] px-4 py-3 text-sm font-medium text-white disabled:opacity-60"
            >
              {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              {form.booking_id ? 'Convert Booking to Trip Log' : 'Log Trip'}
            </button>
          </div>
        </div>

        <div className="space-y-6">
          <div className="rounded-2xl border border-gray-200 bg-white p-6">
            <h2 className="text-lg font-semibold text-[#0F172A]">Recent Trip Logs</h2>
            <p className="mt-1 text-sm text-gray-500">
              Keep an eye on your latest vehicle activity and platform usage entries.
            </p>
          </div>

          {recentTrips.map((trip) => (
            <div key={trip.id} className="rounded-2xl border border-gray-200 bg-white p-5">
              <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="text-base font-semibold text-[#0F172A]">{trip.trip_id}</span>
                    <span className="rounded-full bg-blue-100 px-2.5 py-1 text-xs font-medium text-blue-700">
                      {trip.status}
                    </span>
                  </div>
                  <div className="text-sm text-gray-600">
                    {(trip.customer?.full_name || 'No customer')} - {trip.trip_source} - {trip.trip_purpose}
                  </div>
                  <div className="grid grid-cols-1 gap-2 text-sm text-gray-600">
                    <div className="flex items-center gap-2">
                      <MapPin className="h-4 w-4 text-[#2563EB]" />
                      {trip.pickup_area}
                    </div>
                    <div className="flex items-center gap-2">
                      <Navigation className="h-4 w-4 text-[#10B981]" />
                      {trip.destination_area}
                    </div>
                    <div className="flex items-center gap-2">
                      <Calendar className="h-4 w-4 text-amber-600" />
                      {formatDate(trip.trip_date)}
                    </div>
                    <div className="flex items-center gap-2">
                      <Clock className="h-4 w-4 text-violet-600" />
                      {formatTime(trip.start_time)} - {formatTime(trip.end_time)}
                    </div>
                  </div>
                </div>

                <div className="rounded-xl bg-gray-50 px-4 py-3 text-sm text-gray-600">
                  <div className="flex items-center gap-2">
                    <CarFront className="h-4 w-4 text-[#2563EB]" />
                    {trip.vehicle?.registration_number || 'Vehicle pending'}
                  </div>
                  <div className="mt-2 flex items-center gap-2">
                    <Route className="h-4 w-4 text-[#10B981]" />
                    {trip.odometer_start ?? '-'} to {trip.odometer_end ?? '-'}
                  </div>
                </div>
              </div>
            </div>
          ))}

          {!recentTrips.length && (
            <div className="rounded-2xl border border-dashed border-gray-300 bg-white px-6 py-12 text-center text-gray-500">
              No trip logs yet.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
