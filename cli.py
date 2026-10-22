"""Command-line version.

Examples:
  python cli.py search email user@example.com --since "Last 24 hours"
  python cli.py search ims "timeout" --level ERROR
  python cli.py search email user@example.com --level "Problems only" --from 2026-06-09 --to 2026-06-13
  python cli.py saved email "Recent errors / bounces"
  python cli.py groups --prefix /aws/lambda
"""
import argparse
import json
import sys

import logquery as lq


def main(argv=None):
    p = argparse.ArgumentParser(description="Query CloudWatch logs")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--json", action="store_true", help="output JSON lines")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="simple text search")
    s.add_argument("source")
    s.add_argument("text", nargs="?", default="")
    s.add_argument("--level", default="Any", help="e.g. ERROR, or for email: 'Problems only', Bounces")
    s.add_argument("--since", choices=list(lq.RANGES), default="Last 24 hours")
    s.add_argument("--limit", type=int, default=200)

    q = sub.add_parser("saved", help="run a saved query from config.yaml")
    q.add_argument("source")
    q.add_argument("name")
    q.add_argument("term", nargs="?", default="")
    q.add_argument("--since", choices=list(lq.RANGES), default="Last 24 hours")
    for sp in (s, q):
        sp.add_argument("--from", dest="date_from", help="start date YYYY-MM-DD[ HH:MM] (local)")
        sp.add_argument("--to", dest="date_to", default="", help="end date (default: now)")

    g = sub.add_parser("groups", help="list log group names")
    g.add_argument("--prefix", default="")

    args = p.parse_args(argv)
    cfg = lq.load_config(args.config)
    client = lq.make_client(cfg["region"], cfg["profile"])

    if args.cmd == "groups":
        print("\n".join(lq.list_log_groups(client, args.prefix)))
        return 0

    if args.source not in cfg["sources"]:
        sys.exit(f"Unknown source '{args.source}'. Options: {', '.join(cfg['sources'])}")
    source = cfg["sources"][args.source]
    if args.cmd == "search":
        levels = lq.levels_for(source)
        if args.level not in levels:
            sys.exit(f"Unknown level. Options: {', '.join(levels)}")
        query = lq.build_query(args.text, args.level, args.limit, source)
    else:
        saved = source.get("saved_queries", {})
        if args.name not in saved:
            sys.exit(f"Unknown saved query. Options: {', '.join(saved)}")
        query = lq.fill_template(saved[args.name], args.term, source)

    if args.date_from:
        start, end = lq.custom_window(args.date_from, args.date_to)
    else:
        start, end = lq.time_window(args.since)
    rows = lq.run_query(client, source["log_groups"], query, start, end)
    for r in rows:
        if args.json:
            print(json.dumps(r))
        else:
            ts = r.get("@timestamp") or r.get("Timestamp", "")
            rest = {k: v for k, v in r.items() if k not in ("@timestamp", "Timestamp", "@message")}
            print(ts, " | ".join(rest.values()) if rest else r.get("@message", "").rstrip())
    print(f"-- {len(rows)} rows", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
