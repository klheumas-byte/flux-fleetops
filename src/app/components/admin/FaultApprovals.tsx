import { useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Eye,
  Loader2,
  MessageSquareMore,
  RefreshCw,
  ShieldAlert,
  Wrench,
  XCircle,
} from 'lucide-react';
import { apiRequest, ApiRequestError } from '../../lib/api';
import { getStoredSessionUser } from '../../lib/auth-session';

type FaultStatus =
  | 'reported'
  | 'under_review'
  | 'approved'
  | 'rejected'
  | 'converted_to_maintenance'
  | 'resolved';

type FaultSeverity = 'low' | 'medium' | 'high' | 'critical';

interface UserSummary {
  id: string;
  full_name: string;
  role: 'owner' | 'admin' | 'driver';
}

interface VehicleSummary {
  id: string;
  registration_number: string;
  make?: string | null;
  model?: string | null;
  status?: string | null;
}

interface FaultRecord {
  id: string;
  severity: FaultSeverity;
  status: FaultStatus;
  description: string;
  photos: string[];
  admin_notes: string | null;
  owner_notes: string | null;
  resolution_notes: string | null;
  maintenance_job_id?: string | null;
  reported_at: string | null;
  reviewed_at: string | null;
  approved_at: string | null;
  rejected_at: string | null;
  rejection_reason: string | null;
  requested_info_at: string | null;
  request_info_note: string | null;
  converted_to_maintenance_at: string | null;
  resolved_at: string | null;
  vehicle?: VehicleSummary | null;
  driver?: UserSummary | null;
  category?: { name: string } | null;
  component?: { name: string } | null;
  reviewed_by_user?: UserSummary | null;
  approved_by_user?: UserSummary | null;
  rejected_by_user?: UserSummary | null;
  requested_info_by_user?: UserSummary | null;
  converted_by_user?: UserSummary | null;
}

interface FaultsResponse {
  success: boolean;
  data: {
    faults: FaultRecord[];
  };
}

interface FaultMutationResponse {
  success: boolean;
  data: {
    fault?: FaultRecord;
    job?: {
      id: string;
    };
  };
}

type FilterKey =
  | 'reported'
  | 'under_review'
  | 'approved'
  | 'rejected'
  | 'critical'
  | 'converted_to_maintenance'
  | 'resolved';

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: 'reported', label: 'Reported' },
  { key: 'under_review', label: 'Under Review' },
  { key: 'approved', label: 'Approved' },
  { key: 'rejected', label: 'Rejected' },
  { key: 'critical', label: 'Critical' },
  { key: 'converted_to_maintenance', label: 'Converted To Maintenance' },
  { key: 'resolved', label: 'Resolved' },
];

function formatDate(value: string | null | undefined) {
  if (!value) {
    return 'Not available';
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  return parsed.toLocaleString();
}

function formatLabel(value: string) {
  return value
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function statusClassName(status: FaultStatus) {
  switch (status) {
    case 'approved':
      return 'border-blue-200 bg-blue-100 text-blue-800';
    case 'rejected':
      return 'border-rose-200 bg-rose-100 text-rose-800';
    case 'under_review':
      return 'border-amber-200 bg-amber-100 text-amber-800';
    case 'converted_to_maintenance':
      return 'border-purple-200 bg-purple-100 text-purple-800';
    case 'resolved':
      return 'border-green-200 bg-green-100 text-green-800';
    default:
      return 'border-slate-200 bg-slate-100 text-slate-800';
  }
}

function severityClassName(severity: FaultSeverity) {
  switch (severity) {
    case 'critical':
      return 'border-red-200 bg-red-100 text-red-800';
    case 'high':
      return 'border-orange-200 bg-orange-100 text-orange-800';
    case 'medium':
      return 'border-amber-200 bg-amber-100 text-amber-800';
    default:
      return 'border-slate-200 bg-slate-100 text-slate-800';
  }
}

function getSettledData<T>(result: PromiseSettledResult<T>) {
  return result.status === 'fulfilled' ? result.value : null;
}

function getSettledError(result: PromiseSettledResult<unknown>) {
  if (result.status !== 'rejected') {
    return null;
  }
  return result.reason instanceof ApiRequestError
    ? result.reason.message
    : 'Unable to load the fault approval queue right now.';
}

export default function FaultApprovals() {
  const currentRole = getStoredSessionUser()?.role || null;
  const isOwner = currentRole === 'owner';
  const [faults, setFaults] = useState<FaultRecord[]>([]);
  const [criticalFaults, setCriticalFaults] = useState<FaultRecord[]>([]);
  const [activeFilter, setActiveFilter] = useState<FilterKey>('reported');
  const [selectedFault, setSelectedFault] = useState<FaultRecord | null>(null);
  const [reviewNote, setReviewNote] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [pageError, setPageError] = useState('');
  const [actionError, setActionError] = useState('');

  const loadFaults = async () => {
    setIsLoading(true);
    setPageError('');
    try {
      const [queueResult, criticalResult] = await Promise.allSettled([
        apiRequest<FaultsResponse>('/faults/approvals', { cacheTtlMs: 10000, timeoutMs: 15000 }),
        apiRequest<FaultsResponse>('/faults/critical', { cacheTtlMs: 10000, timeoutMs: 15000 }),
      ]);

      const queueResponse = getSettledData(queueResult);
      const criticalResponse = getSettledData(criticalResult);

      setFaults(Array.isArray(queueResponse?.data?.faults) ? queueResponse.data.faults : []);
      setCriticalFaults(Array.isArray(criticalResponse?.data?.faults) ? criticalResponse.data.faults : []);

      const primaryError = getSettledError(queueResult);
      if (primaryError) {
        setPageError(primaryError);
      }
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setPageError(error.message);
      } else {
        setPageError('Unable to load the fault approval queue right now.');
      }
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void loadFaults();
  }, []);

  const summary = useMemo(() => {
    const pending = faults.filter((fault) => ['reported', 'under_review'].includes(fault.status)).length;
    const pendingCritical = criticalFaults.filter((fault) => ['reported', 'under_review'].includes(fault.status)).length;
    const approved = faults.filter((fault) => fault.status === 'approved').length;
    const converted = faults.filter((fault) => fault.status === 'converted_to_maintenance').length;
    return {
      pending,
      critical: criticalFaults.length,
      pendingCritical,
      approved,
      converted,
    };
  }, [criticalFaults, faults]);

  const filteredFaults = useMemo(() => {
    switch (activeFilter) {
      case 'critical':
        return faults.filter((fault) => fault.severity === 'critical');
      default:
        return faults.filter((fault) => fault.status === activeFilter);
    }
  }, [activeFilter, faults]);

  const ownerTrendData = useMemo(() => {
    const severityCounts = faults.reduce<Record<string, number>>((accumulator, fault) => {
      accumulator[fault.severity] = (accumulator[fault.severity] || 0) + 1;
      return accumulator;
    }, {});
    const categoryCounts = faults.reduce<Record<string, number>>((accumulator, fault) => {
      const name = fault.category?.name || 'Uncategorized';
      accumulator[name] = (accumulator[name] || 0) + 1;
      return accumulator;
    }, {});
    const vehicleCounts = faults.reduce<Record<string, number>>((accumulator, fault) => {
      const label = fault.vehicle?.registration_number || 'Unknown Vehicle';
      accumulator[label] = (accumulator[label] || 0) + 1;
      return accumulator;
    }, {});
    return {
      severityCounts,
      topCategories: Object.entries(categoryCounts).sort((a, b) => b[1] - a[1]).slice(0, 5),
      repeatVehicles: Object.entries(vehicleCounts).sort((a, b) => b[1] - a[1]).slice(0, 5),
    };
  }, [faults]);

  const openReviewModal = (fault: FaultRecord) => {
    setSelectedFault(fault);
    setReviewNote(fault.request_info_note || fault.rejection_reason || fault.admin_notes || '');
    setActionError('');
  };

  const closeReviewModal = () => {
    setSelectedFault(null);
    setReviewNote('');
    setActionError('');
  };

  const runFaultAction = async (faultId: string, action: 'approve' | 'reject' | 'request-info' | 'convert') => {
    setActionError('');
    setIsSubmitting(true);
    try {
      if (action === 'convert') {
        await apiRequest<FaultMutationResponse>(`/faults/${faultId}/convert-to-maintenance`, {
          method: 'POST',
        });
      } else {
        await apiRequest<FaultMutationResponse>(`/faults/${faultId}/${action}`, {
          method: 'PATCH',
          body: JSON.stringify({
            admin_notes: reviewNote,
          }),
        });
      }
      await loadFaults();
      if (selectedFault?.id === faultId) {
        closeReviewModal();
      }
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setActionError(error.message);
      } else {
        setActionError('Unable to complete that fault action right now.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const timeline = useMemo(() => {
    if (!selectedFault) {
      return [];
    }

    return [
      {
        label: 'Reported',
        at: selectedFault.reported_at,
        note: selectedFault.description,
      },
      {
        label: 'Reviewed',
        at: selectedFault.reviewed_at,
        note: selectedFault.admin_notes || selectedFault.owner_notes,
      },
      {
        label: 'More Information Requested',
        at: selectedFault.requested_info_at,
        note: selectedFault.request_info_note,
      },
      {
        label: 'Approved',
        at: selectedFault.approved_at,
        note: selectedFault.admin_notes,
      },
      {
        label: 'Rejected',
        at: selectedFault.rejected_at,
        note: selectedFault.rejection_reason,
      },
      {
        label: 'Converted To Maintenance',
        at: selectedFault.converted_to_maintenance_at,
        note: selectedFault.maintenance_job_id ? `Maintenance Job ${selectedFault.maintenance_job_id}` : null,
      },
      {
        label: 'Resolved',
        at: selectedFault.resolved_at,
        note: selectedFault.resolution_notes,
      },
    ].filter((entry) => entry.at);
  }, [selectedFault]);

  return (
    <div className="space-y-6 p-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-[#0F172A]">Fault Approvals</h1>
          <p className="mt-1 text-gray-600">
            Review new fault submissions, prioritize critical safety issues, and convert approved faults into maintenance jobs.
          </p>
        </div>
        <button
          onClick={() => void loadFaults()}
          className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2.5 font-medium text-gray-700 transition-all hover:bg-gray-50"
        >
          <RefreshCw className="h-4 w-4" />
          Refresh Queue
        </button>
      </div>

      {pageError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {pageError}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-5">
        <SummaryCard label="Pending Fault Approvals" value={summary.pending} icon={Clock3} tone="amber" />
        <SummaryCard label="Critical Faults" value={summary.critical} icon={ShieldAlert} tone="rose" />
        <SummaryCard label="Pending Critical Faults" value={summary.pendingCritical} icon={AlertTriangle} tone="rose" />
        <SummaryCard label="Approved Faults" value={summary.approved} icon={CheckCircle2} tone="blue" />
        <SummaryCard label="Converted To Maintenance" value={summary.converted} icon={Wrench} tone="green" />
      </div>

      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
        <div className="border-b border-gray-200 px-6 py-4">
          <h2 className="text-lg font-semibold text-[#0F172A]">Fault Approval Queue</h2>
          <p className="mt-1 text-sm text-gray-600">
            Critical faults are pinned to the top, highlighted, and ready for review.
          </p>
        </div>

        <div className="border-b border-gray-200 px-4 py-3">
          <div className="flex flex-wrap gap-2">
            {FILTERS.map((filter) => (
              <button
                key={filter.key}
                onClick={() => setActiveFilter(filter.key)}
                className={`rounded-full border px-3 py-1.5 text-sm font-medium transition-all ${
                  activeFilter === filter.key
                    ? 'border-[#2563EB] bg-blue-50 text-[#2563EB]'
                    : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300 hover:text-gray-900'
                }`}
              >
                {filter.label}
              </button>
            ))}
          </div>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center gap-3 px-6 py-16 text-gray-500">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span>Loading fault approval queue...</span>
          </div>
        ) : filteredFaults.length === 0 ? (
          <div className="px-6 py-14 text-center text-gray-500">No faults found for this filter.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  {['Vehicle', 'Driver', 'Category', 'Component', 'Severity', 'Status', 'Date Submitted', 'Action'].map((header) => (
                    <th key={header} className="px-6 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">
                      {header}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {filteredFaults.map((fault) => (
                  <tr
                    key={fault.id}
                    className={`${fault.severity === 'critical' ? 'bg-red-50/60' : 'hover:bg-gray-50'} transition-all`}
                  >
                    <td className="px-6 py-4 text-sm font-medium text-[#0F172A]">
                      <div>{fault.vehicle?.registration_number || 'Vehicle'}</div>
                      <div className="text-xs text-gray-500">
                        {[fault.vehicle?.make, fault.vehicle?.model].filter(Boolean).join(' ') || 'Assigned vehicle'}
                      </div>
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-700">{fault.driver?.full_name || 'Driver'}</td>
                    <td className="px-6 py-4 text-sm text-gray-700">{fault.category?.name || 'Category'}</td>
                    <td className="px-6 py-4 text-sm text-gray-700">{fault.component?.name || 'Component'}</td>
                    <td className="px-6 py-4 text-sm">
                      <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${severityClassName(fault.severity)}`}>
                        {fault.severity === 'critical' ? 'Critical' : formatLabel(fault.severity)}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-sm">
                      <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${statusClassName(fault.status)}`}>
                        {formatLabel(fault.status)}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-600">{formatDate(fault.reported_at)}</td>
                    <td className="px-6 py-4 text-sm">
                      <div className="flex flex-wrap gap-2">
                        <button
                          onClick={() => openReviewModal(fault)}
                          className="inline-flex items-center gap-1 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
                        >
                          <Eye className="h-3.5 w-3.5" />
                          Review
                        </button>
                        {fault.status !== 'approved' && fault.status !== 'converted_to_maintenance' && fault.status !== 'resolved' && (
                          <button
                            onClick={() => openReviewModal(fault)}
                            className="inline-flex items-center gap-1 rounded-lg border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-100"
                          >
                            Approve
                          </button>
                        )}
                        {fault.status !== 'converted_to_maintenance' && fault.status !== 'resolved' && (
                          <button
                            onClick={() => openReviewModal(fault)}
                            className="inline-flex items-center gap-1 rounded-lg border border-red-200 bg-red-50 px-3 py-1.5 text-xs font-medium text-red-700 hover:bg-red-100"
                          >
                            Reject
                          </button>
                        )}
                        {fault.status !== 'converted_to_maintenance' && fault.status !== 'resolved' && (
                          <button
                            onClick={() => openReviewModal(fault)}
                            className="inline-flex items-center gap-1 rounded-lg border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-800 hover:bg-amber-100"
                          >
                            Request More Info
                          </button>
                        )}
                        {fault.status === 'approved' && !fault.maintenance_job_id && (
                          <button
                            onClick={() => void runFaultAction(fault.id, 'convert')}
                            className="inline-flex items-center gap-1 rounded-lg border border-green-200 bg-green-50 px-3 py-1.5 text-xs font-medium text-green-700 hover:bg-green-100"
                          >
                            Convert
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {isOwner && (
        <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
          <OwnerInsightCard
            title="Faults By Severity"
            rows={Object.entries(ownerTrendData.severityCounts).map(([label, value]) => ({
              label: formatLabel(label),
              value,
            }))}
          />
          <OwnerInsightCard
            title="Most Common Faults"
            rows={ownerTrendData.topCategories.map(([label, value]) => ({ label, value }))}
          />
          <OwnerInsightCard
            title="Repeat Fault Vehicles"
            rows={ownerTrendData.repeatVehicles.map(([label, value]) => ({ label, value }))}
          />
        </div>
      )}

      {selectedFault && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4 py-6">
          <div className="flex max-h-[92vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-2xl">
            <div className="flex items-start justify-between border-b border-gray-200 px-6 py-4">
              <div>
                <h2 className="text-xl font-semibold text-[#0F172A]">Fault Review</h2>
                <p className="mt-1 text-sm text-gray-500">
                  {selectedFault.vehicle?.registration_number || 'Vehicle'} • {selectedFault.driver?.full_name || 'Driver'}
                </p>
              </div>
              <button onClick={closeReviewModal} className="rounded-lg p-2 text-gray-500 transition-all hover:bg-gray-100">
                <XCircle className="h-5 w-5" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto px-6 py-5">
              {actionError && (
                <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                  {actionError}
                </div>
              )}

              <div className="grid grid-cols-1 gap-6 xl:grid-cols-[1.5fr,1fr]">
                <div className="space-y-6">
                  <div className={`rounded-xl border p-5 ${selectedFault.severity === 'critical' ? 'border-red-200 bg-red-50' : 'border-gray-200 bg-gray-50'}`}>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${severityClassName(selectedFault.severity)}`}>
                        {selectedFault.severity === 'critical' ? 'Critical' : formatLabel(selectedFault.severity)}
                      </span>
                      <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${statusClassName(selectedFault.status)}`}>
                        {formatLabel(selectedFault.status)}
                      </span>
                    </div>
                    <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
                      <DetailItem label="Vehicle Registration" value={selectedFault.vehicle?.registration_number || 'Not available'} />
                      <DetailItem label="Driver Name" value={selectedFault.driver?.full_name || 'Not available'} />
                      <DetailItem label="Category" value={selectedFault.category?.name || 'Not available'} />
                      <DetailItem label="Component" value={selectedFault.component?.name || 'Not available'} />
                      <DetailItem label="Date Submitted" value={formatDate(selectedFault.reported_at)} />
                      <DetailItem label="Vehicle Status" value={selectedFault.vehicle?.status ? formatLabel(selectedFault.vehicle.status) : 'Not available'} />
                    </div>
                  </div>

                  <div className="rounded-xl border border-gray-200 bg-white p-5">
                    <h3 className="text-sm font-semibold text-[#0F172A]">Description</h3>
                    <p className="mt-2 text-sm leading-6 text-gray-700">
                      {selectedFault.description || 'No description provided.'}
                    </p>
                  </div>

                  <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                    <div className="rounded-xl border border-gray-200 bg-white p-5">
                      <h3 className="text-sm font-semibold text-[#0F172A]">Driver Notes</h3>
                      <p className="mt-2 text-sm text-gray-700">
                        {selectedFault.description || 'No driver notes provided.'}
                      </p>
                    </div>
                    <div className="rounded-xl border border-gray-200 bg-white p-5">
                      <h3 className="text-sm font-semibold text-[#0F172A]">Admin Notes</h3>
                      <p className="mt-2 text-sm text-gray-700">
                        {selectedFault.admin_notes || selectedFault.owner_notes || 'No admin notes recorded yet.'}
                      </p>
                    </div>
                  </div>

                  <div className="rounded-xl border border-gray-200 bg-white p-5">
                    <h3 className="text-sm font-semibold text-[#0F172A]">Photos</h3>
                    {selectedFault.photos.length === 0 ? (
                      <p className="mt-2 text-sm text-gray-500">No photos attached to this fault report.</p>
                    ) : (
                      <div className="mt-3 grid grid-cols-2 gap-3 lg:grid-cols-3">
                        {selectedFault.photos.map((photo, index) => (
                          <div key={`${selectedFault.id}-photo-${index}`} className="overflow-hidden rounded-xl border border-gray-200 bg-gray-50">
                            <img src={photo} alt={`Fault photo ${index + 1}`} className="h-36 w-full object-cover" />
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>

                <div className="space-y-6">
                  <div className="rounded-xl border border-gray-200 bg-gray-50 p-5">
                    <h3 className="text-sm font-semibold text-[#0F172A]">Status Timeline</h3>
                    <div className="mt-4 space-y-4">
                      {timeline.length === 0 ? (
                        <div className="text-sm text-gray-500">No timeline events recorded yet.</div>
                      ) : (
                        timeline.map((entry) => (
                          <div key={`${entry.label}-${entry.at}`} className="flex gap-3">
                            <div className="mt-1 h-2.5 w-2.5 rounded-full bg-[#2563EB]" />
                            <div>
                              <div className="text-sm font-medium text-[#0F172A]">{entry.label}</div>
                              <div className="text-xs text-gray-500">{formatDate(entry.at)}</div>
                              {entry.note && <div className="mt-1 text-sm text-gray-600">{entry.note}</div>}
                            </div>
                          </div>
                        ))
                      )}
                    </div>
                  </div>

                  <div className="rounded-xl border border-gray-200 bg-white p-5">
                    <label className="mb-2 block text-sm font-medium text-gray-700">Review Note</label>
                    <textarea
                      value={reviewNote}
                      onChange={(event) => setReviewNote(event.target.value)}
                      className="min-h-[140px] w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                      placeholder="Add approval notes, rejection reason, or more information request details."
                    />
                    <p className="mt-2 text-xs text-gray-500">
                      Rejection and request-more-information actions require a note.
                    </p>
                  </div>
                </div>
              </div>
            </div>

            <div className="border-t border-gray-200 bg-gray-50 px-6 py-4">
              <div className="flex flex-wrap items-center justify-end gap-3">
                <button
                  type="button"
                  onClick={closeReviewModal}
                  className="rounded-lg border border-gray-300 bg-white px-4 py-2.5 font-medium text-gray-700 transition-all hover:bg-gray-50"
                >
                  Close
                </button>
                {selectedFault.status !== 'approved' &&
                  selectedFault.status !== 'converted_to_maintenance' &&
                  selectedFault.status !== 'resolved' && (
                    <>
                      <button
                        type="button"
                        disabled={isSubmitting}
                        onClick={() => void runFaultAction(selectedFault.id, 'request-info')}
                        className="inline-flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-4 py-2.5 font-medium text-amber-800 transition-all hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-70"
                      >
                        {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <MessageSquareMore className="h-4 w-4" />}
                        Request More Info
                      </button>
                      <button
                        type="button"
                        disabled={isSubmitting}
                        onClick={() => void runFaultAction(selectedFault.id, 'reject')}
                        className="inline-flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 font-medium text-red-700 transition-all hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-70"
                      >
                        {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <XCircle className="h-4 w-4" />}
                        Reject
                      </button>
                      <button
                        type="button"
                        disabled={isSubmitting}
                        onClick={() => void runFaultAction(selectedFault.id, 'approve')}
                        className="inline-flex items-center gap-2 rounded-lg bg-[#2563EB] px-4 py-2.5 font-medium text-white transition-all hover:bg-[#1d4ed8] disabled:cursor-not-allowed disabled:opacity-70"
                      >
                        {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                        Approve
                      </button>
                    </>
                  )}
                {selectedFault.status === 'approved' && !selectedFault.maintenance_job_id && (
                  <button
                    type="button"
                    disabled={isSubmitting}
                    onClick={() => void runFaultAction(selectedFault.id, 'convert')}
                    className="inline-flex items-center gap-2 rounded-lg bg-green-600 px-4 py-2.5 font-medium text-white transition-all hover:bg-green-700 disabled:cursor-not-allowed disabled:opacity-70"
                  >
                    {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wrench className="h-4 w-4" />}
                    Convert To Maintenance
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function SummaryCard({
  label,
  value,
  icon: Icon,
  tone,
}: {
  label: string;
  value: number;
  icon: typeof Clock3;
  tone: 'amber' | 'rose' | 'blue' | 'green';
}) {
  const toneClasses = {
    amber: 'bg-amber-100 text-amber-600',
    rose: 'bg-rose-100 text-rose-600',
    blue: 'bg-blue-100 text-blue-600',
    green: 'bg-green-100 text-green-600',
  }[tone];

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5">
      <div className={`mb-3 flex h-10 w-10 items-center justify-center rounded-lg ${toneClasses}`}>
        <Icon className="h-5 w-5" />
      </div>
      <div className="text-2xl font-semibold text-[#0F172A]">{value}</div>
      <div className="text-sm text-gray-600">{label}</div>
    </div>
  );
}

function DetailItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs font-semibold uppercase tracking-wide text-gray-500">{label}</div>
      <div className="mt-1 text-sm font-medium text-[#0F172A]">{value}</div>
    </div>
  );
}

function OwnerInsightCard({
  title,
  rows,
}: {
  title: string;
  rows: { label: string; value: number }[];
}) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5">
      <h3 className="text-sm font-semibold text-[#0F172A]">{title}</h3>
      <div className="mt-4 space-y-3">
        {rows.length === 0 ? (
          <div className="text-sm text-gray-500">No fault trend data yet.</div>
        ) : (
          rows.map((row) => (
            <div key={`${title}-${row.label}`} className="flex items-center justify-between rounded-lg bg-gray-50 px-3 py-2">
              <span className="text-sm text-gray-700">{row.label}</span>
              <span className="text-sm font-semibold text-[#0F172A]">{row.value}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
