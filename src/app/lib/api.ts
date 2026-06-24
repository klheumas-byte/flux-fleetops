function resolveApiBaseUrl() {
  const configured = import.meta.env.VITE_API_BASE_URL?.trim();
  if (configured) {
    return configured.replace(/\/+$/, '');
  }

  if (typeof window !== 'undefined') {
    const protocol = window.location.protocol || 'http:';
    const hostname = window.location.hostname || '127.0.0.1';
    return `${protocol}//${hostname}:5000/api`;
  }

  return 'http://127.0.0.1:5000/api';
}

const API_BASE_URL = resolveApiBaseUrl();

type ApiRequestOptions = Omit<RequestInit, 'headers'> & {
  headers?: Record<string, string>;
  timeoutMs?: number;
  cacheTtlMs?: number;
  dedupeKey?: string;
  componentName?: string;
  requestLabel?: string;
  cancelGroup?: string;
  replacePending?: boolean;
};

export type ApiResult<T> = {
  ok: true;
  data: T;
  error: null;
  status: number;
} | {
  ok: false;
  data: T;
  error: string;
  status: number | 'timeout' | 'network' | 'aborted';
};

const DEFAULT_TIMEOUT_MS = 15000;
const responseCache = new Map<string, { expiresAt: number; data: unknown }>();
const inflightRequests = new Map<string, Promise<unknown>>();
const requestControllers = new Map<string, AbortController>();
const activeCancelGroups = new Map<string, Set<string>>();

export class ApiRequestError extends Error {
  status: number;
  errors: any[];
  data: any;

  constructor(message: string, status: number, errors: any[] = [], data: any = null) {
    super(message);
    this.name = 'ApiRequestError';
    this.status = status;
    this.errors = errors;
    this.data = data;
  }
}

export function isRequestAborted(error: unknown) {
  return error instanceof ApiRequestError && error.status === -1;
}

function addControllerToGroup(groupKey: string | undefined, requestKey: string) {
  if (!groupKey) {
    return;
  }
  const nextGroup = activeCancelGroups.get(groupKey) || new Set<string>();
  nextGroup.add(requestKey);
  activeCancelGroups.set(groupKey, nextGroup);
}

function removeControllerFromGroup(groupKey: string | undefined, requestKey: string) {
  if (!groupKey) {
    return;
  }
  const currentGroup = activeCancelGroups.get(groupKey);
  if (!currentGroup) {
    return;
  }
  currentGroup.delete(requestKey);
  if (currentGroup.size === 0) {
    activeCancelGroups.delete(groupKey);
  }
}

function abortRequestGroup(groupKey: string) {
  const currentGroup = activeCancelGroups.get(groupKey);
  if (!currentGroup?.size) {
    return;
  }
  currentGroup.forEach((requestKey) => {
    const controller = requestControllers.get(requestKey);
    if (controller) {
      controller.abort('replaced');
    }
  });
  activeCancelGroups.delete(groupKey);
}

function normalizeErrorMessage(status: number, data: any, fallback?: string) {
  const rawMessage = String(data?.error || data?.message || fallback || '').trim();
  const lowerRawMessage = rawMessage.toLowerCase();

  if (lowerRawMessage.includes('vehicle id not found') || lowerRawMessage.includes('vehicle not found')) {
    return 'That vehicle could not be found. Please return to the vehicle list and try again.';
  }
  if (lowerRawMessage.includes('database error')) {
    return 'We could not complete that request right now. Please try again.';
  }
  if (data?.error) {
    return rawMessage;
  }
  if (data?.message) {
    return rawMessage;
  }

  if (status === 401) {
    return 'Your session has expired. Please log in again.';
  }
  if (status === 403) {
    return 'Access denied.';
  }
  if (status === 404) {
    return 'We could not find what you were looking for.';
  }
  if (status >= 500) {
    return 'Something went wrong on our side. Please try again.';
  }

  return fallback || 'Unable to complete the request right now.';
}

export async function apiRequest<T>(
  path: string,
  options: ApiRequestOptions = {},
): Promise<T> {
  const token = localStorage.getItem('flux_token')?.trim() || null;
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers || {}),
  };

  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  console.info('[Flux API] Request', {
    path,
    method: options.method || 'GET',
    hasToken: Boolean(token),
    componentName: options.componentName || null,
    requestLabel: options.requestLabel || null,
  });

  const method = options.method || 'GET';
  const requestUrl = `${API_BASE_URL}${path}`;
  const requestKey = options.dedupeKey || `${method}:${requestUrl}`;
  const cacheTtlMs = options.cacheTtlMs ?? 0;
  const startedAt = typeof performance !== 'undefined' ? performance.now() : Date.now();

  if (method === 'GET' && cacheTtlMs > 0) {
    const cached = responseCache.get(requestKey);
    if (cached && cached.expiresAt > Date.now()) {
      console.info('[Flux API] Cache hit', { path, method, cacheTtlMs });
      return cached.data as T;
    }
  }

  if (inflightRequests.has(requestKey)) {
    return inflightRequests.get(requestKey) as Promise<T>;
  }

  if (options.cancelGroup && options.replacePending) {
    abortRequestGroup(options.cancelGroup);
  }

  const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const timeoutHandle =
    controller && timeoutMs > 0
      ? window.setTimeout(() => controller.abort(), timeoutMs)
      : null;

  if (controller) {
    requestControllers.set(requestKey, controller);
    addControllerToGroup(options.cancelGroup, requestKey);
  }

  const requestPromise = (async () => {
    let response: Response;
    try {
      response = await fetch(requestUrl, {
        ...options,
        headers,
        signal: controller?.signal,
      });
    } catch (error) {
      const durationMs =
        (typeof performance !== 'undefined' ? performance.now() : Date.now()) - startedAt;
      const wasAborted = controller?.signal.aborted;
      const abortReason = controller?.signal.reason;
      const isReplaced = wasAborted && abortReason === 'replaced';
      const isTimeout = wasAborted && !isReplaced;
      console.error(
        isReplaced ? '[Flux API] Request aborted' : isTimeout ? '[Flux API] Timeout' : '[Flux API] Network error',
        {
        path,
        method,
        hasToken: Boolean(token),
        error,
        timeoutMs,
        componentName: options.componentName || null,
        requestLabel: options.requestLabel || null,
        durationMs: Number(durationMs.toFixed(2)),
        requestUrl,
        abortReason: abortReason || null,
      });
      throw new ApiRequestError(
        isReplaced
          ? 'Request aborted.'
          : isTimeout
          ? 'This is taking longer than expected. Please try again.'
          : error instanceof Error && error.message && error.message !== 'Failed to fetch'
            ? error.message
            : 'We could not connect right now. Please check your connection and try again.',
        isReplaced ? -1 : 0,
      );
    } finally {
      if (timeoutHandle !== null) {
        window.clearTimeout(timeoutHandle);
      }
    }

    const responseText = await response.text();
    let data: any = null;

    if (responseText) {
      try {
        data = JSON.parse(responseText);
      } catch {
        data = { message: responseText };
      }
    }

    if (!response.ok) {
      const message = normalizeErrorMessage(
        response.status,
        data,
        response.statusText || 'Unable to complete the request right now.',
      );
      console.error('[Flux API] Request failed', {
        path,
        method,
        status: response.status,
        hasToken: Boolean(token),
        message,
        data,
        componentName: options.componentName || null,
        requestLabel: options.requestLabel || null,
      });

      if (response.status === 401) {
        console.warn('[Flux API] Unauthorized response received. Stored token may be missing, expired, or invalid.');
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('flux-auth-expired'));
        }
      }

      throw new ApiRequestError(message, response.status, data?.errors || [], data);
    }

    if (data?.success === false) {
      const message = normalizeErrorMessage(response.status, data);
      console.error('[Flux API] Request returned unsuccessful payload', {
        path,
        method,
        status: response.status,
        message,
        data,
      });
      throw new ApiRequestError(message, response.status, data?.errors || [], data);
    }

    const durationMs =
      (typeof performance !== 'undefined' ? performance.now() : Date.now()) - startedAt;
    const logPayload = {
      path,
      method,
      status: response.status,
      durationMs: Number(durationMs.toFixed(2)),
      responseTimeHeader: response.headers.get('X-Response-Time-ms'),
      componentName: options.componentName || null,
      requestLabel: options.requestLabel || null,
    };
    if (durationMs > 1000) {
      console.warn('[Flux API] Slow request', logPayload);
    } else {
      console.info('[Flux API] Request successful', logPayload);
    }

    if (method === 'GET' && cacheTtlMs > 0) {
      responseCache.set(requestKey, {
        expiresAt: Date.now() + cacheTtlMs,
        data,
      });
    }

    return data as T;
  })();

  inflightRequests.set(requestKey, requestPromise);
  try {
    return await requestPromise;
  } finally {
    inflightRequests.delete(requestKey);
    requestControllers.delete(requestKey);
    removeControllerFromGroup(options.cancelGroup, requestKey);
  }
}

export async function apiRequestSafe<T>(
  path: string,
  options: ApiRequestOptions & { fallbackData: T },
): Promise<ApiResult<T>> {
  try {
    const data = await apiRequest<T>(path, options);
    return {
      ok: true,
      data,
      error: null,
      status: 200,
    };
  } catch (error) {
    const status =
      error instanceof ApiRequestError
        ? error.status === -1
          ? 'aborted'
          : error.status === 0
          ? /timed out/i.test(error.message)
            ? 'timeout'
            : 'network'
          : error.status
        : 'network';
    return {
      ok: false,
      data: options.fallbackData,
      error:
        error instanceof ApiRequestError
          ? error.message
          : 'We could not connect right now. Please check your connection and try again.',
      status,
    };
  }
}

export { API_BASE_URL };
