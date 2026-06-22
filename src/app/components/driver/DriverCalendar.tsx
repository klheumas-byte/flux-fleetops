import { useEffect, useState } from 'react';
import { AlertTriangle, Calendar, CheckCircle2, Clock, Loader2, MapPin, Phone } from 'lucide-react';
import { ApiRequestError } from '../../lib/api';
import {
  acknowledgeBooking,
  completeBookingAction,
  fetchCalendar,
  markBookingPickedUp,
  reportBookingIssue,
  startBookingPickup,
  type BookingRecord,
  type CalendarEntry,
} from '../../lib/customer-booking-api';
import { usePageToastFeedback } from '../../lib/use-page-toast-feedback';

const views = [
  { id: 'today', label: 'Today' },
  { id: 'tomorrow', label: 'Tomorrow' },
  { id: 'this-week', label: 'This Week' },
  { id: 'upcoming', label: 'Upcoming' },
  { id: 'overdue', label: 'Overdue' },
  { id: 'completed', label: 'Completed' },
] as const;

const issueTypes = [
  'customer cancelled',
  'customer not reachable',
  'pickup delayed',
  'vehicle issue',
  'other',
] as const;

function BookingStatusBadge({ status }: { status: string }) {
  const colorMap: Record<string, string> = {
    Scheduled: 'bg-blue-100 text-blue-700',
    Acknowledged: 'bg-cyan-100 text-cyan-700',
    'En Route': 'bg-amber-100 text-amber-700',
    'Picked Up': 'bg-emerald-100 text-emerald-700',
    Completed: 'bg-slate-100 text-slate-700',
    Cancelled: 'bg-rose-100 text-rose-700',
    Missed: 'bg-red-100 text-red-700',
  };

  return (
    <span className={`rounded-full px-3 py-1.5 text-xs font-medium ${colorMap[status] || 'bg-gray-100 text-gray-700'}`}>
      {status}
    </span>
  );
}

function cardAccent(color?: string, isOverdue?: boolean) {
  if (isOverdue || color === 'red') return 'border-red-200 bg-red-50/50';
  if (color === 'purple') return 'border-purple-200 bg-purple-50/60';
  if (color === 'orange') return 'border-amber-200 bg-amber-50/60';
  if (color === 'green') return 'border-emerald-200 bg-emerald-50/60';
  return 'border-blue-200 bg-blue-50/40';
}

function getNextAction(status: string) {
  if (status === 'Scheduled') {
    return { label: 'Acknowledge', action: 'acknowledge' as const };
  }
  if (status === 'Acknowledged') {
    return { label: 'Start Pickup', action: 'start' as const };
  }
  if (status === 'En Route') {
    return { label: 'Picked Up', action: 'picked-up' as const };
  }
  if (status === 'Picked Up') {
    return { label: 'Complete Booking', action: 'complete' as const };
  }
  return null;
}

function isCompletedBooking(status: string) {
  return status.trim().toLowerCase() === 'completed';
}

export default function DriverCalendar() {
  const [activeView, setActiveView] = useState<(typeof views)[number]['id']>('today');
  const [entries, setEntries] = useState<CalendarEntry[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [pageError, setPageError] = useState('');
  const [actionNotice, setActionNotice] = useState('');
  const [actingBookingId, setActingBookingId] = useState('');
  const [issueBookingId, setIssueBookingId] = useState('');
  const [issueType, setIssueType] = useState<(typeof issueTypes)[number]>('customer cancelled');
  const [issueNote, setIssueNote] = useState('');
  const [completionBookingId, setCompletionBookingId] = useState('');
  const [completionNote, setCompletionNote] = useState('');
  const [createTripLog, setCreateTripLog] = useState(true);
  usePageToastFeedback(pageError, actionNotice);

  useEffect(() => {
    const loadCalendar = async () => {
      setIsLoading(true);
      setPageError('');
      try {
        const nextEntries = await fetchCalendar(activeView);
        setEntries(nextEntries);
      } catch (error) {
        if (error instanceof ApiRequestError) {
          setPageError(error.message);
        } else {
          setPageError('Unable to load your calendar right now.');
        }
      } finally {
        setIsLoading(false);
      }
    };

    void loadCalendar();
  }, [activeView]);

  const replaceBooking = (updatedBooking: BookingRecord) => {
    setEntries((current) =>
      current.map((entry) =>
        entry.booking.id === updatedBooking.id
          ? {
              ...entry,
              booking: updatedBooking,
              status: updatedBooking.status,
              customer: updatedBooking.customer?.full_name || entry.customer,
              pickup: updatedBooking.pickup_location,
              destination: updatedBooking.destination,
              time: updatedBooking.pickup_time,
            }
          : entry,
      ),
    );
  };

  const handleAction = async (booking: BookingRecord) => {
    if (isCompletedBooking(booking.status)) {
      setPageError('');
      setActionNotice('This booking has already been completed.');
      return;
    }

    const nextAction = getNextAction(booking.status);
    if (!nextAction) {
      return;
    }

    if (nextAction.action === 'complete') {
      setCompletionBookingId(booking.id);
      setIssueBookingId('');
      setCompletionNote(booking.completion_note || '');
      setCreateTripLog(false);
      setActionNotice('');
      return;
    }

    setActingBookingId(booking.id);
    setPageError('');
    setActionNotice('');
    try {
      const updatedBooking =
        nextAction.action === 'acknowledge'
          ? await acknowledgeBooking(booking.id)
          : nextAction.action === 'start'
            ? await startBookingPickup(booking.id)
            : await markBookingPickedUp(booking.id);
      replaceBooking(updatedBooking);
      setActionNotice(`${updatedBooking.booking_id} updated to ${updatedBooking.status}.`);
    } catch (error) {
      setPageError(error instanceof ApiRequestError ? error.message : 'Unable to update booking right now.');
    } finally {
      setActingBookingId('');
    }
  };

  const submitIssue = async (bookingId: string) => {
    setActingBookingId(bookingId);
    setPageError('');
    setActionNotice('');
    try {
      const updatedBooking = await reportBookingIssue(bookingId, {
        issue_type: issueType,
        issue_note: issueNote,
      });
      replaceBooking(updatedBooking);
      setIssueBookingId('');
      setIssueNote('');
      setActionNotice(`Issue reported for ${updatedBooking.booking_id}.`);
    } catch (error) {
      setPageError(error instanceof ApiRequestError ? error.message : 'Unable to report issue right now.');
    } finally {
      setActingBookingId('');
    }
  };

  const submitCompletion = async (bookingId: string) => {
    const targetBooking = entries.find((entry) => entry.booking.id === bookingId)?.booking;
    if (!targetBooking) {
      setPageError('This booking is no longer available. Please refresh and try again.');
      return;
    }
    if (isCompletedBooking(targetBooking.status)) {
      setCompletionBookingId('');
      setPageError('');
      setActionNotice('This booking has already been completed.');
      return;
    }
    if (actingBookingId === bookingId) {
      return;
    }

    setActingBookingId(bookingId);
    setPageError('');
    setActionNotice('');
    try {
      const updatedBooking = await completeBookingAction(bookingId, {
        completion_note: completionNote,
        create_trip_log: createTripLog,
      });
      replaceBooking(updatedBooking);
      setCompletionBookingId('');
      setCompletionNote('');
      setCreateTripLog(true);
      setActionNotice(`${updatedBooking.booking_id} marked as completed.`);
    } catch (error) {
      setPageError(error instanceof ApiRequestError ? error.message : 'Unable to complete booking right now.');
    } finally {
      setActingBookingId('');
    }
  };

  return (
    <div className="max-w-full space-y-6 overflow-x-hidden p-4 md:p-6">
      <div className="rounded-2xl bg-gradient-to-r from-[#0F172A] to-[#2563EB] p-6 text-white">
        <h1 className="text-2xl font-semibold">Driver Calendar</h1>
        <p className="mt-1 text-sm text-blue-100">
          See your scheduled pickups by time window and keep each booking moving from acknowledgement to completion.
        </p>
      </div>

      <div className="flex flex-wrap gap-2 overflow-x-auto pb-1">
        {views.map((view) => (
          <button
            key={view.id}
            onClick={() => setActiveView(view.id)}
            className={`rounded-xl border px-4 py-2.5 text-sm font-medium whitespace-nowrap ${
              activeView === view.id ? 'border-[#2563EB] bg-[#2563EB] text-white' : 'border-gray-200 bg-white text-gray-700'
            }`}
          >
            {view.label}
          </button>
        ))}
      </div>

      {actionNotice && (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
          {actionNotice}
        </div>
      )}

      {pageError && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {pageError}
        </div>
      )}

      <div className="rounded-2xl border border-gray-200 bg-white">
        <div className="border-b border-gray-200 px-5 py-4">
          <h2 className="text-lg font-semibold text-[#0F172A]">
            {views.find((view) => view.id === activeView)?.label} Schedule
          </h2>
        </div>

        {isLoading ? (
          <div className="flex min-h-[280px] items-center justify-center gap-3 text-gray-500">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span>Loading calendar...</span>
          </div>
        ) : entries.length ? (
          <div className="divide-y divide-gray-200">
            {entries.map((entry) => {
              const booking = entry.booking;
              const nextAction = getNextAction(booking.status);
              const isActing = actingBookingId === booking.id;
              const alreadyCompleted = isCompletedBooking(booking.status);

              return (
                <div key={booking.id} className={`space-y-4 border-l-4 px-5 py-4 ${cardAccent(entry.color, entry.is_overdue)}`}>
                  <div className="grid grid-cols-1 gap-4 lg:grid-cols-[120px_minmax(0,1fr)_minmax(0,1fr)_220px]">
                    <div>
                      <div className="flex items-center gap-2 text-sm font-semibold text-[#0F172A]">
                        <Clock className="h-4 w-4 text-[#2563EB]" />
                        {entry.time}
                      </div>
                      <div className="mt-1 text-xs text-gray-500">{booking.pickup_date}</div>
                    </div>
                    <div className="space-y-2">
                      <div>
                        <div className="text-sm font-semibold text-[#0F172A]">{entry.customer || 'Customer'}</div>
                        <div className="mt-1 text-xs text-gray-500">{booking.booking_type}</div>
                      </div>
                      <div className="flex flex-wrap items-center gap-3 text-xs text-gray-500">
                        <div className="flex items-center gap-1.5">
                          <Phone className="h-3.5 w-3.5 text-emerald-600" />
                          <span>{booking.customer?.phone_number || 'No phone number'}</span>
                        </div>
                        {booking.notes ? <div className="max-w-full break-words">Notes: {booking.notes}</div> : null}
                      </div>
                    </div>
                    <div className="space-y-1 text-sm text-gray-600">
                      <div className="flex items-start gap-2">
                        <MapPin className="mt-0.5 h-4 w-4 text-emerald-600" />
                        <span className="break-words">{entry.pickup}</span>
                      </div>
                      <div className="flex items-start gap-2">
                        <MapPin className="mt-0.5 h-4 w-4 text-rose-600" />
                        <span className="break-words">{entry.destination}</span>
                      </div>
                    </div>
                    <div className="flex flex-col items-stretch gap-3">
                      <div className="flex flex-wrap items-center justify-start gap-2 lg:justify-end">
                        <BookingStatusBadge status={entry.status} />
                        {booking.issue_type ? (
                          <span className="rounded-full bg-amber-100 px-3 py-1.5 text-xs font-medium text-amber-700">
                            Issue: {booking.issue_type}
                          </span>
                        ) : null}
                        {booking.priority ? (
                          <span className="rounded-full bg-white px-3 py-1.5 text-xs font-medium text-gray-700">
                            {booking.priority}
                          </span>
                        ) : null}
                      </div>
                      <div className="flex flex-col gap-2 sm:flex-row lg:flex-col">
                        {alreadyCompleted ? (
                          <button
                            disabled
                            className="inline-flex w-full cursor-not-allowed items-center justify-center rounded-xl bg-slate-200 px-4 py-2.5 text-sm font-medium text-slate-600 opacity-80"
                          >
                            Completed
                          </button>
                        ) : nextAction ? (
                          <button
                            onClick={() => void handleAction(booking)}
                            disabled={isActing}
                            className="inline-flex w-full items-center justify-center rounded-xl bg-[#2563EB] px-4 py-2.5 text-sm font-medium text-white transition hover:bg-[#1D4ED8] disabled:cursor-not-allowed disabled:opacity-60"
                          >
                            {isActing ? <Loader2 className="h-4 w-4 animate-spin" /> : nextAction.label}
                          </button>
                        ) : null}
                        <button
                          onClick={() => {
                            setIssueBookingId(issueBookingId === booking.id ? '' : booking.id);
                            setCompletionBookingId('');
                            setActionNotice('');
                          }}
                          className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm font-medium text-amber-700 transition hover:bg-amber-100"
                        >
                          <AlertTriangle className="h-4 w-4" />
                          Report Issue
                        </button>
                      </div>
                      {booking.completion_note ? (
                        <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
                          Completion note: {booking.completion_note}
                        </div>
                      ) : null}
                    </div>
                  </div>

                  {completionBookingId === booking.id ? (
                    <div className="rounded-xl border border-blue-200 bg-blue-50 p-4">
                      <div className="flex flex-wrap items-center gap-2 text-sm font-semibold text-[#0F172A]">
                        <CheckCircle2 className="h-4 w-4 text-[#2563EB]" />
                        Complete Booking
                      </div>
                      <textarea
                        value={completionNote}
                        onChange={(event) => setCompletionNote(event.target.value)}
                        rows={3}
                        placeholder="Add an optional completion note"
                        className="mt-3 w-full rounded-xl border border-gray-200 px-3 py-2 text-sm outline-none focus:border-[#2563EB]"
                      />
                      <label className="mt-3 flex items-center gap-2 text-sm text-gray-700">
                        <input
                          type="checkbox"
                          checked={createTripLog}
                          onChange={(event) => setCreateTripLog(event.target.checked)}
                          className="h-4 w-4 rounded border-gray-300"
                        />
                        Create trip log from this completed booking
                      </label>
                      <div className="mt-3 flex flex-col gap-2 sm:flex-row">
                        <button
                          onClick={() => void submitCompletion(booking.id)}
                          disabled={isActing}
                          className="rounded-xl bg-[#2563EB] px-4 py-2.5 text-sm font-medium text-white transition hover:bg-[#1D4ED8] disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          {isActing ? 'Saving...' : 'Confirm Completion'}
                        </button>
                        <button
                          onClick={() => setCompletionBookingId('')}
                          className="rounded-xl border border-gray-200 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : null}

                  {issueBookingId === booking.id ? (
                    <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
                      <div className="text-sm font-semibold text-[#0F172A]">Report Booking Issue</div>
                      <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
                        <label className="text-sm text-gray-700">
                          <span className="mb-1 block font-medium">Issue Type</span>
                          <select
                            value={issueType}
                            onChange={(event) => setIssueType(event.target.value as (typeof issueTypes)[number])}
                            className="w-full rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm outline-none focus:border-[#2563EB]"
                          >
                            {issueTypes.map((option) => (
                              <option key={option} value={option}>
                                {option}
                              </option>
                            ))}
                          </select>
                        </label>
                        <label className="text-sm text-gray-700 md:col-span-2">
                          <span className="mb-1 block font-medium">Issue Note</span>
                          <textarea
                            value={issueNote}
                            onChange={(event) => setIssueNote(event.target.value)}
                            rows={3}
                            placeholder="Add details for admin and owner review"
                            className="w-full rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm outline-none focus:border-[#2563EB]"
                          />
                        </label>
                      </div>
                      <div className="mt-3 flex flex-col gap-2 sm:flex-row">
                        <button
                          onClick={() => void submitIssue(booking.id)}
                          disabled={isActing}
                          className="rounded-xl bg-amber-500 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-amber-600 disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          {isActing ? 'Submitting...' : 'Submit Issue'}
                        </button>
                        <button
                          onClick={() => setIssueBookingId('')}
                          className="rounded-xl border border-gray-200 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        ) : (
          <div className="px-6 py-16 text-center text-gray-500">
            <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-blue-50">
              <Calendar className="h-6 w-6 text-[#2563EB]" />
            </div>
            No scheduled pickups in this view yet.
          </div>
        )}
      </div>
    </div>
  );
}
