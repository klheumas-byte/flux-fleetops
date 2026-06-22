from threading import Lock
from time import perf_counter, time

from flask import current_app


_ttl_cache: dict[str, tuple[float, object]] = {}
_ttl_cache_lock = Lock()


def build_cache_key(prefix: str, **kwargs) -> str:
    parts = [prefix]
    for key in sorted(kwargs):
        value = kwargs[key]
        if value is None:
            continue
        parts.append(f"{key}={value}")
    return "|".join(parts)


def get_ttl_cached(cache_key: str):
    now = time()
    with _ttl_cache_lock:
        cached = _ttl_cache.get(cache_key)
        if cached is None:
            return None
        expires_at, value = cached
        if expires_at <= now:
            _ttl_cache.pop(cache_key, None)
            return None
        return value


def set_ttl_cached(cache_key: str, value, *, ttl_seconds: int = 15):
    expires_at = time() + max(int(ttl_seconds), 1)
    with _ttl_cache_lock:
        _ttl_cache[cache_key] = (expires_at, value)
    return value


def log_db_duration(label: str, started_at: float) -> float:
    duration_ms = round((perf_counter() - started_at) * 1000, 2)
    current_app.logger.info("[Flux DB] %s duration_ms=%s", label, duration_ms)
    return duration_ms
