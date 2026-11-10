"""Apply the bounded native worker setting once on the serving event loop."""
import os

from anyio.to_thread import current_default_thread_limiter


def configure_native_worker_limit(environ=None):
    """Startup only: preserve the default 40 or explicitly select 40/80 workers.

    Validate before obtaining or modifying the loop's existing default limiter.
    The value is never included in an error, and no request path calls this.
    """
    value = (os.environ if environ is None else environ).get('NATIVE_THREAD_TOKENS', '40')
    if value not in ('40', '80'):
        raise RuntimeError('NATIVE_THREAD_TOKENS_INVALID')
    tokens = int(value)
    current_default_thread_limiter().total_tokens = tokens
    return tokens
