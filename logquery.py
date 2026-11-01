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
    "Last 30 days": timedelta(days=30),
}

DEFAULT_BASE = "fields @timestamp, @message, @logStream"

# Filter conditions offered in the "Level" box. A source can replace these
# with its own (e.g. SES event types) via `levels:` in config.yaml.
DEFAULT_LEVELS = {
    "ERROR": "@message like /(?i)(error|exception|fatal)/",
    "WARN+": "@message like /(?i)(warn|error|exception|fatal)/",
}

# Placeholder log groups shipped in the first version of config.yaml.
OLD_PLACEHOLDERS = {"email": ["/aws/lambda/email-sender"], "ims": ["/ecs/ims-service"]}


def load_config(path: str | Path = "config.yaml") -> dict:
    with open(path) as f:
        cfg = yaml.safe_load(f) or {}
    cfg.setdefault("region", "us-east-1")
    cfg.setdefault("profile", None)
    cfg.setdefault("sources", {})
    return cfg


class _Dumper(yaml.SafeDumper):
    pass


def _str_repr(dumper, value):
    style = "|" if "\n" in value else None  # keep multi-line queries readable
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_Dumper.add_representer(str, _str_repr)


def save_config(cfg: dict, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(cfg, f, Dumper=_Dumper, sort_keys=False, allow_unicode=True)


def merge_defaults(user: dict, bundled: dict) -> dict:
    """Bring a user's saved config up to date with the app's bundled defaults.

    A source still pointing at the original placeholder log groups was never
    set up, so it is replaced outright. Otherwise the user's settings win and
    only new keys and new saved queries are added.
    """
    sources = user.setdefault("sources", {})
    for key, default in bundled.get("sources", {}).items():
        mine = sources.get(key)
        if not mine or not mine.get("log_groups") or mine["log_groups"] == OLD_PLACEHOLDERS.get(key):
            sources[key] = default
            continue
        for k, v in default.items():
            if k == "saved_queries":
                saved = mine.setdefault("saved_queries", {})
                for name, q in v.items():
                    saved.setdefault(name, q)
            else:
                mine.setdefault(k, v)
    return user


def levels_for(source: dict | None = None) -> dict:
    """Level/event choices for a source: {label: Insights filter condition}."""
    return {"Any": None, **((source or {}).get("levels") or DEFAULT_LEVELS)}


def escape_regex(text: str) -> str:
    """Escape user text so it is matched literally inside /.../ in Insights."""
    return re.sub(r"([\\/.^$|?*+()\[\]{}])", r"\\\1", text)


def build_query(search: str = "", level: str = "Any", limit: int = 200,
                source: dict | None = None) -> str:
    """Turn simple search inputs into a Logs Insights query.

    Each word must appear somewhere in the raw log line (case-insensitive).
    A source can set `base_query` (fields/parse), `display` and `sort_by`
    to get friendlier columns.
    """
    source = source or {}
    lines = [source.get("base_query", DEFAULT_BASE).strip()]
    for term in search.split():
        lines.append(f"| filter @message like /(?i){escape_regex(term)}/")
    cond = levels_for(source).get(level)
    if cond:
        lines.append(f"| filter {cond}")
    if source.get("display"):
        lines.append(f"| display {source['display']}")
    lines.append(f"| sort {source.get('sort_by', '@timestamp')} desc")
    lines.append(f"| limit {int(limit)}")
    return "\n".join(lines)


def fill_template(query: str, term: str, source: dict | None = None) -> str:
    """Fill a saved query's placeholders.

    {base} and {display} come from the source's config; {term} is the
    (escaped) search text.
    """
    source = source or {}
    query = query.replace("{base}", source.get("base_query", DEFAULT_BASE).strip())
    query = query.replace("{display}", source.get("display", "@timestamp, @message, @logStream"))
    if "{term}" in query and not term.strip():
        raise ValueError("This saved query needs a search term.")
    return query.replace("{term}", escape_regex(term.strip()))


def time_window(range_label: str, now: datetime | None = None) -> tuple[datetime, datetime]:
    now = now or datetime.now(timezone.utc)
    return now - RANGES[range_label], now


def parse_local(text: str, end_of_day: bool = False) -> datetime:
    """Parse 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM' typed in the user's local time.

    A bare date used as an end time means the end of that day.
    """
    text = text.strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if fmt == "%Y-%m-%d" and end_of_day:
            dt += timedelta(days=1) - timedelta(seconds=1)
        return dt.astimezone()  # naive -> local time zone
    raise ValueError(f"Can't read date '{text}'. Use YYYY-MM-DD or YYYY-MM-DD HH:MM.")


def custom_window(start_text: str, end_text: str) -> tuple[datetime, datetime]:
    start = parse_local(start_text)
    end = parse_local(end_text, end_of_day=True) if end_text.strip() else datetime.now(timezone.utc)
    if end <= start:
        raise ValueError("The end date must be after the start date.")
    return start, end


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
