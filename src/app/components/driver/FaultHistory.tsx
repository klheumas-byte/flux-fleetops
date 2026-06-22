import { useEffect, useState } from 'react';
import { AlertTriangle, Loader2 } from 'lucide-react';
import { apiRequest, ApiRequestError } from '../../lib/api';

type FaultStatus =
  | 'reported'
  | 'under_review'
  | 'approved'
  | 'rejected'
  | 'converted_to_maintenance'
  | 'resolved';

interface FaultHistoryRecord {
  id: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  status: FaultStatus;
  reported_at: string | null;
  resolution_notes: string | null;
  admin_notes: string | null;
  owner_notes: string | null;
  vehicle?: {
    registration_number: string;
    make?: string | null;
    model?: string | null;
  } | null;
  category?: {
    name: string;
  } | null;
  component?: {
    name: string;
  } | null;
}

interface FaultsResponse {
  success: boolean;
  data: {
    faults: FaultHistoryRecord[];
  };
}

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
    case 'resolved':
      return 'border-green-200 bg-green-100 text-green-800';
    case 'rejected':
      return 'border-rose-200 bg-rose-100 text-rose-800';
    case 'converted_to_maintenance':
      return 'border-purple-200 bg-purple-100 text-purple-800';
    case 'under_review':
      return 'border-amber-200 bg-amber-100 text-amber-800';
    default:
      return 'border-slate-200 bg-slate-100 text-slate-800';
  }
}

export default function FaultHistory() {
  const [faults, setFaults] = useState<FaultHistoryRecord[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [pageError, setPageError] = useState('');

  useEffect(() => {
    const loadFaults = async () => {
      setIsLoading(true);
      setPageError('');
      try {
        const response = await apiRequest<FaultsResponse>('/faults');
        setFaults(Array.isArray(response.data?.faults) ? response.data.faults : []);
      } catch (error) {
        if (error instanceof ApiRequestError) {
          setPageError(error.message);
        } else {
          setPageError('Unable to load your fault history right now.');
        }
      } finally {
        setIsLoading(false);
      }
    };

    void loadFaults();
  }, []);

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold text-[#0F172A]">Fault History</h1>
        <p className="mt-1 text-gray-600">Track every fault report you have submitted for your assigned vehicle.</p>
      </div>

      {pageError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {pageError}
        </div>
      )}

      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
        <div className="border-b border-gray-200 px-6 py-4">
          <h2 className="text-lg font-semibold text-[#0F172A]">Reported Faults</h2>
          <p className="mt-1 text-sm text-gray-600">Status updates, review notes, and resolution details appear here.</p>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center gap-3 px-6 py-16 text-gray-500">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span>Loading fault history...</span>
          </div>
        ) : faults.length === 0 ? (
          <div className="px-6 py-12 text-center text-gray-500">No fault reports submitted yet.</div>
        ) : (
          <div className="space-y-4 px-6 py-5">
            {faults.map((fault) => (
              <div key={fault.id} className="rounded-xl border border-gray-200 bg-gray-50 p-4">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div className="min-w-0 space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold text-[#0F172A]">
                        {fault.vehicle?.registration_number || 'Vehicle'} - {fault.category?.name || 'Category'}
                      </span>
                      <span className="rounded-full border border-gray-200 bg-white px-2.5 py-1 text-xs font-medium text-gray-700">
                        {fault.component?.name || 'Component'}
                      </span>
                      <span className="rounded-full border border-gray-200 bg-white px-2.5 py-1 text-xs font-medium capitalize text-gray-700">
                        {fault.severity}
                      </span>
                    </div>
                    <div className="text-sm text-gray-600">Reported: {formatDate(fault.reported_at)}</div>
                    <div className="text-sm text-gray-600">
                      Resolution Notes: {fault.resolution_notes || fault.admin_notes || fault.owner_notes || 'No notes yet'}
                    </div>
                  </div>
                  <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${statusClassName(fault.status)}`}>
                    {formatLabel(fault.status)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-800">
        <div className="flex items-start gap-3">
          <AlertTriangle className="mt-0.5 h-5 w-5 flex-shrink-0" />
          <div>Use Report Fault to add more details if an admin requests more information while a fault is under review.</div>
        </div>
      </div>
    </div>
  );
}
