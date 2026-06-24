import { ChangeEvent, useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react';
import {
  AlertTriangle,
  Camera,
  CheckCircle2,
  FilePlus2,
  Loader2,
  Mail,
  Phone,
  Search,
  ShieldAlert,
  Wrench,
} from 'lucide-react';
import { apiRequest, ApiRequestError, isRequestAborted } from '../../lib/api';
import type { SessionUser } from '../../lib/auth-session';
import type { DriverActiveAssignment } from '../../lib/driver-api';
import { useDebouncedValue } from '../../lib/use-debounced-value';

type IncidentRole = 'owner' | 'admin' | 'driver';

type IncidentStatus =
  | 'reported'
  | 'under_review'
  | 'police_report_pending'
  | 'insurance_notified'
  | 'claim_submitted'
  | 'assessment_scheduled'
  | 'repair_approved'
  | 'repair_in_progress'
  | 'resolved'
  | 'rejected'
  | 'closed';

type IncidentType =
  | 'accident'
  | 'breakdown'
  | 'theft'
  | 'fire'
  | 'third_party_damage'
  | 'injury'
  | 'other';

interface IncidentAttachment {
  id: string;
  name: string;
  file_name: string;
  file_kind: string;
  content_type?: string | null;
  data_url: string;
  size_bytes?: number | null;
}

interface SimpleVehicle {
  id: string;
  registration_number: string;
  make?: string | null;
  model?: string | null;
  status?: string | null;
}

interface SimpleDriver {
  id: string;
  full_name: string;
  phone?: string | null;
}

interface IncidentRecord {
  id: string;
  vehicle_id: string;
  driver_id: string;
  replacement_vehicle_id?: string | null;
  maintenance_job_id?: string | null;
  incident_type: IncidentType;
  status: IncidentStatus;
  incident_at: string;
  location: string;
  description: string;
  can_vehicle_move: boolean;
  third_party_involved: boolean;
  witness_name?: string | null;
  witness_phone?: string | null;
  police_station?: string | null;
  police_report_number?: string | null;
  attachments: IncidentAttachment[];
  investigation_notes: Array<{
    id: string;
    note: string;
    created_at: string;
    created_by: string;
    created_by_role: string;
  }>;
  claim_number?: string | null;
  claim_submitted_date?: string | null;
  assessment_date?: string | null;
  claim_status?: string | null;
  repair_cost?: number | null;
  insurance_approved_amount?: number | null;
  paid_amount?: number | null;
  outstanding_claim?: number | null;
  downtime_start_date?: string | null;
  downtime_end_date?: string | null;
  downtime_days?: number | null;
  estimated_revenue_lost?: number | null;
  vehicle_status_after_incident?: string | null;
  emergency_checklist: string[];
  vehicle?: SimpleVehicle | null;
  replacement_vehicle?: SimpleVehicle | null;
  driver?: SimpleDriver | null;
  insurance_claim?: {
    company?: string | null;
    policy_number?: string | null;
    insurance_type?: string | null;
    expiry_date?: string | null;
    claims_officer_name?: string | null;
    claims_officer_phone?: string | null;
    claims_officer_email?: string | null;
    emergency_contact?: string | null;
    status?: 'Active' | 'Expired' | 'Missing' | string;
    claim_eligibility?: string | null;
    eligibility_reason?: string | null;
    eligibility_overridden?: boolean;
    eligibility_override_reason?: string | null;
    claim_number?: string | null;
    claim_submitted_date?: string | null;
    assessment_date?: string | null;
    claim_status?: string | null;
    insurance_notified?: boolean;
  } | null;
  audit_logs: Array<{
    id: string;
    action: string;
    actor_role: string;
    note?: string | null;
    reason?: string | null;
    changes: string[];
    created_at: string;
  }>;
}

interface IncidentsResponse {
  success: boolean;
  data: {
    incidents: IncidentRecord[];
    dashboard: {
      total_incidents: number;
      open_incidents: number;
      repair_cost: number;
      insurance_approved_amount: number;
      amount_paid: number;
      outstanding_claim: number;
      downtime_days: number;
      estimated_revenue_lost: number;
    };
    high_risk_drivers: Array<{
      driver_id: string;
      driver_name?: string | null;
      incident_count: number;
      open_incidents: number;
      downtime_days: number;
      estimated_revenue_lost: number;
      critical_incidents: number;
    }>;
    insurance_directory: Array<{
      vehicle_id: string;
      vehicle?: SimpleVehicle | null;
      insurance_company?: string | null;
      policy_number?: string | null;
      insurance_type?: string | null;
      claims_officer_name?: string | null;
      claims_officer_phone?: string | null;
      claims_officer_email?: string | null;
      emergency_contact?: string | null;
      renewal_date?: string | null;
      status?: string | null;
    }>;
    alerts: Array<{
      type: string;
      message: string;
      vehicle_registration_number?: string | null;
    }>;
    status_options: string[];
  };
}

interface VehiclesResponse {
  success: boolean;
  data: {
    vehicles: SimpleVehicle[];
  };
}

interface IncidentMutationResponse {
  success: boolean;
  data: {
    incident: IncidentRecord;
  };
}

interface IncidentMaintenanceResponse {
  success: boolean;
  data: {
    incident: IncidentRecord;
    job: {
      id: string;
    };
  };
}

interface ReportIncidentFormState {
  incident_type: IncidentType;
  incident_at: string;
  location: string;
  description: string;
  can_vehicle_move: boolean;
  third_party_involved: boolean;
  witness_name: string;
  witness_phone: string;
  police_station: string;
  police_report_number: string;
  attachments: IncidentAttachment[];
}

interface UpdateFormState {
  status: IncidentStatus;
  investigation_note: string;
  claim_number: string;
  claim_submitted_date: string;
  assessment_date: string;
  claim_status: string;
  repair_cost: string;
  insurance_approved_amount: string;
  paid_amount: string;
  downtime_start_date: string;
  downtime_end_date: string;
  estimated_revenue_lost: string;
  replacement_vehicle_id: string;
  vehicle_status_after_incident: string;
  insurance_notified: boolean;
  claim_eligibility_override: string;
  claim_eligibility_override_reason: string;
  attachments: IncidentAttachment[];
}

const initialReportForm: ReportIncidentFormState = {
  incident_type: 'accident',
  incident_at: new Date().toISOString().slice(0, 16),
  location: '',
  description: '',
  can_vehicle_move: false,
  third_party_involved: false,
  witness_name: '',
  witness_phone: '',
  police_station: '',
  police_report_number: '',
  attachments: [],
};

const initialUpdateForm: UpdateFormState = {
  status: 'under_review',
  investigation_note: '',
  claim_number: '',
  claim_submitted_date: '',
  assessment_date: '',
  claim_status: 'under_review',
  repair_cost: '',
  insurance_approved_amount: '',
  paid_amount: '',
  downtime_start_date: '',
  downtime_end_date: '',
  estimated_revenue_lost: '',
  replacement_vehicle_id: '',
  vehicle_status_after_incident: 'accident',
  insurance_notified: false,
  claim_eligibility_override: '',
  claim_eligibility_override_reason: '',
  attachments: [],
};

function formatDateTime(value?: string | null) {
  if (!value) return '-';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function formatDate(value?: string | null) {
  if (!value) return '-';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString();
}

function formatLabel(value?: string | null) {
  if (!value) return '-';
  return value
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function formatCurrency(value?: number | null) {
  if (typeof value !== 'number' || Number.isNaN(value)) return '-';
  return `GHS ${value.toLocaleString()}`;
}

function toAttachment(file: File, dataUrl: string): IncidentAttachment {
  const fileKind = file.type.startsWith('image/')
    ? 'photo'
    : file.type.startsWith('video/')
      ? 'video'
      : 'document';
  return {
    id: `${file.name}-${file.lastModified}`,
    name: file.name,
    file_name: file.name,
    file_kind: fileKind,
    content_type: file.type,
    data_url: dataUrl,
    size_bytes: file.size,
  };
}

async function filesToAttachments(files: File[]): Promise<IncidentAttachment[]> {
  return Promise.all(
    files.map(
      (file) =>
        new Promise<IncidentAttachment>((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(toAttachment(file, typeof reader.result === 'string' ? reader.result : ''));
          reader.onerror = () => reject(new Error('Unable to read file.'));
          reader.readAsDataURL(file);
        }),
    ),
  );
}

export default function IncidentsModule({
  role,
  currentUser,
  activeAssignment,
}: {
  role: IncidentRole;
  currentUser?: SessionUser | null;
  activeAssignment?: DriverActiveAssignment | null;
}) {
  const [incidents, setIncidents] = useState<IncidentRecord[]>([]);
  const [vehicles, setVehicles] = useState<SimpleVehicle[]>([]);
  const [dashboard, setDashboard] = useState<IncidentsResponse['data']['dashboard'] | null>(null);
  const [highRiskDrivers, setHighRiskDrivers] = useState<IncidentsResponse['data']['high_risk_drivers']>([]);
  const [insuranceDirectory, setInsuranceDirectory] = useState<IncidentsResponse['data']['insurance_directory']>([]);
  const [alerts, setAlerts] = useState<IncidentsResponse['data']['alerts']>([]);
  const [statusOptions, setStatusOptions] = useState<string[]>([]);
  const [selectedIncidentId, setSelectedIncidentId] = useState<string | null>(null);
  const [reportForm, setReportForm] = useState<ReportIncidentFormState>(initialReportForm);
  const [updateForm, setUpdateForm] = useState<UpdateFormState>(initialUpdateForm);
  const [pageError, setPageError] = useState('');
  const [formError, setFormError] = useState('');
  const [successMessage, setSuccessMessage] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showChecklist, setShowChecklist] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const debouncedSearchQuery = useDebouncedValue(searchQuery, 250);

  const filteredIncidents = useMemo(() => {
    const query = debouncedSearchQuery.trim().toLowerCase();
    if (!query) {
      return incidents;
    }
    return incidents.filter((incident) =>
      [
        incident.vehicle?.registration_number,
        incident.driver?.full_name,
        incident.driver?.phone,
        incident.status,
        incident.incident_type,
        incident.location,
        incident.description,
        incident.claim_number,
        incident.police_report_number,
      ]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(query)),
    );
  }, [debouncedSearchQuery, incidents]);

  const selectedIncident = useMemo(
    () => filteredIncidents.find((incident) => incident.id === selectedIncidentId) || filteredIncidents[0] || null,
    [filteredIncidents, selectedIncidentId],
  );

  useEffect(() => {
    const loadData = async () => {
      setIsLoading(true);
      setPageError('');
      try {
        const incidentsRequest = apiRequest<IncidentsResponse>('/incidents', {
          cacheTtlMs: 10000,
          dedupeKey: `incidents-${role}`,
          componentName: 'IncidentsModule',
          requestLabel: 'incidents-primary',
        });
        const vehiclesRequest =
          role !== 'driver'
            ? apiRequest<VehiclesResponse>('/vehicles', {
                cacheTtlMs: 10000,
                dedupeKey: 'incidents-vehicles',
                componentName: 'IncidentsModule',
                requestLabel: 'incident-vehicle-options',
              })
            : Promise.resolve(null);

        const [incidentsResult, vehiclesResult] = await Promise.allSettled([incidentsRequest, vehiclesRequest]);
        if (incidentsResult.status === 'rejected') {
          throw incidentsResult.reason;
        }

        const incidentsResponse = incidentsResult.value;
        setIncidents(Array.isArray(incidentsResponse.data?.incidents) ? incidentsResponse.data.incidents : []);
        setDashboard(incidentsResponse.data?.dashboard || null);
        setHighRiskDrivers(incidentsResponse.data?.high_risk_drivers || []);
        setInsuranceDirectory(incidentsResponse.data?.insurance_directory || []);
        setAlerts(incidentsResponse.data?.alerts || []);
        setStatusOptions(incidentsResponse.data?.status_options || []);
        setSelectedIncidentId((current) => current || incidentsResponse.data?.incidents?.[0]?.id || null);

        if (vehiclesResult.status === 'fulfilled' && vehiclesResult.value?.data?.vehicles) {
          setVehicles(vehiclesResult.value.data.vehicles);
        } else if (vehiclesResult.status === 'rejected') {
          console.warn('[Flux Incidents] Vehicle directory failed to load.', vehiclesResult.reason);
        }
      } catch (error) {
        if (!isRequestAborted(error)) {
          setPageError(error instanceof ApiRequestError ? error.message : 'Unable to load incidents right now.');
        }
      } finally {
        setIsLoading(false);
      }
    };
    void loadData();
  }, [role]);

  useEffect(() => {
    if (!selectedIncident) return;
    setUpdateForm({
      status: selectedIncident.status,
      investigation_note: '',
      claim_number: selectedIncident.claim_number || selectedIncident.insurance_claim?.claim_number || '',
      claim_submitted_date: selectedIncident.claim_submitted_date || selectedIncident.insurance_claim?.claim_submitted_date || '',
      assessment_date: selectedIncident.assessment_date || selectedIncident.insurance_claim?.assessment_date || '',
      claim_status: selectedIncident.claim_status || selectedIncident.insurance_claim?.claim_status || 'under_review',
      repair_cost: selectedIncident.repair_cost != null ? String(selectedIncident.repair_cost) : '',
      insurance_approved_amount: selectedIncident.insurance_approved_amount != null ? String(selectedIncident.insurance_approved_amount) : '',
      paid_amount: selectedIncident.paid_amount != null ? String(selectedIncident.paid_amount) : '',
      downtime_start_date: selectedIncident.downtime_start_date || '',
      downtime_end_date: selectedIncident.downtime_end_date || '',
      estimated_revenue_lost: selectedIncident.estimated_revenue_lost != null ? String(selectedIncident.estimated_revenue_lost) : '',
      replacement_vehicle_id: selectedIncident.replacement_vehicle_id || '',
      vehicle_status_after_incident: selectedIncident.vehicle_status_after_incident || 'accident',
      insurance_notified: Boolean(selectedIncident.insurance_claim?.insurance_notified),
      claim_eligibility_override: '',
      claim_eligibility_override_reason: '',
      attachments: [],
    });
  }, [selectedIncident]);

  const driverVehicleLabel = activeAssignment?.vehicle
    ? `${activeAssignment.vehicle.registration_number} ${activeAssignment.vehicle.make || ''} ${activeAssignment.vehicle.model || ''}`.trim()
    : 'No assigned vehicle';

  const replacementVehicleOptions = useMemo(
    () => vehicles.filter((vehicle) => vehicle.status === 'available' || vehicle.id === selectedIncident?.replacement_vehicle_id),
    [selectedIncident?.replacement_vehicle_id, vehicles],
  );

  const handleRefresh = async () => {
    setIsLoading(true);
    setPageError('');
    try {
      const response = await apiRequest<IncidentsResponse>('/incidents', {
        cacheTtlMs: 5000,
        dedupeKey: `incidents-${role}`,
        componentName: 'IncidentsModule',
        requestLabel: 'incidents-refresh',
      });
      setIncidents(response.data?.incidents || []);
      setDashboard(response.data?.dashboard || null);
      setHighRiskDrivers(response.data?.high_risk_drivers || []);
      setInsuranceDirectory(response.data?.insurance_directory || []);
      setAlerts(response.data?.alerts || []);
      setStatusOptions(response.data?.status_options || []);
    } catch (error) {
      if (!isRequestAborted(error)) {
        setPageError(error instanceof ApiRequestError ? error.message : 'Unable to refresh incidents right now.');
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleReportAttachmentUpload = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || []);
    if (!files.length) return;
    try {
      const attachments = await filesToAttachments(files);
      setReportForm((current) => ({ ...current, attachments: [...current.attachments, ...attachments] }));
    } catch {
      setFormError('One or more files could not be read. Please try again.');
    }
  };

  const handleUpdateAttachmentUpload = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || []);
    if (!files.length) return;
    try {
      const attachments = await filesToAttachments(files);
      setUpdateForm((current) => ({ ...current, attachments: [...current.attachments, ...attachments] }));
    } catch {
      setFormError('One or more files could not be read. Please try again.');
    }
  };

  const handleSubmitReport = async (event: FormEvent) => {
    event.preventDefault();
    if (role === 'driver' && !activeAssignment?.vehicle_id) {
      setFormError('You need an assigned vehicle before reporting an incident.');
      return;
    }

    setIsSubmitting(true);
    setFormError('');
    setSuccessMessage('');
    try {
      const response = await apiRequest<IncidentMutationResponse>('/incidents', {
        method: 'POST',
        body: JSON.stringify({
          vehicle_id: activeAssignment?.vehicle_id,
          driver_id: currentUser?.id,
          incident_type: reportForm.incident_type,
          incident_at: new Date(reportForm.incident_at).toISOString(),
          location: reportForm.location,
          description: reportForm.description,
          can_vehicle_move: reportForm.can_vehicle_move,
          third_party_involved: reportForm.third_party_involved,
          witness_name: reportForm.witness_name || undefined,
          witness_phone: reportForm.witness_phone || undefined,
          police_station: reportForm.police_station || undefined,
          police_report_number: reportForm.police_report_number || undefined,
          attachments: reportForm.attachments,
        }),
      });
      setIncidents((current) => [response.data.incident, ...current]);
      setSelectedIncidentId(response.data.incident.id);
      setReportForm(initialReportForm);
      setShowChecklist(true);
      setSuccessMessage('Incident reported successfully. Follow the checklist below while support takes over.');
      await handleRefresh();
    } catch (error) {
      setFormError(error instanceof ApiRequestError ? error.message : 'Unable to submit the incident right now.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleAdminUpdate = async (event: FormEvent) => {
    event.preventDefault();
    if (!selectedIncident) return;
    setIsSubmitting(true);
    setFormError('');
    setSuccessMessage('');
    try {
      const response = await apiRequest<IncidentMutationResponse>(`/incidents/${selectedIncident.id}`, {
        method: 'PATCH',
        body: JSON.stringify({
          status: updateForm.status,
          investigation_note: updateForm.investigation_note || undefined,
          claim_number: updateForm.claim_number || undefined,
          claim_submitted_date: updateForm.claim_submitted_date || undefined,
          assessment_date: updateForm.assessment_date || undefined,
          claim_status: updateForm.claim_status || undefined,
          repair_cost: updateForm.repair_cost ? Number(updateForm.repair_cost) : undefined,
          insurance_approved_amount: updateForm.insurance_approved_amount ? Number(updateForm.insurance_approved_amount) : undefined,
          paid_amount: updateForm.paid_amount ? Number(updateForm.paid_amount) : undefined,
          downtime_start_date: updateForm.downtime_start_date || undefined,
          downtime_end_date: updateForm.downtime_end_date || undefined,
          estimated_revenue_lost: updateForm.estimated_revenue_lost ? Number(updateForm.estimated_revenue_lost) : undefined,
          replacement_vehicle_id: updateForm.replacement_vehicle_id || undefined,
          vehicle_status_after_incident: updateForm.vehicle_status_after_incident || undefined,
          insurance_notified: updateForm.insurance_notified,
          claim_eligibility_override: updateForm.claim_eligibility_override || undefined,
          claim_eligibility_override_reason: updateForm.claim_eligibility_override_reason || undefined,
          attachments: updateForm.attachments.length ? updateForm.attachments : undefined,
        }),
      });
      setIncidents((current) =>
        current.map((incident) => (incident.id === response.data.incident.id ? response.data.incident : incident)),
      );
      setSelectedIncidentId(response.data.incident.id);
      setSuccessMessage('Incident updated successfully.');
      await handleRefresh();
    } catch (error) {
      setFormError(error instanceof ApiRequestError ? error.message : 'Unable to update the incident right now.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleCreateMaintenanceJob = async () => {
    if (!selectedIncident) return;
    setIsSubmitting(true);
    setFormError('');
    setSuccessMessage('');
    try {
      const response = await apiRequest<IncidentMaintenanceResponse>(`/incidents/${selectedIncident.id}/create-maintenance-job`, {
        method: 'POST',
      });
      setIncidents((current) =>
        current.map((incident) => (incident.id === response.data.incident.id ? response.data.incident : incident)),
      );
      setSuccessMessage('Repair job created and linked to this incident.');
      await handleRefresh();
    } catch (error) {
      setFormError(error instanceof ApiRequestError ? error.message : 'Unable to create the repair job right now.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="space-y-6 p-4 sm:p-6">
      <div className="overflow-hidden rounded-2xl border border-slate-200 bg-gradient-to-r from-[#0F172A] via-[#1E293B] to-[#1D4ED8]">
        <div className="flex flex-col gap-4 px-5 py-6 sm:px-6 lg:flex-row lg:items-end lg:justify-between">
          <div className="max-w-3xl">
            <div className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-blue-100">
              Accidents & Incidents
            </div>
            <h1 className="mt-4 text-2xl font-semibold text-white sm:text-3xl">
              {role === 'driver' ? 'Report and Track Incidents' : 'Incident, Insurance & Downtime Control'}
            </h1>
            <p className="mt-2 text-sm text-blue-100 sm:text-base">
              {role === 'driver'
                ? 'Report accidents, breakdowns, theft, fire, and safety incidents quickly so the fleet team can take over.'
                : 'Review incident exposure, insurance progress, repair costs, and downtime without waiting on manual follow-up.'}
            </p>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
            <HeaderStat label="Total Incidents" value={String(dashboard?.total_incidents ?? incidents.length)} />
            <HeaderStat label="Open Cases" value={String(dashboard?.open_incidents ?? 0)} />
            <HeaderStat label="Downtime" value={`${dashboard?.downtime_days ?? 0} days`} />
            <HeaderStat label="Revenue Lost" value={formatCurrency(dashboard?.estimated_revenue_lost ?? 0)} />
          </div>
        </div>
      </div>

      {pageError && <InlineMessage tone="error" message={pageError} />}
      {successMessage && <InlineMessage tone="success" message={successMessage} />}
      {formError && <InlineMessage tone="error" message={formError} />}

      {role !== 'driver' && alerts.length > 0 && (
        <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-amber-900">
            <ShieldAlert className="h-4 w-4" />
            Active Alerts
          </div>
          <div className="mt-3 grid gap-2">
            {alerts.slice(0, 6).map((alert, index) => (
              <div key={`${alert.type}-${index}`} className="rounded-xl border border-amber-200 bg-white/70 px-3 py-2 text-sm text-amber-900">
                {alert.message}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className={`grid gap-6 ${role === 'driver' ? 'xl:grid-cols-[1.05fr_0.95fr]' : 'xl:grid-cols-[0.95fr_1.05fr]'}`}>
        <div className="space-y-6">
          {role === 'driver' ? (
            <div className="rounded-2xl border border-gray-200 bg-white shadow-sm">
              <div className="border-b border-gray-200 px-6 py-4">
                <h2 className="text-lg font-semibold text-[#0F172A]">Report Incident</h2>
                <p className="mt-1 text-sm text-gray-600">Your assigned vehicle and driver details are attached automatically.</p>
              </div>
              {!activeAssignment ? (
                <div className="px-6 py-12 text-center text-sm text-gray-500">You need an active vehicle assignment before you can report an incident.</div>
              ) : (
                <form onSubmit={handleSubmitReport} className="space-y-5 px-6 py-5">
                  <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
                    <InfoCard label="Vehicle" value={driverVehicleLabel} />
                    <InfoCard label="Driver" value={currentUser?.full_name || 'Driver'} />
                    <InfoCard label="Insurance Status" value={selectedIncident?.insurance_claim?.status || activeAssignment.vehicle?.insurance_expiry || 'Will be checked'} />
                  </div>

                  <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                    <Field label="Incident Type">
                      <select
                        value={reportForm.incident_type}
                        onChange={(event) => setReportForm((current) => ({ ...current, incident_type: event.target.value as IncidentType }))}
                        className="w-full rounded-lg border border-gray-300 px-3 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                      >
                        {['accident', 'breakdown', 'theft', 'fire', 'third_party_damage', 'injury', 'other'].map((option) => (
                          <option key={option} value={option}>{formatLabel(option)}</option>
                        ))}
                      </select>
                    </Field>
                    <Field label="Date / Time">
                      <input
                        type="datetime-local"
                        value={reportForm.incident_at}
                        onChange={(event) => setReportForm((current) => ({ ...current, incident_at: event.target.value }))}
                        className="w-full rounded-lg border border-gray-300 px-3 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                        required
                      />
                    </Field>
                  </div>

                  <Field label="Location">
                    <input
                      value={reportForm.location}
                      onChange={(event) => setReportForm((current) => ({ ...current, location: event.target.value }))}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                      placeholder="Street, landmark, or area"
                      required
                    />
                  </Field>

                  <Field label="Description">
                    <textarea
                      value={reportForm.description}
                      onChange={(event) => setReportForm((current) => ({ ...current, description: event.target.value }))}
                      className="min-h-[130px] w-full rounded-lg border border-gray-300 px-3 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                      placeholder="Tell us what happened, what was damaged, and whether anyone was hurt."
                      required
                    />
                  </Field>

                  <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                    <BooleanField
                      label="Can the vehicle move?"
                      value={reportForm.can_vehicle_move}
                      onChange={(value) => setReportForm((current) => ({ ...current, can_vehicle_move: value }))}
                    />
                    <BooleanField
                      label="Was a third party involved?"
                      value={reportForm.third_party_involved}
                      onChange={(value) => setReportForm((current) => ({ ...current, third_party_involved: value }))}
                    />
                  </div>

                  <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                    <Field label="Witness Name">
                      <input value={reportForm.witness_name} onChange={(event) => setReportForm((current) => ({ ...current, witness_name: event.target.value }))} className="w-full rounded-lg border border-gray-300 px-3 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]" />
                    </Field>
                    <Field label="Witness Phone">
                      <input value={reportForm.witness_phone} onChange={(event) => setReportForm((current) => ({ ...current, witness_phone: event.target.value }))} className="w-full rounded-lg border border-gray-300 px-3 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]" />
                    </Field>
                    <Field label="Police Station">
                      <input value={reportForm.police_station} onChange={(event) => setReportForm((current) => ({ ...current, police_station: event.target.value }))} className="w-full rounded-lg border border-gray-300 px-3 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]" />
                    </Field>
                    <Field label="Police Report Number">
                      <input value={reportForm.police_report_number} onChange={(event) => setReportForm((current) => ({ ...current, police_report_number: event.target.value }))} className="w-full rounded-lg border border-gray-300 px-3 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]" />
                    </Field>
                  </div>

                  <AttachmentPicker
                    label="Photos, Videos & Documents"
                    onChange={handleReportAttachmentUpload}
                    attachments={reportForm.attachments}
                    onRemove={(id) => setReportForm((current) => ({ ...current, attachments: current.attachments.filter((item) => item.id !== id) }))}
                  />

                  <div className="flex justify-end">
                    <button
                      type="submit"
                      disabled={isSubmitting}
                      className="inline-flex items-center gap-2 rounded-lg bg-[#DC2626] px-4 py-2.5 font-medium text-white transition-colors hover:bg-[#B91C1C] disabled:cursor-not-allowed disabled:opacity-70"
                    >
                      {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <AlertTriangle className="h-4 w-4" />}
                      {isSubmitting ? 'Submitting...' : 'Report Incident'}
                    </button>
                  </div>
                </form>
              )}
            </div>
          ) : (
            <>
              <DashboardCards dashboard={dashboard} />
              <Panel title="High-Risk Driver Summary" subtitle="Drivers with repeated exposure, open incidents, or downtime impact.">
                {highRiskDrivers.length ? (
                  <div className="space-y-3">
                    {highRiskDrivers.map((item) => (
                      <div key={item.driver_id} className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-3">
                        <div className="flex flex-wrap items-center justify-between gap-3">
                          <div>
                            <div className="font-semibold text-[#0F172A]">{item.driver_name || 'Driver'}</div>
                            <div className="text-sm text-gray-500">{item.incident_count} incident(s), {item.open_incidents} open</div>
                          </div>
                          <div className="text-right text-sm text-gray-600">
                            <div>{item.downtime_days} downtime day(s)</div>
                            <div>{formatCurrency(item.estimated_revenue_lost)}</div>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <EmptyState label="No high-risk driver patterns detected yet." />
                )}
              </Panel>
              <Panel title="Insurance Partner Directory" subtitle="Vehicle-linked policy contacts available for fast claim follow-up.">
                {insuranceDirectory.length ? (
                  <div className="space-y-3">
                    {insuranceDirectory.slice(0, 8).map((entry) => (
                      <div key={`${entry.vehicle_id}-${entry.policy_number || 'policy'}`} className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-3">
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div>
                            <div className="font-semibold text-[#0F172A]">{entry.vehicle?.registration_number || 'Vehicle'} • {entry.insurance_company || 'Insurance provider'}</div>
                            <div className="text-sm text-gray-500">{entry.policy_number || 'No policy number'} • {entry.insurance_type || 'Type not set'}</div>
                            <div className="mt-1 text-sm text-gray-600">{entry.claims_officer_name || 'Claims officer not set'}</div>
                          </div>
                          <div className="text-right text-sm text-gray-600">
                            <div>{entry.status || 'Unknown'}</div>
                            <div>Renewal {formatDate(entry.renewal_date)}</div>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <EmptyState label="No vehicle insurance records are linked yet." />
                )}
              </Panel>
            </>
          )}

          <Panel title={role === 'driver' ? 'My Incidents' : 'Incident Queue'} subtitle={role === 'driver' ? 'You can only view incidents linked to your account.' : 'Open and historical incident reports across the fleet.'}>
            <div className="mb-4 relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
              <input
                type="text"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder="Search by vehicle, driver, status, incident type, phone, or location"
                className="w-full rounded-lg border border-gray-300 py-2.5 pl-9 pr-4 text-sm focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
              />
            </div>
            {isLoading ? (
              <LoadingState label="Loading incidents..." />
            ) : filteredIncidents.length ? (
              <div className="space-y-3">
                {filteredIncidents.map((incident) => (
                  <button
                    key={incident.id}
                    type="button"
                    onClick={() => setSelectedIncidentId(incident.id)}
                    className={`w-full rounded-2xl border px-4 py-4 text-left transition-colors ${selectedIncident?.id === incident.id ? 'border-[#2563EB] bg-blue-50/60' : 'border-gray-200 bg-white hover:bg-gray-50'}`}
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <div className="font-semibold text-[#0F172A]">{incident.vehicle?.registration_number || 'Vehicle'} • {formatLabel(incident.incident_type)}</div>
                        <div className="mt-1 text-sm text-gray-500">{incident.driver?.full_name || 'Driver'} • {formatDateTime(incident.incident_at)}</div>
                        <div className="mt-2 text-sm text-gray-700">{incident.location}</div>
                      </div>
                      <div className="text-right">
                        <div className="inline-flex rounded-full border border-blue-200 bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700">
                          {formatLabel(incident.status)}
                        </div>
                        <div className="mt-2 text-xs text-gray-500">{incident.insurance_claim?.claim_eligibility || 'Claim review pending'}</div>
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            ) : (
              <EmptyState label={incidents.length === 0 ? (role === 'driver' ? 'No incidents reported yet.' : 'No incidents recorded yet.') : 'No matching records found.'} />
            )}
          </Panel>
        </div>

        <div className="space-y-6">
          <Panel title="Incident Details" subtitle="Evidence, insurance eligibility, claim progress, repair status, and audit history live together here.">
            {!selectedIncident ? (
              <EmptyState label="Select an incident to view details." />
            ) : (
              <div className="space-y-5">
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  <InfoCard label="Vehicle" value={selectedIncident.vehicle?.registration_number || '-'} />
                  <InfoCard label="Driver" value={selectedIncident.driver?.full_name || '-'} />
                  <InfoCard label="Status" value={formatLabel(selectedIncident.status)} />
                  <InfoCard label="Date / Time" value={formatDateTime(selectedIncident.incident_at)} />
                  <InfoCard label="Location" value={selectedIncident.location} />
                  <InfoCard label="Can Move" value={selectedIncident.can_vehicle_move ? 'Yes' : 'No'} />
                </div>

                <div className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-4">
                  <div className="text-sm font-semibold text-[#0F172A]">Description</div>
                  <div className="mt-2 text-sm text-gray-700">{selectedIncident.description}</div>
                </div>

                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  <InfoCard label="Third Party Involved" value={selectedIncident.third_party_involved ? 'Yes' : 'No'} />
                  <InfoCard label="Witness" value={[selectedIncident.witness_name, selectedIncident.witness_phone].filter(Boolean).join(' • ') || '-'} />
                  <InfoCard label="Police Station" value={selectedIncident.police_station || '-'} />
                  <InfoCard label="Police Report Number" value={selectedIncident.police_report_number || '-'} />
                </div>

                <div className="rounded-2xl border border-gray-200 bg-white p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <h3 className="text-sm font-semibold text-[#0F172A]">Claim Panel</h3>
                      <p className="mt-1 text-sm text-gray-500">Insurance status, policy type, eligibility, and claims officer contact.</p>
                    </div>
                    <div className={`rounded-full px-3 py-1 text-xs font-medium ${
                      selectedIncident.insurance_claim?.status === 'Active'
                        ? 'bg-green-100 text-green-800'
                        : selectedIncident.insurance_claim?.status === 'Expired'
                          ? 'bg-red-100 text-red-800'
                          : 'bg-gray-100 text-gray-700'
                    }`}>
                      {selectedIncident.insurance_claim?.status || 'Missing'}
                    </div>
                  </div>
                  <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
                    <InfoCard label="Provider" value={selectedIncident.insurance_claim?.company || '-'} />
                    <InfoCard label="Policy Number" value={selectedIncident.insurance_claim?.policy_number || '-'} />
                    <InfoCard label="Insurance Type" value={selectedIncident.insurance_claim?.insurance_type || '-'} />
                    <InfoCard label="Expiry Date" value={formatDate(selectedIncident.insurance_claim?.expiry_date)} />
                    <InfoCard label="Claim Eligibility" value={selectedIncident.insurance_claim?.claim_eligibility || '-'} />
                    <InfoCard label="Eligibility Reason" value={selectedIncident.insurance_claim?.eligibility_reason || '-'} />
                    <InfoCard label="Claims Officer" value={selectedIncident.insurance_claim?.claims_officer_name || '-'} />
                    <InfoCard label="Officer Contact" value={selectedIncident.insurance_claim?.claims_officer_phone || selectedIncident.insurance_claim?.claims_officer_email || '-'} />
                  </div>
                  <div className="mt-4 flex flex-wrap gap-3">
                    {selectedIncident.insurance_claim?.claims_officer_phone && (
                      <a href={`tel:${selectedIncident.insurance_claim.claims_officer_phone}`} className="inline-flex items-center gap-2 rounded-lg border border-green-200 bg-green-50 px-3 py-2 text-sm font-medium text-green-700">
                        <Phone className="h-4 w-4" />
                        Call Insurance Officer
                      </a>
                    )}
                    {selectedIncident.insurance_claim?.claims_officer_email && (
                      <a href={`mailto:${selectedIncident.insurance_claim.claims_officer_email}`} className="inline-flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm font-medium text-blue-700">
                        <Mail className="h-4 w-4" />
                        Email Insurance Officer
                      </a>
                    )}
                  </div>
                </div>

                <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
                  <InfoCard label="Repair Cost" value={formatCurrency(selectedIncident.repair_cost)} />
                  <InfoCard label="Approved Amount" value={formatCurrency(selectedIncident.insurance_approved_amount)} />
                  <InfoCard label="Amount Paid" value={formatCurrency(selectedIncident.paid_amount)} />
                  <InfoCard label="Outstanding Claim" value={formatCurrency(selectedIncident.outstanding_claim)} />
                  <InfoCard label="Downtime" value={`${selectedIncident.downtime_days || 0} day(s)`} />
                  <InfoCard label="Revenue Lost" value={formatCurrency(selectedIncident.estimated_revenue_lost)} />
                </div>

                <div className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-4">
                  <div className="text-sm font-semibold text-[#0F172A]">Evidence</div>
                  {selectedIncident.attachments.length ? (
                    <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
                      {selectedIncident.attachments.map((attachment) => (
                        <div key={attachment.id} className="rounded-xl border border-gray-200 bg-white p-3">
                          <div className="flex items-center gap-2 text-sm font-medium text-[#0F172A]">
                            {attachment.file_kind === 'photo' ? <Camera className="h-4 w-4" /> : <FilePlus2 className="h-4 w-4" />}
                            {attachment.name}
                          </div>
                          <div className="mt-1 text-xs text-gray-500">{attachment.content_type || formatLabel(attachment.file_kind)}</div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="mt-2 text-sm text-gray-500">No evidence files have been linked yet.</div>
                  )}
                </div>

                {role !== 'driver' ? (
                  <form onSubmit={handleAdminUpdate} className="space-y-4 rounded-2xl border border-gray-200 bg-white p-4">
                    <div>
                      <h3 className="text-sm font-semibold text-[#0F172A]">Admin Actions</h3>
                      <p className="mt-1 text-sm text-gray-500">Move the incident forward, track claims, attach official documents, and assign support.</p>
                    </div>
                    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                      <Field label="Status">
                        <select value={updateForm.status} onChange={(event) => setUpdateForm((current) => ({ ...current, status: event.target.value as IncidentStatus }))} className="w-full rounded-lg border border-gray-300 px-3 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]">
                          {(statusOptions.length ? statusOptions : ['reported']).map((option) => (
                            <option key={option} value={option}>{formatLabel(option)}</option>
                          ))}
                        </select>
                      </Field>
                      <Field label="Claim Status">
                        <select value={updateForm.claim_status} onChange={(event) => setUpdateForm((current) => ({ ...current, claim_status: event.target.value }))} className="w-full rounded-lg border border-gray-300 px-3 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]">
                          {['under_review', 'submitted', 'assessment_scheduled', 'approved', 'partially_paid', 'paid', 'rejected', 'closed'].map((option) => (
                            <option key={option} value={option}>{formatLabel(option)}</option>
                          ))}
                        </select>
                      </Field>
                      <Field label="Claim Number">
                        <input value={updateForm.claim_number} onChange={(event) => setUpdateForm((current) => ({ ...current, claim_number: event.target.value }))} className="w-full rounded-lg border border-gray-300 px-3 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]" />
                      </Field>
                      <Field label="Replacement Vehicle">
                        <select value={updateForm.replacement_vehicle_id} onChange={(event) => setUpdateForm((current) => ({ ...current, replacement_vehicle_id: event.target.value }))} className="w-full rounded-lg border border-gray-300 px-3 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]">
                          <option value="">No replacement assigned</option>
                          {replacementVehicleOptions.map((vehicle) => (
                            <option key={vehicle.id} value={vehicle.id}>{vehicle.registration_number} {vehicle.make || ''} {vehicle.model || ''}</option>
                          ))}
                        </select>
                      </Field>
                      <Field label="Claim Submitted Date">
                        <input type="date" value={updateForm.claim_submitted_date} onChange={(event) => setUpdateForm((current) => ({ ...current, claim_submitted_date: event.target.value }))} className="w-full rounded-lg border border-gray-300 px-3 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]" />
                      </Field>
                      <Field label="Assessment Date">
                        <input type="date" value={updateForm.assessment_date} onChange={(event) => setUpdateForm((current) => ({ ...current, assessment_date: event.target.value }))} className="w-full rounded-lg border border-gray-300 px-3 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]" />
                      </Field>
                      <Field label="Repair Cost">
                        <input type="number" step="0.01" value={updateForm.repair_cost} onChange={(event) => setUpdateForm((current) => ({ ...current, repair_cost: event.target.value }))} className="w-full rounded-lg border border-gray-300 px-3 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]" />
                      </Field>
                      <Field label="Insurance Approved Amount">
                        <input type="number" step="0.01" value={updateForm.insurance_approved_amount} onChange={(event) => setUpdateForm((current) => ({ ...current, insurance_approved_amount: event.target.value }))} className="w-full rounded-lg border border-gray-300 px-3 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]" />
                      </Field>
                      <Field label="Amount Paid">
                        <input type="number" step="0.01" value={updateForm.paid_amount} onChange={(event) => setUpdateForm((current) => ({ ...current, paid_amount: event.target.value }))} className="w-full rounded-lg border border-gray-300 px-3 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]" />
                      </Field>
                      <Field label="Vehicle Status">
                        <select value={updateForm.vehicle_status_after_incident} onChange={(event) => setUpdateForm((current) => ({ ...current, vehicle_status_after_incident: event.target.value }))} className="w-full rounded-lg border border-gray-300 px-3 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]">
                          {['accident', 'out_of_service', 'maintenance', 'available', 'assigned', 'suspended'].map((option) => (
                            <option key={option} value={option}>{formatLabel(option)}</option>
                          ))}
                        </select>
                      </Field>
                      <Field label="Downtime Start">
                        <input type="date" value={updateForm.downtime_start_date} onChange={(event) => setUpdateForm((current) => ({ ...current, downtime_start_date: event.target.value }))} className="w-full rounded-lg border border-gray-300 px-3 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]" />
                      </Field>
                      <Field label="Downtime End">
                        <input type="date" value={updateForm.downtime_end_date} onChange={(event) => setUpdateForm((current) => ({ ...current, downtime_end_date: event.target.value }))} className="w-full rounded-lg border border-gray-300 px-3 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]" />
                      </Field>
                      <Field label="Estimated Revenue Lost">
                        <input type="number" step="0.01" value={updateForm.estimated_revenue_lost} onChange={(event) => setUpdateForm((current) => ({ ...current, estimated_revenue_lost: event.target.value }))} className="w-full rounded-lg border border-gray-300 px-3 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]" />
                      </Field>
                    </div>

                    <BooleanField label="Insurance Notified" value={updateForm.insurance_notified} onChange={(value) => setUpdateForm((current) => ({ ...current, insurance_notified: value }))} />

                    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                      <Field label="Claim Eligibility Override">
                        <select value={updateForm.claim_eligibility_override} onChange={(event) => setUpdateForm((current) => ({ ...current, claim_eligibility_override: event.target.value }))} className="w-full rounded-lg border border-gray-300 px-3 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]">
                          <option value="">No override</option>
                          {['Not eligible', 'Limited coverage', 'Potentially eligible', 'Review needed'].map((option) => (
                            <option key={option} value={option}>{option}</option>
                          ))}
                        </select>
                      </Field>
                      <Field label="Override Reason">
                        <input value={updateForm.claim_eligibility_override_reason} onChange={(event) => setUpdateForm((current) => ({ ...current, claim_eligibility_override_reason: event.target.value }))} className="w-full rounded-lg border border-gray-300 px-3 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]" placeholder="Explain why the override is needed" />
                      </Field>
                    </div>

                    <Field label="Investigation Notes">
                      <textarea value={updateForm.investigation_note} onChange={(event) => setUpdateForm((current) => ({ ...current, investigation_note: event.target.value }))} className="min-h-[110px] w-full rounded-lg border border-gray-300 px-3 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]" placeholder="Add findings, police follow-up, repair instructions, or insurance context." />
                    </Field>

                    <AttachmentPicker
                      label="Police / Insurance / Repair Documents"
                      onChange={handleUpdateAttachmentUpload}
                      attachments={updateForm.attachments}
                      onRemove={(id) => setUpdateForm((current) => ({ ...current, attachments: current.attachments.filter((item) => item.id !== id) }))}
                    />

                    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-gray-200 pt-4">
                      <button type="button" onClick={() => void handleCreateMaintenanceJob()} disabled={isSubmitting || Boolean(selectedIncident.maintenance_job_id)} className="inline-flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-2.5 text-sm font-medium text-emerald-700 disabled:cursor-not-allowed disabled:opacity-60">
                        <Wrench className="h-4 w-4" />
                        {selectedIncident.maintenance_job_id ? 'Repair Job Linked' : 'Create Repair Job'}
                      </button>
                      <button type="submit" disabled={isSubmitting} className="inline-flex items-center gap-2 rounded-lg bg-[#2563EB] px-4 py-2.5 font-medium text-white transition-colors hover:bg-[#1D4ED8] disabled:cursor-not-allowed disabled:opacity-70">
                        {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                        Save Incident Update
                      </button>
                    </div>
                  </form>
                ) : (
                  showChecklist && (
                    <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4">
                      <div className="text-sm font-semibold text-amber-900">Emergency Checklist</div>
                      <div className="mt-3 space-y-2">
                        {(selectedIncident?.emergency_checklist || []).map((item) => (
                          <div key={item} className="flex items-start gap-2 text-sm text-amber-900">
                            <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0" />
                            <span>{item}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )
                )}

                <div className="rounded-2xl border border-gray-200 bg-white p-4">
                  <div className="text-sm font-semibold text-[#0F172A]">Audit Log</div>
                  {selectedIncident.audit_logs.length ? (
                    <div className="mt-3 space-y-3">
                      {selectedIncident.audit_logs.slice().reverse().map((log) => (
                        <div key={log.id} className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-3">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <div className="text-sm font-medium text-[#0F172A]">{formatLabel(log.action)}</div>
                            <div className="text-xs text-gray-500">{formatDateTime(log.created_at)}</div>
                          </div>
                          <div className="mt-1 text-xs uppercase tracking-wide text-gray-500">{formatLabel(log.actor_role)}</div>
                          {log.changes.length > 0 && (
                            <div className="mt-2 space-y-1 text-sm text-gray-700">
                              {log.changes.map((change, index) => (
                                <div key={`${log.id}-${index}`}>{change}</div>
                              ))}
                            </div>
                          )}
                          {log.note && <div className="mt-2 text-sm text-gray-700">{log.note}</div>}
                          {log.reason && <div className="mt-2 text-sm text-amber-700">Reason: {log.reason}</div>}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="mt-2 text-sm text-gray-500">No audit entries yet.</div>
                  )}
                </div>
              </div>
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}

function HeaderStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/10 px-4 py-3 backdrop-blur-sm">
      <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-blue-100">{label}</div>
      <div className="mt-1 text-sm font-semibold text-white">{value}</div>
    </div>
  );
}

function DashboardCards({ dashboard }: { dashboard: IncidentsResponse['data']['dashboard'] | null }) {
  const cards = [
    { label: 'Repair Cost', value: formatCurrency(dashboard?.repair_cost ?? 0) },
    { label: 'Approved Amount', value: formatCurrency(dashboard?.insurance_approved_amount ?? 0) },
    { label: 'Paid Amount', value: formatCurrency(dashboard?.amount_paid ?? 0) },
    { label: 'Outstanding Claim', value: formatCurrency(dashboard?.outstanding_claim ?? 0) },
  ];
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {cards.map((card) => (
        <div key={card.label} className="rounded-2xl border border-gray-200 bg-white p-5">
          <div className="text-sm font-medium text-gray-500">{card.label}</div>
          <div className="mt-2 text-2xl font-semibold text-[#0F172A]">{card.value}</div>
        </div>
      ))}
    </div>
  );
}

function Panel({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <div className="rounded-2xl border border-gray-200 bg-white shadow-sm">
      <div className="border-b border-gray-200 px-6 py-4">
        <h2 className="text-lg font-semibold text-[#0F172A]">{title}</h2>
        {subtitle && <p className="mt-1 text-sm text-gray-600">{subtitle}</p>}
      </div>
      <div className="px-6 py-5">{children}</div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-gray-700">{label}</label>
      {children}
    </div>
  );
}

function BooleanField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <div>
      <div className="mb-2 block text-sm font-medium text-gray-700">{label}</div>
      <div className="grid grid-cols-2 gap-3">
        {[{ label: 'Yes', value: true }, { label: 'No', value: false }].map((item) => (
          <button
            key={item.label}
            type="button"
            onClick={() => onChange(item.value)}
            className={`rounded-lg border px-4 py-2.5 text-sm font-medium transition-colors ${
              value === item.value
                ? 'border-[#2563EB] bg-blue-50 text-[#1D4ED8]'
                : 'border-gray-300 bg-white text-gray-700 hover:bg-gray-50'
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function AttachmentPicker({
  label,
  attachments,
  onChange,
  onRemove,
}: {
  label: string;
  attachments: IncidentAttachment[];
  onChange: (event: ChangeEvent<HTMLInputElement>) => void;
  onRemove: (id: string) => void;
}) {
  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-gray-700">{label}</label>
      <label className="flex cursor-pointer flex-col items-center justify-center rounded-2xl border border-dashed border-gray-300 bg-gray-50 px-4 py-6 text-center transition-colors hover:border-[#2563EB] hover:bg-blue-50/40">
        <FilePlus2 className="mb-2 h-5 w-5 text-gray-500" />
        <span className="text-sm font-medium text-gray-700">Upload files</span>
        <span className="mt-1 text-xs text-gray-500">Photos, videos, PDFs, and other documents are supported.</span>
        <input type="file" accept="image/*,video/*,.pdf,.doc,.docx,.xls,.xlsx" multiple className="hidden" onChange={onChange} />
      </label>
      {attachments.length > 0 && (
        <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
          {attachments.map((attachment) => (
            <div key={attachment.id} className="flex items-center justify-between rounded-xl border border-gray-200 bg-white px-3 py-2">
              <div className="min-w-0">
                <div className="truncate text-sm font-medium text-[#0F172A]">{attachment.name}</div>
                <div className="text-xs text-gray-500">{formatLabel(attachment.file_kind)}</div>
              </div>
              <button type="button" onClick={() => onRemove(attachment.id)} className="text-xs font-medium text-red-600">
                Remove
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function InfoCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-3">
      <div className="text-xs font-semibold uppercase tracking-wide text-gray-500">{label}</div>
      <div className="mt-1 text-sm font-medium text-[#0F172A]">{value || '-'}</div>
    </div>
  );
}

function InlineMessage({ tone, message }: { tone: 'error' | 'success'; message: string }) {
  return (
    <div className={`rounded-lg border px-4 py-3 text-sm ${
      tone === 'error'
        ? 'border-red-200 bg-red-50 text-red-700'
        : 'border-green-200 bg-green-50 text-green-700'
    }`}>
      {message}
    </div>
  );
}

function LoadingState({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-center gap-3 py-12 text-gray-500">
      <Loader2 className="h-5 w-5 animate-spin" />
      <span>{label}</span>
    </div>
  );
}

function EmptyState({ label }: { label: string }) {
  return <div className="rounded-xl border border-dashed border-gray-300 bg-gray-50 px-4 py-10 text-center text-sm text-gray-500">{label}</div>;
}
