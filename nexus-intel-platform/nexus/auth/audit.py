import functools, json, time
from fastapi import Request
from nexus.deps import get_db_pool


def audit_log(action: str):
    """
    Decorator that writes an immutable audit record to audit_log table
    after each successful API action.

    Usage:
        @router.post("/ingest")
        @audit_log("INGEST")
        async def ingest_event(req: Request, ...):
            ...
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            request: Request = kwargs.get("request")
            t0       = time.monotonic()
            result   = await func(*args, **kwargs)
            duration = (time.monotonic() - t0) * 1000

            analyst_id = "unknown"
            if request:
                user = request.state.get("user")
                if user: analyst_id = user.analyst_id

            pool = await get_db_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO audit_log
                        (analyst_id, action, resource_type, request_metadata, duration_ms)
                    VALUES ($1, $2, $3, $4::jsonb, $5)
                    """,
                    analyst_id, action, func.__name__,
                    json.dumps({
                        "path": str(request.url) if request else None,
                        "method": request.method if request else None,
                    }),
                    duration,
                )
            return result
        return wrapper
    return decorator
