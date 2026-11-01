"""cw-lens desktop app with a modern UI (pywebview).  Run with:  python webapp.py

The window shows ui/index.html. JavaScript there calls the methods of `Api`
below through `window.pywebview.api.*`; each call runs on its own thread, so
slow CloudWatch queries never freeze the window.
"""
from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

import logquery as lq

APP_NAME = "cw-lens"
CUSTOM = "__custom__"


class Api:
    def __init__(self, config_path: str | Path | None = None):
        self.config_path = Path(config_path or lq.USER_CONFIG)
        self.cfg = lq.load_user_config(self.config_path)
        self.custom_groups: list[str] = []
        self.last_rows: list[dict] = []
        self.window = None  # set by main(); used for the save dialog

    # ---------- helpers ----------
    def _save(self):
        lq.save_config(self.cfg, self.config_path)

    def _source(self, key: str) -> dict:
        return {} if key == CUSTOM else self.cfg["sources"].get(key, {})

    def _groups(self, key: str) -> list[str]:
        return self.custom_groups if key == CUSTOM else self._source(key).get("log_groups", [])

    def _client(self):
        return lq.make_client(self.cfg["region"], self.cfg.get("profile") or None)

    def _query(self, p: dict) -> str:
        source = self._source(p.get("source", ""))
        mode = p.get("mode", "simple")
        if mode == "query":
            query = (p.get("query") or "").strip()
            if not query:
                raise ValueError("The query is empty.")
            return query
        if mode == "saved":
            saved = source.get("saved_queries", {})
            name = p.get("saved", "")
            if name not in saved:
                raise ValueError(f"Saved search “{name}” not found.")
            return lq.fill_template(saved[name], p.get("term", ""), source)
        return lq.build_query(p.get("term", ""), p.get("level", "Any"),
                              int(p.get("limit") or 200), source)

    @staticmethod
    def _window(p: dict):
        if p.get("range") == "Custom dates":
            return lq.custom_window(p.get("from", ""), p.get("to", ""))
        return lq.time_window(p.get("range") or "Last 24 hours")

    # ---------- called from JavaScript ----------
    def get_state(self) -> dict:
        sources = []
        for key, s in self.cfg["sources"].items():
            saved = s.get("saved_queries", {})
            sources.append({
                "key": key,
                "label": s.get("label", key),
                "log_groups": s.get("log_groups", []),
                "search_hint": s.get("search_hint", "keywords, IDs or error text"),
                "levels": list(lq.levels_for(s)),
                "columns": [c.strip() for c in s.get("display", "").split(",") if c.strip()],
                "saved": [{"name": n, "needs_term": "{term}" in q} for n, q in saved.items()],
            })
        sources.append({"key": CUSTOM, "label": "Custom", "log_groups": self.custom_groups,
                        "search_hint": "keywords, IDs or error text",
                        "levels": list(lq.levels_for()), "saved": []})
        return {
            "region": self.cfg["region"],
            "profile": self.cfg.get("profile") or "",
            "ranges": list(lq.RANGES) + ["Custom dates"],
            "sources": sources,
            "config_path": str(self.config_path),
        }

    def preview(self, p: dict) -> dict:
        try:
            return {"query": self._query(p)}
        except Exception as e:  # noqa: BLE001 - shown in the UI
            return {"error": str(e)}

    def run(self, p: dict) -> dict:
        try:
            groups = self._groups(p.get("source", ""))
            if not groups:
                return {"error": "Choose which log groups to search first.", "need_groups": True}
            query = self._query(p)
            start, end = self._window(p)
            began = time.monotonic()
            rows = lq.run_query(self._client(), groups, query, start, end)
        except Exception as e:  # noqa: BLE001 - shown in the UI
            return {"error": lq.friendly_error(e)}
        self.last_rows = rows
        return {"rows": rows, "query": query, "seconds": round(time.monotonic() - began, 1),
                "start": start.isoformat(), "end": end.isoformat()}

    def context(self, source: str, row: dict) -> dict:
        """Lines logged around a result row in the same log stream (whole tracebacks)."""
        stream = row.get("@logStream") or row.get("Stream")
        when = row.get("@timestamp") or row.get("Timestamp")
        if not stream or not when:
            return {"error": "This result has no log stream or time, so there is nothing around it to show."}
        group = lq.log_group_from_row(row, self._groups(source))
        if not group:
            return {"error": "Can't tell which log group this line came from. Run the search again "
                             "(newer searches include it) or search one log group at a time."}
        try:
            lines = lq.get_context(self._client(), group, stream, lq.parse_insights_time(when))
        except Exception as e:  # noqa: BLE001 - shown in the UI
            return {"error": lq.friendly_error(e)}
        return {"lines": lines, "group": group, "stream": stream}

    def list_log_groups(self, prefix: str = "") -> dict:
        try:
            return {"groups": lq.list_log_groups(self._client(), prefix, max_items=5000)}
        except Exception as e:  # noqa: BLE001
            return {"error": lq.friendly_error(e)}

    def set_log_groups(self, key: str, groups: list[str]) -> dict:
        groups = sorted({g.strip() for g in groups if g and g.strip()})
        if key == CUSTOM:
            self.custom_groups = groups
        else:
            self.cfg["sources"][key]["log_groups"] = groups
            self._save()
        return self.get_state()

    def set_settings(self, region: str, profile: str) -> dict:
        region = (region or "").strip()
        if not region:
            return {"error": "Region can't be empty (for example us-east-1)."}
        self.cfg["region"] = region
        self.cfg["profile"] = (profile or "").strip() or None
        self._save()
        return self.get_state()

    def export_csv(self) -> dict:
        if not self.last_rows:
            return {"error": "Nothing to export yet. Run a search first."}
        import webview

        picked = self.window.create_file_dialog(webview.SAVE_DIALOG, save_filename="logs.csv",
                                                file_types=("CSV files (*.csv)",))
        if not picked:
            return {"cancelled": True}
        path = picked if isinstance(picked, str) else picked[0]
        return {"path": self.write_csv(path)}

    def write_csv(self, path: str) -> str:
        fields = list(dict.fromkeys(k for r in self.last_rows for k in r))
        with open(path, "w", newline="", encoding="utf-8-sig") as f:  # -sig: opens cleanly in Excel
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(self.last_rows)
        return path


def selftest(window, out_path: str):
    """Used by CI: wait for the UI to render, record what it shows, then quit.

    The process always ends: a watchdog stops it if anything hangs, so a slow
    CI machine gives a clear FAIL instead of a stuck job.
    """
    import os
    import threading

    def watchdog():
        time.sleep(150)
        out = Path(out_path)
        if not out.exists():
            out.write_text("FAIL: timed out before the UI answered")
        os._exit(2)

    threading.Thread(target=watchdog, daemon=True).start()
    result = "FAIL: UI did not load"
    for _ in range(90):
        try:
            n = window.evaluate_js("document.querySelectorAll('#sources .nav-item').length")
            if n:
                result = f"OK sources={n}"
                break
        except Exception as e:  # noqa: BLE001 - page may still be loading
            result = f"FAIL: {e}"
        time.sleep(0.5)
    Path(out_path).write_text(result)
    window.destroy()
    time.sleep(10)  # normally the app has exited by now; if closing the window hung, force it
    os._exit(0 if result.startswith("OK") else 1)


def main(argv: list[str]) -> int:
    import webview

    api = Api()
    window = webview.create_window(APP_NAME, url=str(lq.bundled_path("ui/index.html")), js_api=api,
                                   width=1320, height=820, min_size=(960, 600))
    api.window = window
    if len(argv) > 2 and argv[1] == "--selftest":
        webview.start(selftest, (window, argv[2]))
    else:
        webview.start()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
