import { useEffect, useMemo, useState } from 'react';
import {
  AlertCircle,
  Calendar,
  CheckCircle,
  Clock,
  Eye,
  Filter,
  History,
  Loader2,
  Plus,
  Search,
  Truck,
  Users,
  XCircle,
} from 'lucide-react';
import { apiRequest, ApiRequestError } from '../../lib/api';
import { useDebouncedValue } from '../../lib/use-debounced-value';

type AssignmentStatus = 'active' | 'ended' | 'suspended';

interface DriverOption {
  id: string;
  full_name: string;
  phone: string;
  status: string;
  driver_profile: {
    approval_status?: string | null;
    assigned_vehicle_id?: string | null;
  } | null;
}

interface VehicleOption {
  id: string;
  registration_number: string;
  vehicle_type: string;
  status: string;
}

interface Assignment {
  id: string;
  driver_id: string;
  vehicle_id: string;
  weekly_target: number;
  daily_target: number;
  start_date: string;
  end_date: string | null;
  status: AssignmentStatus;
  created_at: string | null;
  updated_at: string | null;
  assigned_by?: string | null;
  driver: {
    id: string;
    full_name: string;
    phone: string;
    driver_profile: {
      approval_status?: string | null;
      assigned_vehicle_id?: string | null;
    } | null;
  } | null;
  vehicle: {
    id: string;
    registration_number: string;
    vehicle_type: string;
    status: string;
  } | null;
}

interface AssignmentsResponse {
  success: boolean;
  message: string;
  data: {
    assignments: Assignment[];
  };
}

interface AssignmentOptionsResponse {
  success: boolean;
  message: string;
  data: {
    drivers: DriverOption[];
    vehicles: VehicleOption[];
  };
}

interface AssignmentMutationResponse {
  success: boolean;
  message: string;
  data: {
    assignment: Assignment;
  };
}

interface AssignmentFormState {
  driver_id: string;
  vehicle_id: string;
  weekly_target: string;
  daily_target: string;
  start_date: string;
}

const initialFormState: AssignmentFormState = {
  driver_id: '',
  vehicle_id: '',
  weekly_target: '',
  daily_target: '',
  start_date: '',
};

function formatCurrency(value: number) {
  return `GHS ${value.toLocaleString()}`;
}

function formatDate(value: string | null) {
  if (!value) {
    return 'Not set';
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  return parsed.toLocaleDateString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  });
}

function formatStatus(value: AssignmentStatus) {
  switch (value) {
    case 'active':
      return 'Active';
    case 'suspended':
      return 'Suspended';
    default:
      return 'Ended';
  }
}

export default function Assignments() {
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [showAssignModal, setShowAssignModal] = useState(false);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [assignableDrivers, setAssignableDrivers] = useState<DriverOption[]>([]);
  const [assignableVehicles, setAssignableVehicles] = useState<VehicleOption[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [pageError, setPageError] = useState('');
  const [formError, setFormError] = useState('');
  const [formState, setFormState] = useState<AssignmentFormState>(initialFormState);

  const storedUser = localStorage.getItem('flux_user');
  const currentRole = storedUser ? JSON.parse(storedUser).role : null;
  const debouncedSearchQuery = useDebouncedValue(searchQuery, 250);

  const getSettledData = <T,>(result: PromiseSettledResult<T>, fallback: T): T =>
    result.status === 'fulfilled' ? result.value : fallback;

  const getSettledError = (result: PromiseSettledResult<unknown>) =>
    result.status === 'rejected'
      ? result.reason instanceof ApiRequestError
        ? result.reason.message
        : 'Unable to load some assignment data right now.'
      : null;

  const loadAssignments = async () => {
    setIsLoading(true);
    setPageError('');

    try {
      const [assignmentsResult, optionsResult] = await Promise.allSettled([
        apiRequest<AssignmentsResponse>('/assignments', { cacheTtlMs: 10000, timeoutMs: 15000 }),
        apiRequest<AssignmentOptionsResponse>('/assignments/options', { cacheTtlMs: 10000, timeoutMs: 15000 }),
      ]);

      const assignmentsResponse = getSettledData<AssignmentsResponse | null>(assignmentsResult, null);
      const optionsResponse = getSettledData<AssignmentOptionsResponse | null>(optionsResult, null);
      const errors = [getSettledError(assignmentsResult), getSettledError(optionsResult)].filter(Boolean);

      setAssignments(Array.isArray(assignmentsResponse?.data?.assignments) ? assignmentsResponse.data.assignments : []);
      setAssignableDrivers(Array.isArray(optionsResponse?.data?.drivers) ? optionsResponse.data.drivers : []);
      setAssignableVehicles(Array.isArray(optionsResponse?.data?.vehicles) ? optionsResponse.data.vehicles : []);

      if (errors.length > 0) {
        setPageError(errors[0] as string);
      }
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (currentRole === 'driver') {
      setIsLoading(false);
      return;
    }

    void loadAssignments();
  }, [currentRole]);

  const filteredAssignments = useMemo(
    () =>
      assignments.filter((assignment) => {
        const vehicleName = assignment.vehicle?.registration_number || '';
        const driverName = assignment.driver?.full_name || '';
        const matchesSearch =
          vehicleName.toLowerCase().includes(debouncedSearchQuery.toLowerCase()) ||
          driverName.toLowerCase().includes(debouncedSearchQuery.toLowerCase());
        const matchesStatus = statusFilter === 'all' || assignment.status === statusFilter;
        return matchesSearch && matchesStatus;
      }),
    [assignments, debouncedSearchQuery, statusFilter],
  );

  const activeAssignments = assignments.filter((assignment) => assignment.status === 'active').length;
  const availableVehicles = assignableVehicles.length;
  const assignableDriversCount = assignableDrivers.length;
  const weeklyRevenueForecast = assignments
    .filter((assignment) => assignment.status === 'active')
    .reduce((sum, assignment) => sum + assignment.weekly_target, 0);

  const getStatusColor = (status: AssignmentStatus) => {
    switch (status) {
      case 'active':
        return 'bg-green-100 text-green-800 border-green-200';
      case 'suspended':
        return 'bg-amber-100 text-amber-800 border-amber-200';
      default:
        return 'bg-red-100 text-red-800 border-red-200';
    }
  };

  const getAchievementColor = (weeklyTarget: number, dailyTarget: number) => {
    const rate = weeklyTarget / (dailyTarget * 7) * 100;
    if (rate >= 100) return 'text-green-600';
    if (rate >= 75) return 'text-blue-600';
    if (rate >= 50) return 'text-yellow-600';
    return 'text-red-600';
  };

  const handleFieldChange = (field: keyof AssignmentFormState, value: string) => {
    setFormState((current) => ({
      ...current,
      [field]: value,
    }));
  };

  const closeModal = () => {
    setShowAssignModal(false);
    setFormState(initialFormState);
    setFormError('');
  };

  const handleCreateAssignment = async (event: React.FormEvent) => {
    event.preventDefault();
    setIsSubmitting(true);
    setFormError('');

    try {
      await apiRequest<AssignmentMutationResponse>('/assignments', {
        method: 'POST',
        body: JSON.stringify({
          driver_id: formState.driver_id,
          vehicle_id: formState.vehicle_id,
          weekly_target: Number(formState.weekly_target),
          daily_target: Number(formState.daily_target),
          start_date: formState.start_date,
        }),
      });

      closeModal();
      await loadAssignments();
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setFormError(error.message);
      } else {
        setFormError('Unable to create assignment right now.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleEndAssignment = async (assignmentId: string) => {
    setPageError('');

    try {
      await apiRequest<AssignmentMutationResponse>(`/assignments/${assignmentId}/end`, {
        method: 'PATCH',
      });
      await loadAssignments();
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setPageError(error.message);
      } else {
        setPageError('Unable to end assignment right now.');
      }
    }
  };

  if (currentRole === 'driver') {
    return (
      <div className="p-6">
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Drivers do not have access to Vehicle Assignments.
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-[#0F172A]">Vehicle Assignments</h1>
        <p className="mt-1 text-gray-600">Manage vehicle-to-driver assignments and targets</p>
      </div>

      <div className="grid grid-cols-4 gap-6">
        <div className="rounded-xl border border-gray-200 bg-white p-6">
          <div className="mb-4 flex items-center justify-between">
            <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-green-100">
              <CheckCircle className="h-6 w-6 text-green-600" />
            </div>
            <span className="rounded bg-green-50 px-2 py-1 text-xs font-medium text-green-600">
              Active
            </span>
          </div>
          <div className="mb-1 text-3xl font-bold text-[#0F172A]">{activeAssignments}</div>
          <div className="text-sm text-gray-600">Active Assignments</div>
        </div>

        <div className="rounded-xl border border-gray-200 bg-white p-6">
          <div className="mb-4 flex items-center justify-between">
            <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-blue-100">
              <Truck className="h-6 w-6 text-blue-600" />
            </div>
            <span className="rounded bg-blue-50 px-2 py-1 text-xs font-medium text-blue-600">
              Ready
            </span>
          </div>
          <div className="mb-1 text-3xl font-bold text-[#0F172A]">{availableVehicles}</div>
          <div className="text-sm text-gray-600">Available Vehicles</div>
        </div>

        <div className="rounded-xl border border-gray-200 bg-white p-6">
          <div className="mb-4 flex items-center justify-between">
            <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-purple-100">
              <Users className="h-6 w-6 text-purple-600" />
            </div>
            <span className="rounded bg-purple-50 px-2 py-1 text-xs font-medium text-purple-600">
              Eligible
            </span>
          </div>
          <div className="mb-1 text-3xl font-bold text-[#0F172A]">{assignableDriversCount}</div>
          <div className="text-sm text-gray-600">Approved Drivers</div>
        </div>

        <div className="rounded-xl border border-gray-200 bg-white p-6">
          <div className="mb-4 flex items-center justify-between">
            <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-amber-100">
              <Clock className="h-6 w-6 text-amber-600" />
            </div>
            <span className="rounded bg-amber-50 px-2 py-1 text-xs font-medium text-amber-600">
              Forecast
            </span>
          </div>
          <div className="mb-1 text-3xl font-bold text-[#0F172A]">
            {formatCurrency(weeklyRevenueForecast)}
          </div>
          <div className="text-sm text-gray-600">Weekly Revenue Forecast</div>
        </div>
      </div>

      <div className="rounded-xl border border-gray-200 bg-white p-4">
        <div className="flex items-center justify-between gap-4">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 transform text-gray-400" />
            <input
              type="text"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder="Search by vehicle or driver name..."
              className="w-full rounded-lg border border-gray-300 py-2.5 pl-10 pr-4 transition-all focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
            />
          </div>

          <div className="flex items-center gap-2">
            <Filter className="h-5 w-5 text-gray-500" />
            <select
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value)}
              className="rounded-lg border border-gray-300 px-4 py-2.5 transition-all focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
            >
              <option value="all">All Status</option>
              <option value="active">Active</option>
              <option value="suspended">Suspended</option>
              <option value="ended">Ended</option>
            </select>
          </div>

          <button
            onClick={() => setShowAssignModal(true)}
            className="flex items-center gap-2 rounded-lg bg-[#2563EB] px-4 py-2.5 font-medium text-white transition-all hover:bg-[#1d4ed8]"
          >
            <Plus className="h-5 w-5" />
            Assign Vehicle
          </button>
        </div>
      </div>

      {pageError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {pageError}
        </div>
      )}

      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
        {isLoading ? (
          <div className="flex items-center justify-center gap-3 px-6 py-16 text-gray-500">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span>Loading assignments...</span>
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="border-b border-gray-200 bg-gray-50">
                  <tr>
                    <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">
                      Driver
                    </th>
                    <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">
                      Vehicle
                    </th>
                    <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">
                      Weekly Target
                    </th>
                    <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">
                      Daily Target
                    </th>
                    <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">
                      Status
                    </th>
                    <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">
                      Start Date
                    </th>
                    <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">
                      Performance
                    </th>
                    <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {filteredAssignments.map((assignment) => {
                    const driverName = assignment.driver?.full_name || 'Unknown Driver';
                    const vehicleLabel = assignment.vehicle?.registration_number || 'Unknown Vehicle';
                    const vehicleType = assignment.vehicle?.vehicle_type || 'Vehicle';
                    const achievementColor = getAchievementColor(
                      assignment.weekly_target,
                      assignment.daily_target,
                    );

                    return (
                      <tr key={assignment.id} className="transition-colors hover:bg-gray-50">
                        <td className="px-6 py-4">
                          <div className="flex items-center gap-3">
                            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-[#2563EB]">
                              <span className="text-xs font-semibold text-white">
                                {driverName
                                  .split(' ')
                                  .map((name) => name[0])
                                  .join('')
                                  .slice(0, 2)}
                              </span>
                            </div>
                            <div>
                              <div className="font-medium text-[#0F172A]">{driverName}</div>
                              <div className="text-xs text-gray-500">
                                {assignment.driver?.phone || 'No phone'}
                              </div>
                            </div>
                          </div>
                        </td>
                        <td className="px-6 py-4">
                          <div>
                            <div className="font-semibold text-[#0F172A]">{vehicleLabel}</div>
                            <div className="text-sm text-gray-600">
                              {vehicleType.charAt(0).toUpperCase() + vehicleType.slice(1)}
                            </div>
                          </div>
                        </td>
                        <td className="px-6 py-4">
                          <div className="font-semibold text-[#0F172A]">
                            {formatCurrency(assignment.weekly_target)}
                          </div>
                        </td>
                        <td className="px-6 py-4">
                          <div className="text-gray-700">{formatCurrency(assignment.daily_target)}</div>
                        </td>
                        <td className="px-6 py-4">
                          <span
                            className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-medium ${getStatusColor(assignment.status)}`}
                          >
                            {formatStatus(assignment.status)}
                          </span>
                        </td>
                        <td className="px-6 py-4">
                          <div className="flex items-center gap-2 text-gray-700">
                            <Calendar className="h-4 w-4 text-gray-400" />
                            <span>{formatDate(assignment.start_date)}</span>
                          </div>
                        </td>
                        <td className="px-6 py-4">
                          <div className={`text-sm font-semibold ${achievementColor}`}>
                            {(assignment.weekly_target / (assignment.daily_target * 7) * 100).toFixed(1)}%
                          </div>
                        </td>
                        <td className="px-6 py-4">
                          <div className="flex items-center gap-2">
                            {assignment.status !== 'ended' && (
                              <button
                                onClick={() => void handleEndAssignment(assignment.id)}
                                className="rounded p-1.5 text-red-600 transition-all hover:bg-red-50"
                                title="End Assignment"
                              >
                                <XCircle className="h-4 w-4" />
                              </button>
                            )}
                            <button
                              className="rounded p-1.5 text-gray-600 transition-all hover:bg-gray-100"
                              title="View History"
                            >
                              <History className="h-4 w-4" />
                            </button>
                            <button
                              className="rounded p-1.5 text-gray-600 transition-all hover:bg-gray-100"
                              title="View Details"
                            >
                              <Eye className="h-4 w-4" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {filteredAssignments.length === 0 && (
              <div className="py-12 text-center">
                <Truck className="mx-auto mb-3 h-12 w-12 text-gray-300" />
                <p className="text-gray-500">{assignments.length === 0 ? 'No assignments found.' : 'No matching records found.'}</p>
              </div>
            )}
          </>
        )}
      </div>

      <div className="rounded-xl border border-gray-200 bg-white p-4">
        <div className="flex items-center justify-between text-sm">
          <div className="text-gray-600">
            Showing <span className="font-semibold text-[#0F172A]">{filteredAssignments.length}</span>{' '}
            of <span className="font-semibold text-[#0F172A]">{assignments.length}</span>{' '}
            assignments
          </div>
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-2">
              <div className="h-3 w-3 rounded-full bg-green-500"></div>
              <span className="text-gray-600">
                Active: {assignments.filter((assignment) => assignment.status === 'active').length}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <div className="h-3 w-3 rounded-full bg-amber-500"></div>
              <span className="text-gray-600">
                Suspended:{' '}
                {assignments.filter((assignment) => assignment.status === 'suspended').length}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <div className="h-3 w-3 rounded-full bg-red-500"></div>
              <span className="text-gray-600">
                Ended: {assignments.filter((assignment) => assignment.status === 'ended').length}
              </span>
            </div>
          </div>
        </div>
      </div>

      {showAssignModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4">
          <div className="flex h-[85vh] w-full max-w-2xl flex-col overflow-hidden rounded-xl border border-gray-200 bg-white shadow-2xl">
            <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
              <h2 className="text-xl font-semibold text-[#0F172A]">Assign Vehicle to Driver</h2>
              <button
                onClick={closeModal}
                className="rounded-lg p-2 transition-all hover:bg-gray-100"
              >
                <XCircle className="h-5 w-5 text-gray-500" />
              </button>
            </div>

            <form onSubmit={handleCreateAssignment} className="flex min-h-0 flex-1 flex-col">
              <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-6 py-5">
                {formError && (
                  <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                    {formError}
                  </div>
                )}

                <div>
                  <label className="mb-2 block text-sm font-medium text-gray-700">Select Driver</label>
                  <select
                    value={formState.driver_id}
                    onChange={(event) => handleFieldChange('driver_id', event.target.value)}
                    className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                    required
                  >
                    <option value="">Choose approved driver...</option>
                    {assignableDrivers.map((driver) => (
                      <option key={driver.id} value={driver.id}>
                        {driver.full_name} - {driver.phone}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="mb-2 block text-sm font-medium text-gray-700">Select Vehicle</label>
                  <select
                    value={formState.vehicle_id}
                    onChange={(event) => handleFieldChange('vehicle_id', event.target.value)}
                    className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                    required
                  >
                    <option value="">Choose available vehicle...</option>
                    {assignableVehicles.map((vehicle) => (
                      <option key={vehicle.id} value={vehicle.id}>
                        {vehicle.registration_number} - {vehicle.vehicle_type}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  <div>
                    <label className="mb-2 block text-sm font-medium text-gray-700">
                      Weekly Target (GHS)
                    </label>
                    <input
                      type="number"
                      step="0.01"
                      value={formState.weekly_target}
                      onChange={(event) => handleFieldChange('weekly_target', event.target.value)}
                      className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                      required
                    />
                  </div>
                  <div>
                    <label className="mb-2 block text-sm font-medium text-gray-700">
                      Daily Target (GHS)
                    </label>
                    <input
                      type="number"
                      step="0.01"
                      value={formState.daily_target}
                      onChange={(event) => handleFieldChange('daily_target', event.target.value)}
                      className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                      required
                    />
                  </div>
                </div>

                <div>
                  <label className="mb-2 block text-sm font-medium text-gray-700">Start Date</label>
                  <input
                    type="date"
                    value={formState.start_date}
                    onChange={(event) => handleFieldChange('start_date', event.target.value)}
                    className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                    required
                  />
                </div>

                <div className="flex items-start gap-3 rounded-xl border border-blue-100 bg-blue-50 px-4 py-3 text-sm text-blue-700">
                  <AlertCircle className="mt-0.5 h-5 w-5" />
                  <div>
                    Assignment will link the selected driver and vehicle, mark the vehicle as assigned,
                    and prevent duplicate active assignments.
                  </div>
                </div>
              </div>

              <div className="shrink-0 border-t border-gray-200 bg-gray-50 px-6 py-4">
                <div className="flex items-center justify-end gap-3">
                  <button
                    type="button"
                    onClick={closeModal}
                    className="rounded-lg border border-gray-300 px-4 py-2.5 font-medium transition-all hover:bg-gray-50"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={isSubmitting}
                    className="flex items-center gap-2 rounded-lg bg-[#2563EB] px-4 py-2.5 font-medium text-white transition-all hover:bg-[#1d4ed8] disabled:cursor-not-allowed disabled:opacity-70"
                  >
                    {isSubmitting && <Loader2 className="h-4 w-4 animate-spin" />}
                    {isSubmitting ? 'Creating Assignment...' : 'Create Assignment'}
                  </button>
                </div>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
