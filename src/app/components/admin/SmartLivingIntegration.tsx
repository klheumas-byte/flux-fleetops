import {
  Component,
  useCallback,
  useEffect,
  useState,
  type ErrorInfo,
  type ReactNode,
} from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Link2,
  RefreshCw,
} from 'lucide-react';
import { toast } from 'sonner';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '../ui/dialog';
import { useDataSync } from '../../lib/data-sync';
import {
  emptyManagerProvisioningPreview,
  smartLivingIntegrationApi,
  type IntegrationException,
  type IntegrationMapping,
  type SmartLivingConnectionStatus,
  type SmartLivingDiscovery,
  type SmartLivingDryRun,
  type SmartLivingIntakeControls,
  type SmartLivingManagerProvisioningPreview,
  type SmartLivingOneTimeCredential,
  type SmartLivingPreviewRecord,
  type SmartLivingProvisioningPreview,
} from '../../lib/smart-living-integration-api';

type Tab =
  | 'branch'
  | 'agent'
  | 'manager-provisioning'
  | 'provisioning'
  | 'dry-run'
  | 'exceptions'
  | 'history';

const isoDate = (value: Date) =>
  `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`;
const quickPeriod = (option: 'today' | 'this_week' | 'last_week') => {
  const today = new Date();
  const mondayOffset = (today.getDay() + 6) % 7;
  if (option === 'today')
    return { from_date: isoDate(today), to_date: isoDate(today) };
  const from = new Date(
    today.getFullYear(),
    today.getMonth(),
    today.getDate() - mondayOffset - (option === 'last_week' ? 7 : 0),
  );
  const to = new Date(from.getFullYear(), from.getMonth(), from.getDate() + 6);
  return { from_date: isoDate(from), to_date: isoDate(to) };
};
const sourceLabel = (value: SmartLivingPreviewRecord['source_endpoint']) =>
  value === 'completed-cards' ? 'Completed card' : 'Closed card';

export default function SmartLivingIntegration() {
  const [tab, setTab] = useState<Tab>('branch');
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState<SmartLivingConnectionStatus | null>(
    null,
  );
  const [testingConnection, setTestingConnection] = useState(false);
  const [branches, setBranches] = useState<
    Array<{
      id: string;
      name: string;
      code?: string;
      manager_id?: string | null;
    }>
  >([]);
  const [agents, setAgents] = useState<
    Array<{ id: string; name: string; primary_branch_id?: string | null }>
  >([]);
  const [managers, setManagers] = useState<
    Array<{ id: string; name: string; primary_branch_id?: string | null }>
  >([]);
  const [provisioning, setProvisioning] =
    useState<SmartLivingProvisioningPreview | null>(null);
  const [managerProvisioning, setManagerProvisioning] =
    useState<SmartLivingManagerProvisioningPreview>(
      emptyManagerProvisioningPreview,
    );
  const [managerProvisioningLoading, setManagerProvisioningLoading] =
    useState(true);
  const [managerProvisioningError, setManagerProvisioningError] = useState<
    string | null
  >(null);
  const [branchMappings, setBranchMappings] = useState<IntegrationMapping[]>(
    [],
  );
  const [agentMappings, setAgentMappings] = useState<IntegrationMapping[]>([]);
  const [exceptions, setExceptions] = useState<IntegrationException[]>([]);
  const [events, setEvents] = useState<any[]>([]);
  const [discoveries, setDiscoveries] = useState<{
    branches: SmartLivingDiscovery[];
    managers: SmartLivingDiscovery[];
    agents: SmartLivingDiscovery[];
  }>({ branches: [], managers: [], agents: [] });
  const [dryRun, setDryRun] = useState<SmartLivingDryRun | null>(null);
  const [scanning, setScanning] = useState(false);
  const [runningDryRun, setRunningDryRun] = useState(false);
  const [importing, setImporting] = useState(false);
  const [selectedRecords, setSelectedRecords] = useState<Set<string>>(
    new Set(),
  );
  const [intakeControls, setIntakeControls] =
    useState<SmartLivingIntakeControls>(() => ({
      source: 'both',
      quick_option: 'this_week',
      ...quickPeriod('this_week'),
    }));
  const [previewDialogOpen, setPreviewDialogOpen] = useState(false);
  const [previewControls, setPreviewControls] =
    useState<SmartLivingIntakeControls>(() => ({
      source: 'both',
      quick_option: 'this_week',
      ...quickPeriod('this_week'),
    }));
  const [previewError, setPreviewError] = useState('');
  const [discoveryTargets, setDiscoveryTargets] = useState<
    Record<string, string>
  >({});
  const [form, setForm] = useState({
    external_id: '',
    external_display_name: '',
    fleetops_id: '',
  });

  const loadProvisioning = useCallback(async () => {
    const response = await smartLivingIntegrationApi.provisioningPreview();
    setProvisioning(response.data);
  }, []);

  const loadManagerProvisioning = useCallback(async () => {
    setManagerProvisioningLoading(true);
    setManagerProvisioningError(null);
    try {
      const response =
        await smartLivingIntegrationApi.managerProvisioningPreview();
      setManagerProvisioning(response.data);
      if (response.data.contract_errors.length)
        setManagerProvisioningError(
          `Provisioning data needs attention: ${response.data.contract_errors.join(' ')}`,
        );
    } catch (error) {
      setManagerProvisioningError(
        error instanceof Error
          ? error.message
          : 'Unable to load Branch Manager provisioning.',
      );
    } finally {
      setManagerProvisioningLoading(false);
    }
  }, []);

  const loadDryRun = useCallback(async () => {
    const response = await smartLivingIntegrationApi.latestDryRun();
    setDryRun(response.data.dry_run);
    if (response.data.dry_run?.controls) {
      const { source, from_date, to_date, quick_option } =
        response.data.dry_run.controls;
      setIntakeControls({ source, from_date, to_date, quick_option });
    }
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [
        statusResponse,
        optionsResponse,
        branchResponse,
        agentResponse,
        discoveryResponse,
      ] = await Promise.all([
        smartLivingIntegrationApi.status(),
        smartLivingIntegrationApi.options(),
        smartLivingIntegrationApi.mappings('branch'),
        smartLivingIntegrationApi.mappings('agent'),
        smartLivingIntegrationApi.discoveries(),
      ]);
      setStatus(statusResponse.data);
      setBranches(
        Array.isArray(optionsResponse.data.branches)
          ? optionsResponse.data.branches
          : [],
      );
      setAgents(
        Array.isArray(optionsResponse.data.agents)
          ? optionsResponse.data.agents
          : [],
      );
      setManagers(
        Array.isArray(optionsResponse.data.managers)
          ? optionsResponse.data.managers
          : [],
      );
      setBranchMappings(branchResponse.data.mappings);
      setAgentMappings(agentResponse.data.mappings);
      setDiscoveries(discoveryResponse.data);
    } catch (error) {
      toast.error(
        error instanceof Error
          ? error.message
          : 'Unable to load SmartLiving integration settings.',
      );
    } finally {
      setLoading(false);
    }
  }, []);

  const refresh = async () => {
    await load();
    if (tab === 'dry-run') await loadDryRun();
    else if (tab === 'manager-provisioning') await loadManagerProvisioning();
    else if (tab === 'provisioning') await loadProvisioning();
  };

  useEffect(() => {
    void load();
  }, [load]);
  useDataSync(['users', 'agents', 'managers', 'branches'], () => {
    if (document.visibilityState === 'visible') void refresh();
  });

  useEffect(() => {
    const loadTab = async () => {
      try {
        if (tab === 'manager-provisioning') await loadManagerProvisioning();
        else if (tab === 'provisioning') await loadProvisioning();
        else if (tab === 'dry-run') await loadDryRun();
        else if (tab === 'exceptions')
          setExceptions(
            (await smartLivingIntegrationApi.exceptions()).data.exceptions,
          );
        else if (tab === 'history')
          setEvents((await smartLivingIntegrationApi.history()).data.events);
      } catch (error) {
        toast.error(
          error instanceof Error
            ? error.message
            : 'Unable to load this SmartLiving section.',
        );
      }
    };
    void loadTab();
  }, [tab, loadDryRun, loadManagerProvisioning, loadProvisioning]);

  const testConnection = async () => {
    setTestingConnection(true);
    try {
      const response = await smartLivingIntegrationApi.testConnection();
      setStatus(response.data);
      toast[
        response.data.connection_status === 'connected' ? 'success' : 'error'
      ](
        response.data.connection_status === 'connected'
          ? 'SmartLiving connection succeeded.'
          : 'SmartLiving connection failed.',
      );
    } catch (error) {
      toast.error(
        error instanceof Error
          ? error.message
          : 'Unable to test SmartLiving connection.',
      );
    } finally {
      setTestingConnection(false);
    }
  };

  const scanValues = async () => {
    setScanning(true);
    try {
      const response = await smartLivingIntegrationApi.discover();
      toast.success(
        `Discovered ${response.data.unique_branches} branches and ${response.data.unique_agents} agents.`,
      );
      await load();
      if (tab === 'manager-provisioning') await loadManagerProvisioning();
      if (tab === 'provisioning') await loadProvisioning();
    } catch (error) {
      toast.error(
        error instanceof Error
          ? error.message
          : 'Unable to scan SmartLiving values.',
      );
    } finally {
      setScanning(false);
    }
  };

  const openPreviewDialog = () => {
    setPreviewControls(intakeControls);
    setPreviewError('');
    setPreviewDialogOpen(true);
  };

  const runDryRun = async () => {
    if (!previewControls.from_date || !previewControls.to_date) {
      setPreviewError('From Date and To Date are required.');
      return;
    }
    if (previewControls.from_date > previewControls.to_date) {
      setPreviewError('From Date must be on or before To Date.');
      return;
    }
    setPreviewError('');
    setRunningDryRun(true);
    try {
      const response = await smartLivingIntegrationApi.dryRun(previewControls);
      setIntakeControls(previewControls);
      setDryRun(response.data.dry_run);
      setSelectedRecords(new Set());
      setTab('dry-run');
      setPreviewDialogOpen(false);
      toast.success('Period preview completed without creating deliveries.');
    } catch (error) {
      const message =
        error instanceof Error ? error.message : 'Unable to complete dry run.';
      setPreviewError(message);
      toast.error(message);
    } finally {
      setRunningDryRun(false);
    }
  };

  const importSelected = async () => {
    if (!dryRun || !selectedRecords.size) {
      toast.error('Select at least one READY record.');
      return;
    }
    const selected_records = dryRun.records
      .filter((record) => selectedRecords.has(record.selected_key))
      .map((record) => ({
        source_endpoint: record.source_endpoint,
        source_record_id: record.source_record_id,
      }));
    setImporting(true);
    try {
      const response = await smartLivingIntegrationApi.importSelected({
        ...intakeControls,
        selected_records,
      });
      const batch = response.data.import_batch;
      toast.success(
        `Imported ${batch.imported}; ${batch.duplicate_already_imported} already imported; ${batch.rejected} rejected.`,
      );
      const refreshed = await smartLivingIntegrationApi.dryRun(intakeControls);
      setDryRun(refreshed.data.dry_run);
      setSelectedRecords(new Set());
    } catch (error) {
      toast.error(
        error instanceof Error
          ? error.message
          : 'Unable to import selected deliveries.',
      );
    } finally {
      setImporting(false);
    }
  };

  const setQuickOption = (
    option: SmartLivingIntakeControls['quick_option'],
  ) => {
    setPreviewError('');
    setPreviewControls((current) =>
      option === 'custom'
        ? { ...current, quick_option: option }
        : { ...current, quick_option: option, ...quickPeriod(option) },
    );
  };

  const saveMapping = async () => {
    if (!form.external_id.trim() || !form.fleetops_id) {
      toast.error('External ID/code and FleetOps target are required.');
      return;
    }
    try {
      await smartLivingIntegrationApi.createMapping(
        tab as 'branch' | 'agent',
        form,
      );
      setForm({ external_id: '', external_display_name: '', fleetops_id: '' });
      toast.success('Mapping saved.');
      await load();
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : 'Unable to save mapping.',
      );
    }
  };

  const mapDiscovery = async (item: SmartLivingDiscovery) => {
    const fleetopsId = discoveryTargets[item.id];
    if (!fleetopsId) {
      toast.error('Select a FleetOps target before confirming the mapping.');
      return;
    }
    try {
      await smartLivingIntegrationApi.createMapping(item.discovery_type, {
        external_id: item.external_id || undefined,
        external_code: item.external_code || undefined,
        external_display_name: item.external_display_name,
        fleetops_id: fleetopsId,
      });
      setDiscoveryTargets((current) => ({ ...current, [item.id]: '' }));
      toast.success('Mapping confirmed.');
      await load();
    } catch (error) {
      toast.error(
        error instanceof Error
          ? error.message
          : 'Unable to save discovered mapping.',
      );
    }
  };

  const toggleMapping = async (mapping: IntegrationMapping) => {
    try {
      await smartLivingIntegrationApi.updateMapping(mapping, {
        active: !mapping.active,
      });
      await load();
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : 'Unable to update mapping.',
      );
    }
  };

  const actOnException = async (
    item: IntegrationException,
    action: 'retry' | 'resolve',
  ) => {
    try {
      if (action === 'retry')
        await smartLivingIntegrationApi.retryException(item.id);
      else await smartLivingIntegrationApi.resolveException(item.id);
      toast.success(
        action === 'retry' ? 'Retry completed.' : 'Exception resolved.',
      );
      await load();
    } catch (error) {
      toast.error(
        error instanceof Error
          ? error.message
          : `Unable to ${action} exception.`,
      );
    }
  };

  const currentMappings = tab === 'agent' ? agentMappings : branchMappings;
  const targets = tab === 'agent' ? agents : branches;
  const currentDiscoveries =
    tab === 'agent' ? discoveries.agents : discoveries.branches;
  const targetName = (mapping: IntegrationMapping) =>
    targets.find((item) => item.id === mapping.fleetops_id)?.name ||
    'Name unavailable';
  const mappingForDiscovery = (item: SmartLivingDiscovery) =>
    currentMappings.find(
      (mapping) =>
        (mapping.external_id || mapping.external_code || '')
          .trim()
          .toLocaleLowerCase() === item.external_key,
    );
  const discoveryForMapping = (mapping: IntegrationMapping) =>
    currentDiscoveries.find(
      (item) =>
        item.external_key ===
        (mapping.external_id || mapping.external_code || '')
          .trim()
          .toLocaleLowerCase(),
    );
  const mappingSourceName = (mapping: IntegrationMapping) => {
    const discovery = discoveryForMapping(mapping);
    const sourceId = (
      mapping.external_id ||
      mapping.external_code ||
      ''
    ).trim();
    const saved = (mapping.external_display_name || '').trim();
    return (
      discovery?.external_display_name ||
      (saved && saved.toLocaleLowerCase() !== sourceId.toLocaleLowerCase()
        ? saved
        : '') ||
      'Name unavailable'
    );
  };

  return (
    <div className="space-y-6 p-4 sm:p-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-blue-600">Integrations</p>
          <h1 className="text-2xl font-semibold text-slate-900">SmartLiving</h1>
          <p className="mt-1 text-sm text-slate-500">
            Mapping and dry-run readiness for the existing FleetOps delivery
            workflow.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <ActionButton
            label={scanning ? 'Scanning…' : 'Scan Values'}
            loading={scanning}
            onClick={scanValues}
          />
          <ActionButton
            label="Preview Period"
            loading={false}
            onClick={openPreviewDialog}
            primary
          />
          <ActionButton
            label={tab === 'dry-run' ? 'Refresh Preview' : 'Refresh'}
            loading={loading}
            onClick={refresh}
          />
        </div>
      </header>
      <ConnectionPanel
        status={status}
        testing={testingConnection}
        onTest={testConnection}
      />
      {status && (
        <div className="grid gap-3 sm:grid-cols-4">
          <Metric
            label="Active branch mappings"
            value={status.branch_mapping_count}
          />
          <Metric
            label="Active manager mappings"
            value={status.manager_mapping_count}
          />
          <Metric
            label="Active agent mappings"
            value={status.agent_mapping_count}
          />
          <Metric label="Open exceptions" value={status.open_exception_count} />
        </div>
      )}
      <nav
        className="flex flex-wrap gap-2"
        aria-label="SmartLiving integration sections"
      >
        {(
          [
            ['branch', 'Branch Mappings'],
            ['agent', 'Agent Mappings'],
            ['manager-provisioning', 'Branch Manager Provisioning'],
            ['provisioning', 'Agent Provisioning'],
            ['dry-run', 'Dry Run Preview'],
            ['exceptions', 'Integration Exceptions'],
            ['history', 'Import / Sync History'],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            onClick={() => {
              setTab(id);
              setForm({
                external_id: '',
                external_display_name: '',
                fleetops_id: '',
              });
            }}
            className={`min-h-10 rounded-lg px-3 text-sm font-medium ${tab === id ? 'bg-blue-600 text-white' : 'border bg-white text-slate-700'}`}
          >
            {label}
          </button>
        ))}
      </nav>
      {(tab === 'branch' || tab === 'agent') && (
        <section className="space-y-4">
          <DiscoveredMappings
            items={currentDiscoveries}
            mappings={currentMappings}
            targets={targets}
            selected={discoveryTargets}
            onSelect={(id, value) =>
              setDiscoveryTargets((current) => ({ ...current, [id]: value }))
            }
            onConfirm={mapDiscovery}
          />
          <div className="grid gap-3 rounded-xl border bg-white p-4 md:grid-cols-[1fr_1fr_1fr_auto]">
            <input
              aria-label="External ID or code"
              value={form.external_id}
              onChange={(event) =>
                setForm({ ...form, external_id: event.target.value })
              }
              placeholder="External ID or code"
              className="min-h-11 rounded-lg border px-3"
            />
            <input
              aria-label="External display name"
              value={form.external_display_name}
              onChange={(event) =>
                setForm({ ...form, external_display_name: event.target.value })
              }
              placeholder="External display name (optional)"
              className="min-h-11 rounded-lg border px-3"
            />
            <select
              aria-label="FleetOps target"
              value={form.fleetops_id}
              onChange={(event) =>
                setForm({ ...form, fleetops_id: event.target.value })
              }
              className="min-h-11 rounded-lg border px-3"
            >
              <option value="">Select FleetOps {tab}</option>
              {targets.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
            <button
              onClick={() => void saveMapping()}
              className="min-h-11 rounded-lg bg-blue-600 px-4 font-medium text-white"
            >
              Add mapping
            </button>
          </div>
          <div className="overflow-hidden rounded-xl border bg-white">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-50 text-slate-600">
                <tr>
                  <th className="p-3">External record</th>
                  <th className="p-3">FleetOps target</th>
                  <th className="p-3">Status</th>
                  <th className="p-3 text-right">Action</th>
                </tr>
              </thead>
              <tbody>
                {currentMappings.map((mapping) => {
                  const discovery = discoveryForMapping(mapping);
                  return (
                    <tr key={mapping.id} className="border-t">
                      <td className="p-3">
                        <div className="font-medium">
                          {mappingSourceName(mapping)}
                        </div>
                        {discovery?.branch_name && (
                          <div className="text-xs text-slate-600">
                            {discovery.branch_name}
                          </div>
                        )}
                        <SourceIdentity
                          id={mapping.external_id || mapping.external_code}
                        />
                      </td>
                      <td className="p-3">{targetName(mapping)}</td>
                      <td className="p-3">
                        {mapping.active ? 'Active' : 'Inactive'}
                      </td>
                      <td className="p-3 text-right">
                        <button
                          onClick={() => void toggleMapping(mapping)}
                          className="rounded border px-3 py-2"
                        >
                          {mapping.active ? 'Deactivate' : 'Activate'}
                        </button>
                      </td>
                    </tr>
                  );
                })}
                {!currentMappings.length && (
                  <tr>
                    <td colSpan={4} className="p-8 text-center text-slate-500">
                      No mappings configured.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}
      {tab === 'manager-provisioning' && (
        <ProvisioningErrorBoundary onRetry={loadManagerProvisioning}>
          <ManagerProvisioning
            preview={managerProvisioning}
            branches={branches}
            loading={managerProvisioningLoading}
            error={managerProvisioningError}
            onRetry={loadManagerProvisioning}
            onRefresh={async () => {
              await Promise.all([loadManagerProvisioning(), load()]);
            }}
          />
        </ProvisioningErrorBoundary>
      )}
      {tab === 'provisioning' && (
        <AgentProvisioning
          preview={provisioning}
          branches={branches}
          managers={managers}
          existingAgents={agents}
          onRefresh={loadProvisioning}
        />
      )}
      {tab === 'dry-run' && (
        <DryRunPanel
          dryRun={dryRun}
          selected={selectedRecords}
          onSelected={setSelectedRecords}
          onImport={importSelected}
          importing={importing}
        />
      )}
      {tab === 'exceptions' && (
        <div className="space-y-3">
          {exceptions.map((item) => (
            <article key={item.id} className="rounded-xl border bg-white p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="flex gap-3">
                  <AlertTriangle className="mt-0.5 h-5 w-5 text-amber-600" />
                  <div>
                    <div className="font-semibold text-slate-900">
                      {item.exception_type.replaceAll('_', ' ')}
                    </div>
                    <p className="text-sm text-slate-600">{item.message}</p>
                    <p className="mt-1 text-xs text-slate-500">
                      {item.source_type} · {item.source_record_id} · Attempts{' '}
                      {item.attempt_count}
                    </p>
                  </div>
                </div>
                {item.status === 'open' && (
                  <div className="flex gap-2">
                    {item.retryable !== false && (
                      <button
                        onClick={() => void actOnException(item, 'retry')}
                        className="rounded border px-3 py-2 text-sm"
                      >
                        Retry
                      </button>
                    )}
                    <button
                      onClick={() => void actOnException(item, 'resolve')}
                      className="rounded bg-slate-900 px-3 py-2 text-sm text-white"
                    >
                      Resolve
                    </button>
                  </div>
                )}
              </div>
            </article>
          ))}
          {!exceptions.length && (
            <Empty icon={<CheckCircle2 />} text="No integration exceptions." />
          )}
        </div>
      )}
      {tab === 'history' && (
        <div className="space-y-2">
          {events.map((event) => (
            <article
              key={event.id}
              className="flex items-center gap-3 rounded-lg border bg-white p-3"
            >
              <Link2 className="h-4 w-4 text-blue-600" />
              <div>
                <div className="text-sm font-medium">
                  {String(event.action).replaceAll('_', ' ')}
                </div>
                <div className="text-xs text-slate-500">
                  {event.created_at
                    ? new Date(event.created_at).toLocaleString()
                    : 'Pending timestamp'}
                </div>
              </div>
            </article>
          ))}
          {!events.length && (
            <Empty
              icon={<Clock3 />}
              text="Import and sync history will appear here when canonical intake runs."
            />
          )}
        </div>
      )}
      <PreviewPeriodDialog
        open={previewDialogOpen}
        controls={previewControls}
        error={previewError}
        running={runningDryRun}
        onOpenChange={setPreviewDialogOpen}
        onChange={(value) => {
          setPreviewControls(value);
          setPreviewError('');
        }}
        onQuickOption={setQuickOption}
        onPreview={runDryRun}
      />
    </div>
  );
}

class ProvisioningErrorBoundary extends Component<
  { children: ReactNode; onRetry: () => Promise<void> },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[Branch Manager Provisioning] Render failed', error, info);
  }
  retry = async () => {
    await this.props.onRetry();
    this.setState({ failed: false });
  };
  render() {
    return this.state.failed ? (
      <InlineProvisioningError
        message="Branch Manager provisioning could not render. Retry the preview; if this continues, refresh after restarting the backend."
        onRetry={this.retry}
      />
    ) : (
      this.props.children
    );
  }
}

function InlineProvisioningError({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void | Promise<void>;
}) {
  return (
    <section
      role="alert"
      className="rounded-xl border border-red-200 bg-red-50 p-4"
    >
      <div className="font-semibold text-red-900">
        Branch Manager provisioning unavailable
      </div>
      <p className="mt-1 text-sm text-red-800">{message}</p>
      <button
        onClick={() => void onRetry()}
        className="mt-3 rounded bg-red-700 px-3 py-2 text-sm font-medium text-white"
      >
        Retry
      </button>
    </section>
  );
}

type ProvisionedLoginAccount = {
  id: string;
  name: string;
  username: string;
  roles: string;
  branch: string;
  status: string;
};

function loginDetailsMessage(account: ProvisionedLoginAccount) {
  return `Flux FleetOps Login Details
Name: ${account.name}
Username: ${account.username}
Password: fleet@12345
Role: ${account.roles}
Branch: ${account.branch}

Use your username and password to sign in. You can change your password after login.`;
}

function ProvisionedLoginAccounts({
  accounts,
}: {
  accounts: ProvisionedLoginAccount[];
}) {
  if (!accounts.length) return null;
  const copyLoginDetails = async (account: ProvisionedLoginAccount) => {
    try {
      await navigator.clipboard.writeText(loginDetailsMessage(account));
      toast.success(`Login details copied for ${account.name}.`);
    } catch {
      toast.error('Unable to copy login details. Please try again.');
    }
  };
  return (
    <section className="space-y-3" aria-label="Provisioned login accounts">
      <h3 className="font-semibold text-slate-900">Provisioned login accounts</h3>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {accounts.map((account) => (
          <article key={account.id} className="min-w-0 rounded-xl border bg-white p-4 text-sm shadow-sm">
            <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-2">
              <dt className="text-slate-500">Name</dt>
              <dd className="truncate font-medium text-slate-900">{account.name}</dd>
              <dt className="text-slate-500">Username</dt>
              <dd className="break-all font-mono font-semibold text-blue-900">{account.username}</dd>
              <dt className="text-slate-500">Role</dt>
              <dd className="break-words">{account.roles}</dd>
              <dt className="text-slate-500">Branch</dt>
              <dd className="break-words">{account.branch}</dd>
              <dt className="text-slate-500">Status</dt>
              <dd className="capitalize">{account.status}</dd>
            </dl>
            <button
              type="button"
              onClick={() => void copyLoginDetails(account)}
              className="mt-4 min-h-11 w-full rounded-lg bg-blue-600 px-3 py-2 font-medium text-white hover:bg-blue-700"
            >
              Copy Login Details
            </button>
          </article>
        ))}
      </div>
    </section>
  );
}

function ManagerProvisioning({
  preview,
  branches,
  loading,
  error,
  onRetry,
  onRefresh,
}: {
  preview: SmartLivingManagerProvisioningPreview;
  branches: Array<{ id: string; name: string }>;
  loading: boolean;
  error: string | null;
  onRetry: () => Promise<void>;
  onRefresh: () => Promise<void>;
}) {
  type ReviewEdit = {
    manager_name: string;
    branch_id: string;
    fleetops_user_id: string;
  };
  const [busy, setBusy] = useState('');
  const [edits, setEdits] = useState<Record<string, ReviewEdit>>({});
  if (loading)
    return (
      <Empty
        icon={<Clock3 />}
        text="Loading Branch Manager provisioning preview…"
      />
    );
  if (error)
    return <InlineProvisioningError message={error} onRetry={onRetry} />;
  const managerRows = Array.isArray(preview.managers) ? preview.managers : [];
  const linkedLoginAccounts: ProvisionedLoginAccount[] = managerRows
    .filter((item) => item.status === 'linked' && item.fleetops_user_id && item.fleetops_username)
    .map((item) => ({
      id: item.fleetops_user_id!,
      name: item.fleetops_user_name || item.manager_name || item.fleetops_username!,
      username: item.fleetops_username!,
      roles: item.fleetops_roles || 'Branch Manager',
      branch: item.branch_name || 'Branch unavailable',
      status: item.fleetops_status || 'active',
    }));
  const availableBranches =
    Array.isArray(preview.branches) && preview.branches.length
      ? preview.branches
      : Array.isArray(branches)
        ? branches
        : [];
  const editFor = (
    item: SmartLivingManagerProvisioningPreview['managers'][number],
  ): ReviewEdit =>
    edits[item.discovery_id] || {
      manager_name: item.manager_name || '',
      branch_id: item.branch_id || '',
      fleetops_user_id: '',
    };
  const update = (
    item: SmartLivingManagerProvisioningPreview['managers'][number],
    value: Partial<ReviewEdit>,
  ) =>
    setEdits((current) => ({
      ...current,
      [item.discovery_id]: { ...editFor(item), ...value },
    }));
  const run = async (
    item: SmartLivingManagerProvisioningPreview['managers'][number],
    action: 'resolve' | 'link' | 'create' | 're-evaluate',
  ) => {
    const form = editFor(item);
    setBusy(item.discovery_id);
    try {
      if (action === 'resolve')
        await smartLivingIntegrationApi.matchManager(item.discovery_id, {
          manager_name: form.manager_name,
          branch_id: form.branch_id,
          resolve_only: true,
        });
      else if (action === 'link')
        await smartLivingIntegrationApi.matchManager(item.discovery_id, {
          manager_name: form.manager_name,
          branch_id: form.branch_id,
          fleetops_user_id: form.fleetops_user_id || undefined,
        });
      else if (action === 'create')
        await smartLivingIntegrationApi.createManager(item.discovery_id);
      else await smartLivingIntegrationApi.reevaluateManager(item.discovery_id);
      toast.success(
        action === 'create'
          ? 'Branch Manager created and linked.'
          : action === 'link'
            ? 'Existing Branch Manager linked.'
            : action === 'resolve'
              ? 'Manager review resolved and status recomputed.'
              : 'Branch agents re-evaluated.',
      );
      await onRefresh();
    } catch (error) {
      toast.error(
        error instanceof Error
          ? error.message
          : 'Unable to update the Branch Manager.',
      );
    } finally {
      setBusy('');
    }
  };
  return (
    <section className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Metric
          label="Needs Review"
          value={preview.counts?.needs_review ?? 0}
        />
        <Metric
          label="Ready to Link"
          value={preview.counts?.ready_to_link ?? 0}
        />
        <Metric
          label="Ready to Create"
          value={preview.counts?.ready_to_create ?? 0}
        />
        <Metric label="Linked" value={preview.counts?.linked ?? 0} />
      </div>
      <ProvisionedLoginAccounts accounts={linkedLoginAccounts} />
      <div className="overflow-x-auto rounded-xl border bg-white">
        <table className="w-full min-w-[1200px] text-left text-sm">
          <thead className="bg-slate-50 text-slate-600">
            <tr>
              <th className="p-3">Name</th>
              <th className="p-3">Role</th>
              <th className="p-3">Branch</th>
              <th className="p-3">Source system</th>
              <th className="p-3">FleetOps account</th>
              <th className="p-3">Status</th>
              <th className="p-3">Action</th>
            </tr>
          </thead>
          <tbody>
            {managerRows.map((item) => {
              const form = editFor(item);
              const reviewCodes = Array.isArray(item.error_codes)
                ? item.error_codes
                : [];
              const candidates = Array.isArray(item.candidates)
                ? item.candidates
                : [];
              const needsName = reviewCodes.some(
                (code) =>
                  code === 'MISSING_NAME' ||
                  code === 'CONFLICTING_MANAGER_NAME',
              );
              const needsBranch = reviewCodes.some(
                (code) =>
                  code === 'UNRESOLVED_BRANCH' || code === 'BRANCH_CONFLICT',
              );
              return (
                <tr key={item.discovery_id} className="border-t align-top">
                  <td className="p-3">
                    <div className="font-medium">
                      {item.manager_name || 'Manager identity missing'}
                    </div>
                    {!item.manager_name && (
                      <p className="mt-1 max-w-64 text-xs text-amber-700">
                        SmartLiving source has no manager name. Confirm the
                        readable name before linking an account.
                      </p>
                    )}
                    <div className="text-xs text-slate-500">
                      {item.email || item.phone || 'No contact value'}
                    </div>
                    <ManagerSourceDetails item={item} />
                  </td>
                  <td className="p-3">Branch Manager</td>
                  <td className="p-3">
                    <div>{item.branch_name || 'Unresolved branch'}</div>
                    <div className="mt-1 text-xs text-slate-500">
                      Source branch evidence:{' '}
                      {(Array.isArray(item.source_branch_options)
                        ? item.source_branch_options
                        : []
                      ).join(', ') ||
                        item.source_branch ||
                        'None'}
                    </div>
                  </td>
                  <td className="p-3 text-slate-600">Smart Living</td>
                  <td className="p-3">
                    {candidates.length ? (
                      <div className="space-y-1">
                        {candidates.map((candidate) => (
                          <div key={candidate.id}>
                            <span className="font-medium">
                              {candidate.name || 'Manager identity missing'}
                            </span>
                            <div className="text-xs text-slate-500">
                              {candidate.role} ·{' '}
                              {candidate.match_reason === 'branch_access'
                                ? 'Branch access candidate'
                                : 'Identity candidate'}
                            </div>
                            {candidate.branch_name && (
                              <span className="text-xs text-slate-500">
                                {' '}
                                · {candidate.branch_name}
                              </span>
                            )}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <span className="text-slate-500">
                        No existing account
                      </span>
                    )}
                  </td>
                  <td className="p-3">
                    <div
                      className={
                        item.status === 'needs_review'
                          ? 'font-medium text-amber-700'
                          : 'font-medium text-emerald-700'
                      }
                    >
                      {(item.status || 'needs_review').replaceAll('_', ' ')}
                    </div>
                    <div className="text-xs text-slate-500">
                      Mapping:{' '}
                      {item.mapping_status === 'linked'
                        ? 'Linked'
                        : 'Not linked'}
                    </div>
                    {reviewCodes.length > 0 && (
                      <div className="text-xs text-amber-700">
                        {reviewCodes.join(', ').replaceAll('_', ' ')}
                      </div>
                    )}
                  </td>
                  <td className="p-3">
                    <div className="grid gap-2">
                      {item.status === 'needs_review' && (
                        <>
                          {needsName && (
                            <input
                              aria-label="Confirmed manager name"
                              value={form.manager_name}
                              onChange={(event) =>
                                update(item, {
                                  manager_name: event.target.value,
                                })
                              }
                              placeholder="Confirm readable name"
                              className="min-h-10 rounded border px-2"
                            />
                          )}
                          {needsBranch && (
                            <select
                              aria-label="Confirmed manager branch"
                              value={form.branch_id}
                              onChange={(event) =>
                                update(item, { branch_id: event.target.value })
                              }
                              className="min-h-10 rounded border px-2"
                            >
                              <option value="">Select active branch</option>
                              {availableBranches.map((branch) => (
                                <option key={branch.id} value={branch.id}>
                                  {branch.name || 'Unresolved branch'}
                                </option>
                              ))}
                            </select>
                          )}
                          {candidates.length > 0 && (
                            <select
                              aria-label="Existing manager candidate"
                              value={form.fleetops_user_id}
                              onChange={(event) =>
                                update(item, {
                                  fleetops_user_id: event.target.value,
                                })
                              }
                              className="min-h-10 rounded border px-2"
                            >
                              <option value="">Select correct candidate</option>
                              {candidates.map((candidate) => (
                                <option key={candidate.id} value={candidate.id}>
                                  {candidate.name || 'Name unavailable'}
                                  {candidate.branch_name
                                    ? ` — ${candidate.branch_name}`
                                    : ''}
                                </option>
                              ))}
                            </select>
                          )}
                          {(needsName || needsBranch) && (
                            <button
                              disabled={
                                busy === item.discovery_id ||
                                (needsName && !form.manager_name) ||
                                (needsBranch && !form.branch_id)
                              }
                              onClick={() => void run(item, 'resolve')}
                              className="rounded bg-amber-600 px-3 py-2 text-white disabled:opacity-50"
                            >
                              Resolve
                            </button>
                          )}
                          {candidates.length > 0 && (
                            <button
                              disabled={
                                busy === item.discovery_id ||
                                !form.fleetops_user_id ||
                                (needsName && !form.manager_name) ||
                                (needsBranch && !form.branch_id)
                              }
                              onClick={() => void run(item, 'link')}
                              className="rounded bg-blue-600 px-3 py-2 text-white disabled:opacity-50"
                            >
                              Link Existing
                            </button>
                          )}
                        </>
                      )}
                      {item.status === 'ready_to_link' && (
                        <button
                          disabled={busy === item.discovery_id}
                          onClick={() => void run(item, 'link')}
                          className="rounded bg-blue-600 px-3 py-2 text-white"
                        >
                          Link Existing
                        </button>
                      )}
                      {item.status === 'ready_to_create' && (
                        <button
                          disabled={busy === item.discovery_id}
                          onClick={() => void run(item, 'create')}
                          className="rounded bg-emerald-600 px-3 py-2 text-white"
                        >
                          Create Account
                        </button>
                      )}
                      {item.status === 'linked' && (
                        <button
                          disabled={busy === item.discovery_id}
                          onClick={() => void run(item, 're-evaluate')}
                          className="rounded border px-3 py-2"
                        >
                          Re-evaluate agents
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
            {!managerRows.length && (
              <tr>
                <td colSpan={7} className="p-8 text-center text-slate-500">
                  No Branch Managers were found in the latest SmartLiving scan.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ManagerSourceDetails({
  item,
}: {
  item: SmartLivingManagerProvisioningPreview['managers'][number];
}) {
  const sourceBranches = Array.isArray(item.source_branch_options)
    ? item.source_branch_options
    : [];
  const candidateIds = Array.isArray(item.candidate_ids)
    ? item.candidate_ids
    : [];
  return (
    <details className="mt-1 text-xs text-slate-500">
      <summary className="cursor-pointer">Technical Details</summary>
      <div className="mt-1 space-y-0.5">
        <div>SmartLiving manager ID: {item.source_id || 'Not provided'}</div>
        {!item.manager_name && item.source_id && (
          <div>
            SmartLiving supplied manager ID {item.source_id} but no readable
            manager name.
          </div>
        )}
        {item.source_branch && <div>Source branch: {item.source_branch}</div>}
        {sourceBranches.length > 1 && (
          <div>Source branch keys: {sourceBranches.join(', ')}</div>
        )}
        {item.fleetops_user_id && (
          <div>FleetOps user ID: {item.fleetops_user_id}</div>
        )}
        {candidateIds.length > 1 && (
          <div>Candidate user IDs: {candidateIds.join(', ')}</div>
        )}
      </div>
    </details>
  );
}

function AgentProvisioning({
  preview,
  branches,
  managers,
  existingAgents,
  onRefresh,
}: {
  preview: SmartLivingProvisioningPreview | null;
  branches: Array<{ id: string; name: string; manager_id?: string | null }>;
  managers: Array<{
    id: string;
    name: string;
    primary_branch_id?: string | null;
  }>;
  existingAgents: Array<{
    id: string;
    name: string;
    primary_branch_id?: string | null;
  }>;
  onRefresh: () => Promise<void>;
}) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [searchQuery, setSearchQuery] = useState('');
  const [busy, setBusy] = useState(false);
  const [credentials, setCredentials] = useState<SmartLivingOneTimeCredential[]>([]);
  const [provisioningProgress, setProvisioningProgress] = useState<{
    completed: number;
    total: number;
  } | null>(null);
  const [edits, setEdits] = useState<
    Record<
      string,
      {
        agent_name: string;
        branch_id: string;
        manager_id: string;
        fleetops_user_id: string;
      }
    >
  >({});
  if (!preview)
    return <Empty icon={<Clock3 />} text="Loading SmartLiving Field Agents…" />;
  const agentRows = Array.isArray(preview.agents) ? preview.agents : [];
  const normalizedSearch = searchQuery.trim().toLocaleLowerCase();
  const matchesSearch = (
    item: SmartLivingProvisioningPreview['agents'][number],
  ) =>
    !normalizedSearch ||
    [
      item.name,
      item.username,
      item.branch_name,
      item.source_direct_branch,
      item.source_manager_branch,
      item.manager_name,
      item.confirmed_manager_name,
      item.manager_branch_name,
      item.fleetops_user_name,
      item.status,
      ...(Array.isArray(item.reasons) ? item.reasons : []),
      ...(Array.isArray(item.error_codes) ? item.error_codes : []),
    ].some((value) =>
      String(value || '').toLocaleLowerCase().includes(normalizedSearch),
    );
  const visibleAgentRows = agentRows.filter(matchesSearch);
  const visibleGroups = (Array.isArray(preview.groups) ? preview.groups : [])
    .map((group) => ({
      ...group,
      agents: (Array.isArray(group.agents) ? group.agents : []).filter(
        matchesSearch,
      ),
    }))
    .filter((group) => group.agents.length > 0);
  const linkedLoginAccounts: ProvisionedLoginAccount[] = visibleAgentRows
    .filter((item) => ['existing', 'provisioned'].includes(item.status) && item.user_id && item.username)
    .map((item) => ({
      id: item.user_id!,
      name: item.fleetops_user_name || item.name || item.username!,
      username: item.username!,
      roles: item.role || 'Field Agent',
      branch: item.branch_name || 'Branch unavailable',
      status: item.account_status || 'active',
    }));
  const eligible = agentRows.filter((item) => item.status === 'eligible');
  const pendingCredentials = agentRows.filter(
    (item) =>
      item.status === 'provisioned' &&
      item.must_change_password &&
      item.default_password_active &&
      item.credential_recovery_required &&
      item.user_id,
  );
  const editFor = (item: SmartLivingProvisioningPreview['agents'][number]) =>
    edits[item.discovery_id] || {
      agent_name: item.name || '',
      branch_id: item.branch_id || '',
      manager_id: item.manager_id || '',
      fleetops_user_id: '',
    };
  const update = (id: string, value: Partial<ReturnType<typeof editFor>>) =>
    setEdits((current) => ({
      ...current,
      [id]: {
        ...editFor(agentRows.find((item) => item.discovery_id === id)!),
        ...value,
      },
    }));
  const resolve = async (
    item: SmartLivingProvisioningPreview['agents'][number],
  ) => {
    const form = editFor(item);
    if (!form.agent_name || !form.branch_id || !form.manager_id) {
      toast.error('Name, branch and manager are required to resolve an agent.');
      return;
    }
    setBusy(true);
    try {
      await smartLivingIntegrationApi.resolveProvisioningAgent(
        item.discovery_id,
        form,
      );
      toast.success('Agent issue resolved and eligibility re-evaluated.');
      await onRefresh();
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : 'Unable to resolve agent.',
      );
    } finally {
      setBusy(false);
    }
  };
  const provision = async (all = false) => {
    if (!all && !selected.size) {
      toast.error('Select at least one Eligible agent.');
      return;
    }
    const discoveryIds = all
      ? eligible.map((item) => item.discovery_id)
      : [...selected];
    const batchSize = 10;
    const totals = { created: 0, linked: 0, skipped: 0, failed: 0 };
    let completed = 0;
    setBusy(true);
    setCredentials([]);
    setProvisioningProgress({ completed: 0, total: discoveryIds.length });
    try {
      for (let offset = 0; offset < discoveryIds.length; offset += batchSize) {
        const chunk = discoveryIds.slice(offset, offset + batchSize);
        const response = await smartLivingIntegrationApi.provisionAgents({
          discovery_ids: chunk,
        });
        const result = response.data.provisioning;
        totals.created += result.created;
        totals.linked += result.linked;
        totals.skipped += result.skipped;
        totals.failed += result.failed;
        const createdCredentials = result.results.filter(
          (item) => item.outcome === 'created' && item.temporary_password,
        );
        if (createdCredentials.length) {
          setCredentials((current) => [...current, ...createdCredentials]);
        }
        completed = Math.min(offset + chunk.length, discoveryIds.length);
        setProvisioningProgress({ completed, total: discoveryIds.length });
      }
      toast.success(
        `Created ${totals.created}; linked ${totals.linked}; skipped ${totals.skipped}; failed ${totals.failed}.`,
      );
      setSelected(new Set());
      await onRefresh();
    } catch (error) {
      toast.error(
        `${completed} of ${discoveryIds.length} agents completed. ${
          error instanceof Error ? error.message : 'Unable to provision the next batch.'
        } Safe completed batches were kept; retry to continue.`,
      );
    } finally {
      setBusy(false);
      setProvisioningProgress(null);
    }
  };
  const reissuePendingCredentials = async () => {
    if (!pendingCredentials.length) return;
    if (!window.confirm(
      `Generate replacement credentials for ${pendingCredentials.length} never-logged-in agents? Previously issued temporary passwords will stop working.`,
    )) return;
    setBusy(true);
    setCredentials([]);
    let completed = 0;
    try {
      for (let offset = 0; offset < pendingCredentials.length; offset += 10) {
        const chunk = pendingCredentials.slice(offset, offset + 10);
        const response = await smartLivingIntegrationApi.reissueAgentCredentials(
          chunk.map((item) => item.user_id!),
        );
        setCredentials((current) => [
          ...current,
          ...response.data.credential_reissue.credentials,
        ]);
        completed += chunk.length;
        setProvisioningProgress({ completed, total: pendingCredentials.length });
      }
      toast.success(`Replacement credentials generated for ${completed} agents.`);
      await onRefresh();
    } catch (error) {
      toast.error(`${completed} of ${pendingCredentials.length} credentials regenerated. ${
        error instanceof Error ? error.message : 'Unable to regenerate the next batch.'
      }`);
    } finally {
      setBusy(false);
      setProvisioningProgress(null);
    }
  };
  return (
    <section className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Metric label="Eligible" value={preview.counts?.eligible ?? 0} />
        <Metric label="Existing" value={preview.counts?.existing ?? 0} />
        <Metric
          label="Needs Review"
          value={preview.counts?.needs_review ?? 0}
        />
        <Metric
          label="Ignored / inactive"
          value={preview.counts?.ignored_inactive ?? 0}
        />
        <Metric label="Provisioned" value={preview.counts?.provisioned ?? 0} />
      </div>
      <div className="rounded-xl border bg-white p-4">
        <label
          htmlFor="agent-provisioning-search"
          className="mb-2 block text-sm font-medium text-slate-700"
        >
          Search agents
        </label>
        <input
          id="agent-provisioning-search"
          type="search"
          value={searchQuery}
          onChange={(event) => setSearchQuery(event.target.value)}
          placeholder="Search by agent name, username, branch, manager, or status"
          className="min-h-11 w-full rounded-lg border border-slate-300 px-3 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
        />
        <p className="mt-2 text-xs text-slate-500" aria-live="polite">
          Showing {visibleAgentRows.length} of {agentRows.length} agents
        </p>
      </div>
      <ProvisionedLoginAccounts accounts={linkedLoginAccounts} />
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-white p-4">
        <p className="text-sm text-slate-600">
          {provisioningProgress
            ? `Provisioning ${provisioningProgress.completed} of ${provisioningProgress.total} eligible agents…`
            : 'Only Eligible agents can be provisioned. New accounts receive a temporary password reminder.'}
        </p>
        <div className="flex gap-2">
          <button
            disabled={busy || !eligible.length}
            onClick={() =>
              setSelected(new Set(eligible.map((item) => item.discovery_id)))
            }
            className="rounded-lg border px-3 py-2 text-sm disabled:opacity-50"
          >
            Select all eligible
          </button>
          <button
            disabled={busy || !selected.size}
            onClick={() => void provision(false)}
            className="rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {busy && provisioningProgress
              ? `Provisioning ${provisioningProgress.completed}/${provisioningProgress.total}`
              : 'Provision selected'}
          </button>
          <button
            disabled={busy || !eligible.length}
            onClick={() => void provision(true)}
            className="rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            Provision Eligible Agents ({preview.counts?.eligible ?? 0})
          </button>
          <button
            disabled={busy || !pendingCredentials.length}
            onClick={() => void reissuePendingCredentials()}
            className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm font-medium text-amber-900 disabled:opacity-50"
          >
            Reissue pending credentials ({pendingCredentials.length})
          </button>
        </div>
      </div>
      <Dialog
        open={credentials.length > 0}
        onOpenChange={(open) => {
          if (!open) setCredentials([]);
        }}
      >
        <DialogContent className="max-h-[90vh] max-w-5xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Field Agent accounts created</DialogTitle>
            <DialogDescription>
              Copy these temporary credentials now. Passwords are shown only
              in this response and cannot be retrieved later. Each agent must
              change their password at first login.
            </DialogDescription>
          </DialogHeader>
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full min-w-[900px] text-left text-sm">
              <thead className="bg-slate-50 text-slate-600">
                <tr>
                  <th className="p-3">Name</th>
                  <th className="p-3">Username</th>
                  <th className="p-3">Branch</th>
                  <th className="p-3">Manager</th>
                  <th className="p-3">Role</th>
                  <th className="p-3">Status</th>
                  <th className="p-3">Temporary Password</th>
                </tr>
              </thead>
              <tbody>
                {credentials.map((item) => (
                  <tr key={item.user_id || item.discovery_id} className="border-t">
                    <td className="p-3 font-medium">{item.name}</td>
                    <td className="p-3">
                      <div className="flex items-center gap-2">
                        <code className="rounded bg-blue-50 px-2 py-1 font-semibold text-blue-900">
                          {item.username}
                        </code>
                        <button
                          type="button"
                          className="rounded border px-2 py-1 text-xs"
                          onClick={() => {
                            void navigator.clipboard.writeText(item.username || '');
                            toast.success(`Username copied for ${item.name}.`);
                          }}
                        >
                          Copy Username
                        </button>
                      </div>
                    </td>
                    <td className="p-3">{item.branch_name}</td>
                    <td className="p-3">{item.manager_name}</td>
                    <td className="p-3">{item.role || 'Field Agent'}</td>
                    <td className="p-3 capitalize">
                      {item.account_status || 'active'}
                    </td>
                    <td className="p-3">
                      <div className="flex items-center gap-2">
                        <code className="rounded bg-slate-100 px-2 py-1">
                          {item.temporary_password}
                        </code>
                        <button
                          type="button"
                          className="rounded border px-2 py-1 text-xs"
                          onClick={() => {
                            void navigator.clipboard.writeText(
                              item.temporary_password || '',
                            );
                            toast.success(`Password copied for ${item.name}.`);
                          }}
                        >
                          Copy Password
                        </button>
                        <button
                          type="button"
                          className="rounded border px-2 py-1 text-xs"
                          onClick={() => {
                            void navigator.clipboard.writeText(
                              `Username: ${item.username}\nTemporary password: ${item.temporary_password}`,
                            );
                            toast.success(`Credentials copied for ${item.name}.`);
                          }}
                        >
                          Copy Credentials
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </DialogContent>
      </Dialog>
      {visibleGroups.map((group) => (
        <div
          key={group.branch_name}
          className="overflow-x-auto rounded-xl border bg-white"
        >
          <div className="border-b bg-slate-50 px-4 py-3 font-semibold text-slate-800">
            {group.branch_name}
          </div>
          <table className="w-full min-w-[1300px] text-left text-sm">
            <thead className="text-slate-600">
              <tr>
                <th className="p-3">Select</th>
                <th className="p-3">Agent</th>
                <th className="p-3">Direct Source Branch</th>
                <th className="p-3">Confirmed Manager</th>
                <th className="p-3">Manager Branch</th>
                <th className="p-3">Existing FleetOps Account</th>
                <th className="p-3">Conflict Reason</th>
                <th className="p-3">Resolution Action</th>
              </tr>
            </thead>
            <tbody>
              {(Array.isArray(group.agents) ? group.agents : []).map((item) => {
                const form = editFor(item);
                const needs = item.status === 'needs_review';
                return (
                  <tr key={item.discovery_id} className="border-t align-top">
                    <td className="p-3">
                      <input
                        type="checkbox"
                        aria-label={`Select ${item.name || 'agent identity'}`}
                        disabled={item.status !== 'eligible' || busy}
                        checked={selected.has(item.discovery_id)}
                        onChange={() => {
                          const next = new Set(selected);
                          next.has(item.discovery_id)
                            ? next.delete(item.discovery_id)
                            : next.add(item.discovery_id);
                          setSelected(next);
                        }}
                      />
                    </td>
                    <td className="p-3">
                      <div className="font-medium">
                        {item.name || 'Agent identity missing'}
                      </div>
                      {!item.name && (
                        <p className="mt-1 max-w-64 text-xs text-amber-700">
                          Agent identity missing. SmartLiving has no current
                          readable agent name; confirm it before linking or
                          creating an account.
                        </p>
                      )}
                      <div className="text-xs text-slate-500">Field Agent</div>
                      <AgentTechnicalDetails item={item} />
                    </td>
                    <td className="p-3">
                      <div>{item.source_direct_branch || 'Not supplied'}</div>
                      <div className="text-xs text-slate-500">
                        Confirmed branch: {item.branch_name || 'Unresolved'}
                      </div>
                    </td>
                    <td className="p-3">
                      {item.confirmed_manager_name ||
                        item.manager_name ||
                        'Manager unresolved'}
                      {item.source_manager_name && (
                        <div className="text-xs text-slate-500">
                          SmartLiving: {item.source_manager_name}
                        </div>
                      )}
                    </td>
                    <td className="p-3">
                      {item.manager_branch_name || 'Manager branch unresolved'}
                    </td>
                    <td className="p-3">
                      {item.fleetops_user_name || item.username || (
                        <span className="text-slate-500">
                          No existing account
                        </span>
                      )}
                    </td>
                    <td className="p-3">
                      <div
                        className={
                          item.status === 'eligible'
                            ? 'font-medium text-emerald-700'
                            : item.status === 'needs_review'
                              ? 'font-medium text-amber-700'
                              : 'font-medium text-slate-700'
                        }
                      >
                        {item.status.replaceAll('_', ' ')}
                      </div>
                      <div className="text-xs text-slate-600">
                        {(Array.isArray(item.error_codes)
                          ? item.error_codes
                          : []
                        )
                          .join(', ')
                          .replaceAll('_', ' ') || 'None'}
                      </div>
                      {(Array.isArray(item.reasons) ? item.reasons : [])
                        .length > 0 && (
                        <div className="text-xs text-slate-500">
                          {(Array.isArray(item.reasons) ? item.reasons : [])
                            .join(', ')
                            .replaceAll('_', ' ')}
                        </div>
                      )}
                      {item.must_change_password && (
                        <div className="text-xs text-amber-700">
                          Password change reminder active
                        </div>
                      )}
                    </td>
                    <td className="p-3">
                      {needs ? (
                        <div className="grid gap-2">
                          <input
                            aria-label="Confirmed agent name"
                            value={form.agent_name}
                            onChange={(event) =>
                              update(item.discovery_id, {
                                agent_name: event.target.value,
                              })
                            }
                            placeholder="Readable agent name"
                            className="min-h-10 rounded border px-2"
                          />
                          <select
                            aria-label="Confirmed agent branch"
                            value={form.branch_id}
                            onChange={(event) =>
                              update(item.discovery_id, {
                                branch_id: event.target.value,
                                manager_id: '',
                              })
                            }
                            className="min-h-10 rounded border px-2"
                          >
                            <option value="">Select branch</option>
                            {branches.map((branch) => (
                              <option key={branch.id} value={branch.id}>
                                {branch.name}
                              </option>
                            ))}
                          </select>
                          <select
                            aria-label="Confirmed agent manager"
                            value={form.manager_id}
                            onChange={(event) =>
                              update(item.discovery_id, {
                                manager_id: event.target.value,
                              })
                            }
                            className="min-h-10 rounded border px-2"
                          >
                            <option value="">Select branch manager</option>
                            {managers
                              .filter(
                                (manager) =>
                                  manager.primary_branch_id === form.branch_id,
                              )
                              .map((manager) => (
                                <option key={manager.id} value={manager.id}>
                                  {manager.name}
                                </option>
                              ))}
                          </select>
                          <select
                            aria-label="Existing FleetOps agent"
                            value={form.fleetops_user_id}
                            onChange={(event) =>
                              update(item.discovery_id, {
                                fleetops_user_id: event.target.value,
                              })
                            }
                            className="min-h-10 rounded border px-2"
                          >
                            <option value="">
                              Create new account after resolution
                            </option>
                            {existingAgents
                              .filter(
                                (agent) =>
                                  agent.primary_branch_id === form.branch_id,
                              )
                              .map((agent) => (
                                <option key={agent.id} value={agent.id}>
                                  Link {agent.name}
                                </option>
                              ))}
                          </select>
                          <button
                            disabled={busy}
                            onClick={() => void resolve(item)}
                            className="rounded bg-amber-600 px-3 py-2 font-medium text-white disabled:opacity-50"
                          >
                            {form.fleetops_user_id
                              ? 'Link Existing and Resolve'
                              : 'Resolve for Create New'}
                          </button>
                        </div>
                      ) : (
                        <span className="text-xs text-slate-500">
                          {item.resolved_at
                            ? `Resolved ${new Date(item.resolved_at).toLocaleString()}`
                            : 'No action required'}
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ))}
      {!agentRows.length && (
        <Empty
          icon={<Clock3 />}
          text="Run Scan Values to discover SmartLiving agents."
        />
      )}
      {agentRows.length > 0 && !visibleAgentRows.length && (
        <Empty
          icon={<Clock3 />}
          text={`No agents match “${searchQuery.trim()}”.`}
        />
      )}
    </section>
  );
}

function AgentTechnicalDetails({
  item,
}: {
  item: SmartLivingProvisioningPreview['agents'][number];
}) {
  const directBranches = Array.isArray(item.source_direct_branch_options)
    ? item.source_direct_branch_options
    : [];
  const managerBranches = Array.isArray(item.source_manager_branch_options)
    ? item.source_manager_branch_options
    : [];
  return (
    <details className="mt-1 text-xs text-slate-500">
      <summary className="cursor-pointer">Technical Details</summary>
      <div className="mt-1 space-y-0.5">
        <div>SmartLiving agent ID: {item.agent_id || 'Not provided'}</div>
        {item.user_id && <div>FleetOps user ID: {item.user_id}</div>}
        {item.manager_id && <div>FleetOps manager ID: {item.manager_id}</div>}
        {directBranches.length > 1 && (
          <div>Agent branch references: {directBranches.join(', ')}</div>
        )}
        {managerBranches.length > 1 && (
          <div>Manager branch references: {managerBranches.join(', ')}</div>
        )}
      </div>
    </details>
  );
}

function ActionButton({
  label,
  loading,
  onClick,
  primary = false,
}: {
  label: string;
  loading: boolean;
  onClick: () => void | Promise<void>;
  primary?: boolean;
}) {
  return (
    <button
      onClick={() => void onClick()}
      disabled={loading}
      className={`inline-flex min-h-11 items-center gap-2 rounded-lg px-4 text-sm font-medium disabled:opacity-50 ${primary ? 'bg-blue-600 text-white' : 'border bg-white text-slate-700'}`}
    >
      <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
      {label}
    </button>
  );
}
function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-xl border bg-white p-4">
      <div className="text-2xl font-semibold text-slate-900">{value}</div>
      <div className="text-sm text-slate-500">{label}</div>
    </div>
  );
}
function Empty({ icon, text }: { icon: ReactNode; text: string }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-xl border bg-white p-10 text-slate-500">
      {icon}
      <p>{text}</p>
    </div>
  );
}

function ConnectionPanel({
  status,
  testing,
  onTest,
}: {
  status: SmartLivingConnectionStatus | null;
  testing: boolean;
  onTest: () => void;
}) {
  return (
    <section
      className={`rounded-xl border p-4 ${status?.connection_status === 'connected' ? 'border-emerald-200 bg-emerald-50' : status?.connection_status === 'failed' ? 'border-red-200 bg-red-50' : 'border-amber-200 bg-amber-50'}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex gap-3">
          {status?.connection_status === 'connected' ? (
            <CheckCircle2 className="mt-0.5 h-5 w-5 text-emerald-700" />
          ) : (
            <Clock3 className="mt-0.5 h-5 w-5 text-amber-700" />
          )}
          <div>
            <h2 className="font-semibold text-slate-950">
              {status?.connection_status === 'connected'
                ? 'Connected'
                : status?.connection_status === 'failed'
                  ? 'Connection failed'
                  : status?.configured
                    ? 'Connection not tested'
                    : 'Connection not configured'}
            </h2>
            <p className="mt-1 text-sm text-slate-700">
              Controlled manual preview and selected import only. Automatic sync
              remains disabled.
            </p>
            {status?.last_checked && (
              <p className="mt-1 text-xs text-slate-500">
                Last checked {new Date(status.last_checked).toLocaleString()}
              </p>
            )}
          </div>
        </div>
        <button
          onClick={onTest}
          disabled={!status?.configured || testing}
          className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {testing ? 'Testing…' : 'Test Connection'}
        </button>
      </div>
    </section>
  );
}

function DiscoveredMappings({
  items,
  mappings,
  targets,
  selected,
  onSelect,
  onConfirm,
}: {
  items: SmartLivingDiscovery[];
  mappings: IntegrationMapping[];
  targets: Array<{ id: string; name: string }>;
  selected: Record<string, string>;
  onSelect: (id: string, value: string) => void;
  onConfirm: (item: SmartLivingDiscovery) => void;
}) {
  return (
    <div className="rounded-xl border bg-white p-4">
      <h2 className="font-semibold text-slate-900">
        Discovered external values
      </h2>
      <p className="text-sm text-slate-500">
        Select and confirm a FleetOps target. Names are never matched
        automatically.
      </p>
      <div className="mt-3 space-y-2">
        {items.map((item) => {
          const mapped = mappings.find(
            (mapping) =>
              (mapping.external_id || mapping.external_code || '')
                .trim()
                .toLocaleLowerCase() === item.external_key,
          );
          return (
            <div
              key={item.id}
              className="grid gap-2 rounded-lg border p-3 md:grid-cols-[1fr_1fr_auto]"
            >
              <div>
                <div className="font-medium">
                  {item.external_display_name || 'Name unavailable'}
                </div>
                {item.discovery_type === 'agent' ? (
                  <AgentRelationship item={item} />
                ) : (
                  item.branch_name && (
                    <div className="text-xs text-slate-600">
                      {item.branch_name}
                    </div>
                  )
                )}
                <div className="text-xs text-slate-500">
                  Seen {item.seen_count} times
                </div>
                <SourceIdentity
                  id={item.external_id || item.external_code}
                  relationship={item.relationship}
                />
              </div>
              {mapped ? (
                <div className="self-center text-sm text-emerald-700">
                  Mapping confirmed
                </div>
              ) : (
                <select
                  value={selected[item.id] || ''}
                  onChange={(event) => onSelect(item.id, event.target.value)}
                  className="min-h-10 rounded-lg border px-3"
                >
                  <option value="">Select FleetOps target</option>
                  {targets.map((target) => (
                    <option key={target.id} value={target.id}>
                      {target.name}
                    </option>
                  ))}
                </select>
              )}
              <button
                disabled={Boolean(mapped)}
                onClick={() => onConfirm(item)}
                className="rounded-lg border px-3 py-2 text-sm disabled:opacity-50"
              >
                {mapped ? 'Confirmed' : 'Confirm mapping'}
              </button>
            </div>
          );
        })}
        {!items.length && (
          <p className="py-6 text-center text-sm text-slate-500">
            Run Scan Values to discover external records.
          </p>
        )}
      </div>
    </div>
  );
}

function AgentRelationship({ item }: { item: SmartLivingDiscovery }) {
  const relation = item.relationship;
  if (!relation)
    return <div className="text-xs text-amber-700">Needs Review</div>;
  const agent =
    relation.agent_display_name ||
    item.external_display_name ||
    'Agent name unavailable';
  const manager = relation.manager_display_name || 'Manager name unavailable';
  const branch = relation.external_branch || 'Branch unavailable';
  const label = relation.status === 'resolved' ? 'Resolved' : 'Needs Review';
  const tone =
    relation.status === 'resolved' ? 'text-emerald-700' : 'text-amber-700';
  return (
    <div className="mt-1">
      <div className="text-xs text-slate-700">
        {agent} → {manager} → {branch}
      </div>
      <div className={`text-xs font-medium ${tone}`}>{label}</div>
    </div>
  );
}

function SourceIdentity({
  id,
  relationship,
}: {
  id?: string | null;
  relationship?: SmartLivingDiscovery['relationship'];
}) {
  return (
    <details className="mt-1 text-xs text-slate-500">
      <summary className="cursor-pointer">Source details</summary>
      <div className="mt-1 space-y-0.5">
        <div>Source ID: {id || 'Not provided'}</div>
        {relationship?.agent_id && <div>Agent ID: {relationship.agent_id}</div>}
        {relationship?.manager_id && (
          <div>Manager ID: {relationship.manager_id}</div>
        )}
        {relationship?.external_branch && (
          <div>Branch reference: {relationship.external_branch}</div>
        )}
        {relationship?.fleetops_branch_id && (
          <div>FleetOps Branch ID: {relationship.fleetops_branch_id}</div>
        )}
      </div>
    </details>
  );
}

function PreviewPeriodDialog({
  open,
  controls,
  error,
  running,
  onOpenChange,
  onChange,
  onQuickOption,
  onPreview,
}: {
  open: boolean;
  controls: SmartLivingIntakeControls;
  error: string;
  running: boolean;
  onOpenChange: (open: boolean) => void;
  onChange: (value: SmartLivingIntakeControls) => void;
  onQuickOption: (value: SmartLivingIntakeControls['quick_option']) => void;
  onPreview: () => void | Promise<void>;
}) {
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!running) onOpenChange(next);
      }}
    >
      <DialogContent className="bg-white sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Preview SmartLiving deliveries</DialogTitle>
          <DialogDescription>
            Select the inclusive source completion or closure date range to
            scan. This preview never imports deliveries.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <label className="block text-sm font-medium text-slate-700">
            Source
            <select
              value={controls.source}
              onChange={(event) =>
                onChange({
                  ...controls,
                  source: event.target
                    .value as SmartLivingIntakeControls['source'],
                })
              }
              className="mt-1 block min-h-11 w-full rounded-lg border px-3"
            >
              <option value="completed-cards">Completed cards</option>
              <option value="closed-cards">Closed cards</option>
              <option value="both">Both</option>
            </select>
          </label>
          <div className="flex flex-wrap gap-2" aria-label="Date range presets">
            {(
              [
                ['today', 'Today'],
                ['this_week', 'This Week'],
                ['last_week', 'Last Week'],
                ['custom', 'Custom'],
              ] as const
            ).map(([value, label]) => (
              <button
                type="button"
                key={value}
                onClick={() => onQuickOption(value)}
                className={`rounded-full px-3 py-1.5 text-sm ${controls.quick_option === value ? 'bg-blue-100 text-blue-800' : 'border text-slate-600'}`}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="text-sm font-medium text-slate-700">
              From Date<span className="text-red-600"> *</span>
              <input
                required
                aria-label="From Date"
                type="date"
                value={controls.from_date}
                onChange={(event) =>
                  onChange({
                    ...controls,
                    from_date: event.target.value,
                    quick_option: 'custom',
                  })
                }
                className="mt-1 block min-h-11 w-full rounded-lg border px-3"
              />
            </label>
            <label className="text-sm font-medium text-slate-700">
              To Date<span className="text-red-600"> *</span>
              <input
                required
                aria-label="To Date"
                type="date"
                value={controls.to_date}
                onChange={(event) =>
                  onChange({
                    ...controls,
                    to_date: event.target.value,
                    quick_option: 'custom',
                  })
                }
                className="mt-1 block min-h-11 w-full rounded-lg border px-3"
              />
            </label>
          </div>
          {error && (
            <div
              role="alert"
              className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"
            >
              {error}
            </div>
          )}
          <p className="text-xs text-slate-500">
            Completed cards use created_at; closed cards use at. SmartLiving
            completion means ready for FleetOps physical delivery processing.
          </p>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              disabled={running}
              onClick={() => onOpenChange(false)}
              className="rounded-lg border px-4 py-2 text-sm disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => void onPreview()}
              disabled={running}
              className="inline-flex min-w-40 items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              {running && <RefreshCw className="h-4 w-4 animate-spin" />}
              {running ? 'Scanning…' : 'Preview Deliveries'}
            </button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function resolutionAction(reasons: string[]) {
  if (reasons.includes('unmapped_agent')) return 'Link or provision the SmartLiving agent.';
  if (reasons.includes('unmapped_manager')) return 'Link the SmartLiving manager identity.';
  if (reasons.includes('unmapped_branch') || reasons.includes('missing_branch')) return 'Confirm the SmartLiving branch mapping.';
  if (reasons.includes('missing_product_name') || reasons.includes('missing_product') || reasons.includes('missing_quantity')) return 'Correct the product and quantity in SmartLiving.';
  if (reasons.some((reason) => reason.startsWith('missing_customer'))) return 'Complete the customer contact and delivery location in SmartLiving.';
  if (reasons.includes('invalid_source_date')) return 'Correct the source record date in SmartLiving.';
  if (reasons.includes('duplicate')) return 'This source record is already present in FleetOps.';
  if (reasons.includes('unsupported_status') || reasons.includes('unsupported_action')) return 'Use a supported SmartLiving delivery record.';
  return null;
}

function DryRunPanel({
  dryRun,
  selected,
  onSelected,
  onImport,
  importing,
}: {
  dryRun: SmartLivingDryRun | null;
  selected: Set<string>;
  onSelected: (value: Set<string>) => void;
  onImport: () => void | Promise<void>;
  importing: boolean;
}) {
  if (!dryRun)
    return (
      <Empty
        icon={<Clock3 />}
        text="Choose a source and period to preview mappings, eligibility, duplicates, and errors."
      />
    );
  const ready = dryRun.records.filter((record) => record.import_eligible);
  const allReadySelected =
    ready.length > 0 &&
    ready.every((record) => selected.has(record.selected_key));
  const toggle = (record: SmartLivingPreviewRecord) => {
    const next = new Set(selected);
    if (next.has(record.selected_key)) next.delete(record.selected_key);
    else next.add(record.selected_key);
    onSelected(next);
  };
  return (
    <section className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Metric label="Scanned" value={dryRun.total_scanned} />
        <Metric label="Eligible" value={dryRun.eligible} />
        <Metric label="Ready" value={dryRun.ready} />
        <Metric label="Blocked" value={dryRun.blocked} />
        <Metric label="Already imported" value={dryRun.already_imported} />
        <Metric label="Unmapped branch" value={dryRun.unmapped_branches} />
        <Metric label="Unmapped agent" value={dryRun.unmapped_agents} />
        <Metric label="Invalid / ignored" value={dryRun.invalid_ignored} />
        <Metric label="Created by preview" value={dryRun.deliveries_created} />
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-white p-4">
        <div className="text-sm text-slate-600">
          {dryRun.controls.source} · {dryRun.controls.from_date} to{' '}
          {dryRun.controls.to_date} · {selected.size} selected
        </div>
        <div className="flex gap-2">
          <button
            disabled={!ready.length}
            onClick={() =>
              onSelected(
                allReadySelected
                  ? new Set()
                  : new Set(ready.map((record) => record.selected_key)),
              )
            }
            className="rounded-lg border px-3 py-2 text-sm disabled:opacity-50"
          >
            {allReadySelected ? 'Clear ready' : 'Select all ready'}
          </button>
          <button
            disabled={!selected.size || importing}
            onClick={() => void onImport()}
            className="rounded-lg bg-emerald-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {importing ? 'Importing…' : 'Import selected READY'}
          </button>
        </div>
      </div>
      <div className="overflow-x-auto rounded-xl border bg-white">
        <table className="min-w-[1100px] w-full text-left text-sm">
          <thead className="bg-slate-50 text-slate-600">
            <tr>
              <th className="p-3">Select</th>
              <th className="p-3">Customer</th>
              <th className="p-3">Product / qty</th>
              <th className="p-3">Branch</th>
              <th className="p-3">Agent / manager</th>
              <th className="p-3">Source status / date</th>
              <th className="p-3">Mapping</th>
              <th className="p-3">Import eligibility</th>
            </tr>
          </thead>
          <tbody>
            {dryRun.records.map((record) => (
              <tr key={record.selected_key} className="border-t align-top">
                <td className="p-3">
                  <input
                    type="checkbox"
                    aria-label={`Select ${record.source_record_id}`}
                    checked={selected.has(record.selected_key)}
                    disabled={!record.import_eligible}
                    onChange={() => toggle(record)}
                  />
                </td>
                <td className="p-3">
                  <div className="font-medium">
                    {record.customer_name || 'Not provided'}
                  </div>
                  <div className="text-xs">
                    {record.customer_phone ? (
                      <a
                        className="text-blue-700 hover:underline"
                        href={`tel:${record.customer_phone.replace(/[^\d+]/g, '')}`}
                      >
                        {record.customer_phone}
                      </a>
                    ) : (
                      <span className="text-slate-500">Not provided</span>
                    )}
                  </div>
                  <div className="text-xs text-slate-500">
                    {record.customer_location || 'Not provided'}
                  </div>
                  <div className="text-xs text-slate-500">
                    {record.customer_occupation || 'Not provided'}
                  </div>
                  <CustomerDetails record={record} />
                </td>
                <td className="p-3">
                  {record.products.length
                    ? record.products.map((product, index) => (
                        <div key={`${product.reference}-${index}`}>
                          {product.name || 'Not provided'} ×{' '}
                          {product.quantity || 'Not provided'}
                        </div>
                      ))
                    : 'Not provided'}
                </td>
                <td className="p-3">
                  {record.branch_name ||
                    record.external_branch ||
                    'Not provided'}
                </td>
                <td className="p-3">
                  <div>
                    {record.external_agent_name || 'Agent name unavailable'}
                  </div>
                  <div className="text-xs text-slate-500">
                    Manager:{' '}
                    {record.relationship?.manager_display_name ||
                      'Manager name unavailable'}
                  </div>
                  {record.relationship?.status !== 'resolved' && (
                    <div className="text-xs font-medium text-amber-700">
                      Needs Review
                    </div>
                  )}
                </td>
                <td className="p-3">
                  <div>
                    {sourceLabel(record.source_endpoint)} ·{' '}
                    {record.source_status_label ||
                      record.source_status?.replaceAll('_', ' ') ||
                      'Not provided'}
                  </div>
                  <div className="text-xs text-slate-500">
                    {record.source_date
                      ? new Date(record.source_date).toLocaleString()
                      : 'Not provided'}
                  </div>
                </td>
                <td className="p-3 capitalize">
                  {record.mapping_status.replaceAll('_', ' ')}
                </td>
                <td className="p-3">
                  <div
                    className={
                      record.import_eligible
                        ? 'font-medium text-emerald-700'
                        : 'font-medium text-amber-700'
                    }
                  >
                    {record.import_eligible
                      ? 'READY'
                      : record.outcome.replaceAll('_', ' ').toUpperCase()}
                  </div>
                  {record.reasons.length > 0 && (
                    <div className="mt-1 text-xs text-slate-500">
                      {record.reasons.join(', ').replaceAll('_', ' ')}
                    </div>
                  )}
                  {!record.import_eligible && resolutionAction(record.reasons) && (
                    <div className="mt-1 text-xs font-medium text-blue-700">
                      Action: {resolutionAction(record.reasons)}
                    </div>
                  )}
                </td>
              </tr>
            ))}
            {!dryRun.records.length && (
              <tr>
                <td colSpan={8} className="p-8 text-center text-slate-500">
                  No records found inside this period.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-slate-500">
        Dry run {new Date(dryRun.created_at).toLocaleString()}; no delivery
        orders were created.
      </p>
    </section>
  );
}

function CustomerDetails({ record }: { record: SmartLivingPreviewRecord }) {
  const status =
    record.source_status_label ||
    record.source_status?.replaceAll('_', ' ') ||
    'Not provided';
  return (
    <details className="mt-2 text-xs text-slate-600">
      <summary className="cursor-pointer font-medium text-blue-700">
        View Details
      </summary>
      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-2 gap-y-1 rounded-lg bg-slate-50 p-2">
        <dt>Name</dt>
        <dd>{record.customer_name || 'Not provided'}</dd>
        <dt>Phone</dt>
        <dd>
          {record.customer_phone ? (
            <a
              className="text-blue-700 hover:underline"
              href={`tel:${record.customer_phone.replace(/[^\d+]/g, '')}`}
            >
              {record.customer_phone}
            </a>
          ) : (
            'Not provided'
          )}
        </dd>
        <dt>Location</dt>
        <dd>{record.customer_location || 'Not provided'}</dd>
        <dt>Occupation</dt>
        <dd>{record.customer_occupation || 'Not provided'}</dd>
        <dt>Product / qty</dt>
        <dd>
          {record.products.length
            ? record.products.map((product, index) => (
                <div key={`${product.reference}-${index}`}>
                  {product.name || 'Not provided'} ×{' '}
                  {product.quantity || 'Not provided'}
                </div>
              ))
            : 'Not provided'}
        </dd>
        <dt>Branch</dt>
        <dd>
          {record.branch_name || record.external_branch || 'Not provided'}
        </dd>
        <dt>Agent</dt>
        <dd>{record.external_agent_name || 'Agent name unavailable'}</dd>
        <dt>Manager</dt>
        <dd>
          {record.relationship?.manager_display_name ||
            'Manager name unavailable'}
        </dd>
        <dt>Hierarchy</dt>
        <dd>
          {record.relationship?.status === 'resolved'
            ? 'Resolved'
            : 'Needs Review'}
        </dd>
        <dt>Status</dt>
        <dd>{status}</dd>
        <dt>Source date</dt>
        <dd>
          {record.source_date
            ? new Date(record.source_date).toLocaleString()
            : 'Not provided'}
        </dd>
      </dl>
      <SourceDetails record={record} />
    </details>
  );
}

function SourceDetails({ record }: { record: SmartLivingPreviewRecord }) {
  return (
    <details className="mt-2 text-xs text-slate-500">
      <summary className="cursor-pointer">Source details</summary>
      <div className="mt-1 space-y-0.5">
        <div>Source ID: {record.source_record_id}</div>
        {record.external_agent_id && (
          <div>Agent ID: {record.external_agent_id}</div>
        )}
        {record.relationship?.manager_id && (
          <div>Manager ID: {record.relationship.manager_id}</div>
        )}
        {record.relationship?.external_branch && (
          <div>Branch reference: {record.relationship.external_branch}</div>
        )}
        {record.relationship?.fleetops_branch_id && (
          <div>
            FleetOps Branch ID: {record.relationship.fleetops_branch_id}
          </div>
        )}
        {record.products.map(
          (product, index) =>
            product.reference && (
              <div key={`${product.reference}-${index}`}>
                Product ID: {product.reference}
              </div>
            ),
        )}
        <div>Date field: {record.source_date_field}</div>
      </div>
    </details>
  );
}
