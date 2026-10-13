"""Shared context for the offline translation provider (pytest loads conftest under multiple names)."""
from contextvars import ContextVar

reply = ContextVar("offline_audience_reply", default=None)
