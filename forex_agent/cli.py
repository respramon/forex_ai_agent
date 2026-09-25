"""CLI entrypoint, available directly through python -m forex_agent."""

import argparse
import json
from pathlib import Path
import sys
from .agent import ForexAgent, format_report
from .api import serve
from .demo import make_snapshot
from .journal import Journal
from .llm import explain
from .models import PAIRS, RiskPolicy, SECONDS, ValidationError, utc
from .providers import OandaProvider, alpha_vantage_sentiment, csv_snapshot, read_json


def write_json(path, value):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def parser():
    root = argparse.ArgumentParser(description="Forex AI Agent — analisis, sinyal bersyarat, risiko, jurnal.")
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("demo", "analyze", "risk"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--timeframe", choices=SECONDS, default="M15")
        cmd.add_argument("--policy")
        cmd.add_argument("--json", action="store_true")
        cmd.add_argument("--explain", action="store_true", help="Kirim ringkasan non-akun ke OpenAI untuk narasi opsional.")
        cmd.add_argument("--out")
        if name == "demo":
            cmd.add_argument("--scenario", choices=("bullish", "range", "news", "stale"), default="bullish")
            cmd.add_argument("--pair", choices=PAIRS, default="EUR/USD")
            cmd.add_argument("--mode", choices=("analyst", "signal"), default="signal")
            cmd.add_argument("--save-snapshot")
        else:
            cmd.add_argument("--snapshot", required=True)
            cmd.add_argument("--db", default="data/journal.sqlite3")
            if name == "risk":
                cmd.add_argument("--trade", required=True)
            else:
                cmd.add_argument("--mode", choices=("analyst", "signal"), default="analyst")
    cmd = commands.add_parser("fetch-oanda")
    cmd.add_argument("--pair", choices=PAIRS, required=True)
    cmd.add_argument("--environment", choices=("practice", "live"), default="practice")
    cmd.add_argument("--contract-size", type=float, required=True)
    cmd.add_argument("--day-start-equity", type=float, required=True)
    cmd.add_argument("--fundamentals", required=True)
    cmd.add_argument("--out", required=True)
    cmd = commands.add_parser("import-csv")
    cmd.add_argument("--folder", required=True)
    cmd.add_argument("--metadata", required=True)
    cmd.add_argument("--out", required=True)
    cmd = commands.add_parser("fetch-sentiment")
    cmd.add_argument("--currency", choices=("EUR", "USD", "GBP", "JPY", "AUD"), required=True)
    cmd.add_argument("--out", required=True)
    cmd = commands.add_parser("serve")
    cmd.add_argument("--host", default="127.0.0.1")
    cmd.add_argument("--port", type=int, default=8000)
    cmd.add_argument("--db", default="data/journal.sqlite3")
    cmd.add_argument("--policy")
    cmd = commands.add_parser("journal")
    cmd.add_argument("--db", default="data/journal.sqlite3")
    cmd.add_argument("--timezone", default="Asia/Bangkok")
    sub = cmd.add_subparsers(dest="action", required=True)
    sub.add_parser("open").add_argument("--file", required=True)
    close = sub.add_parser("close")
    close.add_argument("--id", required=True)
    close.add_argument("--net-pnl", required=True, type=float)
    close.add_argument("--closed-at", required=True)
    sub.add_parser("summary").add_argument("--simulated", action="store_true")
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        command = args.command
        policy = RiskPolicy.parse(read_json(args.policy) if getattr(args, "policy", None) else None)
        if command in ("demo", "analyze", "risk"):
            snapshot = make_snapshot(args.pair, args.scenario) if command == "demo" else read_json(args.snapshot)
            if command == "demo" and args.save_snapshot:
                write_json(args.save_snapshot, snapshot)
            with Journal(":memory:" if command == "demo" else args.db) as journal:
                report = ForexAgent(journal, policy).analyze(snapshot, args.timeframe,
                    "risk" if command == "risk" else args.mode,
                    read_json(args.trade) if command == "risk" else None)
            if args.explain:
                try:
                    report["ai_commentary_unverified"] = explain(report)
                except ValidationError as exc:
                    report["ai_commentary_error"] = str(exc)
            if args.out:
                write_json(args.out, report)
            print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) if args.json else format_report(report))
            if args.explain and not args.json:
                print("\nNARASI AI (tambahan, belum diverifikasi):\n" + report.get("ai_commentary_unverified", report.get("ai_commentary_error", "")))
        elif command == "fetch-oanda":
            result = OandaProvider(environment=args.environment).snapshot(args.pair,
                contract_size=args.contract_size, day_start_equity=args.day_start_equity,
                fundamentals=read_json(args.fundamentals))
            write_json(args.out, result)
            print(f"Snapshot tersimpan: {args.out}")
        elif command == "import-csv":
            write_json(args.out, csv_snapshot(args.folder, read_json(args.metadata)))
            print(f"Snapshot tersimpan: {args.out}")
        elif command == "fetch-sentiment":
            write_json(args.out, alpha_vantage_sentiment(args.currency))
            print(f"Sentimen tersimpan: {args.out}")
        elif command == "serve":
            serve(args.db, args.host, args.port, policy)
        elif command == "journal":
            with Journal(args.db, args.timezone) as journal:
                if args.action == "open":
                    result = {"trade_id": journal.open_trade(read_json(args.file))}
                elif args.action == "close":
                    journal.close_trade(args.id, args.net_pnl, utc(args.closed_at))
                    result = {"status": "closed"}
                else:
                    result = journal.summary(args.simulated)
                print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
        return 0
    except (ValidationError, OSError, KeyError, ValueError, TypeError) as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
