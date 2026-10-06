import { apiRequest } from './api';

export type OperationsAction =
  | 'open_record'
  | 'resolve'
  | 'recheck'
  | 'release_reservation'
  | 'force_close_movement'
  | 'release_assignment'
  | 'restart_movement'
  | 'reassign'
  | 'resolve_maintenance';

export type OperationsIssue = {
  id: string;
  kind: string;
  blocker_type: string;
  title: string;
  asset_type: 'vehicle' | 'driver';
  vehicle_id?: string | null;
  driver_id?: string | null;
  source_type?: string | null;
  source_id?: string | null;
  source_reference?: string | null;
  current_status?: string | null;
  movement_id?: string | null;
  reservation_id?: string | null;
  assignment_id?: string | null;
  blocker: string;
  preventing: string;
  recommended_action: string;
  allowed_actions: OperationsAction[];
  open_target?: { page: string; record_id?: string | null } | null;
  detail: Record<string, unknown>;
  vehicle_label?: string | null;
  driver_label?: string | null;
  task?: string | null;
  origin?: string | null;
  destination?: string | null;
  assigned_at?: string | null;
  scheduled_at?: string | null;
  movement_started_at?: string | null;
  movement_ended_at?: string | null;
  last_activity_at?: string | null;
  overdue_seconds?: number | null;
  unresolved_seconds?: number | null;
  asset_blocked?: boolean;
  recovery_required?: boolean;
  primary_action?: OperationsAction;
  timeline_available?: boolean;
};

export type OperationsAssetGroup = {
  asset_type: 'vehicle' | 'driver';
  asset_id: string;
  label: string;
  is_available: boolean;
  operational_state?: string | null;
  recovery_state: 'blocked' | 'recovery_required' | 'available_with_attention' | 'available';
  blockers: OperationsIssue[];
};

export type OperationsControl = {
  overview: { vehicles: Record<string, number>; drivers: Record<string, number> };
  issues: OperationsIssue[];
  groups: OperationsAssetGroup[];
  generated_at: string;
};

const knownActions = new Set<OperationsAction>([
  'open_record', 'resolve', 'recheck', 'release_reservation', 'force_close_movement',
  'release_assignment', 'restart_movement', 'reassign', 'resolve_maintenance',
]);

function record(value: unknown): Record<string, any> {
  return value && typeof value === 'object' ? value as Record<string, any> : {};
}

function normalizeIssue(value: unknown, modernResponse: boolean): OperationsIssue {
  const source = record(value);
  const detail = record(source.detail);
  const assetType: 'vehicle' | 'driver' = source.asset_type === 'driver' || (!source.vehicle_id && source.driver_id)
    ? 'driver'
    : 'vehicle';
  const legacyActionMap: Record<string, OperationsAction> = {
    view_blocking_record: 'open_record',
    retry_source: 'restart_movement',
  };
  const requestedActions = Array.isArray(source.allowed_actions) ? source.allowed_actions : [];
  const actions = requestedActions
    .map((action: unknown) => legacyActionMap[String(action)] || String(action))
    .filter((action: string): action is OperationsAction => knownActions.has(action as OperationsAction))
    .filter((action: OperationsAction) => modernResponse || action === 'open_record' || action === 'recheck');
  if (!actions.includes('recheck')) actions.push('recheck');
  return {
    id: String(source.id || `${assetType}:${source.vehicle_id || source.driver_id || source.source_id || Math.random()}`),
    kind: String(source.kind || detail.type || 'blocker'),
    blocker_type: String(source.blocker_type || detail.code || source.kind || 'operational_blocker'),
    title: String(source.title || 'Operational blocker'),
    asset_type: assetType,
    vehicle_id: source.vehicle_id || null,
    driver_id: source.driver_id || null,
    source_type: source.source_type || detail.source_type || detail.type || null,
    source_id: source.source_id || detail.source_id || detail.entity_id || null,
    source_reference: source.source_reference || detail.reference || source.source_id || detail.entity_id || null,
    current_status: source.current_status || detail.status || detail.movement_status || null,
    movement_id: source.movement_id || null,
    reservation_id: source.reservation_id || (detail.type === 'reservation' ? detail.entity_id : null),
    assignment_id: source.assignment_id || null,
    blocker: String(source.blocker || detail.message || 'Operational blocker'),
    preventing: String(source.preventing || 'New assignments and movement starts'),
    recommended_action: String(source.recommended_action || 'Open the owning workflow and resolve the blocker.'),
    allowed_actions: actions,
    open_target: source.open_target || null,
    detail,
    vehicle_label: source.vehicle_label || null,
    driver_label: source.driver_label || null,
    task: source.task || detail.task || null,
    origin: source.origin || detail.origin || null,
    destination: source.destination || detail.destination || null,
    assigned_at: source.assigned_at || null,
    scheduled_at: source.scheduled_at || null,
    movement_started_at: source.movement_started_at || null,
    movement_ended_at: source.movement_ended_at || null,
    last_activity_at: source.last_activity_at || null,
    overdue_seconds: typeof source.overdue_seconds === 'number' ? source.overdue_seconds : null,
    unresolved_seconds: typeof source.unresolved_seconds === 'number' ? source.unresolved_seconds : null,
    asset_blocked: Boolean(source.asset_blocked),
    recovery_required: Boolean(source.recovery_required),
    primary_action: knownActions.has(source.primary_action) ? source.primary_action : undefined,
    timeline_available: Boolean(source.timeline_available),
  };
}

export function normalizeOperationsControl(value: unknown): OperationsControl {
  const source = record(value);
  const modernResponse = Array.isArray(source.groups);
  const issues = (Array.isArray(source.issues) ? source.issues : []).map((issue: unknown) => normalizeIssue(issue, modernResponse));
  const vehicles = Array.isArray(source.vehicles) ? source.vehicles : [];
  const drivers = Array.isArray(source.drivers) ? source.drivers : [];
  const labels = new Map<string, string>([
    ...vehicles.map((item: unknown) => { const row = record(item); return [`vehicle:${row.id || row.vehicle_id}`, String(row.label || 'Vehicle')]; }),
    ...drivers.map((item: unknown) => { const row = record(item); return [`driver:${row.id || row.driver_id}`, String(row.label || 'Driver')]; }),
  ]);
  const fallbackGroups = new Map<string, OperationsAssetGroup>();
  for (const issue of issues) {
    const assetId = String(issue.asset_type === 'vehicle' ? issue.vehicle_id || '' : issue.driver_id || '');
    if (!assetId) continue;
    const key = `${issue.asset_type}:${assetId}`;
    const group = fallbackGroups.get(key) || {
      asset_type: issue.asset_type,
      asset_id: assetId,
      label: labels.get(key) || issue.title,
      is_available: false,
      operational_state: 'blocked',
      recovery_state: 'blocked',
      blockers: [],
    };
    group.blockers.push(issue);
    fallbackGroups.set(key, group);
  }
  const groups = modernResponse
    ? source.groups.map((value: unknown) => {
      const group = record(value);
      return {
        asset_type: group.asset_type === 'driver' ? 'driver' : 'vehicle',
        asset_id: String(group.asset_id || ''),
        label: String(group.label || 'Asset'),
        is_available: Boolean(group.is_available),
        operational_state: group.operational_state || null,
        recovery_state: ['blocked', 'recovery_required', 'available_with_attention', 'available'].includes(group.recovery_state) ? group.recovery_state : group.is_available ? 'available' : 'blocked',
        blockers: (Array.isArray(group.blockers) ? group.blockers : []).map((issue: unknown) => normalizeIssue(issue, true)),
      } as OperationsAssetGroup;
    })
    : [...fallbackGroups.values()];
  return {
    overview: {
      vehicles: record(record(source.overview).vehicles),
      drivers: record(record(source.overview).drivers),
    },
    issues,
    groups,
    generated_at: String(source.generated_at || new Date().toISOString()),
  };
}

export type OperationsTimeline = {
  records: Array<{ type: string; id: string; reference: string; status?: string | null }>;
  events: Array<{ record_type: string; record_id: string; event: string; status?: string | null; timestamp?: string | null; actor_id?: string | null; note?: string | null }>;
};

export async function fetchOperationsTimeline(issue: OperationsIssue) {
  const params = new URLSearchParams();
  if (issue.source_type) params.set('source_type', issue.source_type);
  if (issue.source_id) params.set('source_id', issue.source_id);
  if (issue.movement_id) params.set('movement_id', issue.movement_id);
  if (issue.reservation_id) params.set('reservation_id', issue.reservation_id);
  if (issue.assignment_id) params.set('assignment_id', issue.assignment_id);
  const response = await apiRequest<{ data: OperationsTimeline }>(`/operations-control/timeline?${params}`, {
    dedupeKey: `operations-control:timeline:${params}`,
    componentName: 'OperationsControlCenter', requestLabel: 'timeline', cacheTtlMs: 10_000,
  });
  return response.data;
}

export async function fetchOperationsControl() {
  const response = await apiRequest<{ data: unknown }>('/operations-control', {
    dedupeKey: 'GET:operations-control',
    cancelGroup: 'operations-control',
    replacePending: false,
    componentName: 'OperationsControlCenter',
    requestLabel: 'control-center-summary',
  });
  return normalizeOperationsControl(response.data);
}

export async function runOperationsControlAction(payload: Record<string, unknown>) {
  const response = await apiRequest<{ data: { action: string; affected_records?: Array<Record<string, unknown>> } }>('/operations-control/actions', {
    method: 'POST',
    body: JSON.stringify(payload),
    componentName: 'OperationsControlCenter',
    requestLabel: `recovery-${String(payload.action || 'action')}`,
  });
  return response.data;
}
