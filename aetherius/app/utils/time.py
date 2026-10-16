from datetime import datetime, timezone


def utcnow() -> datetime:
    """Current UTC time as a naive datetime.

    The schema uses ``TIMESTAMP`` (without time zone) columns that store UTC,
    so persisted values stay naive. This replaces the deprecated
    ``datetime.utcnow()`` with identical semantics.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
