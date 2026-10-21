"""Command-line version.

Examples:
  python cli.py search email user@example.com --since "Last 24 hours"
  python cli.py search ims "timeout" --level ERROR
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
    s.add_argument("--level", choices=list(lq.LEVEL_PATTERNS), default="Any")
    s.add_argument("--since", choices=list(lq.RANGES), default="Last 1 hour")
    s.add_argument("--limit", type=int, default=200)

    q = sub.add_parser("saved", help="run a saved query from config.yaml")
    q.add_argument("source")
    q.add_argument("name")
    q.add_argument("term", nargs="?", default="")
    q.add_argument("--since", choices=list(lq.RANGES), default="Last 1 hour")

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
        query = lq.build_query(args.text, args.level, args.limit)
    else:
        saved = source.get("saved_queries", {})
        if args.name not in saved:
            sys.exit(f"Unknown saved query. Options: {', '.join(saved)}")
        query = lq.fill_template(saved[args.name], args.term)

    start, end = lq.time_window(args.since)
    rows = lq.run_query(client, source["log_groups"], query, start, end)
    for r in rows:
        if args.json:
            print(json.dumps(r))
        else:
            print(r.get("@timestamp", ""), r.get("@message", json.dumps(r)).rstrip())
    print(f"-- {len(rows)} rows", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
