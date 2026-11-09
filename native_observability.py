"""Bounded, content-free process and AnyIO diagnostics for native health.

These process-local samples do not replace platform resource-gate evidence.
No request, player, borrower, environment, or credential values are returned.
"""
import math
import os
import sys

from anyio.to_thread import current_default_thread_limiter

try:
    import resource
except ImportError:  # Explicitly unavailable on platforms without getrusage.
    resource = None


def _cpu_usage_microseconds():
    if resource is None:
        return None
    try:
        usage = resource.getrusage(resource.RUSAGE_SELF)
        values = (usage.ru_utime, usage.ru_stime)
        if not all(math.isfinite(value) and value >= 0 for value in values):
            return None
        return {'user': int(values[0] * 1_000_000),
                'system': int(values[1] * 1_000_000)}
    except (AttributeError, OSError, TypeError, ValueError, OverflowError):
        return None


def _memory_rss_bytes():
    # ru_maxrss is a historical peak, not current RSS. Linux statm reports
    # current resident pages; its kernel counters are diagnostic estimates.
    if not sys.platform.startswith('linux'):
        return None
    try:
        with open('/proc/self/statm', 'rb') as statm:
            resident_pages = int(statm.read(256).split()[1])
        page_size = os.sysconf('SC_PAGE_SIZE')
        if resident_pages < 0 or page_size <= 0:
            return None
        return resident_pages * page_size
    except (AttributeError, OSError, IndexError, TypeError, ValueError):
        return None


def process_health():
    """Cumulative CPU for this process and current Linux RSS, or explicit null."""
    return {'cpu_usage_microseconds': _cpu_usage_microseconds(),
            'memory_rss_bytes': _memory_rss_bytes()}


async def thread_limiter_health():
    """Sample the serving event loop's default limiter without acquiring it.

    Used as an async health dependency so a synchronous health handler can
    include a real queue snapshot taken before its own worker admission.
    Never serialize CapacityLimiterStatistics.borrowers (task identities).
    """
    try:
        stats = current_default_thread_limiter().statistics()
        values = (stats.total_tokens, stats.borrowed_tokens, stats.tasks_waiting)
        if not all(isinstance(value, (int, float)) and not isinstance(value, bool)
                   and math.isfinite(value) and value >= 0 and int(value) == value
                   for value in values):
            return {'anyio_thread_limiter': None}
        sample = dict(zip(('total_tokens', 'borrowed_tokens', 'tasks_waiting'),
                          map(int, values)))
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError, OverflowError):
        sample = None
    return {'anyio_thread_limiter': sample}
