import { useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  Eye,
  Fuel,
  Loader2,
  RefreshCcw,
  Search,
  ShieldAlert,
  TimerReset,
  Truck,
  Wrench,
  XCircle,
} from 'lucide-react';
import { toast } from 'sonner';
import {
  closeDispatchReturn,
  confirmDispatchReturn,
  fetchDispatchReturnDetail,
  fetchDispatchReturns,
  linkOrCreateDispatchReturnFault,
  saveDispatchReturnInspection,
  type DispatchReturnAccessory,
  type DispatchReturnDetail,
  type DispatchReturnFaultRecord,
  type DispatchReturnListItem,
  type DispatchReturnStatus,
} from '../../lib/dispatch-return-api';
import { normalizeFuelLevelEighths } from '../../lib/fuel-gauge';
import { FuelGaugeSelector } from '../shared/FuelGaugeSelector';
import { Drawer, DrawerContent, DrawerDescription, DrawerHeader, DrawerTitle } from '../ui/drawer';
import { Skeleton } from '../ui/skeleton';

const RETURN_STATUS_LABELS: Record<DispatchReturnStatus, string> = {
  awaiting_return: 'Awaiting Return',
  returned: 'Returned',
  inspection_completed: 'Inspection Completed',
  dispatch_closed: 'Dispatch Closed',
};

const RETURN_STATUS_BADGES: Record<DispatchReturnStatus, string> = {
  awaiting_return: 'border-amber-200 bg-amber-100 text-amber-800',
  returned: 'border-blue-200 bg-blue-100 text-blue-800',
  inspection_completed: 'border-emerald-200 bg-emerald-100 text-emerald-800',
  dispatch_closed: 'border-slate-200 bg-slate-100 text-slate-700',
};

const SEVERITY_OPTIONS = ['low', 'medium', 'high', 'critical'];

function formatDateTime(value?: string | null) {
  if (!value) {
    return 'Not recorded';
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString();
}

function toDatetimeLocalValue(value?: string | null) {
  if (!value) {
    return new Date().toISOString().slice(0, 16);
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value.slice(0, 16);
  }
  return new Date(parsed.getTime() - parsed.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

type ConfirmFormState = {
  actual_return_time: string;
  closing_odometer: string;
  closing_fuel_level: string;
  notes: string;
};

type InspectionFormState = {
  return_date: string;
  return_time: string;
  closing_odometer: string;
  closing_fuel_level: string;
  vehicle_condition: string;
  accessories: DispatchReturnAccessory[];
  existing_damage: string;
  new_damage: string;
  driver_remarks: string;
  admin_remarks: string;
  linked_fault_id: string;
  mark_vehicle_unavailable: boolean;
};

type FaultCreateState = {
  existing_fault_id: string;
  category_id: string;
  component_id: string;
  severity: string;
  description: string;
  admin_notes: string;
  mark_vehicle_unavailable: boolean;
};

function buildConfirmState(detail: DispatchReturnDetail): ConfirmFormState {
  return {
    actual_return_time: toDatetimeLocalValue(detail.movement?.actual_return_time || detail.job.expected_return_time as string | undefined),
    closing_odometer: detail.movement?.closing_odometer != null ? String(detail.movement.closing_odometer) : '',
    closing_fuel_level: detail.movement?.closing_fuel_level != null ? String(detail.movement.closing_fuel_level) : '',
    notes: detail.movement?.notes || (detail.movement?.origin ? `Returned from ${detail.movement.origin}` : ''),
  };
}

function getFuelFormValue(value: string) {
  return normalizeFuelLevelEighths(value);
}

function buildInspectionState(detail: DispatchReturnDetail): InspectionFormState {
  const checklist = detail.return_checklist || {};
  return {
    return_date: checklist.return_date || new Date().toISOString().slice(0, 10),
    return_time: checklist.return_time || new Date().toISOString().slice(11, 16),
    closing_odometer: checklist.closing_odometer != null ? String(checklist.closing_odometer) : '',
    closing_fuel_level: checklist.closing_fuel_level != null ? String(checklist.closing_fuel_level) : '',
    vehicle_condition: checklist.vehicle_condition || detail.vehicle_conditions[0] || '',
    accessories: checklist.accessories?.length ? checklist.accessories : detail.default_accessories.map((name) => ({ name, status: 'returned' })),
    existing_damage: checklist.existing_damage || '',
    new_damage: checklist.new_damage || '',
    driver_remarks: checklist.driver_remarks || '',
    admin_remarks: checklist.admin_remarks || '',
    linked_fault_id: checklist.linked_fault_id || detail.linked_fault?.id || '',
    mark_vehicle_unavailable: Boolean(checklist.mark_vehicle_unavailable),
  };
}

function buildFaultCreateState(detail: DispatchReturnDetail): FaultCreateState {
  return {
    existing_fault_id: detail.linked_fault?.id || '',
    category_id: detail.fault_options.categories[0]?.id || '',
    component_id: '',
    severity: 'medium',
    description: '',
    admin_notes: '',
    mark_vehicle_unavailable: false,
  };
}

export default function DispatchReturns() {
  const [items, setItems] = useState<DispatchReturnListItem[]>([]);
  const [pagination, setPagination] = useState({ page: 1, page_size: 20, total: 0, total_pages: 1 });
  const [pageError, setPageError] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [returnStatusFilter, setReturnStatusFilter] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [detail, setDetail] = useState<DispatchReturnDetail | null>(null);
  const [isLoadingDetail, setIsLoadingDetail] = useState(false);
  const [detailError, setDetailError] = useState('');
  const [confirmForm, setConfirmForm] = useState<ConfirmFormState | null>(null);
  const [inspectionForm, setInspectionForm] = useState<InspectionFormState | null>(null);
  const [faultForm, setFaultForm] = useState<FaultCreateState | null>(null);
  const [closureNote, setClosureNote] = useState('');
  const [isSavingReturn, setIsSavingReturn] = useState(false);
  const [isSavingInspection, setIsSavingInspection] = useState(false);
  const [isSavingFault, setIsSavingFault] = useState(false);
  const [isClosingDispatch, setIsClosingDispatch] = useState(false);
  const [detailWarnings, setDetailWarnings] = useState<string[]>([]);

  const loadReturns = async ({
    refresh = false,
    page = currentPage,
    query = searchQuery,
    status = returnStatusFilter,
  }: {
    refresh?: boolean;
    page?: number;
    query?: string;
    status?: string;
  } = {}) => {
    if (refresh) {
      setIsRefreshing(true);
    } else {
      setIsLoading(true);
    }
    setPageError('');
    try {
      const response = await fetchDispatchReturns({
        page,
        page_size: 20,
        q: query || undefined,
        return_status: status || undefined,
      });
      setItems(response.returns || []);
      setPagination(response.pagination);
    } catch (error) {
      setItems([]);
      setPagination({ page: 1, page_size: 20, total: 0, total_pages: 1 });
      setPageError(error instanceof Error ? error.message : 'Unable to load dispatch returns right now.');
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  };

  useEffect(() => {
    void loadReturns();
  }, [currentPage, returnStatusFilter]);

  const openDetails = async (jobId: string) => {
    setSelectedJobId(jobId);
    setDetail(null);
    setDetailError('');
    setDetailWarnings([]);
    setIsLoadingDetail(true);
    try {
      const response = await fetchDispatchReturnDetail(jobId);
      setDetail(response);
      setConfirmForm(buildConfirmState(response));
      setInspectionForm(buildInspectionState(response));
      setFaultForm(buildFaultCreateState(response));
      setClosureNote((response.job.closure_note as string | undefined) || '');
    } catch (error) {
      setDetailError(error instanceof Error ? error.message : 'Unable to load return details right now.');
    } finally {
      setIsLoadingDetail(false);
    }
  };

  const replaceDetail = (nextDetail: DispatchReturnDetail) => {
    setDetail(nextDetail);
    setConfirmForm(buildConfirmState(nextDetail));
    setInspectionForm(buildInspectionState(nextDetail));
    setFaultForm(buildFaultCreateState(nextDetail));
    setItems((current) =>
      current.map((item) =>
        item.id === nextDetail.job.id
          ? {
              ...item,
              current_dispatch_status: nextDetail.job.status,
              driver_workflow_status: nextDetail.job.driver_workflow_status || null,
              return_status: nextDetail.return_status,
              return_time: nextDetail.movement?.actual_return_time || item.return_time,
              movement_id: nextDetail.movement?.id || item.movement_id,
              movement_status: nextDetail.movement?.status || item.movement_status,
            }
          : item
      )
    );
  };

  const handleSearch = async (event: React.FormEvent) => {
    event.preventDefault();
    setCurrentPage(1);
    await loadReturns({ refresh: true, page: 1, query: searchQuery, status: returnStatusFilter });
  };

  const handleConfirmReturn = async () => {
    if (!detail || !confirmForm) {
      return;
    }
    setIsSavingReturn(true);
    try {
      const response = await confirmDispatchReturn(detail.job.id, {
        actual_return_time: confirmForm.actual_return_time || undefined,
        closing_odometer: confirmForm.closing_odometer ? Number(confirmForm.closing_odometer) : undefined,
        closing_fuel_level: confirmForm.closing_fuel_level ? normalizeFuelLevelEighths(confirmForm.closing_fuel_level) ?? undefined : undefined,
        notes: confirmForm.notes || undefined,
      });
      replaceDetail(response.detail);
      toast.success('Vehicle return confirmed.');
      await loadReturns({ refresh: true });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Unable to confirm vehicle return right now.');
    } finally {
      setIsSavingReturn(false);
    }
  };

  const handleSaveInspection = async () => {
    if (!detail || !inspectionForm) {
      return;
    }
    setIsSavingInspection(true);
    try {
      const response = await saveDispatchReturnInspection(detail.job.id, {
        return_date: inspectionForm.return_date,
        return_time: inspectionForm.return_time,
        closing_odometer: inspectionForm.closing_odometer ? Number(inspectionForm.closing_odometer) : undefined,
        closing_fuel_level: inspectionForm.closing_fuel_level ? normalizeFuelLevelEighths(inspectionForm.closing_fuel_level) ?? undefined : undefined,
        vehicle_condition: inspectionForm.vehicle_condition,
        accessories: inspectionForm.accessories,
        existing_damage: inspectionForm.existing_damage || undefined,
        new_damage: inspectionForm.new_damage || undefined,
        driver_remarks: inspectionForm.driver_remarks || undefined,
        admin_remarks: inspectionForm.admin_remarks || undefined,
        linked_fault_id: inspectionForm.linked_fault_id || undefined,
        mark_vehicle_unavailable: inspectionForm.mark_vehicle_unavailable,
      });
      replaceDetail(response.detail);
      setDetailWarnings(response.warnings || []);
      toast.success('Return inspection saved.');
      await loadReturns({ refresh: true });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Unable to save the return inspection right now.');
    } finally {
      setIsSavingInspection(false);
    }
  };

  const handleFaultAction = async () => {
    if (!detail || !faultForm) {
      return;
    }
    setIsSavingFault(true);
    try {
      const response = await linkOrCreateDispatchReturnFault(detail.job.id, faultForm.existing_fault_id
        ? {
            fault_id: faultForm.existing_fault_id,
            mark_vehicle_unavailable: faultForm.mark_vehicle_unavailable,
          }
        : {
            mark_vehicle_unavailable: faultForm.mark_vehicle_unavailable,
            fault_payload: {
              category_id: faultForm.category_id,
              component_id: faultForm.component_id,
              severity: faultForm.severity,
              description: faultForm.description,
              admin_notes: faultForm.admin_notes || undefined,
            },
          });
      replaceDetail(response.detail);
      toast.success(faultForm.existing_fault_id ? 'Fault linked successfully.' : 'Fault created and linked successfully.');
      await loadReturns({ refresh: true });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Unable to save the fault link right now.');
    } finally {
      setIsSavingFault(false);
    }
  };

  const handleCloseDispatch = async () => {
    if (!detail) {
      return;
    }
    setIsClosingDispatch(true);
    try {
      const response = await closeDispatchReturn(detail.job.id, { closure_note: closureNote || undefined });
      replaceDetail(response.detail);
      toast.success('Dispatch closed successfully.');
      await loadReturns({ refresh: true });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Unable to close this dispatch right now.');
    } finally {
      setIsClosingDispatch(false);
    }
  };

  const filteredComponents = useMemo(() => {
    if (!detail || !faultForm?.category_id) {
      return [];
    }
    return detail.fault_options.components.filter((component) => component.category_id === faultForm.category_id);
  }, [detail, faultForm?.category_id]);

  const awaitingCount = items.filter((item) => item.return_status === 'awaiting_return').length;
  const inspectionCount = items.filter((item) => item.return_status === 'inspection_completed').length;
  const closedCount = items.filter((item) => item.return_status === 'dispatch_closed').length;

  return (
    <div className="space-y-6 p-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-[#0F172A]">Vehicle Return & Handover</h1>
          <p className="mt-1 text-gray-600">
            Receive returned dispatch vehicles, complete inspection, link faults, and close the operational dispatch workflow.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void loadReturns({ refresh: true })}
          className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 transition-all hover:bg-gray-50"
        >
          {isRefreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCcw className="h-4 w-4" />}
          Refresh
        </button>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <StatCard icon={TimerReset} label="Awaiting Return" value={awaitingCount} tint="bg-amber-100 text-amber-700" />
        <StatCard icon={ClipboardCheck} label="Inspection Completed" value={inspectionCount} tint="bg-emerald-100 text-emerald-700" />
        <StatCard icon={CheckCircle2} label="Dispatch Closed" value={closedCount} tint="bg-slate-100 text-slate-700" />
      </div>

      <div className="rounded-xl border border-gray-200 bg-white p-5">
        <form onSubmit={handleSearch} className="grid grid-cols-1 gap-3 lg:grid-cols-[1fr_220px_auto]">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
            <input
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder="Search dispatch ID"
              className="w-full rounded-lg border border-gray-300 py-2.5 pl-9 pr-3 text-sm"
            />
          </div>
          <select
            value={returnStatusFilter}
            onChange={(event) => {
              setReturnStatusFilter(event.target.value);
              setCurrentPage(1);
            }}
            className="rounded-lg border border-gray-300 px-3 py-2.5 text-sm"
          >
            <option value="">All Return Statuses</option>
            {Object.entries(RETURN_STATUS_LABELS).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
          <button type="submit" className="rounded-lg bg-[#2563EB] px-4 py-2.5 text-sm font-medium text-white hover:bg-[#1d4ed8]">
            Search
          </button>
        </form>
      </div>

      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
        {isLoading ? (
          <div className="space-y-3 px-6 py-5">
            {Array.from({ length: 6 }).map((_, index) => (
              <div key={index} className="grid grid-cols-1 gap-3 rounded-xl border border-gray-200 p-4 md:grid-cols-6">
                {Array.from({ length: 6 }).map((__, innerIndex) => (
                  <Skeleton key={innerIndex} className="h-5 w-full" />
                ))}
              </div>
            ))}
          </div>
        ) : pageError ? (
          <div className="px-6 py-6 text-sm text-red-700">{pageError}</div>
        ) : items.length === 0 ? (
          <div className="px-6 py-10 text-center text-sm text-gray-500">No dispatch returns matched the current filters.</div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200 text-sm">
                <thead className="bg-gray-50">
                  <tr className="text-left text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">
                    <th className="px-4 py-3">Dispatch ID</th>
                    <th className="px-4 py-3">Vehicle</th>
                    <th className="px-4 py-3">Driver</th>
                    <th className="px-4 py-3">Dispatch Date</th>
                    <th className="px-4 py-3">Return Status</th>
                    <th className="px-4 py-3">Return Time</th>
                    <th className="px-4 py-3">Current Dispatch Status</th>
                    <th className="px-4 py-3">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200 bg-white">
                  {items.map((item) => (
                    <tr key={item.id}>
                      <td className="px-4 py-3 font-medium text-[#0F172A]">{item.dispatch_job_id}</td>
                      <td className="px-4 py-3 text-gray-700">{item.vehicle?.registration_number || 'Unassigned vehicle'}</td>
                      <td className="px-4 py-3 text-gray-700">{item.driver?.full_name || 'Unassigned driver'}</td>
                      <td className="px-4 py-3 text-gray-700">{formatDateTime(item.scheduled_start_time)}</td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${RETURN_STATUS_BADGES[item.return_status]}`}>
                          {RETURN_STATUS_LABELS[item.return_status]}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-gray-700">{formatDateTime(item.return_time)}</td>
                      <td className="px-4 py-3 text-gray-700">{item.current_dispatch_status.replaceAll('_', ' ')}</td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap gap-2">
                          <ActionButton icon={Eye} label="Open Return Checklist" onClick={() => void openDetails(item.id)} tone="neutral" />
                          {item.return_status === 'awaiting_return' ? (
                            <ActionButton icon={TimerReset} label="Confirm Vehicle Returned" onClick={() => void openDetails(item.id)} tone="warning" />
                          ) : null}
                          {item.return_status === 'inspection_completed' ? (
                            <ActionButton icon={CheckCircle2} label="Close Dispatch" onClick={() => void openDetails(item.id)} tone="dark" />
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {pagination.total_pages > 1 ? (
              <div className="flex items-center justify-between border-t border-gray-200 px-4 py-4 text-sm text-gray-600">
                <div>Page {pagination.page} of {pagination.total_pages}</div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    disabled={pagination.page <= 1}
                    onClick={() => setCurrentPage((current) => Math.max(1, current - 1))}
                    className="rounded-lg border border-gray-300 px-3 py-2 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    Previous
                  </button>
                  <button
                    type="button"
                    disabled={pagination.page >= pagination.total_pages}
                    onClick={() => setCurrentPage((current) => Math.min(pagination.total_pages, current + 1))}
                    className="rounded-lg border border-gray-300 px-3 py-2 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    Next
                  </button>
                </div>
              </div>
            ) : null}
          </>
        )}
      </div>

      <Drawer open={Boolean(selectedJobId)} direction="right" onOpenChange={(open) => !open && setSelectedJobId(null)}>
        <DrawerContent className="w-full max-w-[960px] border-l border-gray-200 bg-white">
          <DrawerHeader className="border-b border-gray-200 px-6 py-4 text-left">
            <DrawerTitle className="text-xl font-semibold text-[#0F172A]">
              {detail?.job.dispatch_job_id || 'Vehicle Return & Handover'}
            </DrawerTitle>
            <DrawerDescription className="text-sm text-gray-500">
              Confirm return, complete inspection, report damage, and close the dispatch safely.
            </DrawerDescription>
          </DrawerHeader>
          <div className="flex-1 overflow-y-auto px-6 py-5">
            {isLoadingDetail ? (
              <div className="space-y-4">
                <Skeleton className="h-20 w-full" />
                <Skeleton className="h-40 w-full" />
                <Skeleton className="h-40 w-full" />
              </div>
            ) : detailError ? (
              <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{detailError}</div>
            ) : detail && confirmForm && inspectionForm && faultForm ? (
              <div className="space-y-6">
                <DetailSection title="Overview">
                  <DetailGrid>
                    <DetailRow label="Dispatch ID" value={detail.job.dispatch_job_id} />
                    <DetailRow label="Vehicle" value={detail.vehicle?.registration_number || 'Unknown vehicle'} />
                    <DetailRow label="Driver" value={detail.driver?.full_name || 'Unknown driver'} />
                    <DetailRow label="Current Dispatch Status" value={detail.job.status.replaceAll('_', ' ')} />
                    <DetailRow label="Return Status" value={RETURN_STATUS_LABELS[detail.return_status]} />
                    <DetailRow label="Return Time" value={formatDateTime(detail.movement?.actual_return_time)} />
                  </DetailGrid>
                </DetailSection>

                <DetailSection title="Confirm Vehicle Returned">
                  <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                    <InputField label="Return Time" type="datetime-local" value={confirmForm.actual_return_time} onChange={(value) => setConfirmForm((current) => current ? { ...current, actual_return_time: value } : current)} />
                    <InputField label="Closing Odometer" type="number" value={confirmForm.closing_odometer} onChange={(value) => setConfirmForm((current) => current ? { ...current, closing_odometer: value } : current)} />
                    <div className="md:col-span-2">
                      <FuelGaugeSelector
                        label="Closing Fuel Level"
                        value={getFuelFormValue(confirmForm.closing_fuel_level)}
                        onChange={(value) => setConfirmForm((current) => current ? { ...current, closing_fuel_level: String(value) } : current)}
                        compareToValue={detail.movement?.opening_fuel_level ?? null}
                        showEstimatedLitres
                        tankCapacityLitres={detail.vehicle?.tank_capacity_litres}
                      />
                    </div>
                    <div className="md:col-span-2">
                      <TextAreaField label="Return Remarks" value={confirmForm.notes} onChange={(value) => setConfirmForm((current) => current ? { ...current, notes: value } : current)} placeholder="Capture return notes, handover context, or exceptions." />
                    </div>
                  </div>
                  <div className="mt-4 flex justify-end">
                    <button type="button" onClick={() => void handleConfirmReturn()} disabled={isSavingReturn || detail.return_status !== 'awaiting_return'} className="inline-flex items-center gap-2 rounded-lg bg-[#2563EB] px-4 py-2.5 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-60">
                      {isSavingReturn ? <Loader2 className="h-4 w-4 animate-spin" /> : <TimerReset className="h-4 w-4" />}
                      Confirm Vehicle Returned
                    </button>
                  </div>
                </DetailSection>

                <DetailSection title="Return Checklist">
                  <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                    <InputField label="Return Date" type="date" value={inspectionForm.return_date} onChange={(value) => setInspectionForm((current) => current ? { ...current, return_date: value } : current)} />
                    <InputField label="Return Time" type="time" value={inspectionForm.return_time} onChange={(value) => setInspectionForm((current) => current ? { ...current, return_time: value } : current)} />
                    <InputField label="Closing Odometer" type="number" value={inspectionForm.closing_odometer} onChange={(value) => setInspectionForm((current) => current ? { ...current, closing_odometer: value } : current)} />
                    <div className="md:col-span-2">
                      <FuelGaugeSelector
                        label="Closing Fuel Level"
                        value={getFuelFormValue(inspectionForm.closing_fuel_level)}
                        onChange={(value) => setInspectionForm((current) => current ? { ...current, closing_fuel_level: String(value) } : current)}
                        compareToValue={detail.movement?.opening_fuel_level ?? null}
                        showEstimatedLitres
                        tankCapacityLitres={detail.vehicle?.tank_capacity_litres}
                      />
                    </div>
                    <SelectField label="Vehicle Condition" value={inspectionForm.vehicle_condition} onChange={(value) => setInspectionForm((current) => current ? { ...current, vehicle_condition: value } : current)}>
                      {detail.vehicle_conditions.map((condition) => (
                        <option key={condition} value={condition}>{condition}</option>
                      ))}
                    </SelectField>
                    <SelectField label="Linked Fault" value={inspectionForm.linked_fault_id} onChange={(value) => setInspectionForm((current) => current ? { ...current, linked_fault_id: value } : current)}>
                      <option value="">No linked fault</option>
                      {detail.existing_faults.map((fault) => (
                        <option key={fault.id} value={fault.id}>
                          {fault.severity.toUpperCase()} • {fault.description.slice(0, 60)}
                        </option>
                      ))}
                    </SelectField>
                    <div className="md:col-span-2">
                      <AccessoryChecklist
                        accessories={inspectionForm.accessories}
                        onChange={(accessories) => setInspectionForm((current) => current ? { ...current, accessories } : current)}
                      />
                    </div>
                    <TextAreaField label="Existing Damage" value={inspectionForm.existing_damage} onChange={(value) => setInspectionForm((current) => current ? { ...current, existing_damage: value } : current)} placeholder="Record any known pre-existing damage." />
                    <TextAreaField label="New Damage" value={inspectionForm.new_damage} onChange={(value) => setInspectionForm((current) => current ? { ...current, new_damage: value } : current)} placeholder="Record any new damage detected during return." />
                    <TextAreaField label="Driver Remarks" value={inspectionForm.driver_remarks} onChange={(value) => setInspectionForm((current) => current ? { ...current, driver_remarks: value } : current)} placeholder="Driver-facing remarks if provided." />
                    <TextAreaField label="Admin Remarks" value={inspectionForm.admin_remarks} onChange={(value) => setInspectionForm((current) => current ? { ...current, admin_remarks: value } : current)} placeholder="Inspection remarks, return notes, or accessory issues." />
                  </div>
                  <label className="mt-4 flex items-center gap-2 text-sm text-gray-700">
                    <input
                      type="checkbox"
                      checked={inspectionForm.mark_vehicle_unavailable}
                      onChange={(event) => setInspectionForm((current) => current ? { ...current, mark_vehicle_unavailable: event.target.checked } : current)}
                    />
                    Mark vehicle unavailable after inspection
                  </label>
                  {detailWarnings.length ? (
                    <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                      {detailWarnings.join(' ')}
                    </div>
                  ) : null}
                  <div className="mt-4 flex justify-end">
                    <button type="button" onClick={() => void handleSaveInspection()} disabled={isSavingInspection || detail.return_status === 'awaiting_return'} className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2.5 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-60">
                      {isSavingInspection ? <Loader2 className="h-4 w-4 animate-spin" /> : <ClipboardCheck className="h-4 w-4" />}
                      Save Inspection
                    </button>
                  </div>
                </DetailSection>

                <DetailSection title="Fuel Comparison">
                  <FuelGaugeSelector
                    label="Opening Fuel"
                    value={detail.movement?.opening_fuel_level ?? null}
                    readOnly
                    compact
                    showEstimatedLitres
                    tankCapacityLitres={detail.vehicle?.tank_capacity_litres}
                  />
                  <div className="mt-4">
                    <FuelGaugeSelector
                      label="Closing Fuel"
                      value={detail.movement?.closing_fuel_level ?? null}
                      compareToValue={detail.movement?.opening_fuel_level ?? null}
                      readOnly
                      compact
                      showEstimatedLitres
                      tankCapacityLitres={detail.vehicle?.tank_capacity_litres}
                    />
                  </div>
                </DetailSection>

                <DetailSection title="Damage & Fault Integration">
                  <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                    <SelectField label="Link Existing Fault" value={faultForm.existing_fault_id} onChange={(value) => setFaultForm((current) => current ? { ...current, existing_fault_id: value } : current)}>
                      <option value="">Create new or skip</option>
                      {detail.existing_faults.map((fault: DispatchReturnFaultRecord) => (
                        <option key={fault.id} value={fault.id}>
                          {fault.severity.toUpperCase()} • {fault.description.slice(0, 60)}
                        </option>
                      ))}
                    </SelectField>
                    <SelectField label="Category" value={faultForm.category_id} onChange={(value) => setFaultForm((current) => current ? { ...current, category_id: value, component_id: '' } : current)} disabled={Boolean(faultForm.existing_fault_id)}>
                      {detail.fault_options.categories.map((category) => (
                        <option key={category.id} value={category.id}>{category.name}</option>
                      ))}
                    </SelectField>
                    <SelectField label="Component" value={faultForm.component_id} onChange={(value) => setFaultForm((current) => current ? { ...current, component_id: value } : current)} disabled={Boolean(faultForm.existing_fault_id)}>
                      <option value="">Select component</option>
                      {filteredComponents.map((component) => (
                        <option key={component.id} value={component.id}>{component.name}</option>
                      ))}
                    </SelectField>
                    <SelectField label="Severity" value={faultForm.severity} onChange={(value) => setFaultForm((current) => current ? { ...current, severity: value } : current)} disabled={Boolean(faultForm.existing_fault_id)}>
                      {SEVERITY_OPTIONS.map((severity) => (
                        <option key={severity} value={severity}>{severity}</option>
                      ))}
                    </SelectField>
                    <div className="md:col-span-2">
                      <TextAreaField label="Fault Description" value={faultForm.description} onChange={(value) => setFaultForm((current) => current ? { ...current, description: value } : current)} placeholder="Describe the new damage or condition issue." />
                    </div>
                    <div className="md:col-span-2">
                      <TextAreaField label="Fault Admin Notes" value={faultForm.admin_notes} onChange={(value) => setFaultForm((current) => current ? { ...current, admin_notes: value } : current)} placeholder="Optional internal notes for the fault record." />
                    </div>
                  </div>
                  <label className="mt-4 flex items-center gap-2 text-sm text-gray-700">
                    <input
                      type="checkbox"
                      checked={faultForm.mark_vehicle_unavailable}
                      onChange={(event) => setFaultForm((current) => current ? { ...current, mark_vehicle_unavailable: event.target.checked } : current)}
                    />
                    Mark vehicle unavailable when linking this fault
                  </label>
                  <div className="mt-4 flex justify-end gap-3">
                    <button type="button" onClick={() => setFaultForm(buildFaultCreateState(detail))} className="rounded-lg border border-gray-300 px-4 py-2.5 text-sm font-medium text-gray-700">
                      Reset Fault Form
                    </button>
                    <button type="button" onClick={() => void handleFaultAction()} disabled={isSavingFault || (!faultForm.existing_fault_id && (!faultForm.category_id || !faultForm.component_id || !faultForm.description))} className="inline-flex items-center gap-2 rounded-lg bg-rose-600 px-4 py-2.5 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-60">
                      {isSavingFault ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldAlert className="h-4 w-4" />}
                      {faultForm.existing_fault_id ? 'Link Fault' : 'Create Fault'}
                    </button>
                  </div>
                </DetailSection>

                <DetailSection title="Close Dispatch">
                  <TextAreaField label="Closure Note" value={closureNote} onChange={setClosureNote} placeholder="Optional note for dispatch closure and handover completion." />
                  <div className="mt-4 flex justify-end">
                    <button type="button" onClick={() => void handleCloseDispatch()} disabled={isClosingDispatch || detail.return_status !== 'inspection_completed'} className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-60">
                      {isClosingDispatch ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wrench className="h-4 w-4" />}
                      Close Dispatch
                    </button>
                  </div>
                </DetailSection>
              </div>
            ) : null}
          </div>
        </DrawerContent>
      </Drawer>
    </div>
  );
}

function StatCard({
  icon: Icon,
  label,
  value,
  tint,
}: {
  icon: typeof Truck;
  label: string;
  value: number;
  tint: string;
}) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5">
      <div className={`mb-3 flex h-10 w-10 items-center justify-center rounded-lg ${tint}`}>
        <Icon className="h-5 w-5" />
      </div>
      <div className="text-2xl font-semibold text-[#0F172A]">{value.toLocaleString()}</div>
      <div className="text-sm text-gray-600">{label}</div>
    </div>
  );
}

function ActionButton({
  icon: Icon,
  label,
  onClick,
  tone,
}: {
  icon: typeof Eye;
  label: string;
  onClick: () => void;
  tone: 'neutral' | 'warning' | 'dark';
}) {
  const className = {
    neutral: 'border-gray-300 bg-white text-gray-700 hover:bg-gray-50',
    warning: 'border-amber-200 bg-amber-50 text-amber-700 hover:bg-amber-100',
    dark: 'border-slate-900 bg-slate-900 text-white hover:bg-slate-800',
  }[tone];
  return (
    <button type="button" onClick={onClick} className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-medium ${className}`}>
      <Icon className="h-3.5 w-3.5" />
      {label}
    </button>
  );
}

function AccessoryChecklist({
  accessories,
  onChange,
}: {
  accessories: DispatchReturnAccessory[];
  onChange: (accessories: DispatchReturnAccessory[]) => void;
}) {
  return (
    <div className="rounded-xl border border-gray-200 bg-gray-50 p-4">
      <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-[#0F172A]">
        <Fuel className="h-4 w-4" />
        Accessories Returned
      </div>
      <div className="space-y-3">
        {accessories.map((accessory, index) => (
          <div key={`${accessory.name}-${index}`} className="grid grid-cols-1 gap-3 md:grid-cols-[1fr_180px]">
            <div className="rounded-lg border border-gray-200 bg-white px-3 py-2.5 text-sm text-gray-700">{accessory.name}</div>
            <select
              value={accessory.status}
              onChange={(event) =>
                onChange(
                  accessories.map((item, itemIndex) =>
                    itemIndex === index ? { ...item, status: event.target.value as DispatchReturnAccessory['status'] } : item
                  )
                )
              }
              className="rounded-lg border border-gray-300 px-3 py-2.5 text-sm"
            >
              <option value="returned">Returned</option>
              <option value="missing">Missing</option>
              <option value="damaged">Damaged</option>
            </select>
          </div>
        ))}
      </div>
    </div>
  );
}

function DetailSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h3 className="mb-3 text-sm font-semibold uppercase tracking-[0.18em] text-gray-500">{title}</h3>
      {children}
    </section>
  );
}

function DetailGrid({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-1 gap-3 md:grid-cols-2">{children}</div>;
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3">
      <div className="text-xs font-semibold uppercase tracking-[0.14em] text-gray-500">{label}</div>
      <div className="mt-1 text-sm font-medium text-[#0F172A]">{value}</div>
    </div>
  );
}

function InputField({
  label,
  value,
  onChange,
  type = 'text',
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
}) {
  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-gray-700">{label}</label>
      <input
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm"
      />
    </div>
  );
}

function SelectField({
  label,
  value,
  onChange,
  children,
  disabled = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  children: ReactNode;
  disabled?: boolean;
}) {
  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-gray-700">{label}</label>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm disabled:cursor-not-allowed disabled:bg-gray-50"
      >
        {children}
      </select>
    </div>
  );
}

function TextAreaField({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}) {
  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-gray-700">{label}</label>
      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="min-h-[110px] w-full rounded-lg border border-gray-300 px-4 py-3 text-sm"
      />
    </div>
  );
}
