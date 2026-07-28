import { useEffect, useMemo, useState, type ChangeEvent, type ReactNode } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Loader2,
  MapPin,
  Package,
  Phone,
  Route,
  Truck,
  XCircle,
} from 'lucide-react';
import { toast } from 'sonner';
import {
  acceptDriverDispatchJob,
  clarifyDriverDispatchJob,
  confirmDriverDispatchOpeningFuel,
  fetchDriverDispatchJob,
  fetchDriverDispatchWorkspace,
  rejectDriverDispatchJob,
  updateDriverDispatchWorkflow,
  type DriverDispatchJob,
  type DriverDispatchStop,
  type DriverDispatchWorkspacePage,
  type DriverDispatchWorkspaceSummary,
} from '../../lib/driver-api';
import { FuelGaugeSelector } from '../shared/FuelGaugeSelector';
import {
  getDriverDispatchActionState,
  matchesDriverDispatchSection,
  normalizeDriverDispatchWorkflowStatus,
  type DriverDispatchSectionKey,
} from '../../lib/driver-dispatch-ui';

type DispatchSectionConfig = {
  key: DispatchSectionKey;
  title: string;
  description: string;
  emptyLabel: string;
};

const SECTION_CONFIG: DispatchSectionConfig[] = [
  {
    key: 'upcoming',
    title: 'Upcoming Dispatches',
    description: 'Assignments waiting for acceptance or start.',
    emptyLabel: 'No upcoming dispatches right now.',
  },
  {
    key: 'active',
    title: 'Active Dispatch',
    description: 'Dispatches currently in motion.',
    emptyLabel: 'No active dispatch at the moment.',
  },
  {
    key: 'completed',
    title: 'Completed Dispatches',
    description: 'Recently completed dispatch history.',
    emptyLabel: 'No completed dispatches yet.',
  },
  {
    key: 'cancelled',
    title: 'Cancelled / Rejected Dispatches',
    description: 'Dispatches that were rejected or cancelled.',
    emptyLabel: 'No cancelled or rejected dispatches yet.',
  },
];

function formatDateTime(value?: string | null) {
  if (!value) {
    return 'Not scheduled';
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString();
}

function workflowLabel(job: DriverDispatchJob) {
  return normalizeDriverDispatchWorkflowStatus(job)
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function stopOptions(stops: DriverDispatchStop[] | undefined, type: 'complete' | 'deliver') {
  return (stops || []).filter((stop) => {
    if (type === 'complete') {
      return stop.stop_status !== 'completed' && stop.stop_status !== 'cancelled';
    }
    return stop.delivery_status !== 'delivered';
  });
}

function readImageAsDataUrl(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(new Error('Unable to read the selected fuel photo.'));
    reader.readAsDataURL(file);
  });
}

export default function MyDispatches() {
  const [sections, setSections] = useState<Record<DispatchSectionKey, DriverDispatchWorkspacePage | null>>({
    upcoming: null,
    active: null,
    completed: null,
    cancelled: null,
  });
  const [loading, setLoading] = useState<Record<DispatchSectionKey, boolean>>({
    upcoming: false,
    active: false,
    completed: false,
    cancelled: false,
  });
  const [errors, setErrors] = useState<Record<DispatchSectionKey, string>>({
    upcoming: '',
    active: '',
    completed: '',
    cancelled: '',
  });
  const [summary, setSummary] = useState<DriverDispatchWorkspaceSummary | null>(null);
  const [selectedJobId, setSelectedJobId] = useState('');
  const [selectedJob, setSelectedJob] = useState<DriverDispatchJob | null>(null);
  const [detailCache, setDetailCache] = useState<Record<string, DriverDispatchJob>>({});
  const [detailError, setDetailError] = useState('');
  const [isLoadingDetail, setIsLoadingDetail] = useState(false);
  const [actionJobId, setActionJobId] = useState('');
  const [notesByJob, setNotesByJob] = useState<Record<string, string>>({});
  const [selectedStopByJob, setSelectedStopByJob] = useState<Record<string, string>>({});
  const [openingFuelByJob, setOpeningFuelByJob] = useState<Record<string, number | null>>({});
  const [openingOdometerByJob, setOpeningOdometerByJob] = useState<Record<string, string>>({});
  const [openingNoteByJob, setOpeningNoteByJob] = useState<Record<string, string>>({});
  const [openingPhotoByJob, setOpeningPhotoByJob] = useState<Record<string, string>>({});
  const [openingErrorsByJob, setOpeningErrorsByJob] = useState<Record<string, { fuel?: string; odometer?: string }>>({});

  const loadSection = async (section: DispatchSectionKey, page = 1, includeSummary = section === 'upcoming') => {
    setLoading((current) => ({ ...current, [section]: true }));
    setErrors((current) => ({ ...current, [section]: '' }));
    try {
      const response = await fetchDriverDispatchWorkspace({
        section,
        page,
        pageSize: section === 'active' ? 5 : 8,
        includeSummary,
      });
      setSections((current) => ({ ...current, [section]: response }));
      if (response.summary) {
        setSummary(response.summary);
      }
    } catch (error) {
      setErrors((current) => ({
        ...current,
        [section]: error instanceof Error ? error.message : `Unable to load ${section} dispatches right now.`,
      }));
    } finally {
      setLoading((current) => ({ ...current, [section]: false }));
    }
  };

  useEffect(() => {
    void Promise.all(SECTION_CONFIG.map((section, index) => loadSection(section.key, 1, index === 0)));
  }, []);

  const refreshAfterAction = async (sectionKeys: DispatchSectionKey[]) => {
    const uniqueSections = Array.from(new Set<DispatchSectionKey>(['upcoming', ...sectionKeys]));
    await Promise.all(
      uniqueSections.map((section) => loadSection(section, sections[section]?.pagination.page || 1, section === 'upcoming'))
    );
  };

  const replaceJobAcrossSections = (job: DriverDispatchJob) => {
    setSections((current) => {
      const nextSections = { ...current };
      (Object.keys(nextSections) as DispatchSectionKey[]).forEach((sectionKey) => {
        const page = nextSections[sectionKey];
        if (!page) {
          return;
        }
        const otherJobs = (page.jobs || []).filter((item) => item.id !== job.id);
        nextSections[sectionKey] = {
          ...page,
          jobs: matchesDriverDispatchSection(job, sectionKey) ? [job, ...otherJobs] : otherJobs,
        };
      });
      return nextSections;
    });
    setDetailCache((current) => ({ ...current, [job.id]: job }));
    setSelectedJob((current) => (current?.id === job.id ? job : current));
  };

  const syncSummaryForJob = (previousJob: DriverDispatchJob | null, nextJob: DriverDispatchJob) => {
    setSummary((current) => {
      if (!current) {
        return current;
      }
      const wasPendingAcceptance = previousJob?.status === 'assigned' && previousJob?.driver_response_status === 'pending';
      const isPendingAcceptance = nextJob.status === 'assigned' && nextJob.driver_response_status === 'pending';
      const wasUpcoming = previousJob ? matchesDriverDispatchSection(previousJob, 'upcoming') : false;
      const isUpcoming = matchesDriverDispatchSection(nextJob, 'upcoming');
      const wasActive = previousJob ? matchesDriverDispatchSection(previousJob, 'active') : false;
      const isActive = matchesDriverDispatchSection(nextJob, 'active');
      return {
        ...current,
        pending_acceptance: Math.max(0, current.pending_acceptance - (wasPendingAcceptance ? 1 : 0) + (isPendingAcceptance ? 1 : 0)),
        upcoming_dispatches: Math.max(0, current.upcoming_dispatches - (wasUpcoming ? 1 : 0) + (isUpcoming ? 1 : 0)),
        current_active_dispatch: isActive ? nextJob : wasActive ? null : current.current_active_dispatch,
        completed_today:
          nextJob.status === 'completed' && previousJob?.status !== 'completed'
            ? current.completed_today + 1
            : current.completed_today,
      };
    });
  };

  const openDetails = async (jobId: string) => {
    setSelectedJobId(jobId);
    const cachedJob = detailCache[jobId];
    setSelectedJob(cachedJob || null);
    setDetailError('');
    if (cachedJob) {
      return;
    }
    setIsLoadingDetail(true);
    try {
      const job = await fetchDriverDispatchJob(jobId);
      setDetailCache((current) => ({ ...current, [jobId]: job }));
      setSelectedJob(job);
    } catch (error) {
      setDetailError(error instanceof Error ? error.message : 'Unable to load dispatch details right now.');
    } finally {
      setIsLoadingDetail(false);
    }
  };

  const handleAccept = async (jobId: string) => {
    setActionJobId(jobId);
    try {
      const previousJob = sections.upcoming?.jobs.find((item) => item.id === jobId) || selectedJob || null;
      const job = await acceptDriverDispatchJob(jobId);
      replaceJobAcrossSections(job);
      syncSummaryForJob(previousJob, job);
      toast.success('Dispatch accepted successfully.');
      await refreshAfterAction(['upcoming', 'active']);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Unable to accept this dispatch right now.');
    } finally {
      setActionJobId('');
    }
  };

  const handleReject = async (jobId: string) => {
    const reason = (notesByJob[jobId] || '').trim();
    if (!reason) {
      toast.error('A rejection reason is required.');
      return;
    }
    setActionJobId(jobId);
    try {
      const previousJob = sections.upcoming?.jobs.find((item) => item.id === jobId) || selectedJob || null;
      const job = await rejectDriverDispatchJob(jobId, { reason });
      replaceJobAcrossSections(job);
      syncSummaryForJob(previousJob, job);
      setNotesByJob((current) => ({ ...current, [jobId]: '' }));
      toast.success('Dispatch rejected.');
      await refreshAfterAction(['upcoming', 'cancelled']);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Unable to reject this dispatch right now.');
    } finally {
      setActionJobId('');
    }
  };

  const handleClarify = async (jobId: string) => {
    const reason = (notesByJob[jobId] || '').trim();
    if (!reason) {
      toast.error('A clarification note is required.');
      return;
    }
    setActionJobId(jobId);
    try {
      const previousJob = sections.upcoming?.jobs.find((item) => item.id === jobId) || selectedJob || null;
      const job = await clarifyDriverDispatchJob(jobId, { reason });
      replaceJobAcrossSections(job);
      syncSummaryForJob(previousJob, job);
      setNotesByJob((current) => ({ ...current, [jobId]: '' }));
      toast.success('Clarification requested.');
      await refreshAfterAction(['upcoming']);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Unable to request clarification right now.');
    } finally {
      setActionJobId('');
    }
  };

  const handleWorkflow = async (
    jobId: string,
    action: 'start' | 'pause' | 'resume' | 'goods_loaded' | 'stop_completed' | 'delivery_completed' | 'end'
  ) => {
    const note = (notesByJob[jobId] || '').trim();
    const stopId = selectedStopByJob[jobId] || undefined;
    if ((action === 'stop_completed' || action === 'delivery_completed') && !stopId) {
      toast.error('Choose a stop first.');
      return;
    }
    setActionJobId(jobId);
    try {
      const previousJob =
        sections.upcoming?.jobs.find((item) => item.id === jobId)
        || sections.active?.jobs.find((item) => item.id === jobId)
        || selectedJob
        || null;
      const job = await updateDriverDispatchWorkflow(jobId, {
        action,
        note: note || undefined,
        stop_id: stopId,
      });
      replaceJobAcrossSections(job);
      syncSummaryForJob(previousJob, job);
      if (action !== 'pause' && action !== 'resume') {
        setNotesByJob((current) => ({ ...current, [jobId]: '' }));
      }
      if (action === 'stop_completed' || action === 'delivery_completed') {
        setSelectedStopByJob((current) => ({ ...current, [jobId]: '' }));
      }
      toast.success('Dispatch updated.');
      await refreshAfterAction(action === 'end' ? ['active', 'completed'] : ['active']);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Unable to update this dispatch right now.');
    } finally {
      setActionJobId('');
    }
  };

  const handleOpeningFuel = async (job: DriverDispatchJob) => {
    const openingFuel = openingFuelByJob[job.id];
    const openingOdometer = openingOdometerByJob[job.id] || '';
    const nextErrors: { fuel?: string; odometer?: string } = {};
    if (openingFuel == null) {
      nextErrors.fuel = 'Opening fuel level is required.';
    }
    if (openingOdometer !== '' && (!Number.isFinite(Number(openingOdometer)) || Number(openingOdometer) < 0)) {
      nextErrors.odometer = 'Opening odometer must be a non-negative number when recorded.';
    }
    if (Object.keys(nextErrors).length) {
      setOpeningErrorsByJob((current) => ({ ...current, [job.id]: nextErrors }));
      return;
    }
    setActionJobId(job.id);
    try {
      await confirmDriverDispatchOpeningFuel(job.id, {
        opening_fuel_level: openingFuel as number,
        opening_odometer: openingOdometer === '' ? undefined : Number(openingOdometer),
        inspection_note: openingNoteByJob[job.id] || undefined,
        opening_fuel_photo: openingPhotoByJob[job.id] || undefined,
      });
      setOpeningErrorsByJob((current) => ({ ...current, [job.id]: {} }));
      toast.success('Opening fuel and odometer confirmed.');
      await refreshAfterAction(['upcoming']);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unable to confirm opening fuel right now.';
      setOpeningErrorsByJob((current) => ({
        ...current,
        [job.id]: /odometer/i.test(message) ? { odometer: message } : { fuel: message },
      }));
      toast.error(message);
    } finally {
      setActionJobId('');
    }
  };

  const summaryCards = useMemo(
    () => [
      { label: "Today's Dispatches", value: summary?.todays_dispatches || 0, accent: 'bg-blue-50 text-blue-700' },
      { label: 'Upcoming Dispatches', value: summary?.upcoming_dispatches || 0, accent: 'bg-amber-50 text-amber-700' },
      { label: 'Current Active Dispatch', value: summary?.current_active_dispatch ? 1 : 0, accent: 'bg-emerald-50 text-emerald-700' },
      { label: 'Pending Acceptance', value: summary?.pending_acceptance || 0, accent: 'bg-rose-50 text-rose-700' },
      { label: 'Completed Today', value: summary?.completed_today || 0, accent: 'bg-slate-100 text-slate-700' },
    ],
    [summary]
  );

  return (
    <div className="space-y-6 p-4 sm:p-6">
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-slate-900">My Dispatches</h1>
            <p className="text-sm text-slate-500">Receive, manage, and complete dispatch assignments without leaving the driver portal.</p>
          </div>
          <button
            type="button"
            onClick={() => void Promise.all(SECTION_CONFIG.map((section, index) => loadSection(section.key, sections[section.key]?.pagination.page || 1, index === 0)))}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            <Route className="h-4 w-4" />
            Refresh Dispatches
          </button>
        </div>

        <div className="mt-5 grid grid-cols-1 gap-4 md:grid-cols-5">
          {summaryCards.map((card) => (
            <button
              key={card.label}
              type="button"
              className={`rounded-xl px-4 py-4 text-left ${card.accent}`}
              onClick={() => {
                const targetSection =
                  card.label === 'Completed Today'
                    ? 'completed'
                    : card.label === 'Current Active Dispatch'
                      ? 'active'
                      : 'upcoming';
                document.getElementById(`dispatch-section-${targetSection}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
              }}
            >
              <div className="text-2xl font-semibold">{card.value}</div>
              <div className="mt-1 text-sm">{card.label}</div>
            </button>
          ))}
        </div>
      </div>

      {SECTION_CONFIG.map((section) => {
        const page = sections[section.key];
        const jobs = page?.jobs || [];
        const isBusy = loading[section.key];
        return (
          <section key={section.key} id={`dispatch-section-${section.key}`} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex flex-col gap-2 border-b border-slate-100 pb-4 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <h2 className="text-lg font-semibold text-slate-900">{section.title}</h2>
                <p className="text-sm text-slate-500">{section.description}</p>
              </div>
              <button
                type="button"
                onClick={() => void loadSection(section.key, page?.pagination.page || 1, section.key === 'upcoming')}
                className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50"
              >
                {isBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Clock3 className="h-4 w-4" />}
                Refresh
              </button>
            </div>

            {errors[section.key] ? (
              <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{errors[section.key]}</div>
            ) : null}

            <div className="mt-5 space-y-4">
              {isBusy && !jobs.length ? (
                <>
                  <div className="h-32 animate-pulse rounded-xl bg-slate-100" />
                  <div className="h-32 animate-pulse rounded-xl bg-slate-100" />
                </>
              ) : jobs.length ? (
                jobs.map((job) => (
                  <article key={job.id} className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                    <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                      <div>
                        <div className="text-xs font-semibold uppercase tracking-[0.18em] text-blue-600">{job.dispatch_job_id}</div>
                        <h3 className="mt-2 text-lg font-semibold text-slate-900">
                          {job.pickup || 'Pickup pending'} to {job.destination || 'Destination pending'}
                        </h3>
                        <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-600">
                          <span className="rounded-full bg-white px-2.5 py-1 ring-1 ring-slate-200">{workflowLabel(job)}</span>
                          <span className="rounded-full bg-white px-2.5 py-1 ring-1 ring-slate-200">{formatDateTime(job.scheduled_start_time)}</span>
                          <span className="rounded-full bg-white px-2.5 py-1 ring-1 ring-slate-200">{job.vehicle?.registration_number || 'Vehicle pending'}</span>
                          <span className="rounded-full bg-white px-2.5 py-1 ring-1 ring-slate-200">{job.driver_response_status}</span>
                        </div>
                      </div>
                      <div className="rounded-xl bg-white px-4 py-3 text-sm text-slate-600 ring-1 ring-slate-200">
                        <div className="font-medium text-slate-900">Expected Return</div>
                        <div className="mt-1">{formatDateTime(job.expected_return_time)}</div>
                      </div>
                    </div>

                    <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                      <MiniInfo icon={MapPin} label="Pickup" value={job.pickup || 'Not set'} />
                      <MiniInfo icon={Truck} label="Destination" value={job.destination || 'Not set'} />
                      <MiniInfo icon={Package} label="Goods" value={job.goods_description || 'Not provided'} />
                      <MiniInfo icon={Phone} label="Customer Contact" value={job.customer_contact || 'Not provided'} />
                    </div>

                    {job.status === 'accepted' ? (
                      job.fuel_accountability?.opening_fuel_recorded_at ? (
                        <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
                          Opening fuel {job.fuel_accountability.opening_fuel_level}/8 confirmed. {job.fuel_accountability.opening_odometer != null ? `Odometer ${job.fuel_accountability.opening_odometer.toLocaleString()} recorded.` : 'Distance unavailable — odometer not recorded.'} This vehicle is ready to start.
                        </div>
                      ) : (
                        <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4">
                          <div className="font-semibold text-amber-900">Opening Fuel &amp; Odometer</div>
                          <p className="mt-1 text-sm text-amber-800">Record the opening fuel level before starting this dispatch. Odometer is optional.</p>
                          <div className="mt-4 grid gap-4 lg:grid-cols-2">
                            <FuelGaugeSelector
                              label="Opening Fuel Level"
                              value={openingFuelByJob[job.id] ?? null}
                              onChange={(value) => {
                                setOpeningFuelByJob((current) => ({ ...current, [job.id]: value }));
                                setOpeningErrorsByJob((current) => ({ ...current, [job.id]: { ...current[job.id], fuel: undefined } }));
                              }}
                              required
                              compact
                              error={openingErrorsByJob[job.id]?.fuel}
                              showEstimatedLitres
                              tankCapacityLitres={job.vehicle?.tank_capacity_litres}
                            />
                            <div className="space-y-3">
                              <label className="block text-sm font-medium text-slate-700">
                                Opening Odometer (Optional)
                                <input
                                  type="number"
                                  min="0"
                                  value={openingOdometerByJob[job.id] || ''}
                                  onChange={(event) => {
                                    setOpeningOdometerByJob((current) => ({ ...current, [job.id]: event.target.value }));
                                    setOpeningErrorsByJob((current) => ({ ...current, [job.id]: { ...current[job.id], odometer: undefined } }));
                                  }}
                                  className={`mt-1 w-full rounded-lg border bg-white px-3 py-2.5 text-sm ${openingErrorsByJob[job.id]?.odometer ? 'border-rose-300' : 'border-slate-200'}`}
                                />
                              </label>
                              {openingErrorsByJob[job.id]?.odometer ? <p className="text-sm text-rose-600">{openingErrorsByJob[job.id]?.odometer}</p> : null}
                              <label className="block text-sm font-medium text-slate-700">
                                Inspection Note
                                <textarea
                                  rows={2}
                                  value={openingNoteByJob[job.id] || ''}
                                  onChange={(event) => setOpeningNoteByJob((current) => ({ ...current, [job.id]: event.target.value }))}
                                  className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm"
                                  placeholder="Optional pre-dispatch inspection note"
                                />
                              </label>
                              <label className="block text-sm font-medium text-slate-700">
                                Fuel-level Photo
                                <input
                                  type="file"
                                  accept="image/jpeg,image/png,image/webp"
                                  onChange={(event: ChangeEvent<HTMLInputElement>) => {
                                    const file = event.target.files?.[0];
                                    if (!file) {
                                      setOpeningPhotoByJob((current) => ({ ...current, [job.id]: '' }));
                                      return;
                                    }
                                    void readImageAsDataUrl(file)
                                      .then((value) => setOpeningPhotoByJob((current) => ({ ...current, [job.id]: value })))
                                      .catch((error) => toast.error(error instanceof Error ? error.message : 'Unable to read fuel photo.'));
                                  }}
                                  className="mt-1 block w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm"
                                />
                              </label>
                              <button
                                type="button"
                                disabled={actionJobId === job.id}
                                onClick={() => void handleOpeningFuel(job)}
                                className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-amber-600 px-4 py-2.5 text-sm font-medium text-white disabled:opacity-60"
                              >
                                {actionJobId === job.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                                Confirm Opening Reading
                              </button>
                            </div>
                          </div>
                        </div>
                      )
                    ) : null}

                    <div className="mt-4 grid gap-3 lg:grid-cols-[1fr_auto]">
                      <div className="space-y-3">
                        <textarea
                          value={notesByJob[job.id] || ''}
                          onChange={(event) => setNotesByJob((current) => ({ ...current, [job.id]: event.target.value }))}
                          placeholder={
                            section.key === 'cancelled'
                              ? 'Rejection or cancellation notes'
                              : 'Optional dispatch note, rejection reason, stop note, or delivery note'
                          }
                          rows={2}
                          className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm outline-none transition focus:border-blue-300"
                        />
                        {(section.key === 'active' || section.key === 'completed') && stopOptions(job.stops, 'complete').length ? (
                          <select
                            value={selectedStopByJob[job.id] || ''}
                            onChange={(event) => setSelectedStopByJob((current) => ({ ...current, [job.id]: event.target.value }))}
                            className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm"
                          >
                            <option value="">Select stop for progress update</option>
                            {(job.stops || []).map((stop) => (
                              <option key={stop.stop_id} value={stop.stop_id}>
                                Stop {stop.stop_sequence || '-'} • {stop.location || stop.stop_type || 'Planned stop'}
                              </option>
                            ))}
                          </select>
                        ) : null}
                      </div>

                      <div className="flex flex-wrap gap-2 lg:max-w-[320px] lg:justify-end">
                        {(() => {
                          const actionState = getDriverDispatchActionState(job);
                          return (
                            <>
                        <button
                          type="button"
                          onClick={() => void openDetails(job.id)}
                          className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
                        >
                          <Route className="h-4 w-4" />
                          View Details
                        </button>

                        {actionState.canAccept ? (
                          <>
                            <ActionButton
                              busy={actionJobId === job.id}
                              icon={CheckCircle2}
                              label="Accept Dispatch"
                              onClick={() => void handleAccept(job.id)}
                              tone="success"
                            />
                          </>
                        ) : null}

                        {actionState.canReject ? (
                          <>
                            <ActionButton
                              busy={actionJobId === job.id}
                              icon={XCircle}
                              label="Reject Dispatch"
                              onClick={() => void handleReject(job.id)}
                              tone="danger"
                            />
                          </>
                        ) : null}

                        {actionState.canClarify ? (
                          <ActionButton
                            busy={actionJobId === job.id}
                            icon={AlertTriangle}
                            label="Request Clarification"
                            onClick={() => void handleClarify(job.id)}
                            tone="warning"
                          />
                        ) : null}

                        {actionState.canStart ? (
                          <ActionButton busy={actionJobId === job.id} icon={Route} label="Start Dispatch" onClick={() => void handleWorkflow(job.id, 'start')} tone="primary" />
                        ) : null}
                        {actionState.canPause || actionState.canResume || actionState.canMarkGoodsLoaded || actionState.canMarkStopCompleted || actionState.canMarkDeliveryCompleted || actionState.canEnd ? (
                          <>
                            {actionState.canPause ? (
                              <ActionButton busy={actionJobId === job.id} icon={AlertTriangle} label="Pause Dispatch" onClick={() => void handleWorkflow(job.id, 'pause')} tone="warning" />
                            ) : null}
                            {actionState.canResume ? (
                              <ActionButton busy={actionJobId === job.id} icon={CheckCircle2} label="Resume Dispatch" onClick={() => void handleWorkflow(job.id, 'resume')} tone="primary" />
                            ) : null}
                            {actionState.canMarkGoodsLoaded ? (
                              <ActionButton busy={actionJobId === job.id} icon={Package} label="Mark Goods Loaded" onClick={() => void handleWorkflow(job.id, 'goods_loaded')} tone="primary" />
                            ) : null}
                            {actionState.canMarkStopCompleted && stopOptions(job.stops, 'complete').length ? (
                              <ActionButton busy={actionJobId === job.id} icon={CheckCircle2} label="Mark Stop Completed" onClick={() => void handleWorkflow(job.id, 'stop_completed')} tone="primary" />
                            ) : null}
                            {actionState.canMarkDeliveryCompleted ? (
                              <ActionButton busy={actionJobId === job.id} icon={Truck} label="Mark Delivery Completed" onClick={() => void handleWorkflow(job.id, 'delivery_completed')} tone="success" />
                            ) : null}
                            {actionState.canEnd ? (
                              <ActionButton busy={actionJobId === job.id} icon={CheckCircle2} label="End Dispatch" onClick={() => void handleWorkflow(job.id, 'end')} tone="dark" />
                            ) : null}
                          </>
                        ) : null}
                            </>
                          );
                        })()}
                      </div>
                    </div>
                  </article>
                ))
              ) : (
                <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">
                  {section.emptyLabel}
                </div>
              )}
            </div>

            {page?.pagination && page.pagination.total_pages > 1 ? (
              <div className="mt-5 flex items-center justify-between border-t border-slate-100 pt-4">
                <div className="text-sm text-slate-500">
                  Page {page.pagination.page} of {page.pagination.total_pages}
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    disabled={page.pagination.page <= 1 || loading[section.key]}
                    onClick={() => void loadSection(section.key, page.pagination.page - 1, section.key === 'upcoming')}
                    className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <ChevronLeft className="h-4 w-4" />
                    Previous
                  </button>
                  <button
                    type="button"
                    disabled={page.pagination.page >= page.pagination.total_pages || loading[section.key]}
                    onClick={() => void loadSection(section.key, page.pagination.page + 1, section.key === 'upcoming')}
                    className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    Next
                    <ChevronRight className="h-4 w-4" />
                  </button>
                </div>
              </div>
            ) : null}
          </section>
        );
      })}

      {selectedJobId ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-4">
          <div className="max-h-[92vh] w-full max-w-5xl overflow-y-auto rounded-2xl bg-white shadow-2xl">
            <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-5 py-4">
              <div>
                <h3 className="text-lg font-semibold text-slate-900">{selectedJob?.dispatch_job_id || 'Dispatch Details'}</h3>
                <p className="mt-1 text-sm text-slate-500">Review route, cargo, contacts, and timeline before the next action.</p>
              </div>
              <button type="button" onClick={() => setSelectedJobId('')} className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 hover:text-slate-700">
                <XCircle className="h-5 w-5" />
              </button>
            </div>

            <div className="px-5 py-5">
              {isLoadingDetail ? (
                <div className="space-y-3">
                  <div className="h-24 animate-pulse rounded-xl bg-slate-100" />
                  <div className="h-24 animate-pulse rounded-xl bg-slate-100" />
                  <div className="h-40 animate-pulse rounded-xl bg-slate-100" />
                </div>
              ) : detailError ? (
                <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{detailError}</div>
              ) : selectedJob ? (
                <div className="space-y-6">
                  <div className="grid gap-4 lg:grid-cols-2">
                    <DetailGroup title="Route">
                      <DetailItem label="Pickup" value={selectedJob.pickup || 'Not provided'} />
                      <DetailItem label="Destination" value={selectedJob.destination || 'Not provided'} />
                      <DetailItem label="Planned Stops" value={(selectedJob.stops || []).length ? `${selectedJob.stops?.length} stop(s)` : 'No planned stops'} />
                    </DetailGroup>
                    <DetailGroup title="Cargo">
                      <DetailItem label="Goods Description" value={selectedJob.goods_description || 'Not provided'} />
                      <DetailItem label="Quantity" value={selectedJob.quantity || 'Not provided'} />
                      <DetailItem label="Weight Category" value={selectedJob.weight_category || 'Not provided'} />
                      <DetailItem label="Loading Notes" value={selectedJob.loading_notes || 'Not provided'} />
                    </DetailGroup>
                  </div>

                  <div className="grid gap-4 lg:grid-cols-2">
                    <DetailGroup title="Contacts">
                      <DetailItem label="Customer Name" value={selectedJob.customer_contact || 'Not provided'} />
                      <DetailItem label="Customer Phone" value={selectedJob.customer_contact || 'Not provided'} />
                      <DetailItem label="Receiver Name" value={selectedJob.receiver_contact || 'Not provided'} />
                      <DetailItem label="Receiver Phone" value={selectedJob.receiver_contact || 'Not provided'} />
                    </DetailGroup>
                    <DetailGroup title="Operational Instructions">
                      <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
                        {selectedJob.dispatch_instructions || 'No operational instructions were recorded.'}
                      </div>
                    </DetailGroup>
                  </div>

                  <DetailGroup title="Dispatch Timeline">
                    <div className="space-y-3">
                      {(selectedJob.timeline || []).length ? (
                        selectedJob.timeline?.map((entry) => (
                          <div key={entry.event_id} className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
                            <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
                              <div className="font-medium text-slate-900">{entry.title}</div>
                              <div className="text-xs uppercase tracking-[0.16em] text-slate-500">{formatDateTime(entry.timestamp)}</div>
                            </div>
                            <div className="mt-1 text-sm text-slate-600">{entry.status.replaceAll('_', ' ')}</div>
                            {entry.note ? <div className="mt-2 text-sm text-slate-500">{entry.note}</div> : null}
                          </div>
                        ))
                      ) : (
                        <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
                          Timeline entries will appear as this dispatch progresses.
                        </div>
                      )}
                    </div>
                  </DetailGroup>
                </div>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function MiniInfo({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof MapPin;
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-xl bg-white p-3 ring-1 ring-slate-200">
      <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </div>
      <div className="mt-2 text-sm text-slate-700">{value}</div>
    </div>
  );
}

function ActionButton({
  busy,
  icon: Icon,
  label,
  onClick,
  tone,
}: {
  busy: boolean;
  icon: typeof Route;
  label: string;
  onClick: () => void;
  tone: 'primary' | 'success' | 'warning' | 'danger' | 'dark';
}) {
  const className = {
    primary: 'bg-blue-600 text-white',
    success: 'bg-emerald-600 text-white',
    warning: 'border border-amber-200 bg-amber-50 text-amber-700',
    danger: 'border border-rose-200 bg-rose-50 text-rose-700',
    dark: 'bg-slate-900 text-white',
  }[tone];

  return (
    <button type="button" onClick={onClick} disabled={busy} className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-60 ${className}`}>
      {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Icon className="h-4 w-4" />}
      {label}
    </button>
  );
}

function DetailGroup({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4">
      <h4 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500">{title}</h4>
      <div className="mt-4 space-y-3">{children}</div>
    </div>
  );
}

function DetailItem({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-xl bg-slate-50 px-4 py-3">
      <div className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">{label}</div>
      <div className="mt-1 text-sm text-slate-700">{value}</div>
    </div>
  );
}
