import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import logquery as lq  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def test_escape_regex():
    assert lq.escape_regex("a.b/c(d)") == r"a\.b\/c\(d\)"


def test_build_query_terms_and_level():
    q = lq.build_query("user@x.com 42", "ERROR", 50)
    assert r"/(?i)user@x\.com/" in q
    assert "/(?i)42/" in q
    assert "error|exception|fatal" in q
    assert q.endswith("| limit 50")


def test_build_query_empty():
    q = lq.build_query()
    assert "filter" not in q


def test_fill_template():
    assert lq.fill_template("like /{term}/", " a.b ") == r"like /a\.b/"
    with pytest.raises(ValueError):
        lq.fill_template("like /{term}/", "")
    assert lq.fill_template("no placeholder", "") == "no placeholder"


def test_config_loads_and_saved_queries_fill():
    cfg = lq.load_config(ROOT / "config.yaml")
    assert {"email", "ims"} <= set(cfg["sources"])
    for src in cfg["sources"].values():
        for q in src["saved_queries"].values():
            lq.fill_template(q, "x")


def test_run_query_polls_and_drops_ptr():
    client = MagicMock()
    client.start_query.return_value = {"queryId": "q1"}
    client.get_query_results.side_effect = [
        {"status": "Running", "results": []},
        {"status": "Complete", "results": [[
            {"field": "@timestamp", "value": "t"},
            {"field": "@message", "value": "hello"},
            {"field": "@ptr", "value": "p"},
        ]]},
    ]
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = lq.run_query(client, ["g"], "q", start, start, poll=0)
    assert rows == [{"@timestamp": "t", "@message": "hello"}]
    kw = client.start_query.call_args.kwargs
    assert kw["logGroupNames"] == ["g"] and kw["startTime"] == int(start.timestamp())


def test_run_query_failed():
    client = MagicMock()
    client.start_query.return_value = {"queryId": "q1"}
    client.get_query_results.return_value = {"status": "Failed", "results": []}
    now = datetime.now(timezone.utc)
    with pytest.raises(RuntimeError):
        lq.run_query(client, ["g"], "q", now, now, poll=0)


def test_run_query_requires_groups():
    with pytest.raises(ValueError):
        lq.run_query(MagicMock(), [], "q", None, None)


def test_email_source_query_uses_friendly_columns():
    email = lq.load_config(ROOT / "config.yaml")["sources"]["email"]
    assert email["log_groups"] == ["aws-ses-event-logs"]
    q = lq.build_query("jane@example.com", "Problems only", 100, email)
    assert q.startswith("fields @timestamp as Timestamp")
    assert r"| filter @message like /(?i)jane@example\.com/" in q
    assert '| filter Event in ["Bounce"' in q
    assert "| display Timestamp, Event" in q
    assert "| sort Timestamp desc" in q


def test_saved_query_fills_base_and_display():
    email = lq.load_config(ROOT / "config.yaml")["sources"]["email"]
    q = lq.fill_template(email["saved_queries"]["Find by subject"], "Invoice", email)
    assert "{" not in q.replace("{term}", "")  # no unfilled placeholders
    assert "fields @timestamp as Timestamp" in q and "/(?i)Invoice/" in q


def test_levels_for_defaults_and_custom():
    assert list(lq.levels_for()) == ["Any", "ERROR", "WARN+"]
    assert "Bounces" in lq.levels_for({"levels": {"Bounces": 'Event = "Bounce"'}})


def test_merge_defaults_replaces_placeholders_keeps_user_choices():
    bundled = lq.load_config(ROOT / "config.yaml")
    user = {"region": "ap-southeast-1", "sources": {
        "email": {"label": "Email", "log_groups": ["/aws/lambda/email-sender"],
                  "saved_queries": {"Old": "x"}},
        "ims": {"label": "IMS", "log_groups": ["/ecs/my-real-ims"],
                "saved_queries": {"Mine": "y"}},
    }}
    out = lq.merge_defaults(user, bundled)
    assert out["region"] == "ap-southeast-1"
    assert out["sources"]["email"]["log_groups"] == ["aws-ses-event-logs"]
    assert "Old" not in out["sources"]["email"]["saved_queries"]
    ims = out["sources"]["ims"]
    assert ims["log_groups"] == ["/ecs/my-real-ims"]
    assert "Mine" in ims["saved_queries"] and "Recent errors" in ims["saved_queries"]


def test_save_config_round_trip(tmp_path):
    cfg = lq.load_config(ROOT / "config.yaml")
    lq.save_config(cfg, tmp_path / "c.yaml")
    assert lq.load_config(tmp_path / "c.yaml") == cfg
    assert "base_query: |" in (tmp_path / "c.yaml").read_text()


def test_custom_window():
    start, end = lq.custom_window("2026-06-09", "2026-06-13")
    assert (end - start).total_seconds() == 5 * 86400 - 1
    start, end = lq.custom_window("2026-06-09 16:00", "2026-06-09 17:30")
    assert (end - start).total_seconds() == 90 * 60
    with pytest.raises(ValueError):
        lq.custom_window("2026-06-13", "2026-06-09")
    with pytest.raises(ValueError):
        lq.custom_window("13/06/2026", "")
