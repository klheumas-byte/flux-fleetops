import { apiRequest } from './api';

export type IntegrationMapping = {
  id: string;
  mapping_type: 'branch' | 'manager' | 'agent';
  external_id?: string | null;
  external_code?: string | null;
  external_display_name?: string | null;
  fleetops_id: string;
  active: boolean;
  updated_at?: string;
};

export type IntegrationException = {
  id: string;
  source_type: string;
  source_record_id: string;
  exception_type: string;
  message: string;
  status: string;
  attempt_count: number;
  created_at: string;
  retryable?: boolean;
  preview_only?: boolean;
};

type Envelope<T> = { data: T };

export type SmartLivingEndpointStatus = {
  endpoint: string;
  reachable: boolean;
  http_status: number | null;
  record_count: number | null;
  returned_count: number | null;
  json: boolean;
  sample_structure: Array<Record<string, unknown>>;
};

export type SmartLivingConnectionStatus = {
  configured: boolean;
  configuration_missing?: string[];
  connection_status: 'connected' | 'failed' | 'not_configured' | null;
  endpoints: SmartLivingEndpointStatus[];
  last_checked: string | null;
  api_calls_enabled: boolean;
  branch_mapping_count: number;
  agent_mapping_count: number;
  manager_mapping_count: number;
  open_exception_count: number;
};

export type SmartLivingDiscovery = {
  id: string;
  discovery_type: 'branch' | 'manager' | 'agent';
  external_key: string;
  external_id?: string | null;
  external_code?: string | null;
  external_display_name?: string | null;
  display_name_status?: 'resolved' | 'unavailable';
  branch_name?: string | null;
  relationship?: SmartLivingAgentRelationship | null;
  seen_count: number;
  source_endpoints: string[];
  last_seen_at: string;
};

export type SmartLivingAgentRelationship = {
  status: 'resolved' | 'needs_review' | 'conflicting';
  reason?: string | null;
  resolution_source?: 'manager_branch' | 'direct_branch' | null;
  agent_id?: string | null;
  agent_display_name?: string | null;
  manager_id?: string | null;
  manager_display_name?: string | null;
  direct_branch?: string | null;
  manager_branch?: string | null;
  direct_branch_options: string[];
  manager_branch_options: string[];
  external_branch?: string | null;
  fleetops_branch_id?: string | null;
  fleetops_branch_name?: string | null;
};

export type SmartLivingDryRun = {
  id: string;
  total_scanned: number;
  eligible: number;
  source_eligible: number;
  ready: number;
  blocked: number;
  already_imported: number;
  duplicates: number;
  unmapped_branches: number;
  unmapped_agents: number;
  invalid_ignored: number;
  deliveries_created: number;
  found: number;
  controls: SmartLivingIntakeControls & { exclude_already_delivered: boolean };
  date_fields: { 'completed-cards': 'created_at'; 'closed-cards': 'at' };
  range_counts: {
    fetched: number;
    outside_period: number;
    missing_or_invalid_date: number;
  };
  source_counts: {
    completed_rows: number;
    completed_records: number;
    closed_rows: number;
    closed_records: number;
  };
  deduplication: {
    completed_rows_collapsed_by_card_id: number;
    canonical_source_ids_seen: number;
  };
  sample_ready: Array<Record<string, any>>;
  sample_errors: Array<Record<string, any>>;
  records: SmartLivingPreviewRecord[];
  created_at: string;
};

export type SmartLivingSource = 'completed-cards' | 'closed-cards' | 'both';
export type SmartLivingIntakeControls = {
  source: SmartLivingSource;
  from_date: string;
  to_date: string;
  quick_option: 'today' | 'this_week' | 'last_week' | 'custom';
};
export type SmartLivingPreviewRecord = {
  selected_key: string;
  source_record_id: string;
  source_endpoint: 'completed-cards' | 'closed-cards';
  customer_name?: string | null;
  customer_phone?: string | null;
  customer_location?: string | null;
  customer_occupation?: string | null;
  products: Array<{
    name?: string | null;
    reference?: string | null;
    quantity: number;
  }>;
  external_branch?: string | null;
  branch_name?: string | null;
  external_agent_id?: string | null;
  external_agent_name?: string | null;
  source_status?: string | null;
  source_status_label?: string;
  source_date?: string | null;
  source_date_field: 'created_at' | 'at';
  mapping_status: string;
  import_eligible: boolean;
  physically_delivered: boolean;
  outcome: string;
  reasons: string[];
  blockers?: string[];
  other_detail?: string[];
  relationship?: SmartLivingAgentRelationship | null;
  entities?: {
    customer?: {
      id?: string | null;
      display_name?: string | null;
      phone?: string | null;
      location?: string | null;
      occupation?: string | null;
    };
    agent?: { id?: string | null; display_name?: string | null };
    branch?: { id?: string | null; display_name?: string | null };
    manager?: { id?: string | null; display_name?: string | null };
    products?: Array<{
      id?: string | null;
      display_name?: string | null;
      quantity: number;
    }>;
  };
};

export type SmartLivingImportBatch = {
  batch_id: string;
  selected: number;
  imported: number;
  duplicate_already_imported: number;
  rejected: number;
};

export type SmartLivingProvisioningAgent = {
  discovery_id: string;
  agent_id?: string | null;
  name?: string | null;
  status:
    | 'eligible'
    | 'existing'
    | 'needs_review'
    | 'ignored_inactive'
    | 'provisioned'
    | 'failed';
  reasons: string[];
  error_codes?: string[];
  branch_id?: string | null;
  branch_name?: string | null;
  manager_id?: string | null;
  manager_name?: string | null;
  fleetops_user_name?: string | null;
  source_direct_branch?: string | null;
  source_manager_branch?: string | null;
  source_direct_branch_options?: string[];
  source_manager_branch_options?: string[];
  source_manager_name?: string | null;
  confirmed_manager_name?: string | null;
  manager_branch_name?: string | null;
  conflict_reason?: string | null;
  relationship_status?: string | null;
  relationship_reason?: string | null;
  user_id?: string | null;
  username?: string | null;
  must_change_password?: boolean | null;
  default_password_active?: boolean | null;
  credential_recovery_required?: boolean;
  role?: string;
  account_status?: string | null;
  identity_match_method?: string | null;
  candidate_user_ids?: string[];
  resolved_by?: string | null;
  resolved_at?: string | null;
};

export type SmartLivingProvisioningResult = SmartLivingProvisioningAgent & {
  outcome: 'created' | 'linked' | 'skipped' | 'duplicate' | 'failed';
  temporary_password?: string;
  credential_available_once?: boolean;
  message?: string;
};

export type SmartLivingOneTimeCredential = {
  discovery_id?: string;
  user_id?: string;
  name?: string | null;
  username?: string | null;
  branch_name?: string | null;
  manager_name?: string | null;
  role?: string;
  account_status?: string | null;
  temporary_password?: string;
  credential_available_once?: boolean;
};

export type SmartLivingProvisioningManager = {
  discovery_id: string;
  source_id: string | null;
  manager_name: string | null;
  email: string | null;
  phone: string | null;
  source_branch: string | null;
  source_branch_options: string[];
  branch_id: string | null;
  branch_name: string | null;
  fleetops_user_id: string | null;
  fleetops_user_name: string | null;
  fleetops_username: string | null;
  fleetops_roles: string | null;
  fleetops_status: string | null;
  match_method: string | null;
  name_resolution_source: string | null;
  account_status: 'existing' | 'missing';
  mapping_status: 'linked' | 'unlinked';
  status: 'linked' | 'ready_to_link' | 'ready_to_create' | 'needs_review';
  error_codes: string[];
  candidate_ids: string[];
  candidates: Array<{
    id: string;
    name: string;
    role: string;
    match_reason: string;
    username: string | null;
    branch_id: string | null;
    branch_name: string | null;
  }>;
};

export type SmartLivingManagerProvisioningPreview = {
  contract_version: number;
  counts: Record<SmartLivingProvisioningManager['status'], number>;
  managers: SmartLivingProvisioningManager[];
  branches: Array<{ id: string; name: string }>;
  contract_errors: string[];
};

const managerStatuses = [
  'linked',
  'ready_to_link',
  'ready_to_create',
  'needs_review',
] as const;
const recordValue = (value: unknown): Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
const nullableText = (value: unknown): string | null =>
  typeof value === 'string' && value.trim() ? value.trim() : null;
const textArray = (value: unknown): string[] =>
  Array.isArray(value)
    ? value
        .filter(
          (item): item is string =>
            typeof item === 'string' && Boolean(item.trim()),
        )
        .map((item) => item.trim())
    : [];
const countValue = (value: unknown): number =>
  typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : 0;

export const emptyManagerProvisioningPreview =
  (): SmartLivingManagerProvisioningPreview => ({
    contract_version: 1,
    counts: {
      needs_review: 0,
      ready_to_link: 0,
      ready_to_create: 0,
      linked: 0,
    },
    managers: [],
    branches: [],
    contract_errors: [],
  });

export function normalizeManagerProvisioningPreview(
  value: unknown,
): SmartLivingManagerProvisioningPreview {
  const root = recordValue(value);
  const errors: string[] = [];
  const rawManagers = Array.isArray(root.managers) ? root.managers : [];
  if (!Array.isArray(root.managers))
    errors.push('The backend response did not include a managers array.');
  const managers = rawManagers.flatMap(
    (rawItem, index): SmartLivingProvisioningManager[] => {
      const item = recordValue(rawItem);
      if (!Object.keys(item).length) {
        errors.push(`Manager record ${index + 1} was not an object.`);
        return [];
      }
      const discoveryId = nullableText(item.discovery_id) || '';
      if (!discoveryId)
        errors.push(`Manager record ${index + 1} is missing its discovery ID.`);
      const rawStatus =
        item.status === 'ready_to_match' ? 'ready_to_link' : item.status;
      const status = managerStatuses.includes(
        rawStatus as SmartLivingProvisioningManager['status'],
      )
        ? (rawStatus as SmartLivingProvisioningManager['status'])
        : 'needs_review';
      if (rawStatus !== status)
        errors.push(`Manager record ${index + 1} has an invalid status.`);
      const candidateIds = textArray(item.candidate_ids);
      const rawCandidates = Array.isArray(item.candidates)
        ? item.candidates
        : [];
      const candidates = rawCandidates
        .map((rawCandidate) => {
          const candidate = recordValue(rawCandidate);
          return {
            id: nullableText(candidate.id) || '',
            name: nullableText(candidate.name) || 'Name unavailable',
            role: nullableText(candidate.role) || 'Branch Manager',
            match_reason: nullableText(candidate.match_reason) || 'identity',
            username: nullableText(candidate.username),
            branch_id: nullableText(candidate.branch_id),
            branch_name: nullableText(candidate.branch_name),
          };
        })
        .filter((candidate) => Boolean(candidate.id));
      if (!candidates.length && candidateIds.length) {
        candidateIds.forEach((id, candidateIndex) =>
          candidates.push({
            id,
            name:
              candidateIndex === 0
                ? nullableText(item.fleetops_user_name) || 'Name unavailable'
                : 'Name unavailable',
            role: 'Branch Manager',
            match_reason: 'identity',
            username: null,
            branch_id: null,
            branch_name: null,
          }),
        );
      }
      return [
        {
          discovery_id: discoveryId,
          source_id: nullableText(item.source_id),
          manager_name: nullableText(item.manager_name),
          email: nullableText(item.email),
          phone: nullableText(item.phone),
          source_branch: nullableText(item.source_branch),
          source_branch_options: textArray(item.source_branch_options),
          branch_id: nullableText(item.branch_id),
          branch_name: nullableText(item.branch_name),
          fleetops_user_id: nullableText(item.fleetops_user_id),
          fleetops_user_name: nullableText(item.fleetops_user_name),
          fleetops_username: nullableText(item.fleetops_username),
          fleetops_roles: nullableText(item.fleetops_roles),
          fleetops_status: nullableText(item.fleetops_status),
          match_method: nullableText(item.match_method),
          name_resolution_source: nullableText(item.name_resolution_source),
          account_status:
            item.account_status === 'existing' || candidates.length
              ? 'existing'
              : 'missing',
          mapping_status:
            item.mapping_status === 'linked' ? 'linked' : 'unlinked',
          status,
          error_codes: textArray(item.error_codes),
          candidate_ids: candidateIds.length
            ? candidateIds
            : candidates.map((candidate) => candidate.id),
          candidates,
        },
      ];
    },
  );
  const rawCounts = recordValue(root.counts);
  const branches = (Array.isArray(root.branches) ? root.branches : [])
    .map((rawBranch) => {
      const branch = recordValue(rawBranch);
      return {
        id: nullableText(branch.id) || '',
        name: nullableText(branch.name) || 'Unresolved branch',
      };
    })
    .filter((branch) => Boolean(branch.id));
  return {
    contract_version: countValue(root.contract_version) || 1,
    counts: {
      needs_review: countValue(rawCounts.needs_review),
      ready_to_link: countValue(
        rawCounts.ready_to_link ?? rawCounts.ready_to_match,
      ),
      ready_to_create: countValue(rawCounts.ready_to_create),
      linked: countValue(rawCounts.linked),
    },
    managers,
    branches,
    contract_errors: [...textArray(root.contract_errors), ...errors],
  };
}

export type SmartLivingProvisioningPreview = {
  counts: Record<SmartLivingProvisioningAgent['status'], number>;
  groups: Array<{
    branch_name: string;
    agents: SmartLivingProvisioningAgent[];
  }>;
  agents: SmartLivingProvisioningAgent[];
};

export const smartLivingIntegrationApi = {
  status: () =>
    apiRequest<Envelope<SmartLivingConnectionStatus>>(
      '/integrations/smartliving/status',
    ),
  testConnection: () =>
    apiRequest<Envelope<SmartLivingConnectionStatus>>(
      '/integrations/smartliving/test-connection',
      { method: 'POST' },
    ),
  discoveries: () =>
    apiRequest<
      Envelope<{
        branches: SmartLivingDiscovery[];
        managers: SmartLivingDiscovery[];
        agents: SmartLivingDiscovery[];
      }>
    >('/integrations/smartliving/discoveries'),
  discover: () =>
    apiRequest<
      Envelope<{
        unique_branches: number;
        unique_agents: number;
        relationship_counts: {
          resolved: number;
          unresolved: number;
          conflicting: number;
        };
        last_scanned: string;
      }>
    >('/integrations/smartliving/discover', {
      method: 'POST',
      timeoutMs: 120000,
    }),
  latestDryRun: () =>
    apiRequest<Envelope<{ dry_run: SmartLivingDryRun | null }>>(
      '/integrations/smartliving/dry-run/latest',
    ),
  dryRun: (body: SmartLivingIntakeControls) =>
    apiRequest<Envelope<{ dry_run: SmartLivingDryRun }>>(
      '/integrations/smartliving/dry-run',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        timeoutMs: 120000,
      },
    ),
  importSelected: (
    body: SmartLivingIntakeControls & {
      selected_records: Array<{
        source_endpoint: string;
        source_record_id: string;
      }>;
    },
  ) =>
    apiRequest<Envelope<{ import_batch: SmartLivingImportBatch }>>(
      '/integrations/smartliving/import-selected',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        timeoutMs: 120000,
      },
    ),
  options: () =>
    apiRequest<
      Envelope<{
        branches: Array<{
          id: string;
          name: string;
          code?: string;
          manager_id?: string | null;
        }>;
        agents: Array<{
          id: string;
          name: string;
          primary_branch_id?: string | null;
        }>;
        managers: Array<{
          id: string;
          name: string;
          primary_branch_id?: string | null;
        }>;
      }>
    >('/integrations/smartliving/mapping-options'),
  provisioningPreview: () =>
    apiRequest<Envelope<SmartLivingProvisioningPreview>>(
      '/integrations/smartliving/agents/preview',
    ),
  managerProvisioningPreview: async () => {
    const response = await apiRequest<Envelope<unknown>>(
      '/integrations/smartliving/managers/preview',
    );
    return {
      ...response,
      data: normalizeManagerProvisioningPreview(response.data),
    } as Envelope<SmartLivingManagerProvisioningPreview>;
  },
  matchManager: (
    discoveryId: string,
    body: {
      fleetops_user_id?: string;
      manager_name?: string;
      branch_id?: string;
      resolve_only?: boolean;
    } = {},
  ) =>
    apiRequest(`/integrations/smartliving/managers/${discoveryId}/match`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  createManager: (discoveryId: string) =>
    apiRequest(`/integrations/smartliving/managers/${discoveryId}/create`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ approved: true }),
    }),
  reevaluateManager: (discoveryId: string) =>
    apiRequest(
      `/integrations/smartliving/managers/${discoveryId}/re-evaluate`,
      { method: 'POST' },
    ),
  backfillManagers: (apply = false) =>
    apiRequest<
      Envelope<{
        backfill: {
          dry_run: boolean;
          branch_keys_normalized: number;
          manager_source_ids_linked: number;
          conflicts: number;
          skipped: number;
        };
      }>
    >('/integrations/smartliving/managers/backfill', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apply }),
    }),
  resolveProvisioningAgent: (
    discoveryId: string,
    body: {
      agent_name: string;
      branch_id: string;
      manager_id: string;
      fleetops_user_id?: string;
    },
  ) =>
    apiRequest<Envelope<{ agent: SmartLivingProvisioningAgent }>>(
      `/integrations/smartliving/agents/${discoveryId}/resolve`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      },
    ),
  provisionAgents: (body: {
    discovery_ids?: string[];
    all_eligible?: boolean;
  }) =>
    apiRequest<
      Envelope<{
        provisioning: {
          preview_eligible: number;
          selected: number;
          created: number;
          linked: number;
          skipped: number;
          failed: number;
          provisioned: number;
          duplicate: number;
          rejected: number;
          duration_ms: number;
          results: SmartLivingProvisioningResult[];
        };
      }>
    >('/integrations/smartliving/agents/provision', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      timeoutMs: 120000,
    }),
  reissueAgentCredentials: (userIds: string[]) =>
    apiRequest<
      Envelope<{
        credential_reissue: {
          requested: number;
          reissued: number;
          skipped: number;
          credentials: SmartLivingOneTimeCredential[];
        };
      }>
    >('/integrations/smartliving/agents/reissue-credentials', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_ids: userIds }),
      timeoutMs: 120000,
    }),
  mappings: (type: 'branch' | 'manager' | 'agent') =>
    apiRequest<Envelope<{ mappings: IntegrationMapping[] }>>(
      `/integrations/smartliving/mappings/${type}`,
    ),
  createMapping: (
    type: 'branch' | 'manager' | 'agent',
    body: Record<string, unknown>,
  ) =>
    apiRequest(`/integrations/smartliving/mappings/${type}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  updateMapping: (mapping: IntegrationMapping, body: Record<string, unknown>) =>
    apiRequest(
      `/integrations/smartliving/mappings/${mapping.mapping_type}/${mapping.id}`,
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      },
    ),
  exceptions: () =>
    apiRequest<Envelope<{ exceptions: IntegrationException[] }>>(
      '/integrations/smartliving/exceptions',
    ),
  retryException: (id: string) =>
    apiRequest(`/integrations/smartliving/exceptions/${id}/retry`, {
      method: 'POST',
    }),
  resolveException: (id: string) =>
    apiRequest(`/integrations/smartliving/exceptions/${id}/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ notes: 'Resolved by integration administrator.' }),
    }),
  history: () =>
    apiRequest<
      Envelope<{
        events: Array<{
          id: string;
          action: string;
          created_at: string;
          target_id?: string;
          metadata?: Record<string, unknown>;
        }>;
      }>
    >('/integrations/smartliving/history'),
};
