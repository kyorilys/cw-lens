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
