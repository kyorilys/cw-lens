"""Core logic: build CloudWatch Logs Insights queries and run them."""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

RANGES = {
    "Last 15 minutes": timedelta(minutes=15),
    "Last 1 hour": timedelta(hours=1),
    "Last 6 hours": timedelta(hours=6),
    "Last 24 hours": timedelta(days=1),
    "Last 7 days": timedelta(days=7),
}

LEVEL_PATTERNS = {
    "Any": None,
    "ERROR": r"(?i)(error|exception|fatal)",
    "WARN+": r"(?i)(warn|error|exception|fatal)",
}


def load_config(path: str | Path = "config.yaml") -> dict:
    with open(path) as f:
        cfg = yaml.safe_load(f) or {}
    cfg.setdefault("region", "us-east-1")
    cfg.setdefault("profile", None)
    cfg.setdefault("sources", {})
    return cfg


def save_config(cfg: dict, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.safe_dump(cfg, f, sort_keys=False, allow_unicode=True)


def escape_regex(text: str) -> str:
    """Escape user text so it is matched literally inside /.../ in Insights."""
    return re.sub(r"([\\/.^$|?*+()\[\]{}])", r"\\\1", text)


def build_query(search: str = "", level: str = "Any", limit: int = 200) -> str:
    """Turn simple search inputs into a Logs Insights query."""
    lines = ["fields @timestamp, @message, @logStream"]
    for term in search.split():
        lines.append(f"| filter @message like /(?i){escape_regex(term)}/")
    pattern = LEVEL_PATTERNS.get(level)
    if pattern:
        lines.append(f"| filter @message like /{pattern}/")
    lines.append("| sort @timestamp desc")
    lines.append(f"| limit {int(limit)}")
    return "\n".join(lines)


def fill_template(query: str, term: str) -> str:
    """Replace {term} in a saved query with the (escaped) search term."""
    if "{term}" in query and not term.strip():
        raise ValueError("This saved query needs a search term.")
    return query.replace("{term}", escape_regex(term.strip()))


def time_window(range_label: str, now: datetime | None = None) -> tuple[datetime, datetime]:
    now = now or datetime.now(timezone.utc)
    return now - RANGES[range_label], now


def make_client(region: str, profile: str | None = None):
    import boto3

    session = boto3.Session(profile_name=profile or None, region_name=region)
    return session.client("logs")


def run_query(client, log_groups: list[str], query: str, start: datetime, end: datetime,
              timeout: float = 120, poll: float = 1.0) -> list[dict]:
    """Start an Insights query, wait for it, and return rows as dicts."""
    if not log_groups:
        raise ValueError("No log groups selected.")
    resp = client.start_query(
        logGroupNames=log_groups,
        startTime=int(start.timestamp()),
        endTime=int(end.timestamp()),
        queryString=query,
    )
    query_id = resp["queryId"]
    deadline = time.monotonic() + timeout
    while True:
        result = client.get_query_results(queryId=query_id)
        status = result["status"]
        if status == "Complete":
            break
        if status in ("Failed", "Cancelled", "Timeout"):
            raise RuntimeError(f"Query {status.lower()}.")
        if time.monotonic() > deadline:
            client.stop_query(queryId=query_id)
            raise TimeoutError("Query took too long; try a shorter time range.")
        time.sleep(poll)
    return [
        {f["field"]: f["value"] for f in row if f["field"] != "@ptr"}
        for row in result["results"]
    ]


def list_log_groups(client, prefix: str = "", max_items: int = 500) -> list[str]:
    kwargs = {"logGroupNamePrefix": prefix} if prefix else {}
    names: list[str] = []
    for page in client.get_paginator("describe_log_groups").paginate(**kwargs):
        names += [g["logGroupName"] for g in page["logGroups"]]
        if len(names) >= max_items:
            break
    return names[:max_items]
