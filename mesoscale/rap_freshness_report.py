"""Structured, machine-readable decisions from the RAP archive freshness check."""

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any


def build_rap_freshness_report(
    *,
    event_name: str,
    target_cycle: str | None,
    existing_archive: Mapping[str, Any] | None,
    needs_update: bool,
    checked_utc: str | None = None,
) -> dict[str, Any]:
    """Describe the RAP freshness decision without adding or inferring model data."""
    published_cycle = (
        existing_archive.get("model_cycle_utc")
        if isinstance(existing_archive, Mapping)
        else None
    )
    if event_name == "workflow_dispatch":
        decision = "manual_rebuild_requested"
    elif not isinstance(existing_archive, Mapping) or not existing_archive:
        decision = "publish_initial_or_repair_archive"
    elif needs_update:
        decision = "publish_new_cycle_or_repair_archive"
    else:
        decision = "retain_current_complete_archive"

    return {
        "schema_version": 1,
        "model": "RAP",
        "trigger_event": event_name,
        "checked_utc": checked_utc or datetime.now(timezone.utc).isoformat(),
        "latest_complete_cycle_utc": target_cycle,
        "published_cycle_utc": published_cycle,
        "archive_update_required": bool(needs_update),
        "decision": decision,
    }
