import { useEffect, useRef } from 'react';

export type DataResource =
  | 'vehicles'
  | 'vehicle_movements'
  | 'drivers'
  | 'users'
  | 'deliveries'
  | 'delivery_runs'
  | 'returns'
  | 'branches'
  | 'agents'
  | 'managers'
  | 'dispatch_opportunities'
  | 'notifications'
  | 'finance';

export type DataSyncEvent = {
  resources: DataResource[];
  path?: string;
  method?: string;
  timestamp: number;
};

const EVENT_NAME = 'flux-data-sync';

export function emitDataSync(resources: DataResource | DataResource[], detail: Omit<DataSyncEvent, 'resources' | 'timestamp'> = {}) {
  if (typeof window === 'undefined') return;
  const values = Array.isArray(resources) ? resources : [resources];
  window.dispatchEvent(new CustomEvent<DataSyncEvent>(EVENT_NAME, {
    detail: { ...detail, resources: [...new Set(values)], timestamp: Date.now() },
  }));
}

export function useDataSync(resources: DataResource | DataResource[], onChange: () => void) {
  const callback = useRef(onChange);
  callback.current = onChange;
  const keys = Array.isArray(resources) ? resources.join('|') : resources;
  useEffect(() => {
    const listen = (event: Event) => {
      const detail = (event as CustomEvent<DataSyncEvent>).detail;
      if (!detail?.resources?.some((resource) => resource === 'notifications' || keys.split('|').includes(resource))) return;
      callback.current();
    };
    window.addEventListener(EVENT_NAME, listen);
    return () => window.removeEventListener(EVENT_NAME, listen);
  }, [keys]);
}
