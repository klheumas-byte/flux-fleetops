import { useEffect, useMemo, useState, type ChangeEvent, type ReactNode } from 'react';
import {
  AlertCircle,
  BarChart3,
  Calendar,
  CheckCircle2,
  DollarSign,
  Droplets,
  Fuel,
  Gauge,
  Loader2,
  Plus,
  RefreshCw,
  Upload,
  XCircle,
} from 'lucide-react';
import { apiRequest, ApiRequestError } from '../../lib/api';
import { fetchDriverActiveAssignment, type DriverActiveAssignment } from '../../lib/driver-api';

type FuelLogStatus = 'submitted' | 'approved' | 'rejected';

interface FuelStation {
  id: string;
  station_name: string;
  brand_name: string | null;
  location: string | null;
  city: string | null;
  status: 'active' | 'inactive';
}

interface FuelLog {
  id: string;
  fuel_date: string;
  fuel_type: string;
  litres: number;
  amount: number;
  price_per_litre: number;
  odometer_reading: number;
  receipt_image: string | null;
  notes: string | null;
  status: FuelLogStatus;
  rejection_reason: string | null;
  cost_per_km: number | null;
  abnormal_spending: boolean;
  fuel_station?: FuelStation | null;
}

interface FuelAnalytics {
  total_fuel_spend: number;
  total_litres: number;
  average_price_per_litre: number;
  abnormal_fuel_spending: FuelLog[];
}

interface DriverFuelLogsResponse {
  success: boolean;
  data: {
    logs: FuelLog[];
    analytics: FuelAnalytics;
  };
}

interface FuelStationsResponse {
  success: boolean;
  data: {
    stations: FuelStation[];
  };
}

interface FuelLogMutationResponse {
  success: boolean;
  data: {
    log: FuelLog;
  };
}

interface FuelFormState {
  fuel_station_id: string;
  fuel_date: string;
  fuel_type: string;
  litres: string;
  amount: string;
  odometer_reading: string;
  notes: string;
  receipt_image: string | null;
  receipt_file_name: string;
}

const initialFuelForm: FuelFormState = {
  fuel_station_id: '',
  fuel_date: new Date().toISOString().slice(0, 10),
  fuel_type: 'petrol',
  litres: '',
  amount: '',
  odometer_reading: '',
  notes: '',
  receipt_image: null,
  receipt_file_name: '',
};

function formatCurrency(value: number) {
  return `GHS ${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatDate(value: string | null | undefined) {
  if (!value) {
    return 'Not provided';
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleDateString();
}

function statusClassName(status: FuelLogStatus) {
  switch (status) {
    case 'approved':
      return 'border-green-200 bg-green-100 text-green-700';
    case 'rejected':
      return 'border-red-200 bg-red-100 text-red-700';
    default:
      return 'border-amber-200 bg-amber-100 text-amber-700';
  }
}

function readFileAsDataUrl(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(new Error('Unable to read the selected file.'));
    reader.readAsDataURL(file);
  });
}

export default function FuelLogs() {
  const [activeAssignment, setActiveAssignment] = useState<DriverActiveAssignment | null>(null);
  const [logs, setLogs] = useState<FuelLog[]>([]);
  const [analytics, setAnalytics] = useState<FuelAnalytics>({
    total_fuel_spend: 0,
    total_litres: 0,
    average_price_per_litre: 0,
    abnormal_fuel_spending: [],
  });
  const [stations, setStations] = useState<FuelStation[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [pageError, setPageError] = useState('');
  const [formError, setFormError] = useState('');
  const [showAddModal, setShowAddModal] = useState(false);
  const [formState, setFormState] = useState<FuelFormState>(initialFuelForm);

  const loadFuelData = async () => {
    setIsLoading(true);
    setPageError('');
    try {
      const [assignment, logsResponse, stationsResponse] = await Promise.all([
        fetchDriverActiveAssignment(),
        apiRequest<DriverFuelLogsResponse>('/driver/fuel-logs'),
        apiRequest<FuelStationsResponse>('/fuel-stations'),
      ]);
      setActiveAssignment(assignment);
      setLogs(Array.isArray(logsResponse.data?.logs) ? logsResponse.data.logs : []);
      setAnalytics(logsResponse.data?.analytics || analytics);
      const nextStations = Array.isArray(stationsResponse.data?.stations) ? stationsResponse.data.stations : [];
      setStations(nextStations);
      setFormState((current) => ({
        ...current,
        fuel_station_id: current.fuel_station_id || nextStations[0]?.id || '',
        fuel_type: assignment?.vehicle?.fuel_type || current.fuel_type,
      }));
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setPageError(error.message);
      } else {
        setPageError('Unable to load fuel logs right now.');
      }
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void loadFuelData();
  }, []);

  const approvedLogs = logs.filter((log) => log.status === 'approved');
  const averageLitres = approvedLogs.length
    ? approvedLogs.reduce((sum, log) => sum + log.litres, 0) / approvedLogs.length
    : 0;

  const pricePerLitrePreview = useMemo(() => {
    const litres = Number(formState.litres);
    const amount = Number(formState.amount);
    if (!litres || !amount) {
      return null;
    }
    return amount / litres;
  }, [formState.amount, formState.litres]);

  const handleFileChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) {
      setFormState((current) => ({
        ...current,
        receipt_image: null,
        receipt_file_name: '',
      }));
      return;
    }

    try {
      const dataUrl = await readFileAsDataUrl(file);
      setFormState((current) => ({
        ...current,
        receipt_image: dataUrl,
        receipt_file_name: file.name,
      }));
    } catch (error) {
      setFormError(error instanceof Error ? error.message : 'Unable to process the selected receipt file.');
    }
  };

  const handleSubmitFuelLog = async (event: React.FormEvent) => {
    event.preventDefault();
    setIsSubmitting(true);
    setFormError('');
    try {
      await apiRequest<FuelLogMutationResponse>('/fuel-logs', {
        method: 'POST',
        body: JSON.stringify({
          fuel_station_id: formState.fuel_station_id,
          fuel_date: formState.fuel_date,
          fuel_type: formState.fuel_type,
          litres: Number(formState.litres),
          amount: Number(formState.amount),
          odometer_reading: Number(formState.odometer_reading),
          receipt_image: formState.receipt_image,
          notes: formState.notes,
        }),
      });
      setShowAddModal(false);
      setFormState({
        ...initialFuelForm,
        fuel_station_id: stations[0]?.id || '',
        fuel_type: activeAssignment?.vehicle?.fuel_type || 'petrol',
      });
      await loadFuelData();
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setFormError(error.message);
      } else {
        setFormError('Unable to submit fuel log right now.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#F8FAFC] pb-6">
      <div className="mb-6 bg-gradient-to-r from-[#0F172A] to-[#1e293b] p-6">
        <div className="mx-auto max-w-6xl">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <h1 className="text-2xl font-bold text-white">Fuel Logs</h1>
              <p className="mt-2 text-sm text-gray-300">
                Submit fuel purchases for your assigned vehicle and track approval status.
              </p>
              <div className="mt-3 text-sm text-gray-300">
                Assigned Vehicle:{' '}
                <span className="font-medium text-white">
                  {activeAssignment?.vehicle?.registration_number || 'No active vehicle'}
                </span>
              </div>
            </div>
            <div className="flex flex-wrap gap-3">
              <button
                onClick={() => void loadFuelData()}
                className="inline-flex items-center gap-2 rounded-lg bg-white/10 px-4 py-2.5 text-sm font-medium text-white transition-all hover:bg-white/20"
              >
                <RefreshCw className="h-4 w-4" />
                Refresh
              </button>
              <button
                onClick={() => setShowAddModal(true)}
                disabled={!activeAssignment}
                className="inline-flex items-center gap-2 rounded-lg bg-[#2563EB] px-4 py-2.5 text-sm font-medium text-white transition-all hover:bg-[#1d4ed8] disabled:cursor-not-allowed disabled:opacity-70"
              >
                <Plus className="h-4 w-4" />
                Submit Fuel Log
              </button>
            </div>
          </div>
        </div>
      </div>

      <div className="mx-auto max-w-6xl space-y-6 px-4">
        {pageError && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {pageError}
          </div>
        )}

        {!activeAssignment && !isLoading && (
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-5">
            <div className="flex items-start gap-3">
              <AlertCircle className="mt-0.5 h-5 w-5 text-amber-600" />
              <div>
                <h3 className="text-sm font-semibold text-amber-900">No active assignment</h3>
                <p className="mt-1 text-sm text-amber-700">
                  You need an active vehicle assignment before you can submit a fuel log.
                </p>
              </div>
            </div>
          </div>
        )}

        <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
          <MetricCard icon={DollarSign} title="Approved Fuel Spend" value={formatCurrency(analytics.total_fuel_spend)} tone="purple" />
          <MetricCard icon={Droplets} title="Approved Litres" value={`${analytics.total_litres.toLocaleString()} L`} tone="amber" />
          <MetricCard icon={Fuel} title="Average Price / Litre" value={formatCurrency(analytics.average_price_per_litre)} tone="blue" />
          <MetricCard icon={BarChart3} title="Average Litres / Fill" value={`${averageLitres.toFixed(1)} L`} tone="green" />
        </div>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1.25fr_1fr]">
          <div className="rounded-xl border border-gray-200 bg-white p-5">
            <div className="mb-4 flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-100">
                <Fuel className="h-5 w-5 text-blue-600" />
              </div>
              <div>
                <h2 className="text-lg font-semibold text-[#0F172A]">Fuel History</h2>
                <p className="text-sm text-gray-500">Your submitted fuel logs and approval outcomes</p>
              </div>
            </div>

            {isLoading ? (
              <LoadingState label="Loading your fuel logs..." />
            ) : logs.length === 0 ? (
              <EmptyState label="No fuel logs recorded yet." />
            ) : (
              <div className="space-y-3">
                {logs.map((log) => (
                  <div key={log.id} className={`rounded-xl border px-4 py-4 ${log.abnormal_spending ? 'border-red-200 bg-red-50/50' : 'border-gray-200 bg-gray-50'}`}>
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                      <div>
                        <div className="flex items-center gap-2">
                          <h3 className="text-sm font-semibold text-[#0F172A]">
                            {log.fuel_station?.station_name || 'Fuel Station'}
                          </h3>
                          {log.receipt_image ? (
                            <span className="inline-flex items-center gap-1 rounded-full bg-green-100 px-2 py-1 text-xs font-medium text-green-700">
                              <CheckCircle2 className="h-3 w-3" />
                              Receipt
                            </span>
                          ) : null}
                        </div>
                        <p className="mt-1 text-sm text-gray-600">
                          {formatDate(log.fuel_date)} • {log.fuel_type} • {log.litres.toLocaleString()} L
                        </p>
                      </div>
                      <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${statusClassName(log.status)}`}>
                        {log.status}
                      </span>
                    </div>

                    <div className="mt-4 grid grid-cols-1 gap-3 text-sm text-gray-600 md:grid-cols-2 xl:grid-cols-4">
                      <div>
                        <span className="font-medium text-[#0F172A]">Amount:</span> {formatCurrency(log.amount)}
                      </div>
                      <div>
                        <span className="font-medium text-[#0F172A]">Price / Litre:</span> {formatCurrency(log.price_per_litre)}
                      </div>
                      <div>
                        <span className="font-medium text-[#0F172A]">Odometer:</span> {log.odometer_reading.toLocaleString()} km
                      </div>
                      <div>
                        <span className="font-medium text-[#0F172A]">Cost / KM:</span>{' '}
                        {log.cost_per_km != null ? log.cost_per_km.toFixed(2) : 'Not available'}
                      </div>
                    </div>

                    {log.status === 'rejected' && log.rejection_reason && (
                      <div className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                        {log.rejection_reason}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="space-y-6">
            <div className="rounded-xl border border-gray-200 bg-white p-5">
              <div className="mb-4 flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-amber-100">
                  <Gauge className="h-5 w-5 text-amber-600" />
                </div>
                <div>
                  <h2 className="text-lg font-semibold text-[#0F172A]">Fuel Summary</h2>
                  <p className="text-sm text-gray-500">Quick performance view from approved fuel logs</p>
                </div>
              </div>
              <div className="space-y-3">
                <SummaryRow label="Approved Fuel Spend" value={formatCurrency(analytics.total_fuel_spend)} />
                <SummaryRow label="Approved Litres" value={`${analytics.total_litres.toLocaleString()} L`} />
                <SummaryRow label="Average Price / Litre" value={formatCurrency(analytics.average_price_per_litre)} />
                <SummaryRow label="Abnormal Fuel Flags" value={String(analytics.abnormal_fuel_spending.length)} />
              </div>
            </div>

            <div className="rounded-xl border border-gray-200 bg-white p-5">
              <div className="mb-4 flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-red-100">
                  <AlertCircle className="h-5 w-5 text-red-600" />
                </div>
                <div>
                  <h2 className="text-lg font-semibold text-[#0F172A]">Attention Items</h2>
                  <p className="text-sm text-gray-500">Logs flagged for unusual fuel behaviour</p>
                </div>
              </div>
              {analytics.abnormal_fuel_spending.length === 0 ? (
                <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 px-4 py-6 text-center text-sm text-gray-500">
                  No abnormal fuel spending flags right now.
                </div>
              ) : (
                <div className="space-y-3">
                  {analytics.abnormal_fuel_spending.slice(0, 4).map((log) => (
                    <div key={log.id} className="rounded-lg border border-red-200 bg-red-50 px-4 py-3">
                      <div className="text-sm font-semibold text-red-800">{log.fuel_station?.station_name || 'Fuel Station'}</div>
                      <div className="mt-1 text-sm text-red-700">
                        {formatDate(log.fuel_date)} • {formatCurrency(log.amount)}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {showAddModal && (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 p-0 lg:items-center lg:p-4">
          <div className="max-h-[90vh] w-full overflow-y-auto rounded-t-2xl bg-white lg:max-w-2xl lg:rounded-2xl">
            <div className="sticky top-0 flex items-center justify-between border-b border-gray-200 bg-white px-4 py-4">
              <div>
                <h2 className="text-lg font-semibold text-[#0F172A]">Submit Fuel Log</h2>
                <p className="mt-1 text-sm text-gray-500">Record a fuel purchase for your assigned vehicle.</p>
              </div>
              <button onClick={() => setShowAddModal(false)} className="rounded-lg p-2 hover:bg-gray-100">
                <XCircle className="h-5 w-5 text-gray-500" />
              </button>
            </div>

            <form onSubmit={handleSubmitFuelLog} className="space-y-5 p-6">
              {formError && (
                <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                  {formError}
                </div>
              )}

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <SelectField label="Fuel Station" value={formState.fuel_station_id} onChange={(value) => setFormState((current) => ({ ...current, fuel_station_id: value }))}>
                  <option value="">Choose active station...</option>
                  {stations.map((station) => (
                    <option key={station.id} value={station.id}>
                      {station.station_name}
                    </option>
                  ))}
                </SelectField>

                <InputField label="Fuel Date" type="date" value={formState.fuel_date} onChange={(value) => setFormState((current) => ({ ...current, fuel_date: value }))} />
                <SelectField label="Fuel Type" value={formState.fuel_type} onChange={(value) => setFormState((current) => ({ ...current, fuel_type: value }))}>
                  <option value="petrol">Petrol</option>
                  <option value="diesel">Diesel</option>
                  <option value="hybrid">Hybrid</option>
                  <option value="electric">Electric</option>
                </SelectField>
                <InputField label="Litres" type="number" step="0.01" value={formState.litres} onChange={(value) => setFormState((current) => ({ ...current, litres: value }))} />
                <InputField label="Amount" type="number" step="0.01" value={formState.amount} onChange={(value) => setFormState((current) => ({ ...current, amount: value }))} />
                <InputField label="Odometer Reading" type="number" step="0.01" value={formState.odometer_reading} onChange={(value) => setFormState((current) => ({ ...current, odometer_reading: value }))} />
              </div>

              <div className="rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-700">
                Automatic price per litre:{' '}
                <span className="font-semibold">
                  {pricePerLitrePreview != null ? formatCurrency(pricePerLitrePreview) : 'Enter litres and amount'}
                </span>
              </div>

              <div>
                <label className="mb-2 block text-sm font-medium text-gray-700">Receipt Image</label>
                <label className="flex cursor-pointer items-center justify-center gap-2 rounded-lg border border-dashed border-gray-300 bg-gray-50 px-4 py-5 text-sm text-gray-600 transition-all hover:border-[#2563EB] hover:bg-blue-50">
                  <Upload className="h-4 w-4" />
                  <span>{formState.receipt_file_name || 'Choose image or receipt file'}</span>
                  <input type="file" accept="image/*,.pdf" className="hidden" onChange={(event) => void handleFileChange(event)} />
                </label>
              </div>

              <div>
                <label className="mb-2 block text-sm font-medium text-gray-700">Notes</label>
                <textarea
                  value={formState.notes}
                  onChange={(event) => setFormState((current) => ({ ...current, notes: event.target.value }))}
                  className="min-h-[110px] w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                  placeholder="Optional notes about this fuel purchase."
                />
              </div>

              <div className="flex gap-3 border-t border-gray-200 pt-4">
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  className="flex-1 rounded-lg border border-gray-300 px-4 py-2.5 font-medium text-gray-700 hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting || !activeAssignment}
                  className="flex-1 inline-flex items-center justify-center gap-2 rounded-lg bg-[#2563EB] px-4 py-2.5 font-medium text-white hover:bg-[#1d4ed8] disabled:opacity-70"
                >
                  {isSubmitting && <Loader2 className="h-4 w-4 animate-spin" />}
                  Submit Fuel Log
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

function MetricCard({
  icon: Icon,
  title,
  value,
  tone,
}: {
  icon: typeof Fuel;
  title: string;
  value: string;
  tone: 'purple' | 'amber' | 'blue' | 'green';
}) {
  const toneClasses = {
    purple: 'bg-purple-100 text-purple-600',
    amber: 'bg-amber-100 text-amber-600',
    blue: 'bg-blue-100 text-blue-600',
    green: 'bg-green-100 text-green-600',
  }[tone];

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5">
      <div className={`mb-3 flex h-10 w-10 items-center justify-center rounded-lg ${toneClasses}`}>
        <Icon className="h-5 w-5" />
      </div>
      <div className="text-2xl font-semibold text-[#0F172A]">{value}</div>
      <div className="text-sm text-gray-600">{title}</div>
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-lg border border-gray-100 bg-gray-50 px-4 py-3">
      <span className="text-sm text-gray-600">{label}</span>
      <span className="text-sm font-semibold text-[#0F172A]">{value}</span>
    </div>
  );
}

function LoadingState({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-center gap-3 rounded-xl border border-gray-200 bg-gray-50 px-4 py-5 text-sm text-gray-600">
      <Loader2 className="h-4 w-4 animate-spin" />
      {label}
    </div>
  );
}

function EmptyState({ label }: { label: string }) {
  return (
    <div className="rounded-xl border border-dashed border-gray-200 bg-gray-50 px-4 py-5 text-sm text-gray-600">
      {label}
    </div>
  );
}

function InputField({
  label,
  value,
  onChange,
  type = 'text',
  step,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  step?: string;
}) {
  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-gray-700">{label}</label>
      <input
        type={type}
        step={step}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
      />
    </div>
  );
}

function SelectField({
  label,
  value,
  onChange,
  children,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  children: ReactNode;
}) {
  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-gray-700">{label}</label>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
      >
        {children}
      </select>
    </div>
  );
}
