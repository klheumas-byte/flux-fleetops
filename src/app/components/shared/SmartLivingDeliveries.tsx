import { useEffect, useMemo, useRef, useState } from "react";
import {
  CalendarDays,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock,
  Filter,
  GripVertical,
  ListChecks,
  Loader2,
  Lock,
  MapPin,
  PackageCheck,
  Plus,
  RefreshCw,
  Route,
  Search,
  Send,
  Truck,
  Users,
  AlertTriangle,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";
import { apiRequest } from "../../lib/api";
import { getActiveSessionRole, getStoredSessionUser } from "../../lib/auth-session";
import { useDataSync } from "../../lib/data-sync";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "../ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "../ui/alert-dialog";

type Line = {
  line_id?: string;
  product_name: string;
  product_code?: string;
  quantity: number;
  quantity_requested?: number;
  delivery_type: string;
  original_product_name?: string;
  original_product_value?: number;
  contributed_amount?: number;
  deduction_amount?: number;
  approved_delivery_value?: number;
  notes?: string;
  status?: string;
  delivery_status?: string;
  operational_instruction?: string;
  quantity_issued?: number;
  quantity_delivered?: number;
};
type Order = {
  id: string;
  reference_number?: string;
  external_reference?: string;
  customer_name: string;
  phone?: string;
  customer_phone?: string;
  alternative_phone?: string;
  branch_id: string;
  sales_agent_id?: string;
  delivery_address: string;
  landmark?: string;
  latitude?: number;
  longitude?: number;
  requested_delivery_date?: string;
  notes?: string;
  status: string;
  product_lines: Line[];
  source_reference?: string;
  branch?: { id: string; name: string; code?: string } | null;
  agent?: { id: string; name: string } | null;
  manager?: { id: string; name: string } | null;
};
type FieldDelivery = Order & {
  planning_status: string;
  delivery_date?: string;
  delivery_time?: string;
  driver?: { id: string; name: string } | null;
  vehicle?: { id: string; name: string } | null;
  stop_sequence?: number | null;
  stop_status?: string | null;
};
type Stop = {
  stop_id: string;
  delivery_order_id: string;
  sequence_number: number;
  stop_type: string;
  customer_name: string;
  agent_id?: string;
  agent?: { id: string; name: string; phone?: string };
  address: string;
  landmark?: string;
  latitude?: number;
  longitude?: number;
  expected_arrival_time?: string;
  estimated_service_minutes?: number;
  notes?: string;
  status: string;
  phone?: string;
  products?: Line[];
};
type Run = {
  id: string;
  run_number?: string;
  batch_number?: string;
  branch_id: string;
  delivery_date?: string;
  planned_departure_time?: string;
  transport_method?: "VEHICLE" | "KAYA" | "OTHER_MANUAL";
  manual_transport?: { provider_name?: string; handler_name?: string; phone?: string; handler_phone?: string; agreed_cost?: number | null; notes?: string } | null;
  readiness?: "PLANNING_REQUIRED" | "PARTIALLY_PLANNED" | "READY";
  driver_id?: string;
  vehicle_id?: string;
  assigned_agent_ids?: string[];
  delivery_order_ids: string[];
  notes?: string;
  status: string;
  version?: number;
  published_at?: string;
  locked_at?: string;
  driver?: { id: string; name: string };
  vehicle?: { id: string; name: string };
  agents?: { id: string; name: string }[];
  stops: Stop[];
  delivery_orders: Order[];
  review?: { valid: boolean; errors: string[]; warnings: string[] };
  assignment_status?: string;
  custody_status?: string;
  branch?: { id: string; name: string; code?: string } | null;
};
type Meta = {
  branches: { id: string; code: string; name: string }[];
  drivers: LookupItem[];
  agents: LookupItem[];
  vehicles: {
    id: string;
    name: string;
    label?: string;
    status: string;
    branch?: string;
    branch_id?: string;
    assigned_driver_id?: string;
    disabled_reason?: string | null;
  }[];
};
type LookupItem = {
  id: string;
  name: string;
  label?: string;
  status?: string;
  branch?: string;
  primary_branch_id?: string;
  disabled_reason?: string | null;
};
type SchedulerTab = "queue" | "runs" | "week" | "loading" | "accountability";
type AssignedView = "upcoming" | "today" | "history";
type ActionFeedback = {
  tone: "success" | "error";
  text: string;
} | null;
type AccountabilityBatch = Run & {
  return?: { id: string; items: Array<{ condition?: string; conditions?: string[]; returned_quantity?: number }>; receiving_events?: Array<{ items?: Array<{ condition?: string; received_quantity?: number }> }>; total_returned_quantity?: number; total_outstanding_quantity?: number; status?: string } | null;
  exception_summary?: Record<string, number>;
  reconciliation?: {
    issued: number; delivered: number; returned: number; approved_loss: number;
    outstanding_difference: number; balanced: boolean;
    lines: Array<{ delivery_order_id: string; line_id: string; customer_name: string; product_name: string; issued_quantity: number; delivered_quantity: number; expected_return_quantity?: number; returned_quantity: number; approved_exception_quantity: number; outstanding_difference: number; reconciliation_status?: string }>;
  };
};

const EMPTY_META: Meta = {
  branches: [],
  drivers: [],
  agents: [],
  vehicles: [],
};
const EMPTY_LINE: Line = {
  product_name: "",
  product_code: "",
  quantity: 1,
  delivery_type: "FULLY_COMPLETED_PRODUCT",
  original_product_name: "",
  notes: "",
};
const EMPTY_ORDER = {
  reference_number: "",
  customer_name: "",
  phone: "",
  alternative_phone: "",
  branch_id: "",
  sales_agent_id: "",
  delivery_address: "",
  landmark: "",
  latitude: "",
  longitude: "",
  requested_delivery_date: "",
  notes: "",
  status: "CERTIFIED",
  product_lines: [{ ...EMPTY_LINE }],
};
const fieldClass =
  "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100";
const statusTone = (status: string) =>
  ["LOCKED", "COMPLETED", "CLOSED", "RECONCILED"].includes(status)
    ? "bg-emerald-100 text-emerald-700"
    : status === "PUBLISHED"
      ? "bg-blue-100 text-blue-700"
      : status.includes("CANCEL")
        ? "bg-rose-100 text-rose-700"
        : "bg-amber-100 text-amber-700";
const quantity = (line: Line) =>
  Number(line.quantity ?? line.quantity_requested ?? 0);
const localDateKey = (date = new Date()) =>
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(
    date.getDate(),
  ).padStart(2, "0")}`;
const shiftedLocalDateKey = (days: number) => {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return localDateKey(date);
};
const runName = (run: Run) =>
  run.run_number || run.batch_number || "Delivery run";

export default function SmartLivingDeliveries() {
  const user = getStoredSessionUser();
  const has = (permission: string) =>
    Boolean(
      user?.permissions?.includes("*") ||
      user?.permissions?.includes(permission),
    );
  const activeWorkspace = getActiveSessionRole(user);
  const isDriverWorkspace = activeWorkspace === "driver";
  const canManage = !isDriverWorkspace && has("delivery_scheduler.manage");
  const canViewScheduler =
    !isDriverWorkspace && has("delivery_scheduler.view");
  const canCreate = !isDriverWorkspace && has("deliveries.create");
  const canPublish = !isDriverWorkspace && has("delivery_runs.publish");
  const canLock = !isDriverWorkspace && has("delivery_runs.lock");
  const canLoading =
    !isDriverWorkspace && has("loading_schedule.view");
  const canIssue = has("delivery_items.issue") || has("items.issue");
  const canAcceptExecution =
    has("delivery_routes.execute") || has("delivery_execution.accept");
  const canCustody =
    has("delivery_items.acknowledge") || has("custody.accept");
  const canStartExecution =
    has("delivery_execution.manage") || has("delivery_execution.start");
  const canUpdateStops =
    has("delivery_execution.manage") || has("delivery_execution.stop_update");
  const canCompleteExecution =
    has("delivery_execution.manage") || has("delivery_execution.complete");
  const canReceiveReturns = has("returns.receive");
  const canManageReturns = has("returns.manage");
  const canManageExceptions = has("exceptions.manage");
  const canInvestigate = has("investigations.manage");
  const canReconcile = has("reconciliation.manage");
  const canCloseBatch = has("delivery_batches.close");
  const canReopenBatch = has("delivery_batches.reopen");
  const canAccountability = !isDriverWorkspace && (canReceiveReturns || canManageReturns || canManageExceptions || canReconcile);
  const assignedOnly =
    isDriverWorkspace ||
    (has("delivery_schedule.view_assigned") && !canViewScheduler);
  const isFieldAgent = activeWorkspace === "field_agent";

  const [tab, setTab] = useState<SchedulerTab>(
    canManage ? "queue" : canLoading && !assignedOnly ? "loading" : "runs",
  );
  const [assignedView, setAssignedView] = useState<AssignedView>("upcoming");
  const [meta, setMeta] = useState<Meta>(EMPTY_META);
  const [queue, setQueue] = useState<Order[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [fieldDeliveries, setFieldDeliveries] = useState<FieldDelivery[]>([]);
  const [fieldDeliveryCounts, setFieldDeliveryCounts] = useState({ upcoming: 0, delivered: 0 });
  const [loadingRuns, setLoadingRuns] = useState<Run[]>([]);
  const [accountabilityBatches, setAccountabilityBatches] = useState<AccountabilityBatch[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [branchFilter, setBranchFilter] = useState("");
  const [dateFilter, setDateFilter] = useState("");
  const [productFilter, setProductFilter] = useState("");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [orderOpen, setOrderOpen] = useState(false);
  const [orderForm, setOrderForm] = useState(EMPTY_ORDER);
  const [builderOpen, setBuilderOpen] = useState(false);
  const [builder, setBuilder] = useState({
    branch_id: "",
    delivery_date: "",
    planned_departure_time: "",
    transport_method: "VEHICLE" as "VEHICLE" | "KAYA" | "OTHER_MANUAL",
    manual_transport: { provider_name: "", phone: "", agreed_cost: "", notes: "" },
    driver_id: "",
    vehicle_id: "",
    notes: "",
    stops: [] as Stop[],
  });
  const [activeRun, setActiveRun] = useState<Run | null>(null);
  const [saving, setSaving] = useState(false);
  const [savingAction, setSavingAction] = useState<
    "delivery" | "create-run" | "confirm" | ""
  >("");
  const [busyAction, setBusyAction] = useState("");
  const runMutationLock = useRef(false);
  const [actionFeedback, setActionFeedback] = useState<ActionFeedback>(null);
  const [accountabilityFocusId, setAccountabilityFocusId] = useState("");
  const [formError, setFormError] = useState("");
  const [confirm, setConfirm] = useState<{
    title: string;
    description: string;
    action: () => Promise<void>;
  } | null>(null);
  const [draggedStop, setDraggedStop] = useState<string | null>(null);
  const [cancelTarget, setCancelTarget] = useState<Run | null>(null);
  const [cancelReason, setCancelReason] = useState("");

  const load = async () => {
    setLoading(true);
    try {
      if (canViewScheduler) {
        const [metadata, queueResult, runResult] = await Promise.all([
          apiRequest<any>("/smart-living-deliveries/scheduler/metadata"),
          apiRequest<any>(
            "/smart-living-deliveries/scheduler/queue?page_size=100",
          ),
          apiRequest<any>("/smart-living-deliveries/scheduler/runs"),
        ]);
        const lookupItems = (value: unknown) =>
          Array.isArray(value)
            ? value
            : value &&
                typeof value === "object" &&
                Array.isArray((value as { items?: unknown[] }).items)
              ? (value as { items: unknown[] }).items
              : [];
        setMeta({
          branches: metadata.data.branches || [],
          drivers: lookupItems(metadata.data.drivers) as Meta["drivers"],
          agents: lookupItems(metadata.data.agents) as Meta["agents"],
          vehicles: lookupItems(metadata.data.vehicles) as Meta["vehicles"],
        });
        setQueue(queueResult.data.orders || []);
        setRuns(runResult.data.runs || []);
        if (canLoading)
          setLoadingRuns(
            (
              await apiRequest<any>(
                "/smart-living-deliveries/scheduler/loading",
              )
            ).data.runs || [],
          );
      } else if (assignedOnly) {
        const [assigned, fieldSchedule] = await Promise.all([
          apiRequest<any>("/smart-living-deliveries/scheduler/assigned"),
          isFieldAgent ? apiRequest<any>("/smart-living-deliveries/field-schedule") : Promise.resolve(null),
        ]);
        setRuns(assigned.data.runs || []);
        if (fieldSchedule) {
          setFieldDeliveries(fieldSchedule.data.deliveries || []);
          setFieldDeliveryCounts(fieldSchedule.data.counts || { upcoming: 0, delivered: 0 });
        }
      } else if (canLoading) {
        setLoadingRuns(
          (await apiRequest<any>("/smart-living-deliveries/scheduler/loading"))
            .data.runs || [],
        );
      }
      if (canAccountability) {
        const accountability = await apiRequest<any>(
          "/smart-living-deliveries/accountability/batches?page_size=100",
        );
        setAccountabilityBatches(accountability.data.batches || []);
      }
    } catch (error) {
      toast.error(
        error instanceof Error
          ? error.message
          : "Unable to load the delivery schedule.",
      );
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    void load();
  }, []);
  useDataSync(['deliveries', 'delivery_runs', 'vehicle_movements', 'returns'], () => {
    if (document.visibilityState === 'visible') void load();
  });

  const filteredQueue = useMemo(
    () =>
      queue.filter((order) => {
        const text =
          `${order.customer_name} ${order.reference_number || order.external_reference || ""} ${order.delivery_address} ${order.landmark || ""} ${order.product_lines.map((line) => line.product_name).join(" ")}`.toLowerCase();
        return (
          (!search || text.includes(search.toLowerCase())) &&
          (!branchFilter || order.branch_id === branchFilter) &&
          (!dateFilter || order.requested_delivery_date === dateFilter) &&
          (!productFilter ||
            order.product_lines.some((line) =>
              line.product_name
                .toLowerCase()
                .includes(productFilter.toLowerCase()),
            ))
        );
      }),
    [queue, search, branchFilter, dateFilter, productFilter],
  );

  const openBuilder = () => {
    const selectedOrders = queue.filter((order) => selected.includes(order.id));
    if (!selectedOrders.length)
      return toast.error("Select at least one certified delivery.");
    const branch = selectedOrders[0].branch_id;
    if (selectedOrders.some((order) => order.branch_id !== branch))
      return toast.error(
        "A daily run can contain deliveries from one branch only.",
      );
    const stops = selectedOrders.map((order, index) => ({
      stop_id: `new-${order.id}`,
      delivery_order_id: order.id,
      sequence_number: index + 1,
      stop_type: "CUSTOMER_DELIVERY",
      customer_name: order.customer_name,
      agent_id: order.sales_agent_id || "",
      address: order.delivery_address,
      landmark: order.landmark,
      latitude: order.latitude,
      longitude: order.longitude,
      expected_arrival_time: "",
      estimated_service_minutes: 20,
      notes: order.notes,
      status: "PLANNED",
      phone: order.phone || order.customer_phone,
      products: order.product_lines,
    }));
    setBuilder({
      branch_id: branch,
      delivery_date:
        selectedOrders
          .map((order) => order.requested_delivery_date)
          .filter(Boolean)
          .sort()[0] || "",
      planned_departure_time: "08:00",
      transport_method: "VEHICLE",
      manual_transport: { provider_name: "", phone: "", agreed_cost: "", notes: "" },
      driver_id: "",
      vehicle_id: "",
      notes: "",
      stops,
    });
    setFormError("");
    setBuilderOpen(true);
  };

  const saveOrder = async (event: React.FormEvent) => {
    event.preventDefault();
    setFormError("");
    if (
      !orderForm.reference_number ||
      !orderForm.customer_name ||
      !orderForm.phone ||
      !orderForm.branch_id ||
      !orderForm.delivery_address
    )
      return setFormError(
        "Complete all required delivery and customer fields.",
      );
    setSaving(true);
    setSavingAction("delivery");
    try {
      await apiRequest("/smart-living-deliveries/scheduler/orders", {
        method: "POST",
        body: JSON.stringify({
          ...orderForm,
          latitude:
            orderForm.latitude === "" ? null : Number(orderForm.latitude),
          longitude:
            orderForm.longitude === "" ? null : Number(orderForm.longitude),
        }),
      });
      toast.success("Certified delivery added to the scheduling queue.");
      setOrderOpen(false);
      setOrderForm(EMPTY_ORDER);
      await load();
    } catch (error) {
      setFormError(
        error instanceof Error
          ? error.message
          : "Unable to create the delivery.",
      );
    } finally {
      setSaving(false);
      setSavingAction("");
    }
  };

  const saveNewRun = async (event: React.FormEvent) => {
    event.preventDefault();
    setFormError("");
    if (
      !builder.delivery_date ||
      !builder.planned_departure_time ||
      (builder.transport_method === "VEHICLE" && (!builder.driver_id || !builder.vehicle_id)) ||
      (builder.transport_method !== "VEHICLE" && (!builder.manual_transport.provider_name || !builder.manual_transport.phone))
    )
      return setFormError(
        builder.transport_method === "VEHICLE" ? "Assign a date, departure time, driver, and vehicle." : "Assign a date, departure time, and manual transport handler with phone.",
      );
    if (builder.stops.some((stop) => !stop.agent_id))
      return setFormError("Every customer stop needs a responsible agent.");
    setSaving(true);
    setSavingAction("create-run");
    try {
      const response = await apiRequest<any>(
        "/smart-living-deliveries/scheduler/runs",
        {
          method: "POST",
          body: JSON.stringify({
            ...builder,
            delivery_order_ids: selected,
            stops: builder.stops,
          }),
        },
      );
      toast.success(`${runName(response.data.run)} saved as a draft.`);
      setBuilderOpen(false);
      setSelected([]);
      setTab("runs");
      await load();
    } catch (error) {
      setFormError(
        error instanceof Error
          ? error.message
          : "Unable to create the daily run.",
      );
    } finally {
      setSaving(false);
      setSavingAction("");
    }
  };

  const openRun = async (run: Run) => {
    if (!canViewScheduler) {
      setActiveRun(run);
      setFormError("");
      setActionFeedback(null);
      return;
    }
    try {
      setActiveRun(
        (
          await apiRequest<any>(
            `/smart-living-deliveries/scheduler/runs/${run.id}`,
          )
        ).data.run,
      );
      setFormError("");
      setActionFeedback(null);
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Unable to load run details.",
      );
    }
  };
  const reorder = (stops: Stop[], fromId: string, toId: string) => {
    const from = stops.findIndex((stop) => stop.stop_id === fromId);
    const to = stops.findIndex((stop) => stop.stop_id === toId);
    if (from < 0 || to < 0 || from === to) return stops;
    const next = [...stops];
    const [item] = next.splice(from, 1);
    next.splice(to, 0, item);
    return next.map((stop, index) => ({ ...stop, sequence_number: index + 1 }));
  };
  const moveStop = (index: number, direction: -1 | 1) => {
    if (
      !activeRun ||
      index + direction < 0 ||
      index + direction >= activeRun.stops.length
    )
      return;
    const next = [...activeRun.stops];
    [next[index], next[index + direction]] = [
      next[index + direction],
      next[index],
    ];
    setActiveRun({
      ...activeRun,
      stops: next.map((stop, sequence) => ({
        ...stop,
        sequence_number: sequence + 1,
      })),
    });
  };
  const saveRun = async () => {
    if (!activeRun || runMutationLock.current) return;
    runMutationLock.current = true;
    setBusyAction("save");
    setFormError("");
    setActionFeedback(null);
    try {
      const response = await apiRequest<any>(
        `/smart-living-deliveries/scheduler/runs/${activeRun.id}`,
        {
          method: "PATCH",
          body: JSON.stringify({
            delivery_date: activeRun.delivery_date,
            planned_departure_time: activeRun.planned_departure_time,
            transport_method: activeRun.transport_method || "VEHICLE",
            manual_transport: activeRun.manual_transport,
            driver_id: activeRun.driver_id,
            vehicle_id: activeRun.vehicle_id,
            notes: activeRun.notes,
            stops: activeRun.stops,
          }),
        },
      );
      setActiveRun(response.data.run);
      const message = `Run saved as version ${response.data.run.version} and assigned users notified.`;
      setActionFeedback({ tone: "success", text: message });
      toast.success(message);
      await load();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unable to save the run.";
      setFormError(message);
      setActionFeedback({ tone: "error", text: message });
      toast.error(message);
    } finally {
      runMutationLock.current = false;
      setBusyAction("");
    }
  };
  const transition = async (run: Run, action: "publish" | "lock") => {
    if (runMutationLock.current) return;
    runMutationLock.current = true;
    setBusyAction(action);
    setActionFeedback(null);
    try {
      const response = await apiRequest<any>(
        `/smart-living-deliveries/scheduler/runs/${run.id}/${action}`,
        { method: "POST" },
      );
      setActiveRun(response.data.run);
      const message =
        action === "publish"
          ? "Run published successfully."
          : "Operational schedule locked successfully.";
      setActionFeedback({ tone: "success", text: message });
      toast.success(message);
      await load();
    } catch (error) {
      const message = error instanceof Error ? error.message : `Unable to ${action} this run.`;
      setActionFeedback({ tone: "error", text: message });
      toast.error(message);
      throw error;
    } finally {
      runMutationLock.current = false;
      setBusyAction("");
    }
  };
  const executeRunAction = async (
    path: string,
    body?: Record<string, unknown>,
    success = "Delivery run updated.",
  ) => {
    if (!activeRun || runMutationLock.current) return;
    runMutationLock.current = true;
    const actionKey =
      path.includes("/stops/") || path.startsWith("stops/")
        ? String(body?.action || "stop").toLowerCase()
        : path;
    setBusyAction(actionKey);
    setFormError("");
    setActionFeedback(null);
    try {
      const response = await apiRequest<any>(
        `/smart-living-deliveries/scheduler/runs/${activeRun.id}/${path}`,
        { method: "POST", body: body ? JSON.stringify(body) : undefined },
      );
      if (response.data.run) setActiveRun(response.data.run);
      else {
        const result = canViewScheduler
          ? await apiRequest<any>(
              `/smart-living-deliveries/scheduler/runs/${activeRun.id}`,
            )
          : canLoading && !assignedOnly
            ? await apiRequest<any>(
                "/smart-living-deliveries/scheduler/loading",
              )
          : await apiRequest<any>(
              "/smart-living-deliveries/scheduler/assigned",
            );
        const refreshed = canViewScheduler
          ? result.data.run
          : result.data.runs?.find((item: Run) => item.id === activeRun.id);
        if (refreshed) setActiveRun(refreshed);
      }
      setActionFeedback({ tone: "success", text: success });
      toast.success(success);
      await load();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unable to update this run.";
      setFormError(message);
      setActionFeedback({ tone: "error", text: message });
      toast.error(message);
    } finally {
      runMutationLock.current = false;
      setBusyAction("");
    }
  };
  const cancelRun = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!cancelTarget || !cancelReason.trim())
      return setFormError("Enter a cancellation reason for the audit trail.");
    if (runMutationLock.current) return;
    runMutationLock.current = true;
    setBusyAction("cancel");
    try {
      await apiRequest(
        `/smart-living-deliveries/scheduler/runs/${cancelTarget.id}/cancel`,
        { method: "POST", body: JSON.stringify({ reason: cancelReason }) },
      );
      toast.success(
        "Delivery run cancelled and deliveries returned to the queue.",
      );
      setCancelTarget(null);
      setCancelReason("");
      setActiveRun(null);
      await load();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unable to cancel this run.";
      setFormError(message);
      toast.error(message);
    } finally {
      runMutationLock.current = false;
      setBusyAction("");
    }
  };

  const weekGroups = useMemo(
    () =>
      runs.reduce<Record<string, Run[]>>((groups, run) => {
        const key = run.delivery_date || "Unscheduled";
        (groups[key] ||= []).push(run);
        return groups;
      }, {}),
    [runs],
  );
  const availableVehicles = meta.vehicles
    .filter(
      (vehicle) =>
        !builder.branch_id ||
        !vehicle.branch_id ||
        vehicle.branch_id === builder.branch_id,
    )
    .filter(
      (vehicle) =>
        !builder.driver_id ||
        !vehicle.assigned_driver_id ||
        vehicle.assigned_driver_id === builder.driver_id,
    );
  const viewRuns = tab === "loading" ? loadingRuns : runs;
  const today = localDateKey();
  const historyStatuses = [
    "EXECUTION_COMPLETED",
    "AWAITING_RECONCILIATION",
    "AWAITING_RETURN_RECONCILIATION",
    "COMPLETED",
    "CANCELLED",
  ];
  const assignedRuns = !assignedOnly
    ? runs
    : runs.filter((run) =>
        assignedView === "today"
          ? run.delivery_date === today && !historyStatuses.includes(run.status)
          : assignedView === "history"
            ? historyStatuses.includes(run.status) || Boolean(run.delivery_date && run.delivery_date < today)
            : !historyStatuses.includes(run.status) && (!run.delivery_date || run.delivery_date >= today),
      );
  const activeAccountability = activeRun
    ? accountabilityBatches.find((batch) => batch.id === activeRun.id)
    : undefined;
  const planningEditable = Boolean(
    activeRun &&
      canManage &&
      ["DRAFT", "READY_FOR_REVIEW", "PUBLISHED"].includes(activeRun.status),
  );

  if (!canViewScheduler && !assignedOnly && !canLoading && !canAccountability)
    return (
      <div className="m-6 rounded-xl border bg-white p-10 text-center">
        <h1 className="font-semibold text-slate-900">
          Delivery schedule unavailable
        </h1>
        <p className="mt-2 text-sm text-slate-500">
          Your account is not assigned delivery schedule access.
        </p>
      </div>
    );

  return (
    <div className="min-h-full bg-slate-50 p-3 sm:p-4 md:p-6">
      <div className="mx-auto max-w-7xl space-y-4 md:space-y-5">
        <header className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold text-slate-900">
              {canViewScheduler
                ? "Delivery Scheduler"
                : canLoading && !assignedOnly
                  ? "Upcoming Loading Schedule"
                  : "Upcoming Deliveries"}
            </h1>
            <p className="mt-1 text-sm text-slate-500">
              {canViewScheduler
                ? "Plan certified customer deliveries, publish daily runs, and coordinate field teams."
                : "Published and locked delivery work assigned to your workspace."}
            </p>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => void load()}
              className="rounded-lg border bg-white p-2.5"
              aria-label="Refresh schedule"
            >
              <RefreshCw
                className={`h-4 w-4 ${loading ? "animate-spin" : ""}`}
              />
            </button>
            {canCreate && (
              <button
                onClick={() => {
                  setOrderForm({
                    ...EMPTY_ORDER,
                    branch_id: user?.primary_branch_id || "",
                  });
                  setFormError("");
                  setOrderOpen(true);
                }}
                className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white"
              >
                <Plus className="h-4 w-4" />
                Certified delivery
              </button>
            )}
          </div>
        </header>
        {(canViewScheduler || canAccountability) && (
          <nav className="scrollbar-none flex snap-x gap-1 overflow-x-auto border-b" aria-label="Delivery operations views">
            {(
              [
                ...(canViewScheduler ? [
                  { id: "queue", label: "Certified Deliveries", icon: ListChecks },
                  { id: "runs", label: "Daily Runs", icon: Route },
                  { id: "week", label: "Weekly View", icon: CalendarDays },
                ] : []),
                ...(canLoading
                  ? [
                      {
                        id: "loading",
                        label: "Loading Schedule",
                        icon: PackageCheck,
                      },
                    ]
                  : []),
                ...(canAccountability
                  ? [{ id: "accountability", label: "Returns & Reconciliation", icon: PackageCheck }]
                  : []),
              ] as { id: SchedulerTab; label: string; icon: typeof Route }[]
            ).map((item) => (
              <button
                key={item.id}
                onClick={() => setTab(item.id)}
                className={`flex shrink-0 snap-start items-center gap-2 whitespace-nowrap border-b-2 px-3 py-3 text-sm font-medium ${tab === item.id ? "border-blue-600 text-blue-700" : "border-transparent text-slate-500"}`}
              >
                <item.icon className="h-4 w-4" />
                {item.label}
              </button>
            ))}
          </nav>
        )}
        {assignedOnly && (
          <nav className="scrollbar-none flex snap-x gap-1 overflow-x-auto rounded-xl border bg-white p-1" aria-label="My deliveries views">
            {([
              ["upcoming", "Upcoming Deliveries"],
              ["today", "Today's Route"],
              ["history", "Delivery History"],
            ] as [AssignedView, string][]).map(([id, label]) => (
              <button key={id} onClick={() => setAssignedView(id)} className={`shrink-0 snap-start whitespace-nowrap rounded-lg px-4 py-2 text-sm font-medium ${assignedView === id ? "bg-blue-600 text-white" : "text-slate-600"}`}>
                {label}
              </button>
            ))}
          </nav>
        )}

        {loading ? (
          <div className="flex h-64 items-center justify-center">
            <Loader2 className="h-7 w-7 animate-spin text-blue-600" />
          </div>
        ) : (
          <>
            {canViewScheduler && tab === "queue" && (
              <section className="space-y-4">
                <button type="button" onClick={() => setFiltersOpen((open) => !open)} className="flex min-h-11 w-full items-center justify-center gap-2 rounded-lg border bg-white px-3 py-2 text-sm font-medium text-slate-700 md:hidden" aria-expanded={filtersOpen}><Filter className="h-4 w-4" />{filtersOpen ? "Hide filters" : `Filters${[branchFilter, dateFilter, productFilter].filter(Boolean).length ? ` (${[branchFilter, dateFilter, productFilter].filter(Boolean).length})` : ""}`}</button>
                <div className={`${filtersOpen ? "grid" : "hidden"} gap-2 rounded-xl border bg-white p-3 sm:grid-cols-2 md:grid lg:grid-cols-5`}>
                  <div className="relative sm:col-span-2">
                    <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
                    <input
                      className={`${fieldClass} pl-9`}
                      placeholder="Customer, reference, area or product"
                      value={search}
                      onChange={(event) => setSearch(event.target.value)}
                    />
                  </div>
                  <select
                    className={fieldClass}
                    value={branchFilter}
                    onChange={(event) => setBranchFilter(event.target.value)}
                  >
                    <option value="">All branches</option>
                    {meta.branches.map((branch) => (
                      <option key={branch.id} value={branch.id}>
                        {branch.name}
                      </option>
                    ))}
                  </select>
                  <input
                    type="date"
                    className={fieldClass}
                    value={dateFilter}
                    onChange={(event) => setDateFilter(event.target.value)}
                  />
                  <input
                    className={fieldClass}
                    placeholder="Product filter"
                    value={productFilter}
                    onChange={(event) => setProductFilter(event.target.value)}
                  />
                </div>
                <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                  <p className="text-sm text-slate-500">
                    {filteredQueue.length} certified deliveries waiting
                  </p>
                  <button
                    disabled={!selected.length || saving}
                    onClick={openBuilder}
                    className="flex min-h-11 w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-40 sm:w-auto"
                  >
                    <Route className="h-4 w-4" />
                    Create daily run ({selected.length})
                  </button>
                </div>
                <CertifiedOrderCards
                  orders={filteredQueue}
                  selected={selected}
                  setSelected={setSelected}
                  meta={meta}
                  disabled={saving}
                />
                <div className="hidden overflow-x-auto rounded-xl border bg-white md:block">
                  <table className="w-full min-w-[900px] text-left text-sm">
                    <thead className="bg-slate-50 text-xs uppercase text-slate-500">
                      <tr>
                        <th className="p-3"></th>
                        {[
                          "Customer",
                          "Agent",
                          "Area",
                          "Products",
                          "Requested date",
                          "Branch",
                          "Certification",
                          "Scheduling",
                        ].map((item) => (
                          <th key={item} className="p-3">
                            {item}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {filteredQueue.map((order) => {
                        const branch = meta.branches.find(
                          (item) => item.id === order.branch_id,
                        );
                        const agent = meta.agents.find(
                          (item) => item.id === order.sales_agent_id,
                        );
                        return (
                          <tr key={order.id} className="border-t">
                            <td className="p-3">
                              <input
                                type="checkbox"
                                aria-label={`Select ${order.customer_name}`}
                                checked={selected.includes(order.id)}
                                disabled={saving}
                                onChange={(event) =>
                                  setSelected(
                                    event.target.checked
                                      ? [...selected, order.id]
                                      : selected.filter(
                                          (id) => id !== order.id,
                                        ),
                                  )
                                }
                              />
                            </td>
                            <td className="p-3">
                              <strong className="block text-slate-900">
                                {order.customer_name}
                              </strong>
                              <span className="text-xs text-slate-500">
                                {order.reference_number ||
                                  order.external_reference ||
                                  "Reference unavailable"}
                              </span>
                            </td>
                            <td className="p-3">
                              {order.agent?.name || agent?.name || (
                                <span className="text-amber-700">
                                  Name unavailable
                                </span>
                              )}
                            </td>
                            <td className="p-3">
                              {order.delivery_address}
                              <p className="text-xs text-slate-500">
                                {order.landmark || "No landmark"}
                                {order.latitude == null && " · GPS missing"}
                              </p>
                            </td>
                            <td className="p-3">
                              {order.product_lines.map((line) => (
                                <div key={line.line_id || line.product_name}>
                                  {line.product_name} × {quantity(line)}
                                </div>
                              ))}
                            </td>
                            <td className="p-3">
                              {order.requested_delivery_date || "Flexible"}
                            </td>
                            <td className="p-3">
                              {order.branch?.name || branch?.name || "Name unavailable"}
                            </td>
                            <td className="p-3">
                              <span className="rounded-full bg-emerald-50 px-2 py-1 text-xs text-emerald-700">
                                {order.status}
                              </span>
                            </td>
                            <td className="p-3 text-amber-700">Waiting</td>
                          </tr>
                        );
                      })}
                      {!filteredQueue.length && (
                        <tr>
                          <td
                            colSpan={9}
                            className="p-10 text-center text-slate-500"
                          >
                            No certified deliveries match the current filters.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </section>
            )}

            {(tab === "runs" || !canViewScheduler) && (
              <div className="space-y-4">
                {assignedOnly && isFieldAgent && (
                  <FieldAgentDeliveryCards deliveries={fieldDeliveries} counts={fieldDeliveryCounts} />
                )}
                <RunCards
                  runs={assignedOnly ? assignedRuns : runs}
                  onOpen={(run) => void openRun(run)}
                  assigned={!canViewScheduler}
                />
              </div>
            )}
            {canViewScheduler && tab === "week" && (
              <section className="grid gap-4 lg:grid-cols-2">
                {Object.entries(weekGroups).map(([date, dayRuns]) => (
                  <div key={date} className="rounded-xl border bg-white p-4">
                    <h2 className="font-semibold text-slate-900">{date}</h2>
                    <div className="mt-3 space-y-2">
                      {dayRuns.map((run) => (
                        <button
                          key={run.id}
                          onClick={() => void openRun(run)}
                          className="flex w-full flex-col gap-2 rounded-lg bg-slate-50 p-3 text-left sm:flex-row sm:items-center sm:justify-between"
                        >
                          <span>
                            <strong className="block text-sm">
                              {runName(run)}
                            </strong>
                            <span className="text-xs text-slate-500">
                              {run.planned_departure_time || "Time needed"} ·{" "}
                              {run.stops?.length || 0} stops
                            </span>
                          </span>
                          <span
                            className={`rounded-full px-2 py-1 text-xs ${statusTone(run.status)}`}
                          >
                            {run.status}
                          </span>
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
                {!Object.keys(weekGroups).length && (
                  <Empty text="No delivery runs have been planned." />
                )}
              </section>
            )}
            {tab === "loading" && (
              <LoadingSchedule
                runs={loadingRuns}
                onOpen={(run) => void openRun(run)}
              />
            )}
            {tab === "accountability" && (
              <AccountabilityPanel
                batches={accountabilityBatches}
                userId={user?.id}
                canReceive={canReceiveReturns}
                canExceptions={canManageExceptions}
                canInvestigate={canInvestigate}
                canReconcile={canReconcile}
                canClose={canCloseBatch}
                canReopen={canReopenBatch}
                focusId={accountabilityFocusId}
                refresh={load}
              />
            )}
          </>
        )}
      </div>

      <Dialog open={orderOpen} onOpenChange={setOrderOpen}>
        <DialogContent className="max-h-[96vh] w-[calc(100vw-1rem)] overflow-y-auto p-4 sm:max-w-2xl sm:p-6">
          <DialogHeader>
            <DialogTitle>Certified delivery order</DialogTitle>
            <DialogDescription>
              Record the final certified customer and product instruction.
              FleetOps does not calculate product conversions.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={saveOrder} className="space-y-5">
            {formError && (
              <div
                role="alert"
                className="rounded-lg bg-red-50 p-3 text-sm text-red-700"
              >
                {formError}
              </div>
            )}
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <Field label="Reference number" required>
                <input
                  className={fieldClass}
                  value={orderForm.reference_number}
                  onChange={(e) =>
                    setOrderForm({
                      ...orderForm,
                      reference_number: e.target.value,
                    })
                  }
                />
              </Field>
              <Field label="Customer name" required>
                <input
                  className={fieldClass}
                  value={orderForm.customer_name}
                  onChange={(e) =>
                    setOrderForm({
                      ...orderForm,
                      customer_name: e.target.value,
                    })
                  }
                />
              </Field>
              <Field label="Phone" required>
                <input
                  className={fieldClass}
                  value={orderForm.phone}
                  onChange={(e) =>
                    setOrderForm({ ...orderForm, phone: e.target.value })
                  }
                />
              </Field>
              <Field label="Alternative phone">
                <input
                  className={fieldClass}
                  value={orderForm.alternative_phone}
                  onChange={(e) =>
                    setOrderForm({
                      ...orderForm,
                      alternative_phone: e.target.value,
                    })
                  }
                />
              </Field>
              <Field label="Branch" required>
                <select
                  className={fieldClass}
                  value={orderForm.branch_id}
                  onChange={(e) =>
                    setOrderForm({
                      ...orderForm,
                      branch_id: e.target.value,
                      sales_agent_id: "",
                    })
                  }
                >
                  <option value="">Select branch</option>
                  {meta.branches.map((branch) => (
                    <option key={branch.id} value={branch.id}>
                      {branch.code} — {branch.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Sales / field agent">
                <select
                  className={fieldClass}
                  value={orderForm.sales_agent_id}
                  onChange={(e) =>
                    setOrderForm({
                      ...orderForm,
                      sales_agent_id: e.target.value,
                    })
                  }
                >
                  <option value="">Assign during scheduling</option>
                  {meta.agents
                    .filter(
                      (agent) =>
                        !orderForm.branch_id ||
                        !agent.primary_branch_id ||
                        agent.primary_branch_id === orderForm.branch_id,
                    )
                    .map((agent) => (
                      <option
                        key={agent.id}
                        value={agent.id}
                        disabled={Boolean(agent.disabled_reason)}
                      >
                        {agent.label || agent.name} · {agent.branch || "Unassigned"}
                      </option>
                    ))}
                </select>
              </Field>
              <Field
                label="Delivery address"
                required
                className="sm:col-span-2"
              >
                <input
                  className={fieldClass}
                  value={orderForm.delivery_address}
                  onChange={(e) =>
                    setOrderForm({
                      ...orderForm,
                      delivery_address: e.target.value,
                    })
                  }
                />
              </Field>
              <Field label="Landmark">
                <input
                  className={fieldClass}
                  value={orderForm.landmark}
                  onChange={(e) =>
                    setOrderForm({ ...orderForm, landmark: e.target.value })
                  }
                />
              </Field>
              <Field label="Requested date">
                <input
                  type="date"
                  className={fieldClass}
                  value={orderForm.requested_delivery_date}
                  onChange={(e) =>
                    setOrderForm({
                      ...orderForm,
                      requested_delivery_date: e.target.value,
                    })
                  }
                />
              </Field>
            </div>
            <div>
              <div className="mb-2 flex items-center justify-between">
                <div>
                  <h3 className="font-semibold text-slate-900">
                    Certified product lines
                  </h3>
                  <p className="text-xs text-slate-500">
                    Drivers always receive product names and quantities.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() =>
                    setOrderForm({
                      ...orderForm,
                      product_lines: [
                        ...orderForm.product_lines,
                        { ...EMPTY_LINE },
                      ],
                    })
                  }
                  className="text-sm font-medium text-blue-700"
                >
                  + Add product
                </button>
              </div>
              <div className="space-y-3">
                {orderForm.product_lines.map((line, index) => (
                  <div key={index} className="rounded-xl border p-4">
                    <div className="grid gap-3 sm:grid-cols-2">
                      <Field label="Product name" required>
                        <input
                          className={fieldClass}
                          value={line.product_name}
                          onChange={(e) =>
                            updateLine(
                              index,
                              { product_name: e.target.value },
                              orderForm,
                              setOrderForm,
                            )
                          }
                        />
                      </Field>
                      <Field label="Product code">
                        <input
                          className={fieldClass}
                          value={line.product_code}
                          onChange={(e) =>
                            updateLine(
                              index,
                              { product_code: e.target.value },
                              orderForm,
                              setOrderForm,
                            )
                          }
                        />
                      </Field>
                      <Field label="Quantity" required>
                        <input
                          type="number"
                          min="1"
                          className={fieldClass}
                          value={line.quantity}
                          onChange={(e) =>
                            updateLine(
                              index,
                              { quantity: Number(e.target.value) },
                              orderForm,
                              setOrderForm,
                            )
                          }
                        />
                      </Field>
                      <Field label="Delivery type">
                        <select
                          className={fieldClass}
                          value={line.delivery_type}
                          onChange={(e) =>
                            updateLine(
                              index,
                              { delivery_type: e.target.value },
                              orderForm,
                              setOrderForm,
                            )
                          }
                        >
                          <option value="FULLY_COMPLETED_PRODUCT">
                            Fully completed product
                          </option>
                          <option value="CLOSED_CONTRIBUTION_CONVERSION">
                            Closed contribution conversion
                          </option>
                          <option value="OTHER_APPROVED_PRODUCT">
                            Other approved product
                          </option>
                        </select>
                      </Field>
                      {line.delivery_type ===
                        "CLOSED_CONTRIBUTION_CONVERSION" && (
                        <>
                          <Field label="Original product" required>
                            <input
                              className={fieldClass}
                              value={line.original_product_name}
                              onChange={(e) =>
                                updateLine(
                                  index,
                                  { original_product_name: e.target.value },
                                  orderForm,
                                  setOrderForm,
                                )
                              }
                            />
                          </Field>
                          <Field label="Original value">
                            <input
                              type="number"
                              className={fieldClass}
                              value={line.original_product_value || ""}
                              onChange={(e) =>
                                updateLine(
                                  index,
                                  {
                                    original_product_value: Number(
                                      e.target.value,
                                    ),
                                  },
                                  orderForm,
                                  setOrderForm,
                                )
                              }
                            />
                          </Field>
                          <Field label="Contributed amount">
                            <input
                              type="number"
                              className={fieldClass}
                              value={line.contributed_amount || ""}
                              onChange={(e) =>
                                updateLine(
                                  index,
                                  {
                                    contributed_amount: Number(e.target.value),
                                  },
                                  orderForm,
                                  setOrderForm,
                                )
                              }
                            />
                          </Field>
                          <Field label="Approved delivery value">
                            <input
                              type="number"
                              className={fieldClass}
                              value={line.approved_delivery_value || ""}
                              onChange={(e) =>
                                updateLine(
                                  index,
                                  {
                                    approved_delivery_value: Number(
                                      e.target.value,
                                    ),
                                  },
                                  orderForm,
                                  setOrderForm,
                                )
                              }
                            />
                          </Field>
                        </>
                      )}
                    </div>
                    {orderForm.product_lines.length > 1 && (
                      <button
                        type="button"
                        onClick={() =>
                          setOrderForm({
                            ...orderForm,
                            product_lines: orderForm.product_lines.filter(
                              (_, itemIndex) => itemIndex !== index,
                            ),
                          })
                        }
                        className="mt-2 text-xs text-red-600"
                      >
                        Remove line
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </div>
            <Field label="Notes">
              <textarea
                rows={3}
                className={fieldClass}
                value={orderForm.notes}
                onChange={(e) =>
                  setOrderForm({ ...orderForm, notes: e.target.value })
                }
              />
            </Field>
            <div className="sticky bottom-0 -mx-4 flex flex-col-reverse gap-2 border-t bg-white px-4 pb-1 pt-4 sm:mx-0 sm:flex-row sm:justify-end sm:px-0">
              <button
                type="button"
                onClick={() => setOrderOpen(false)}
                className="rounded-lg border px-4 py-2 text-sm"
              >
                Cancel
              </button>
              <button
                disabled={saving}
                className="flex min-h-11 items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white disabled:opacity-50"
              >
                {saving && <Loader2 className="h-4 w-4 animate-spin" />}
                {savingAction === "delivery"
                  ? "Saving delivery…"
                  : "Save certified delivery"}
              </button>
            </div>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={builderOpen} onOpenChange={setBuilderOpen}>
        <DialogContent className="h-[100dvh] w-screen max-w-none overflow-y-auto rounded-none p-4 sm:h-auto sm:max-h-[94vh] sm:max-w-4xl sm:rounded-xl sm:p-6">
          <DialogHeader>
            <DialogTitle>Create Daily Delivery Run</DialogTitle>
            <DialogDescription>
              Assign resources, confirm agents, and set the initial manual stop
              order. The run is saved as a draft.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={saveNewRun} className="space-y-5">
            {formError && (
              <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700">
                {formError}
              </div>
            )}
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Field label="Delivery date" required>
                <input
                  type="date"
                  className={fieldClass}
                  value={builder.delivery_date}
                  onChange={(e) =>
                    setBuilder({ ...builder, delivery_date: e.target.value })
                  }
                />
              </Field>
              <Field label="Departure time" required>
                <input
                  type="time"
                  className={fieldClass}
                  value={builder.planned_departure_time}
                  onChange={(e) =>
                    setBuilder({
                      ...builder,
                      planned_departure_time: e.target.value,
                    })
                  }
                />
              </Field>
              <Field label="Transport method" required>
                <select className={fieldClass} value={builder.transport_method} onChange={(e) => setBuilder({...builder, transport_method:e.target.value as "VEHICLE" | "KAYA" | "OTHER_MANUAL", driver_id:"", vehicle_id:""})}>
                  <option value="VEHICLE">Company vehicle</option><option value="KAYA">Kaya</option><option value="OTHER_MANUAL">Other manual</option>
                </select>
              </Field>
              {builder.transport_method === "VEHICLE" ? <>
              <Field label="Driver" required>
                <select
                  className={fieldClass}
                  value={builder.driver_id}
                  onChange={(e) =>
                    setBuilder({
                      ...builder,
                      driver_id: e.target.value,
                      vehicle_id: "",
                    })
                  }
                >
                  <option value="">Select driver</option>
                  {meta.drivers
                    .map((driver) => (
                      <option
                        key={driver.id}
                        value={driver.id}
                        disabled={Boolean(driver.disabled_reason)}
                      >
                        {driver.label || driver.name} · {driver.branch || "Unassigned"}
                      </option>
                    ))}
                </select>
              </Field>
              <Field label="Vehicle" required>
                <select
                  className={fieldClass}
                  value={builder.vehicle_id}
                  onChange={(e) =>
                    setBuilder({ ...builder, vehicle_id: e.target.value })
                  }
                >
                  <option value="">Select vehicle</option>
                  {availableVehicles.map((vehicle) => (
                    <option
                      key={vehicle.id}
                      value={vehicle.id}
                      disabled={Boolean(
                        vehicle.disabled_reason &&
                          vehicle.assigned_driver_id !== builder.driver_id,
                      )}
                    >
                      {vehicle.label || vehicle.name} · {vehicle.branch || "Unassigned"} · {vehicle.status}
                      {vehicle.disabled_reason ? ` · ${vehicle.disabled_reason}` : ""}
                    </option>
                  ))}
                </select>
              </Field>
              </> : <>
                <Field label="Handler / provider" required><input className={fieldClass} value={builder.manual_transport.provider_name} onChange={(e)=>setBuilder({...builder,manual_transport:{...builder.manual_transport,provider_name:e.target.value}})}/></Field>
                <Field label="Handler phone" required><input className={fieldClass} value={builder.manual_transport.phone} onChange={(e)=>setBuilder({...builder,manual_transport:{...builder.manual_transport,phone:e.target.value}})}/></Field>
                <Field label="Agreed cost"><input type="number" min="0" className={fieldClass} value={builder.manual_transport.agreed_cost} onChange={(e)=>setBuilder({...builder,manual_transport:{...builder.manual_transport,agreed_cost:e.target.value}})}/></Field>
                <Field label="Transport notes"><input className={fieldClass} value={builder.manual_transport.notes} onChange={(e)=>setBuilder({...builder,manual_transport:{...builder.manual_transport,notes:e.target.value}})}/></Field>
              </>}
            </div>
            <StopEditor
              stops={builder.stops}
              agents={meta.agents}
              onChange={(stops) => setBuilder({ ...builder, stops })}
              dragged={draggedStop}
              setDragged={setDraggedStop}
              onDrop={(target) => {
                if (draggedStop)
                  setBuilder({
                    ...builder,
                    stops: reorder(builder.stops, draggedStop, target),
                  });
                setDraggedStop(null);
              }}
            />
            <Field label="Run notes">
              <textarea
                rows={2}
                className={fieldClass}
                value={builder.notes}
                onChange={(e) =>
                  setBuilder({ ...builder, notes: e.target.value })
                }
              />
            </Field>
            <div className="sticky bottom-0 flex justify-end gap-2 border-t bg-white pt-4">
              <button
                type="button"
                onClick={() => setBuilderOpen(false)}
                className="rounded-lg border px-4 py-2 text-sm"
              >
                Cancel
              </button>
              <button
                disabled={saving}
                className="flex min-h-11 items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white disabled:opacity-50"
              >
                {saving && <Loader2 className="h-4 w-4 animate-spin" />}
                {savingAction === "create-run"
                  ? "Creating draft run…"
                  : "Save draft run"}
              </button>
            </div>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog
        open={Boolean(activeRun)}
        onOpenChange={(open) => {
          if (!open) setActiveRun(null);
        }}
      >
        <DialogContent className="h-[100dvh] w-screen max-w-none overflow-y-auto rounded-none p-4 sm:h-[92vh] sm:max-w-4xl sm:rounded-xl sm:p-6">
          {activeRun && (
            <>
              <DialogHeader>
                <DialogTitle>{runName(activeRun)}</DialogTitle>
                <DialogDescription>
                  Version {activeRun.version || 1} ·{" "}
                  {activeRun.status.replaceAll("_", " ")} ·{" "}
                  {activeRun.delivery_date || "Date not set"}
                </DialogDescription>
              </DialogHeader>
              {formError && (
                <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700">
                  {formError}
                </div>
              )}
              <RunStatusPanel
                run={activeRun}
                accountability={activeAccountability}
                feedback={actionFeedback}
              />
              <RunSummary run={activeRun} />
              {planningEditable && (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Field label="Delivery date">
                  <input
                    type="date"
                    className={fieldClass}
                    value={activeRun.delivery_date || ""}
                    onChange={(e) =>
                      setActiveRun({
                        ...activeRun,
                        delivery_date: e.target.value,
                      })
                    }
                  />
                </Field>
                <Field label="Departure">
                  <input
                    type="time"
                    className={fieldClass}
                    value={activeRun.planned_departure_time || ""}
                    onChange={(e) =>
                      setActiveRun({
                        ...activeRun,
                        planned_departure_time: e.target.value,
                      })
                    }
                  />
                </Field>
                <Field label="Transport method"><select className={fieldClass} value={activeRun.transport_method || "VEHICLE"} onChange={(e)=>setActiveRun({...activeRun,transport_method:e.target.value as Run["transport_method"],driver_id:"",vehicle_id:"",manual_transport:activeRun.manual_transport || {provider_name:"",phone:"",agreed_cost:null,notes:""}})}><option value="VEHICLE">Company vehicle</option><option value="KAYA">Kaya</option><option value="OTHER_MANUAL">Other manual</option></select></Field>
                {(activeRun.transport_method || "VEHICLE") === "VEHICLE" ? <>
                <Field label="Driver">
                  <select
                    className={fieldClass}
                    value={activeRun.driver_id || ""}
                    onChange={(e) =>
                      setActiveRun({ ...activeRun, driver_id: e.target.value })
                    }
                  >
                    <option value="">Select driver</option>
                    {meta.drivers.map((driver) => (
                      <option
                        key={driver.id}
                        value={driver.id}
                        disabled={Boolean(driver.disabled_reason)}
                      >
                        {driver.label || driver.name} · {driver.branch || "Unassigned"}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Vehicle">
                  <select
                    className={fieldClass}
                    value={activeRun.vehicle_id || ""}
                    onChange={(e) =>
                      setActiveRun({ ...activeRun, vehicle_id: e.target.value })
                    }
                  >
                    <option value="">Select vehicle</option>
                    {meta.vehicles.map((vehicle) => (
                      <option
                        key={vehicle.id}
                        value={vehicle.id}
                        disabled={Boolean(
                          vehicle.disabled_reason &&
                            vehicle.id !== activeRun.vehicle_id,
                        )}
                      >
                        {vehicle.label || vehicle.name} · {vehicle.branch || "Unassigned"}
                        {vehicle.disabled_reason ? ` · ${vehicle.disabled_reason}` : ""}
                      </option>
                    ))}
                  </select>
                </Field>
                </> : <>
                  <Field label="Handler / provider"><input className={fieldClass} value={activeRun.manual_transport?.provider_name || activeRun.manual_transport?.handler_name || ""} onChange={(e)=>setActiveRun({...activeRun,manual_transport:{...(activeRun.manual_transport || {}),provider_name:e.target.value}})}/></Field>
                  <Field label="Handler phone"><input className={fieldClass} value={activeRun.manual_transport?.phone || activeRun.manual_transport?.handler_phone || ""} onChange={(e)=>setActiveRun({...activeRun,manual_transport:{...(activeRun.manual_transport || {}),phone:e.target.value}})}/></Field>
                  <Field label="Agreed cost"><input type="number" min="0" className={fieldClass} value={activeRun.manual_transport?.agreed_cost ?? ""} onChange={(e)=>setActiveRun({...activeRun,manual_transport:{...(activeRun.manual_transport || {}),agreed_cost:e.target.value ? Number(e.target.value) : null}})}/></Field>
                  <Field label="Transport notes"><input className={fieldClass} value={activeRun.manual_transport?.notes || ""} onChange={(e)=>setActiveRun({...activeRun,manual_transport:{...(activeRun.manual_transport || {}),notes:e.target.value}})}/></Field>
                </>}
              </div>
              )}
              {planningEditable ? (
                <StopEditor
                  stops={activeRun.stops}
                  agents={meta.agents}
                  onChange={(stops) => setActiveRun({ ...activeRun, stops })}
                  dragged={draggedStop}
                  setDragged={setDraggedStop}
                  onDrop={(target) => {
                    if (draggedStop)
                      setActiveRun({
                        ...activeRun,
                        stops: reorder(activeRun.stops, draggedStop, target),
                      });
                    setDraggedStop(null);
                  }}
                  move={moveStop}
                />
              ) : (
                <AssignedStops run={activeRun} userId={user?.id} />
              )}
              <ExecutionPanel
                run={activeRun}
                userId={user?.id}
                busyAction={busyAction}
                canIssue={canIssue}
                canAccept={canAcceptExecution}
                canCustody={canCustody}
                canStart={canStartExecution}
                canUpdateStops={canUpdateStops}
                canComplete={canCompleteExecution}
                action={executeRunAction}
              />
              <div className="sticky bottom-0 -mx-4 flex flex-col gap-2 border-t bg-white px-4 pb-1 pt-4 sm:mx-0 sm:flex-row sm:justify-end sm:px-0">
                {planningEditable && (
                    <button
                      onClick={() => void saveRun()}
                      disabled={Boolean(busyAction)}
                      className="flex min-h-11 items-center justify-center gap-2 rounded-lg border px-4 py-2 text-sm font-medium disabled:opacity-50"
                    >
                      {busyAction === "save" && <Loader2 className="h-4 w-4 animate-spin" />}
                      {busyAction === "save"
                        ? "Saving changes…"
                        : activeRun.status === "PUBLISHED"
                          ? "Save & notify team"
                          : "Save changes"}
                    </button>
                  )}
                {canManage && activeRun.status === "DRAFT" && (
                    <button
                      onClick={() => {
                        setCancelReason("");
                        setFormError("");
                        setCancelTarget(activeRun);
                        setActiveRun(null);
                      }}
                      disabled={Boolean(busyAction)}
                      className="min-h-11 rounded-lg border border-red-200 px-4 py-2 text-sm font-medium text-red-700 disabled:opacity-50"
                    >
                      Cancel run
                    </button>
                  )}
                {canPublish &&
                  ["DRAFT", "READY_FOR_REVIEW"].includes(activeRun.status) && (
                    <button
                      onClick={() =>
                        setConfirm({
                          title: `Publish ${runName(activeRun)}?`,
                          description:
                            "The driver, assigned agents, and loading team will be able to see this schedule.",
                          action: () => transition(activeRun, "publish"),
                        })
                      }
                      disabled={!activeRun.review?.valid || Boolean(busyAction)}
                      className="flex min-h-11 items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
                    >
                      {busyAction === "publish" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                      {busyAction === "publish" ? "Publishing…" : "Publish"}
                    </button>
                  )}
                {canLock && activeRun.status === "PUBLISHED" && (
                  <button
                    onClick={() =>
                      setConfirm({
                        title: `Lock ${runName(activeRun)}?`,
                        description:
                          "This confirms the operational plan. Material corrections will require override authority and a reason.",
                        action: () => transition(activeRun, "lock"),
                      })
                    }
                    disabled={Boolean(busyAction)}
                    className="flex min-h-11 items-center justify-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
                  >
                    <Lock className="h-4 w-4" />
                    Lock schedule
                  </button>
                )}
                {["AWAITING_RECONCILIATION", "AWAITING_RETURN_RECONCILIATION", "RECONCILIATION", "REOPENED"].includes(activeRun.status) && canAccountability && (
                  <button
                    onClick={() => {
                      setAccountabilityFocusId(activeRun.id);
                      setTab("accountability");
                      setActiveRun(null);
                    }}
                    className="min-h-11 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white"
                  >
                    Continue to Returns & Reconciliation
                  </button>
                )}
                {["CLOSED", "COMPLETED"].includes(activeRun.status) && (
                  <button
                    onClick={() => window.print()}
                    className="min-h-11 rounded-lg border px-4 py-2 text-sm font-medium"
                  >
                    Export / print summary
                  </button>
                )}
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>

      <Dialog
        open={Boolean(cancelTarget)}
        onOpenChange={(open) => {
          if (!open) {
            setCancelTarget(null);
            setCancelReason("");
          }
        }}
      >
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>
              Cancel {cancelTarget && runName(cancelTarget)}?
            </DialogTitle>
            <DialogDescription>
              Assigned deliveries return to the scheduling queue. The reason is
              recorded and assigned users are notified.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={cancelRun} className="space-y-4">
            {formError && (
              <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700">
                {formError}
              </div>
            )}
            <Field label="Cancellation reason" required>
              <textarea
                autoFocus
                rows={3}
                className={fieldClass}
                value={cancelReason}
                onChange={(event) => setCancelReason(event.target.value)}
              />
            </Field>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                className="rounded-lg border px-4 py-2 text-sm"
                onClick={() => setCancelTarget(null)}
              >
                Keep run
              </button>
              <button
                disabled={busyAction === "cancel" || !cancelReason.trim()}
                className="flex min-h-11 items-center justify-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
              >
                {busyAction === "cancel" && <Loader2 className="h-4 w-4 animate-spin" />}
                {busyAction === "cancel" ? "Cancelling…" : "Cancel delivery run"}
              </button>
            </div>
          </form>
        </DialogContent>
      </Dialog>

      <AlertDialog
        open={Boolean(confirm)}
        onOpenChange={(open) => {
          if (!open) setConfirm(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{confirm?.title}</AlertDialogTitle>
            <AlertDialogDescription>
              {confirm?.description}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              disabled={saving || Boolean(busyAction)}
              onClick={async (event) => {
                event.preventDefault();
                if (!confirm) return;
                setSaving(true);
                setSavingAction("confirm");
                try {
                  await confirm.action();
                  setConfirm(null);
                } catch {
                  // The mutation reports its specific inline and toast error.
                } finally {
                  setSaving(false);
                  setSavingAction("");
                }
              }}
            >
              {busyAction === "publish"
                ? "Publishing…"
                : busyAction === "lock"
                  ? "Locking schedule…"
                  : savingAction === "confirm"
                    ? "Working…"
                    : "Confirm"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

function Field({
  label,
  required,
  className = "",
  children,
}: {
  label: string;
  required?: boolean;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <label className={className}>
      <span className="mb-1 block text-sm font-medium text-slate-700">
        {label}
        {required && <span className="text-red-500"> *</span>}
      </span>
      {children}
    </label>
  );
}
function updateLine(
  index: number,
  update: Partial<Line>,
  form: typeof EMPTY_ORDER,
  setForm: (value: typeof EMPTY_ORDER) => void,
) {
  const lines = [...form.product_lines];
  lines[index] = { ...lines[index], ...update };
  setForm({ ...form, product_lines: lines });
}
function Empty({ text }: { text: string }) {
  return (
    <div className="rounded-xl border border-dashed bg-white p-10 text-center text-sm text-slate-500">
      {text}
    </div>
  );
}

function CertifiedOrderCards({
  orders,
  selected,
  setSelected,
  meta,
  disabled,
}: {
  orders: Order[];
  selected: string[];
  setSelected: (ids: string[]) => void;
  meta: Meta;
  disabled?: boolean;
}) {
  if (!orders.length)
    return (
      <div className="md:hidden">
        <Empty text="No certified deliveries match the current filters." />
      </div>
    );
  return (
    <div className="space-y-3 md:hidden">
      {orders.map((order) => {
        const agent = meta.agents.find((item) => item.id === order.sales_agent_id);
        const branch = meta.branches.find((item) => item.id === order.branch_id);
        const checked = selected.includes(order.id);
        return (
          <label
            key={order.id}
            className={`block rounded-xl border bg-white p-4 ${checked ? "border-blue-500 ring-2 ring-blue-100" : ""}`}
          >
            <div className="flex items-start gap-3">
              <input
                type="checkbox"
                className="mt-1 h-5 w-5"
                checked={checked}
                disabled={disabled}
                onChange={(event) =>
                  setSelected(
                    event.target.checked
                      ? [...selected, order.id]
                      : selected.filter((id) => id !== order.id),
                  )
                }
              />
              <div className="min-w-0 flex-1">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <strong className="block text-slate-900">{order.customer_name}</strong>
                    <span className="text-xs text-slate-500">
                      {order.reference_number ||
                        order.external_reference ||
                        "Reference unavailable"}
                    </span>
                  </div>
                  <span className="rounded-full bg-emerald-50 px-2 py-1 text-xs text-emerald-700">
                    {order.status}
                  </span>
                </div>
                <p className="mt-3 text-sm text-slate-700">{order.delivery_address}</p>
                <p className="text-xs text-slate-500">
                  {order.landmark || "No landmark"} ·{" "}
                  {order.branch?.name || branch?.name || "Name unavailable"}
                </p>
                {order.latitude == null && (
                  <p className="mt-1 text-xs text-amber-700">
                    GPS is unavailable; scheduling can continue using the address and landmark.
                  </p>
                )}
                <div className="mt-3 space-y-1 text-sm">
                  {order.product_lines.map((line) => (
                    <div key={line.line_id || line.product_name}>
                      {line.product_name} × {quantity(line)}
                    </div>
                  ))}
                </div>
                <p className="mt-3 text-xs text-slate-500">
                  Agent: {order.agent?.name || agent?.name || "Name unavailable"} · Requested {order.requested_delivery_date || "Flexible"}
                </p>
              </div>
            </div>
          </label>
        );
      })}
    </div>
  );
}

function FieldAgentDeliveryCards({
  deliveries,
  counts,
}: {
  deliveries: FieldDelivery[];
  counts: { upcoming: number; delivered: number };
}) {
  return (
    <section className="space-y-3">
      <div className="grid grid-cols-2 gap-3 sm:max-w-md">
        <div className="rounded-xl border bg-white p-4"><p className="text-xs text-slate-500">Upcoming</p><strong className="mt-1 block text-2xl text-slate-900">{counts.upcoming}</strong></div>
        <div className="rounded-xl border bg-white p-4"><p className="text-xs text-slate-500">Delivered</p><strong className="mt-1 block text-2xl text-emerald-700">{counts.delivered}</strong></div>
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {deliveries.map((delivery) => (
          <article key={delivery.id} className="rounded-xl border bg-white p-4 shadow-sm">
            <div className="flex items-start justify-between gap-2">
              <div><h3 className="font-semibold text-slate-900">{delivery.customer_name}</h3><p className="text-sm text-slate-500">{delivery.phone || delivery.customer_phone || 'No phone'}</p></div>
              <span className={`rounded-full px-2 py-1 text-xs ${statusTone(delivery.status.toUpperCase())}`}>{delivery.status.replaceAll('_', ' ')}</span>
            </div>
            <p className="mt-3 flex items-start gap-2 text-sm text-slate-600"><MapPin className="mt-0.5 h-4 w-4 shrink-0" />{delivery.delivery_address}</p>
            <p className="mt-2 text-sm text-slate-700">{delivery.product_lines.map((line) => `${line.product_name} × ${quantity(line)}`).join(', ')}</p>
            <dl className="mt-3 grid grid-cols-2 gap-2 text-xs">
              <div><dt className="text-slate-400">Planning</dt><dd className="font-medium text-slate-700">{delivery.planning_status.replaceAll('_', ' ')}</dd></div>
              <div><dt className="text-slate-400">Date / time</dt><dd>{delivery.delivery_date || 'Not planned'} {delivery.delivery_time || ''}</dd></div>
              <div><dt className="text-slate-400">Driver</dt><dd>{delivery.driver?.name || 'Not assigned'}</dd></div>
              <div><dt className="text-slate-400">Vehicle</dt><dd>{delivery.vehicle?.name || 'Not assigned'}</dd></div>
              <div><dt className="text-slate-400">Stop</dt><dd>{delivery.stop_sequence ? `#${delivery.stop_sequence}` : 'Not sequenced'}</dd></div>
              <div><dt className="text-slate-400">Stop status</dt><dd>{delivery.stop_status?.replaceAll('_', ' ') || 'Pending planning'}</dd></div>
            </dl>
          </article>
        ))}
        {!deliveries.length && <p className="rounded-xl border border-dashed bg-white p-8 text-center text-sm text-slate-500 md:col-span-2 xl:col-span-3">No Smart Living deliveries are assigned to you.</p>}
      </div>
    </section>
  );
}

function RunCards({
  runs,
  onOpen,
  assigned,
}: {
  runs: Run[];
  onOpen: (run: Run) => void;
  assigned?: boolean;
}) {
  const today = localDateKey();
  const tomorrow = shiftedLocalDateKey(1);
  return (
    <section className="space-y-4">
      {assigned && (
        <h2 className="text-lg font-semibold text-slate-900">My Deliveries</h2>
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        {runs.map((run) => {
          const itemCount =
            run.delivery_orders
              ?.flatMap((order) => order.product_lines)
              .reduce((sum, line) => sum + quantity(line), 0) || 0;
          return (
            <button
              key={run.id}
              onClick={() => onOpen(run)}
              className="rounded-xl border bg-white p-5 text-left shadow-sm hover:border-blue-300"
            >
              <div className="flex min-w-0 items-start justify-between gap-3">
                <div className="min-w-0">
                  <span className="text-xs font-semibold uppercase tracking-wide text-blue-600">
                    {runName(run)} · v{run.version || 1}
                  </span>
                  <h2 className="mt-1 font-semibold text-slate-900">
                    {run.delivery_date === today
                      ? "Today"
                      : run.delivery_date === tomorrow
                        ? "Tomorrow"
                        : run.delivery_date || "Date needed"}{" "}
                    at {run.planned_departure_time || "—"}
                  </h2>
                </div>
                <span
                  className={`shrink-0 rounded-full px-2 py-1 text-xs ${statusTone(run.status)}`}
                >
                  {run.status.replaceAll("_", " ")}
                </span>
              </div>
              <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
                <Metric
                  icon={Truck}
                  label={(run.transport_method || "VEHICLE") === "VEHICLE" ? run.vehicle?.name || "Vehicle needed" : run.manual_transport?.provider_name || run.manual_transport?.handler_name || "Handler needed"}
                />
                <Metric
                  icon={Users}
                  label={`${run.stops?.length || 0} customers`}
                />
                <Metric icon={PackageCheck} label={`${itemCount} products`} />
                <Metric
                  icon={Clock}
                  label={`${run.assigned_agent_ids?.length || run.agents?.length || 0} agents`}
                />
              </div>
              {run.stops?.[0] && (
                <div className="mt-4 rounded-lg bg-blue-50 p-3">
                  <span className="text-xs font-medium text-blue-700">
                    Next stop
                  </span>
                  <p className="text-sm font-semibold text-blue-950">
                    1. {run.stops[0].customer_name}
                  </p>
                  <p className="text-xs text-blue-700">
                    {run.stops[0].address}
                  </p>
                </div>
              )}
            </button>
          );
        })}
      </div>
      {!runs.length && (
        <Empty text="No published delivery runs are available for this view." />
      )}
    </section>
  );
}
function Metric({ icon: Icon, label }: { icon: typeof Truck; label: string }) {
  return (
    <div className="flex items-center gap-2 rounded-lg bg-slate-50 p-2 text-xs text-slate-600">
      <Icon className="h-4 w-4 text-slate-400" />
      <span className="truncate">{label}</span>
    </div>
  );
}

function RunSummary({ run }: { run: Run }) {
  const productCount = (run.delivery_orders || [])
    .flatMap((order) => order.product_lines || [])
    .reduce((sum, line) => sum + quantity(line), 0);
  return (
    <section className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-7" aria-label="Run summary">
      {[
        ["Branch", run.branch?.name || "Name unavailable"],
        ["Transport", (run.transport_method || "VEHICLE").replaceAll("_", " ")],
        [(run.transport_method || "VEHICLE") === "VEHICLE" ? "Driver" : "Handler", (run.transport_method || "VEHICLE") === "VEHICLE" ? run.driver?.name || "Name unavailable" : run.manual_transport?.provider_name || run.manual_transport?.handler_name || "Name unavailable"],
        ["Departure", run.planned_departure_time || "Not set"],
        ["Customers", String(run.stops?.length || 0)],
        ["Products", String(productCount)],
        ["Agents", String(run.assigned_agent_ids?.length || run.agents?.length || 0)],
      ].map(([label, value]) => (
        <div key={label} className="min-w-0 rounded-lg bg-slate-50 p-3">
          <span className="block text-xs text-slate-500">{label}</span>
          <strong className="block truncate text-sm text-slate-900">{value}</strong>
        </div>
      ))}
    </section>
  );
}

function RunStatusPanel({
  run,
  accountability,
  feedback,
}: {
  run: Run;
  accountability?: AccountabilityBatch;
  feedback: ActionFeedback;
}) {
  const gpsWarnings = run.stops.filter(
    (stop) => stop.latitude == null || stop.longitude == null,
  ).length;
  const blockers = [...(run.review?.errors || [])];
  if (
    ["AWAITING_RECONCILIATION", "AWAITING_RETURN_RECONCILIATION", "RECONCILIATION"].includes(
      run.status,
    ) &&
    accountability &&
    !accountability.reconciliation?.balanced
  )
    blockers.push(
      `${accountability.reconciliation?.outstanding_difference ?? 0} item(s) remain unaccounted for.`,
    );
  const warnings = [...(run.review?.warnings || [])];
  if (gpsWarnings)
    warnings.push(
      `${gpsWarnings} stop(s) have no GPS. Continue with the area, address, and landmark.`,
    );
  const completed = [
    (run.transport_method || "VEHICLE") === "VEHICLE" ? (run.driver_id ? "Driver assigned" : null) : (run.manual_transport?.provider_name ? "Manual handler assigned" : null),
    (run.transport_method || "VEHICLE") === "VEHICLE" ? (run.vehicle_id ? "Vehicle assigned" : null) : "No company vehicle required",
    run.stops.length && run.stops.every((stop) => Boolean(stop.agent_id))
      ? "Responsible agents assigned"
      : null,
    ["EXECUTION_COMPLETED", "AWAITING_RECONCILIATION", "AWAITING_RETURN_RECONCILIATION", "RECONCILED", "CLOSED"].includes(run.status)
      ? "All route outcomes recorded"
      : null,
    accountability?.return ? "Returns received" : null,
    accountability?.reconciliation?.balanced ? "Reconciliation balances" : null,
    run.status === "CLOSED" ? "Run closed and records locked" : null,
  ].filter(Boolean) as string[];
  const nextAction: Record<string, string> = {
    DRAFT: "Complete planning checks, save, then publish.",
    READY_FOR_REVIEW: "Resolve blockers and publish the run.",
    PUBLISHED: "Assigned users are notified; await acceptance or save a permitted update.",
    LOCKED: "Await driver acceptance.",
    ACCEPTED: "Issue ready delivery items.",
    ITEMS_ISSUED: "Acknowledge custody, then start the route.",
    IN_PROGRESS: "Record the next stop outcome.",
    EXECUTION_COMPLETED: "Confirm completion and hand off returns.",
    AWAITING_RECONCILIATION: "Receive returns, resolve exceptions, reconcile, then close.",
    AWAITING_RETURN_RECONCILIATION: "Receive returns, resolve exceptions, reconcile, then close.",
    RECONCILED: "Close the run and lock its records.",
    CLOSED: "Review or export the read-only audit summary.",
    COMPLETED: "Review or export the read-only audit summary.",
  };
  return (
    <section className="space-y-2 rounded-xl border bg-white p-3" aria-label="Run status">
      {feedback && (
        <div
          role={feedback.tone === "error" ? "alert" : "status"}
          className={`flex items-start gap-2 rounded-lg p-3 text-sm ${feedback.tone === "error" ? "bg-red-50 text-red-800" : "bg-emerald-50 text-emerald-800"}`}
        >
          {feedback.tone === "error" ? <XCircle className="mt-0.5 h-4 w-4 shrink-0" /> : <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />}
          {feedback.text}
        </div>
      )}
      <div className="grid gap-2 sm:grid-cols-3">
        <StatusList
          title="Completed checks"
          icon={CheckCircle2}
          tone="success"
          items={completed.length ? completed : ["No checks completed yet."]}
        />
        <StatusList
          title="Blocking issues"
          icon={XCircle}
          tone="error"
          items={blockers.length ? blockers : ["No blocking issues."]}
        />
        <StatusList
          title="Warnings"
          icon={AlertTriangle}
          tone="warning"
          items={warnings.length ? warnings : ["No advisory warnings."]}
        />
      </div>
      <p className="rounded-lg bg-blue-50 p-3 text-sm font-medium text-blue-800">
        Next: {nextAction[run.status] || "Follow the available status action."}
      </p>
    </section>
  );
}

function StatusList({
  title,
  icon: Icon,
  tone,
  items,
}: {
  title: string;
  icon: typeof CheckCircle2;
  tone: "success" | "warning" | "error";
  items: string[];
}) {
  const style =
    tone === "success"
      ? "bg-emerald-50 text-emerald-800"
      : tone === "error"
        ? "bg-red-50 text-red-800"
        : "bg-amber-50 text-amber-800";
  return (
    <div className={`rounded-lg p-3 ${style}`}>
      <strong className="flex items-center gap-1.5 text-xs">
        <Icon className="h-4 w-4" /> {title}
      </strong>
      <ul className="mt-1 space-y-1 text-xs">
        {items.slice(0, 3).map((item) => <li key={item}>{item}</li>)}
      </ul>
    </div>
  );
}

function StopEditor({
  stops,
  agents,
  onChange,
  dragged,
  setDragged,
  onDrop,
  move,
}: {
  stops: Stop[];
  agents: Meta["agents"];
  onChange: (stops: Stop[]) => void;
  dragged: string | null;
  setDragged: (id: string | null) => void;
  onDrop: (id: string) => void;
  move?: (index: number, direction: -1 | 1) => void;
}) {
  return (
    <div>
      <div className="mb-2">
        <h3 className="font-semibold text-slate-900">Manual stop order</h3>
        <p className="text-xs text-slate-500">
          Drag stops or use the arrow controls. Sequence numbers update
          automatically.
        </p>
      </div>
      <div className="space-y-2">
        {stops.map((stop, index) => (
          <div
            key={stop.stop_id}
            draggable
            onDragStart={() => setDragged(stop.stop_id)}
            onDragOver={(event) => event.preventDefault()}
            onDrop={() => onDrop(stop.stop_id)}
            className={`grid gap-3 rounded-xl border bg-white p-3 md:grid-cols-[32px_1fr_180px_130px_90px] ${dragged === stop.stop_id ? "opacity-50" : ""}`}
          >
            <div className="flex items-center gap-1">
              <GripVertical className="h-4 w-4 text-slate-400" />
              <strong className="text-sm">{index + 1}</strong>
            </div>
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <p className="font-medium text-slate-900">{stop.customer_name}</p>
                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
                  {stop.status.replaceAll("_", " ")}
                </span>
              </div>
              <p className="text-xs text-slate-500">
                {stop.address}
                {stop.landmark ? ` · ${stop.landmark}` : ""}
              </p>
              <p className="mt-1 text-xs text-slate-600">
                {stop.products
                  ?.map((line) => `${line.product_name} × ${quantity(line)}`)
                  .join(", ")}
              </p>
              {(stop.latitude == null || stop.longitude == null) && (
                <p className="mt-1 text-xs text-amber-700">
                  GPS unavailable — use the address and landmark.
                </p>
              )}
              {stop.products
                ?.filter((line) => (line.status || line.delivery_status) === "CLOSED_PRODUCT")
                .map((line) => (
                  <p key={line.line_id || line.product_name} className="mt-1 rounded bg-red-50 p-2 text-xs font-medium text-red-700">
                    {line.product_name}: closed product — read only, do not issue or deliver.
                  </p>
                ))}
            </div>
            <select
              aria-label={`Agent for ${stop.customer_name}`}
              className={fieldClass}
              value={stop.agent_id || ""}
              onChange={(e) =>
                onChange(
                  stops.map((item) =>
                    item.stop_id === stop.stop_id
                      ? { ...item, agent_id: e.target.value }
                      : item,
                  ),
                )
              }
            >
              <option value="">Responsible agent</option>
              {agents.map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.name}
                </option>
              ))}
            </select>
            <input
              aria-label={`Arrival time for ${stop.customer_name}`}
              type="time"
              className={fieldClass}
              value={stop.expected_arrival_time || ""}
              onChange={(e) =>
                onChange(
                  stops.map((item) =>
                    item.stop_id === stop.stop_id
                      ? { ...item, expected_arrival_time: e.target.value }
                      : item,
                  ),
                )
              }
            />
            <div className="flex justify-end gap-1">
              <button
                type="button"
                aria-label="Move stop up"
                onClick={() =>
                  move
                    ? move(index, -1)
                    : index > 0 &&
                      onChange(reorderLocal(stops, index, index - 1))
                }
                className="min-h-11 min-w-11 rounded border p-2 disabled:opacity-30"
                disabled={index === 0}
              >
                <ChevronUp className="h-4 w-4" />
              </button>
              <button
                type="button"
                aria-label="Move stop down"
                onClick={() =>
                  move
                    ? move(index, 1)
                    : index < stops.length - 1 &&
                      onChange(reorderLocal(stops, index, index + 1))
                }
                className="min-h-11 min-w-11 rounded border p-2 disabled:opacity-30"
                disabled={index === stops.length - 1}
              >
                <ChevronDown className="h-4 w-4" />
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
function reorderLocal(stops: Stop[], from: number, to: number) {
  const next = [...stops];
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item);
  return next.map((stop, index) => ({ ...stop, sequence_number: index + 1 }));
}

function ExecutionPanel({
  run,
  userId,
  busyAction,
  canIssue,
  canAccept,
  canCustody,
  canStart,
  canUpdateStops,
  canComplete,
  action,
}: {
  run: Run;
  userId?: string;
  busyAction: string;
  canIssue: boolean;
  canAccept: boolean;
  canCustody: boolean;
  canStart: boolean;
  canUpdateStops: boolean;
  canComplete: boolean;
  action: (
    path: string,
    body?: Record<string, unknown>,
    success?: string,
  ) => Promise<void>;
}) {
  const [delivered, setDelivered] = useState<Record<string, number>>({});
  const [outcome, setOutcome] = useState("COMPLETED");
  const [reason, setReason] = useState("");
  const [recipientName, setRecipientName] = useState("");
  const isDriver = run.driver_id === userId;
  const isExecutor = isDriver || ((run.transport_method || "VEHICLE") !== "VEHICLE" && Boolean(run.assigned_agent_ids?.includes(userId || "")));
  const isBusy = (key: string) => busyAction === key;
  const terminal = ["COMPLETED", "PARTIAL", "PARTIALLY_COMPLETED", "FAILED", "SKIPPED"];
  const nextStop = [...run.stops]
    .sort((a, b) => a.sequence_number - b.sequence_number)
    .find((stop) => !terminal.includes(stop.status));
  const allFinished = run.stops.every((stop) => terminal.includes(stop.status));
  const readyLines =
    nextStop?.products?.filter(
      (line) =>
        (line.status || line.delivery_status || "READY_FOR_DELIVERY") !==
        "CLOSED_PRODUCT",
    ) || [];
  const closedLines =
    nextStop?.products?.filter(
      (line) => (line.status || line.delivery_status) === "CLOSED_PRODUCT",
    ) || [];

  if (
    !canIssue &&
    !canComplete &&
    !(isExecutor && (canAccept || canCustody || canStart || canUpdateStops))
  )
    return null;

  const submitOutcome = () => {
    if (!nextStop) return;
    const items = readyLines.map((line) => {
      const issued = Number(line.quantity_issued || 0);
      const deliveredQuantity = Math.min(
        Math.max(Number(delivered[line.line_id || ""] ?? issued), 0),
        issued,
      );
      return {
        line_id: line.line_id,
        quantity_delivered: deliveredQuantity,
        quantity_undelivered: issued - deliveredQuantity,
        reason: deliveredQuantity < issued ? reason : undefined,
      };
    });
    void action(
      `stops/${nextStop.stop_id}`,
      { action: "OUTCOME", outcome, items, reason, notes: reason, recipient_name: recipientName || undefined },
      "Stop outcome recorded. The next stop is ready.",
    );
  };

  return (
    <section className="space-y-3 rounded-xl border border-blue-200 bg-blue-50 p-4">
      <div>
        <h3 className="font-semibold text-slate-900">Execution controls</h3>
        <p className="text-xs text-slate-600">
          Assignment, custody, and route actions are recorded in the audit trail.
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        {isExecutor && canAccept && ["PUBLISHED", "LOCKED"].includes(run.status) && (
          <button disabled={isBusy("accept")} onClick={() => void action("accept", undefined, "Run assignment accepted.")} className="flex min-h-11 items-center justify-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-50">
            {isBusy("accept") && <Loader2 className="h-4 w-4 animate-spin" />} {isBusy("accept") ? "Accepting…" : "Accept assignment"}
          </button>
        )}
        {canIssue && run.status === "ACCEPTED" && (
          <button disabled={isBusy("issue")} onClick={() => void action("issue", {}, "Ready products issued to the driver.")} className="flex min-h-11 items-center justify-center gap-2 rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-50">
            {isBusy("issue") && <Loader2 className="h-4 w-4 animate-spin" />} {isBusy("issue") ? "Issuing…" : "Issue ready items"}
          </button>
        )}
        {isExecutor && canCustody && run.status === "ITEMS_ISSUED" && run.custody_status !== "ACCEPTED" && (
          <>
            <button disabled={isBusy("custody")} onClick={() => void action("custody", { decision: "ACCEPT" }, "Issued-item custody accepted.")} className="flex min-h-11 items-center justify-center gap-2 rounded-lg bg-emerald-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-50">
              {isBusy("custody") && <Loader2 className="h-4 w-4 animate-spin" />} {isBusy("custody") ? "Acknowledging…" : "Accept custody"}
            </button>
            <input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Discrepancy details" className={`${fieldClass} max-w-xs`} />
            <button disabled={isBusy("custody") || !reason.trim()} onClick={() => void action("custody", { decision: "DISPUTE", reason }, "Custody discrepancy submitted.")} className="min-h-11 rounded-lg border border-red-300 bg-white px-3 py-2 text-sm font-medium text-red-700 disabled:opacity-40">
              Report discrepancy
            </button>
          </>
        )}
        {isExecutor && canStart && run.status === "ITEMS_ISSUED" && run.custody_status === "ACCEPTED" && (
          <button disabled={isBusy("start")} onClick={() => void action("start", {}, "Delivery route started.")} className="flex min-h-11 items-center justify-center gap-2 rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-50">
            {isBusy("start") && <Loader2 className="h-4 w-4 animate-spin" />} {isBusy("start") ? "Starting…" : "Start route"}
          </button>
        )}
      </div>
      {isExecutor && canUpdateStops && run.status === "IN_PROGRESS" && nextStop && (
        <div className="space-y-3 rounded-lg bg-white p-3">
          <div>
            <span className="text-xs font-semibold text-blue-700">NEXT · STOP {nextStop.sequence_number}</span>
            <h4 className="font-semibold text-slate-900">{nextStop.customer_name}</h4>
            <p className="text-sm text-slate-600">{nextStop.address}</p>
          </div>
          {closedLines.map((line) => (
            <div key={line.line_id || line.product_name} className="rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-800">
              <strong>{line.product_name}: CLOSED PRODUCT — DO NOT LOAD OR DELIVER</strong>
              <p>This closed product is visible for reference and has no delivery action.</p>
            </div>
          ))}
          {nextStop.status === "PENDING" && (
            <button disabled={isBusy("arrive")} onClick={() => void action(`stops/${nextStop.stop_id}`, { action: "ARRIVE" }, "Arrival recorded.")} className="flex min-h-11 items-center justify-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm text-white disabled:opacity-50">{isBusy("arrive") && <Loader2 className="h-4 w-4 animate-spin" />} {isBusy("arrive") ? "Recording arrival…" : "Mark arrived"}</button>
          )}
          {nextStop.status === "ARRIVED" && (
            <button disabled={isBusy("start_service")} onClick={() => void action(`stops/${nextStop.stop_id}`, { action: "START_SERVICE" }, "Service started.")} className="flex min-h-11 items-center justify-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm text-white disabled:opacity-50">{isBusy("start_service") && <Loader2 className="h-4 w-4 animate-spin" />} {isBusy("start_service") ? "Starting service…" : "Start service"}</button>
          )}
          {["ARRIVED", "IN_SERVICE"].includes(nextStop.status) && (
            <div className="space-y-3">
              {readyLines.map((line) => {
                const issued = Number(line.quantity_issued || 0);
                return (
                  <label key={line.line_id || line.product_name} className="grid items-center gap-2 text-sm sm:grid-cols-[1fr_120px]">
                    <span><strong>{line.product_name}</strong> · issued {issued}</span>
                    <input type="number" min={0} max={issued} value={delivered[line.line_id || ""] ?? issued} onChange={(event) => setDelivered({ ...delivered, [line.line_id || ""]: Number(event.target.value) })} className={fieldClass} aria-label={`Delivered quantity for ${line.product_name}`} />
                  </label>
                );
              })}
              <div className="grid gap-2 sm:grid-cols-3">
                <select value={outcome} onChange={(event) => setOutcome(event.target.value)} className={fieldClass}>
                  <option value="COMPLETED">Completed</option>
                  <option value="PARTIAL">Partially completed</option>
                  <option value="FAILED">Failed</option>
                  <option value="SKIPPED">Skipped</option>
                </select>
                <input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Exception or outcome notes" className={fieldClass} />
                <input value={recipientName} onChange={(event) => setRecipientName(event.target.value)} placeholder="Recipient name" className={fieldClass} />
              </div>
              <button disabled={isBusy("outcome")} onClick={submitOutcome} className="flex min-h-11 items-center justify-center gap-2 rounded-lg bg-emerald-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-50">{isBusy("outcome") && <Loader2 className="h-4 w-4 animate-spin" />} {isBusy("outcome") ? "Recording outcome…" : "Record outcome & continue"}</button>
            </div>
          )}
        </div>
      )}
      {isExecutor && canComplete && run.status === "IN_PROGRESS" && allFinished && (
        <button disabled={isBusy("complete-execution")} onClick={() => void action("complete-execution", undefined, "Route execution completed and frozen for return handoff.")} className="flex min-h-11 items-center justify-center gap-2 rounded-lg bg-emerald-700 px-3 py-2 text-sm font-medium text-white disabled:opacity-50">
          {isBusy("complete-execution") && <Loader2 className="h-4 w-4 animate-spin" />} {isBusy("complete-execution") ? "Confirming completion…" : "Complete route execution"}
        </button>
      )}
      {run.status === "EXECUTION_COMPLETED" && canComplete && (
        <button disabled={isBusy("return-handoff")} onClick={() => void action("return-handoff", undefined, "Execution confirmed and handed off to Returns & Reconciliation.")} className="flex min-h-11 items-center justify-center gap-2 rounded-lg bg-blue-700 px-3 py-2 text-sm font-medium text-white disabled:opacity-50">
          {isBusy("return-handoff") && <Loader2 className="h-4 w-4 animate-spin" />} {isBusy("return-handoff") ? "Confirming…" : "Confirm completion"}
        </button>
      )}
    </section>
  );
}

function AssignedStops({ run, userId }: { run: Run; userId?: string }) {
  const isAgent =
    run.assigned_agent_ids?.includes(userId || "") && run.driver_id !== userId;
  const stops = isAgent
    ? run.stops.filter((stop) => stop.agent_id === userId)
    : run.stops;
  return (
    <div className="space-y-3">
      <div className="rounded-lg bg-slate-50 p-3 text-sm text-slate-700"><strong>{(run.transport_method || "VEHICLE").replaceAll("_", " ")}</strong> · {(run.transport_method || "VEHICLE") === "VEHICLE" ? `${run.driver?.name || "Driver pending"} · ${run.vehicle?.name || "Vehicle pending"}` : `${run.manual_transport?.provider_name || run.manual_transport?.handler_name || "Handler pending"} · ${run.manual_transport?.phone || run.manual_transport?.handler_phone || "Phone pending"}`}</div>
      <h3 className="font-semibold text-slate-900">
        {isAgent ? "Your customer stops" : "Ordered stops"}
      </h3>
      {stops.map((stop, index) => (
        <div
          key={stop.stop_id}
          className={`rounded-xl border p-4 ${index === 0 ? "border-blue-300 bg-blue-50" : "bg-white"}`}
        >
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <span className="text-xs font-semibold text-blue-700">
                Stop {stop.sequence_number}
                {index === 0 ? " · NEXT" : ""}
              </span>
              <h4 className="font-semibold text-slate-900">
                {stop.customer_name}
              </h4>
              {stop.phone && <a href={`tel:${stop.phone}`} className="text-sm font-medium text-blue-700">Call customer · {stop.phone}</a>}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-full bg-slate-100 px-2 py-1 text-xs font-medium text-slate-700">
                {stop.status.replaceAll("_", " ")}
              </span>
              <span className="text-sm font-medium text-slate-600">
                {stop.expected_arrival_time || "Time pending"}
              </span>
            </div>
          </div>
          <p className="mt-2 text-sm text-slate-600">
            {stop.address}
            {stop.landmark ? ` · ${stop.landmark}` : ""}
          </p>
          {stop.latitude != null && stop.longitude != null && (
            <a
              href={`https://www.google.com/maps?q=${stop.latitude},${stop.longitude}`}
              target="_blank"
              rel="noreferrer"
              className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-blue-700"
            >
              <MapPin className="h-4 w-4" />
              Open navigation
            </a>
          )}
          {(stop.latitude == null || stop.longitude == null) && (
            <p className="mt-2 rounded-lg bg-amber-50 p-2 text-xs text-amber-800">
              GPS unavailable — continue using the address and landmark.
            </p>
          )}
          <div className="mt-3 space-y-1">
            {stop.products?.map((line) => (
              <div
                key={line.line_id || line.product_name}
                className="rounded-lg bg-white/80 p-2 text-sm"
              >
                <strong>{line.product_name}</strong> × {quantity(line)}
                {(line.status || line.delivery_status) === "CLOSED_PRODUCT" && (
                  <p className="text-xs font-medium text-red-700">
                    Closed product — read only, do not issue or deliver.
                  </p>
                )}
                {line.delivery_type === "CLOSED_CONTRIBUTION_CONVERSION" && (
                  <p className="text-xs text-amber-700">
                    Approved replacement for {line.original_product_name}
                  </p>
                )}
              </div>
            ))}
          </div>
          {stop.agent?.name && (
            <p className="mt-2 text-xs text-slate-500">Responsible agent: {stop.agent.phone ? <a href={`tel:${stop.agent.phone}`} className="font-medium text-blue-700">{stop.agent.name} · call</a> : stop.agent.name}</p>
          )}
          {!stop.agent?.name && (
            <p className="mt-2 text-xs text-slate-500">
              Responsible agent: {run.agents?.find((agent) => agent.id === stop.agent_id)?.name || "Unassigned"}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}

function AccountabilityPanel({
  batches,
  userId,
  canReceive,
  canExceptions,
  canInvestigate,
  canReconcile,
  canClose,
  canReopen,
  focusId,
  refresh,
}: {
  batches: AccountabilityBatch[];
  userId?: string;
  canReceive: boolean;
  canExceptions: boolean;
  canInvestigate: boolean;
  canReconcile: boolean;
  canClose: boolean;
  canReopen: boolean;
  focusId: string;
  refresh: () => Promise<void>;
}) {
  const [selectedId, setSelectedId] = useState(focusId);
  const [busyAction, setBusyAction] = useState("");
  const mutationLock = useRef(false);
  const [feedback, setFeedback] = useState<ActionFeedback>(null);
  const [returnValues, setReturnValues] = useState<Record<string, { quantity: number; condition: string; reason: string }>>({});
  const [caseForm, setCaseForm] = useState({ category: "MISSING_ITEM", severity: "MEDIUM", description: "", responsible_department: "OPERATIONS", quantity: 0, notes: "", lineKey: "" });
  const [exceptions, setExceptions] = useState<any[]>([]);
  const [approved, setApproved] = useState<Record<string, number>>({});
  const [investigation, setInvestigation] = useState({ findings: "", resolution: "", corrective_action: "", approved_exception_quantity: 0, notes: "" });
  const [reason, setReason] = useState("");
  const selected = batches.find((item) => item.id === selectedId) || batches[0];
  useEffect(() => {
    if (focusId) setSelectedId(focusId);
  }, [focusId]);

  const loadExceptions = async (batchId: string) => {
    if (!canExceptions) return;
    const response = await apiRequest<any>(`/smart-living-deliveries/exceptions?batch_id=${batchId}&page_size=100`);
    setExceptions(response.data.exceptions || []);
  };
  useEffect(() => {
    if (selected?.id) void loadExceptions(selected.id);
  }, [selected?.id]);

  const mutate = async (
    path: string,
    method = "POST",
    body?: Record<string, unknown>,
    success = "Accountability record updated.",
    actionKey = path,
  ) => {
    if (mutationLock.current) return;
    mutationLock.current = true;
    setBusyAction(actionKey);
    setFeedback(null);
    try {
      await apiRequest(`/smart-living-deliveries/${path}`, {
        method,
        body: body ? JSON.stringify(body) : undefined,
        headers:
          method === "POST" && (path.includes("/exceptions") || path.includes("/returns/receive"))
            ? { "Idempotency-Key": crypto.randomUUID() }
            : undefined,
      });
      setFeedback({ tone: "success", text: success });
      toast.success(success);
      await refresh();
      if (selected?.id) await loadExceptions(selected.id);
      if (actionKey === "receive_return") setReturnValues({});
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unable to update this batch.";
      setFeedback({ tone: "error", text: message });
      toast.error(message);
    } finally {
      mutationLock.current = false;
      setBusyAction("");
    }
  };

  if (!selected) return <Empty text="No completed delivery batches are awaiting accountability work." />;
  const lines = selected.reconciliation?.lines || [];
  const lineOptions = lines.map((line) => ({ ...line, key: `${line.delivery_order_id}:${line.line_id}` }));

  const receive = () => {
    const items = lineOptions.filter((line) => line.outstanding_difference > 0).map((line) => {
      const outstanding = Math.max(line.outstanding_difference, 0);
      const value = returnValues[line.key] || { quantity: outstanding, condition: "GOOD", reason: "" };
      return { delivery_order_id: line.delivery_order_id, line_id: line.line_id, returned_quantity: value.quantity, condition: value.condition, return_reason: value.reason };
    });
    const total = items.reduce((sum, item) => sum + Number(item.returned_quantity || 0), 0);
    void mutate(`scheduler/runs/${selected.id}/returns/receive`, "POST", { items }, `${total} returned item(s) received and audited.`, "receive_return");
  };
  const createCase = () => {
    const line = lineOptions.find((item) => item.key === caseForm.lineKey);
    void mutate(`scheduler/runs/${selected.id}/exceptions`, "POST", { ...caseForm, delivery_order_id: line?.delivery_order_id, line_id: line?.line_id }, "Delivery exception opened.", "open_exception");
  };
  const damagedReturns = selected.return?.receiving_events?.reduce((total, event) => total + (event.items || []).reduce((subtotal, item) => subtotal + (item.condition && item.condition !== "GOOD" ? Number(item.received_quantity || 0) : 0), 0), 0) || 0;
  const exceptionCount = Object.values(selected.exception_summary || {}).reduce((total, count) => total + Number(count || 0), 0);
  const outstandingReturnLines = lineOptions.filter((line) => line.outstanding_difference > 0);

  return (
    <section className="space-y-4">
      <div className="grid gap-3 lg:grid-cols-[280px_1fr]">
        <aside className="space-y-2">
          {batches.map((batch) => (
            <button key={batch.id} onClick={() => setSelectedId(batch.id)} className={`w-full rounded-xl border p-3 text-left ${selected.id === batch.id ? "border-blue-500 bg-blue-50" : "bg-white"}`}>
              <strong className="block text-sm text-slate-900">{runName(batch)}</strong>
              <span className="text-xs text-slate-500">{batch.status.replaceAll("_", " ")} · {batch.delivery_date}</span>
              <span className={`mt-2 block text-xs font-medium ${batch.reconciliation?.balanced ? "text-emerald-700" : "text-red-700"}`}>Outstanding: {batch.reconciliation?.outstanding_difference ?? 0}</span>
            </button>
          ))}
        </aside>
        <div className="space-y-4">
          {feedback && (
            <div role={feedback.tone === "error" ? "alert" : "status"} className={`flex items-start gap-2 rounded-lg p-3 text-sm ${feedback.tone === "error" ? "bg-red-50 text-red-800" : "bg-emerald-50 text-emerald-800"}`}>
              {feedback.tone === "error" ? <XCircle className="mt-0.5 h-4 w-4 shrink-0" /> : <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />}
              {feedback.text}
            </div>
          )}
          <article className="rounded-xl border bg-white p-4">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div><h2 className="font-semibold text-slate-900">{runName(selected)}</h2><p className="text-sm text-slate-500">Driver {selected.driver?.name || "Unassigned"} · Vehicle {selected.vehicle?.name || "Unassigned"}</p></div>
              <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium">{selected.status.replaceAll("_", " ")}</span>
            </div>
            <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
              {[
                ['Expected return', Math.max((selected.reconciliation?.issued || 0) - (selected.reconciliation?.delivered || 0), 0)],
                ['Received', selected.reconciliation?.returned],
                ['Outstanding', selected.reconciliation?.outstanding_difference],
                ['Damaged', damagedReturns],
                ['Exceptions', exceptionCount],
              ].map(([label, value]) => <div key={String(label)} className="rounded-lg bg-slate-50 p-3"><span className="block text-xs text-slate-500">{label}</span><strong>{value ?? 0}</strong></div>)}
            </div>
          </article>

          <article className="space-y-3 rounded-xl border bg-white p-4">
            <div><h3 className="font-semibold">Product-line reconciliation</h3><p className="text-xs text-slate-500">Values come from issue, delivery outcome, return receipts, and approved exceptions.</p></div>
            {lineOptions.map((line) => <div key={`reconciliation:${line.key}`} className="rounded-lg border p-3">
              <div className="flex flex-wrap items-start justify-between gap-2"><div><strong className="text-sm">{line.customer_name}</strong><p className="text-sm text-slate-700">{line.product_name}</p></div><span className={`rounded-full px-2 py-1 text-[11px] font-medium ${line.reconciliation_status === "RECONCILED" || line.reconciliation_status === "BALANCED" ? "bg-emerald-100 text-emerald-700" : line.reconciliation_status === "EXCEPTION_PENDING" ? "bg-amber-100 text-amber-800" : "bg-red-100 text-red-700"}`}>{(line.reconciliation_status || "MISMATCH").replaceAll("_", " ")}</span></div>
              <div className="mt-2 grid grid-cols-3 gap-2 text-xs sm:grid-cols-5">{[["Issued", line.issued_quantity], ["Delivered", line.delivered_quantity], ["Returned", line.returned_quantity], ["Approved exception", line.approved_exception_quantity], ["Difference", line.outstanding_difference]].map(([label, value]) => <div key={String(label)}><span className="block text-slate-500">{label}</span><strong className={label === "Difference" && Number(value) !== 0 ? "text-red-700" : "text-slate-800"}>{value}</strong></div>)}</div>
            </div>)}
          </article>

          {canReceive && selected.status !== "CLOSED" && outstandingReturnLines.length > 0 && (
            <article className="space-y-3 rounded-xl border bg-white p-4">
              <div><h3 className="font-semibold">Return Receiving</h3><p className="text-xs text-slate-500">Receive all or part of each outstanding product line. Partial receipts remain available for the next handoff.</p></div>
              {outstandingReturnLines.map((line) => {
                const expected = Math.max(line.issued_quantity - line.delivered_quantity, 0); const outstanding = Math.max(line.outstanding_difference, 0); const value = returnValues[line.key] || { quantity: outstanding, condition: "GOOD", reason: "" };
                return <div key={line.key} className="grid gap-2 rounded-lg border p-3 md:grid-cols-[1fr_90px_170px_1fr]">
                  <div><strong className="text-sm">{line.customer_name} · {line.product_name}</strong><p className="text-xs text-slate-500">Issued {line.issued_quantity} · Delivered {line.delivered_quantity} · Expected {expected} · Previously received {line.returned_quantity} · Outstanding {outstanding}</p></div>
                  <input aria-label={`Returned ${line.product_name}`} type="number" min={0} max={outstanding} className={fieldClass} value={value.quantity} onChange={(event) => setReturnValues({ ...returnValues, [line.key]: { ...value, quantity: Number(event.target.value) } })} />
                  <select className={fieldClass} value={value.condition} onChange={(event) => setReturnValues({ ...returnValues, [line.key]: { ...value, condition: event.target.value } })}>{["GOOD", "DAMAGED", "PACKAGING_DAMAGED", "WRONG_ITEM", "MISSING_PARTS", "DESTROYED"].map((item) => <option key={item}>{item.replaceAll("_", " ")}</option>)}</select>
                  <input className={fieldClass} placeholder="Return or variance reason" value={value.reason} onChange={(event) => setReturnValues({ ...returnValues, [line.key]: { ...value, reason: event.target.value } })} />
                </div>;
              })}
              <button disabled={busyAction === "receive_return"} onClick={receive} className="flex min-h-11 items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">{busyAction === "receive_return" && <Loader2 className="h-4 w-4 animate-spin" />} {busyAction === "receive_return" ? "Receiving returns…" : "Receive returns"}</button>
            </article>
          )}

          {canExceptions && selected.status !== "CLOSED" && (
            <article className="space-y-3 rounded-xl border bg-white p-4">
              <h3 className="font-semibold">Exceptions & Investigations</h3>
              <div className="grid gap-2 md:grid-cols-2 lg:grid-cols-6">
                <select className={fieldClass} value={caseForm.category} onChange={(event) => setCaseForm({ ...caseForm, category: event.target.value })}>{["CUSTOMER_UNAVAILABLE", "CUSTOMER_REFUSED", "WRONG_ADDRESS", "WRONG_PHONE", "PRODUCT_DAMAGED", "VEHICLE_BREAKDOWN", "SAFETY", "THEFT", "MISSING_ITEM", "OTHER"].map((item) => <option key={item}>{item}</option>)}</select>
                <select className={fieldClass} value={caseForm.severity} onChange={(event) => setCaseForm({ ...caseForm, severity: event.target.value })}>{["LOW", "MEDIUM", "HIGH", "CRITICAL"].map((item) => <option key={item}>{item}</option>)}</select>
                <select className={fieldClass} value={caseForm.lineKey} onChange={(event) => setCaseForm({ ...caseForm, lineKey: event.target.value })}><option value="">Batch-level exception</option>{lineOptions.map((line) => <option key={line.key} value={line.key}>{line.customer_name} · {line.product_name}</option>)}</select>
                <input type="number" min={0} className={fieldClass} aria-label="Exception quantity" placeholder="Quantity" value={caseForm.quantity} onChange={(event) => setCaseForm({ ...caseForm, quantity: Number(event.target.value) })} />
                <input className={`${fieldClass} lg:col-span-2`} placeholder="Describe the exception" value={caseForm.description} onChange={(event) => setCaseForm({ ...caseForm, description: event.target.value })} />
              </div>
              <button disabled={busyAction === "open_exception" || !caseForm.description.trim()} onClick={createCase} className="flex min-h-11 items-center justify-center gap-2 rounded-lg border border-red-300 px-4 py-2 text-sm font-medium text-red-700 disabled:opacity-50">{busyAction === "open_exception" && <Loader2 className="h-4 w-4 animate-spin" />} {busyAction === "open_exception" ? "Opening exception…" : "Open exception"}</button>
              {exceptions.map((item) => <div key={item.id} className="space-y-2 rounded-lg border p-3">
                <div className="flex flex-wrap justify-between"><strong>{item.exception_number} · {item.category}</strong><span className="text-xs">{item.severity} · {item.status}</span></div><p className="text-sm text-slate-600">{item.description}</p>
                <div className="flex flex-wrap gap-2">
                  {item.status === "OPEN" && <button disabled={busyAction === `review:${item.id}`} onClick={() => void mutate(`exceptions/${item.id}`, "PATCH", { status: "UNDER_REVIEW", note: "Review started" }, "Exception review started.", `review:${item.id}`)} className="flex min-h-11 items-center justify-center gap-2 rounded border px-3 py-1.5 text-xs disabled:opacity-50">{busyAction === `review:${item.id}` && <Loader2 className="h-4 w-4 animate-spin" />} {busyAction === `review:${item.id}` ? "Starting review…" : "Start review"}</button>}
                  {item.status === "UNDER_REVIEW" && <><input type="number" min={0} className={`${fieldClass} max-w-32`} placeholder="Approved loss" value={approved[item.id] ?? item.approved_exception_quantity ?? 0} onChange={(event) => setApproved({ ...approved, [item.id]: Number(event.target.value) })} /><button disabled={busyAction === `resolve:${item.id}`} onClick={() => void mutate(`exceptions/${item.id}`, "PATCH", { status: "RESOLVED", resolution: "Approved after review", approved_exception_quantity: approved[item.id] ?? item.approved_exception_quantity ?? 0 }, "Exception resolved and approved quantity recorded.", `resolve:${item.id}`)} className="min-h-11 rounded border px-3 py-1.5 text-xs disabled:opacity-50">{busyAction === `resolve:${item.id}` ? "Resolving…" : "Resolve"}</button></>}
                </div>
                {canInvestigate && item.requires_investigation && item.status === "UNDER_REVIEW" && <div className="grid gap-2 md:grid-cols-3"><input className={fieldClass} placeholder="Findings" value={investigation.findings} onChange={(event) => setInvestigation({ ...investigation, findings: event.target.value })} /><input className={fieldClass} placeholder="Resolution" value={investigation.resolution} onChange={(event) => setInvestigation({ ...investigation, resolution: event.target.value })} /><input className={fieldClass} placeholder="Corrective action" value={investigation.corrective_action} onChange={(event) => setInvestigation({ ...investigation, corrective_action: event.target.value })} /><input type="number" min={0} className={fieldClass} placeholder="Approved quantity" value={investigation.approved_exception_quantity} onChange={(event) => setInvestigation({ ...investigation, approved_exception_quantity: Number(event.target.value) })} /><input className={fieldClass} placeholder="Investigation notes" value={investigation.notes} onChange={(event) => setInvestigation({ ...investigation, notes: event.target.value })} /><button disabled={busyAction === `investigate:${item.id}` || !investigation.findings || !investigation.resolution || !investigation.corrective_action} onClick={() => void mutate(`exceptions/${item.id}/investigation`, "PUT", { assigned_investigator_id: userId, status: "CLOSED", ...investigation }, "Investigation completed.", `investigate:${item.id}`)} className="flex min-h-11 items-center justify-center gap-2 rounded bg-slate-900 px-3 py-2 text-xs text-white disabled:opacity-50">{busyAction === `investigate:${item.id}` && <Loader2 className="h-4 w-4 animate-spin" />} {busyAction === `investigate:${item.id}` ? "Completing…" : "Complete investigation"}</button></div>}
              </div>)}
            </article>
          )}

          <article className="space-y-3 rounded-xl border bg-white p-4">
            <h3 className="font-semibold">Reconciliation & Closure</h3>
            <input className={fieldClass} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Audit, closure, or reopening note" />
            <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
              {canReconcile && !["RECONCILED", "CLOSED"].includes(selected.status) && <button disabled={busyAction === "reconcile" || !selected.reconciliation?.balanced} onClick={() => void mutate(`scheduler/runs/${selected.id}/reconcile`, "POST", { note: reason }, "Batch reconciled successfully.", "reconcile")} className="flex min-h-11 items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white disabled:opacity-40">{busyAction === "reconcile" && <Loader2 className="h-4 w-4 animate-spin" />} {busyAction === "reconcile" ? "Reconciling…" : "Reconcile batch"}</button>}
              {canClose && selected.status === "RECONCILED" && <button disabled={busyAction === "close"} onClick={() => void mutate(`scheduler/runs/${selected.id}/close`, "POST", { note: reason }, "Batch closed and records locked.", "close")} className="flex min-h-11 items-center justify-center gap-2 rounded-lg bg-emerald-700 px-4 py-2 text-sm text-white disabled:opacity-50">{busyAction === "close" && <Loader2 className="h-4 w-4 animate-spin" />} {busyAction === "close" ? "Closing…" : "Close batch"}</button>}
              {canReopen && selected.status === "CLOSED" && <button disabled={busyAction === "reopen" || !reason.trim()} onClick={() => void mutate(`scheduler/runs/${selected.id}/reopen`, "POST", { reason }, "Batch reopened with audit reason.", "reopen")} className="flex min-h-11 items-center justify-center gap-2 rounded-lg border border-amber-400 px-4 py-2 text-sm text-amber-800 disabled:opacity-40">{busyAction === "reopen" && <Loader2 className="h-4 w-4 animate-spin" />} {busyAction === "reopen" ? "Reopening…" : "Authorized reopen"}</button>}
            </div>
            {!selected.reconciliation?.balanced && <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">Mismatch detected: {selected.reconciliation?.outstanding_difference}. Resolve returns or approved exceptions before reconciliation.</p>}
          </article>
        </div>
      </div>
    </section>
  );
}

function LoadingSchedule({
  runs,
  onOpen,
}: {
  runs: Run[];
  onOpen: (run: Run) => void;
}) {
  return (
    <section className="space-y-4">
      <div className="md:hidden">
        <RunCards runs={runs} onOpen={onOpen} />
      </div>
      <div className="hidden overflow-x-auto rounded-xl border bg-white md:block">
        <table className="w-full min-w-[850px] text-left text-sm">
          <thead className="bg-slate-50 text-xs uppercase text-slate-500">
            <tr>
              {[
                "Run",
                "Delivery date",
                "Driver",
                "Vehicle",
                "Customers",
                "Product totals",
                "Planned issue",
                "Status",
              ].map((item) => (
                <th key={item} className="p-3">
                  {item}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => {
              const lines =
                run.delivery_orders?.flatMap((order) => order.product_lines) ||
                [];
              return (
                <tr
                  key={run.id}
                  onClick={() => onOpen(run)}
                  className="cursor-pointer border-t hover:bg-slate-50"
                >
                  <td className="p-3 font-medium text-blue-700">
                    {runName(run)} · v{run.version || 1}
                  </td>
                  <td className="p-3">{run.delivery_date}</td>
                  <td className="p-3">{run.driver?.name || "—"}</td>
                  <td className="p-3">{run.vehicle?.name || "—"}</td>
                  <td className="p-3">{run.stops.length}</td>
                  <td className="p-3">
                    {lines.reduce((sum, line) => sum + quantity(line), 0)} units
                    <p className="max-w-72 truncate text-xs text-slate-500">
                      {lines
                        .map(
                          (line) => `${line.product_name} × ${quantity(line)}`,
                        )
                        .join(", ")}
                    </p>
                  </td>
                  <td className="p-3">
                    Before {run.planned_departure_time || "departure"}
                  </td>
                  <td className="p-3">
                    <span
                      className={`rounded-full px-2 py-1 text-xs ${statusTone(run.status)}`}
                    >
                      {run.status}
                    </span>
                  </td>
                </tr>
              );
            })}
            {!runs.length && (
              <tr>
                <td colSpan={8} className="p-10 text-center text-slate-500">
                  No published runs require loading preparation.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
