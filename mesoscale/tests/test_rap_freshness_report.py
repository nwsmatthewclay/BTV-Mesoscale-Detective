from mesoscale.rap_freshness_report import build_rap_freshness_report


def test_freshness_report_records_a_no_update_decision_without_inventing_data():
    report = build_rap_freshness_report(
        event_name="workflow_run",
        target_cycle="2026-11-14T02:00:00Z",
        existing_archive={
            "model_cycle_utc": "2026-11-14T02:00:00Z",
            "quality": {"status": "passed"},
        },
        needs_update=False,
        checked_utc="2026-11-14T03:33:38Z",
    )

    assert report == {
        "schema_version": 1,
        "model": "RAP",
        "trigger_event": "workflow_run",
        "checked_utc": "2026-11-14T03:33:38Z",
        "latest_complete_cycle_utc": "2026-11-14T02:00:00Z",
        "published_cycle_utc": "2026-11-14T02:00:00Z",
        "archive_update_required": False,
        "decision": "retain_current_complete_archive",
    }


def test_freshness_report_distinguishes_a_new_cycle_from_the_published_cycle():
    report = build_rap_freshness_report(
        event_name="schedule",
        target_cycle="2026-11-14T03:00:00Z",
        existing_archive={"model_cycle_utc": "2026-11-14T02:00:00Z"},
        needs_update=True,
        checked_utc="2026-11-14T03:47:00Z",
    )

    assert report["latest_complete_cycle_utc"] == "2026-11-14T03:00:00Z"
    assert report["published_cycle_utc"] == "2026-11-14T02:00:00Z"
    assert report["archive_update_required"] is True
    assert report["decision"] == "publish_new_cycle_or_repair_archive"


def test_freshness_report_identifies_an_initial_archive():
    report = build_rap_freshness_report(
        event_name="workflow_run",
        target_cycle="2026-11-14T02:00:00Z",
        existing_archive=None,
        needs_update=True,
        checked_utc="2026-11-14T03:00:00Z",
    )

    assert report["published_cycle_utc"] is None
    assert report["decision"] == "publish_initial_or_repair_archive"


def test_manual_rebuild_is_explicit_in_the_freshness_report():
    report = build_rap_freshness_report(
        event_name="workflow_dispatch",
        target_cycle="2026-11-14T02:00:00Z",
        existing_archive={"model_cycle_utc": "2026-11-14T02:00:00Z"},
        needs_update=True,
        checked_utc="2026-11-14T04:00:00Z",
    )

    assert report["archive_update_required"] is True
    assert report["decision"] == "manual_rebuild_requested"


def test_freshness_report_generates_an_offset_aware_utc_timestamp():
    report = build_rap_freshness_report(
        event_name="schedule",
        target_cycle=None,
        existing_archive=None,
        needs_update=False,
    )

    assert report["checked_utc"].endswith("+00:00")
    assert report["latest_complete_cycle_utc"] is None
