import csv
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import logquery as lq  # noqa: E402
import webapp  # noqa: E402


def make_api(tmp_path, monkeypatch, results=None):
    fake = MagicMock()
    fake.start_query.return_value = {"queryId": "q"}
    fake.get_query_results.return_value = {"status": "Complete", "results": results or []}
    monkeypatch.setattr(lq, "make_client", lambda *a, **k: fake)
    return webapp.Api(tmp_path / "config.yaml"), fake


def test_state_lists_sources_with_custom(tmp_path, monkeypatch):
    api, _ = make_api(tmp_path, monkeypatch)
    st = api.get_state()
    keys = [s["key"] for s in st["sources"]]
    assert keys[:2] == ["email", "ims"] and keys[-1] == webapp.CUSTOM
    email = st["sources"][0]
    assert email["log_groups"] == ["aws-ses-event-logs"]
    assert email["columns"][:2] == ["Timestamp", "Event"]
    assert any(q["needs_term"] for q in email["saved"])
    assert "Custom dates" in st["ranges"]


def test_preview_modes(tmp_path, monkeypatch):
    api, _ = make_api(tmp_path, monkeypatch)
    q = api.preview({"source": "email", "mode": "simple", "term": "a@b.com", "level": "Bounces"})["query"]
    assert 'filter Event = "Bounce"' in q
    q = api.preview({"source": "email", "mode": "saved", "saved": "Find by subject", "term": "Hi"})["query"]
    assert "Subject like /(?i)Hi/" in q
    assert "needs a search term" in api.preview({"source": "email", "mode": "saved",
                                                 "saved": "Find by subject", "term": ""})["error"]
    assert api.preview({"source": "email", "mode": "query", "query": " stats count(*) "})["query"] == "stats count(*)"


def test_run_returns_rows_and_remembers_them(tmp_path, monkeypatch):
    rows = [[{"field": "Timestamp", "value": "2026-06-12 09:14:03.000"}, {"field": "Event", "value": "Bounce"}]]
    api, fake = make_api(tmp_path, monkeypatch, rows)
    res = api.run({"source": "email", "mode": "simple", "term": "x", "range": "Custom dates",
                   "from": "2026-06-09T00:00", "to": "2026-06-13T23:59"})
    assert res["rows"] == [{"Timestamp": "2026-06-12 09:14:03.000", "Event": "Bounce"}]
    assert fake.start_query.call_args.kwargs["logGroupNames"] == ["aws-ses-event-logs"]
    out = api.write_csv(str(tmp_path / "out.csv"))
    with open(out, encoding="utf-8-sig") as f:
        assert list(csv.DictReader(f)) == res["rows"]


def test_run_without_groups_asks_for_them(tmp_path, monkeypatch):
    api, fake = make_api(tmp_path, monkeypatch)
    assert api.run({"source": "ims"})["need_groups"] is True
    assert api.run({"source": webapp.CUSTOM})["need_groups"] is True
    fake.start_query.assert_not_called()


def test_run_reports_friendly_errors(tmp_path, monkeypatch):
    from botocore.exceptions import NoCredentialsError
    api, fake = make_api(tmp_path, monkeypatch)
    fake.start_query.side_effect = NoCredentialsError()
    assert "aws sso login" in api.run({"source": "email"})["error"]


def test_set_log_groups_and_settings_persist(tmp_path, monkeypatch):
    api, _ = make_api(tmp_path, monkeypatch)
    api.set_log_groups("ims", ["/ecs/b", "/ecs/a", " ", "/ecs/a"])
    api.set_log_groups(webapp.CUSTOM, ["/x"])
    assert api.set_settings("", "")["error"]
    api.set_settings(" ap-southeast-1 ", " dev ")
    cfg = lq.load_config(tmp_path / "config.yaml")
    assert cfg["sources"]["ims"]["log_groups"] == ["/ecs/a", "/ecs/b"]
    assert cfg["region"] == "ap-southeast-1" and cfg["profile"] == "dev"
    assert webapp.CUSTOM not in cfg["sources"]


def test_context_uses_row_log_group(tmp_path, monkeypatch):
    api, fake = make_api(tmp_path, monkeypatch)
    fake.get_log_events.return_value = {"events": [{"timestamp": 1793500000000, "message": "x"}]}
    res = api.context("ims", {"Timestamp": "2026-11-01 09:10:02.551", "Stream": "web/1", "@log": "1:/ecs/ims-api"})
    assert res["group"] == "/ecs/ims-api" and res["lines"][0]["message"] == "x"
    assert "no log stream" in api.context("ims", {"Timestamp": "2026-11-01 09:10:02"})["error"]
    assert "which log group" in api.context("ims", {"Timestamp": "2026-11-01 09:10:02", "Stream": "s"})["error"]
