import { useCallback, useEffect, useRef, useState } from 'react';
import { apiRequest } from './api';
import type { AppModule } from './role-access';

export type ActionableNotificationCounts = {
  critical: number;
  action_required: number;
  reminders: number;
  total_actionable: number;
  completed_today: number;
  highest_priority: 'critical' | 'action_required' | 'reminder' | null;
};
type CountResponse = { data?: Partial<ActionableNotificationCounts> };
export type WorkQueueModuleCount = {
  status: 'ok' | 'error';
  count: number | null;
  priority: 'critical' | 'action_required' | 'reminder' | null;
  critical_count: number | null;
  latest_actionable?: { id: string; created_at?: string | null; priority: 'critical' | 'action_required' | 'reminder' } | null;
};
type WorkQueueResponse = { data?: { modules?: Record<string, WorkQueueModuleCount>; total_actionable?: number; highest_priority?: ActionableNotificationCounts['highest_priority'] } };

export const SIDEBAR_COUNT_KEY_BY_MODULE: Partial<Record<AppModule, string>> = {
  'dispatch-requests': 'dispatch_requests',
  'dispatch-planner': 'dispatch_planner',
  'dispatch-returns': 'vehicle_return',
  maintenance: 'maintenance_jobs',
  'preventive-maintenance': 'preventive_maintenance',
  'fault-approvals': 'fault_approvals',
  incidents: 'accidents_incidents',
  notifications: 'notifications',
  'my-dispatches': 'dispatch_planner',
  'my-vehicle': 'maintenance_jobs',
  'operational-requests': 'operational_requests',
  'stock-transfers': 'stock_transfers',
  'my-operational-tasks': 'operational_tasks',
};

const EMPTY_COUNTS: ActionableNotificationCounts = {
  critical: 0, action_required: 0, reminders: 0, total_actionable: 0,
  completed_today: 0, highest_priority: null,
};

export function useActionableNotificationCount() {
  const [counts, setCounts] = useState<ActionableNotificationCounts>(EMPTY_COUNTS);
  const [moduleCounts, setModuleCounts] = useState<Record<string, WorkQueueModuleCount>>({});
  const [isLoading, setIsLoading] = useState(true);
  const [countError, setCountError] = useState<string | null>(null);
  const latestActionableRef = useRef<{ id: string; created_at?: string | null } | null>(null);
  const refresh = useCallback(async (): Promise<boolean> => {
    try {
      const response = await apiRequest<WorkQueueResponse>('/notifications/work-queue-counts', {
        componentName: 'NotificationBadge',
        requestLabel: 'actionable-count',
        dedupeKey: 'notifications:actionable-count',
      });
      const modules = response.data?.modules || {};
      if (!Object.keys(modules).length) throw new Error('Work queue count response did not include module counts.');
      setModuleCounts(modules);
      setCountError(null);
      const notification = modules.notifications;
      const incomingAction = notification?.latest_actionable;
      const previousAction = latestActionableRef.current;
      if (
        previousAction && incomingAction?.id && incomingAction.id !== previousAction.id &&
        Date.parse(incomingAction.created_at || '') > Date.parse(previousAction.created_at || '')
      ) {
        window.dispatchEvent(new CustomEvent('flux-new-actionable-notification', { detail: incomingAction }));
      }
      latestActionableRef.current = incomingAction || previousAction;
      setCounts((current) => ({
        ...current,
        critical: Math.max(0, Number(notification?.critical_count) || 0),
        total_actionable: Math.max(0, Number(notification?.count) || 0),
        highest_priority: notification?.priority || null,
      }));
      return true;
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unable to load sidebar counts.';
      setCountError(message);
      console.error('[Flux Sidebar] Work queue count refresh failed', { message });
      // Preserve the last valid moduleCounts instead of replacing them with misleading zeros.
      return false;
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    let timer: number | undefined;
    let recoveryTimer: number | undefined;
    let cancelled = false;
    let lastRefresh = Date.now();
    const loadWithRecovery = async () => {
      const loaded = await refresh();
      if (!loaded && !cancelled) {
        // One bounded retry recovers when the API starts just after the UI. This is not polling.
        recoveryTimer = window.setTimeout(() => { if (!cancelled) void refresh(); }, 3000);
      }
    };
    void loadWithRecovery();
    const revalidate = (event?: Event) => {
      const path = (event as CustomEvent<{ path?: string }>)?.detail?.path || '';
      const moduleKey =
        /dispatch-opportunities\/.+\/(approve|reject|clarification)/.test(path) ? 'dispatch_requests' :
        /dispatch-requests\/.+\/(approve|reject)|dispatch\/requests\/.+\/pricing\/(approve|reject)/.test(path) ? 'dispatch_requests' :
        /dispatch-planner\/driver\/jobs\/.+\/(accept|reject)/.test(path) ? 'dispatch_planner' :
        /preventive-maintenance\/.+\/generate-maintenance-job/.test(path) ? 'preventive_maintenance' :
        /vehicle-movements\/.+\/review-maintenance-completion/.test(path) ? 'maintenance_jobs' :
        /dispatch\/returns\/.+\/confirm-return/.test(path) ? 'vehicle_return' : null;
      if (moduleKey) {
        setModuleCounts((current) => {
          const decrement = (key: string) => {
            const item = current[key];
            return item?.status === 'ok' && Number(item.count) > 0 ? { ...item, count: Number(item.count) - 1 } : item;
          };
          return { ...current, [moduleKey]: decrement(moduleKey), notifications: decrement('notifications') };
        });
        setCounts((current) => ({ ...current, total_actionable: Math.max(0, current.total_actionable - 1) }));
      }
      window.clearTimeout(timer);
      timer = window.setTimeout(() => { lastRefresh = Date.now(); void refresh(); }, 400);
    };
    const revalidateOnFocus = () => { if (Date.now() - lastRefresh > 30000) revalidate(); };
    const revalidateWhenVisible = () => { if (document.visibilityState === 'visible') revalidate(); };
    window.addEventListener('flux-notifications-changed', revalidate);
    window.addEventListener('focus', revalidateOnFocus);
    window.addEventListener('online', revalidate);
    document.addEventListener('visibilitychange', revalidateWhenVisible);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      window.clearTimeout(recoveryTimer);
      window.removeEventListener('flux-notifications-changed', revalidate);
      window.removeEventListener('focus', revalidateOnFocus);
      window.removeEventListener('online', revalidate);
      document.removeEventListener('visibilitychange', revalidateWhenVisible);
    };
  }, [refresh]);

  return { actionableCount: counts.total_actionable, actionableCounts: counts, moduleCounts, isLoading, countError, refreshActionableCount: refresh };
}
