"""
Instaply command-line interface.

Invoked via the ./instaply wrapper script (which bootstraps the virtualenv)
or directly with `.venv/bin/python -m src.cli`.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

VERSION = "0.1.0"

EXAMPLES = """\
examples:
  instaply serve                      run the app on http://127.0.0.1:8001/app
  instaply serve --port 9000          run on a different port
  instaply serve --reload             auto-reload on code changes (dev)
  instaply digest                     email the match digest now
  instaply digest --lookback-days 30  include matches from the last 30 days
  instaply judge                      LLM-judge the top pending matches now
  instaply rescore                    score every job that was never matched
  instaply rescore --all              also recompute existing match results
  instaply rescore --limit 200 --llm  score 200 jobs with LLM extraction
  instaply discover                   find new company boards to monitor
  instaply discover --no-llm          discover from the seed list only
  instaply status                     show config and database counts
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="instaply",
        description="Instaply — fast job discovery and alerting.",
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version", version=f"instaply {VERSION}"
    )
    subparsers = parser.add_subparsers(
        dest="command", required=True, metavar="<command>"
    )

    serve = subparsers.add_parser(
        "serve",
        help="run the web app and background scheduler",
        description=(
            "Run the Instaply server: web UI, API, source polling, "
            "instant alerts, and the scheduled digest."
        ),
    )
    serve.add_argument(
        "-p",
        "--port",
        type=int,
        default=8001,
        help="port to listen on (default: 8001 — 8000 is often taken on this machine)",
    )
    serve.add_argument(
        "--host",
        default="127.0.0.1",
        help="host to bind (default: 127.0.0.1)",
    )
    serve.add_argument(
        "--reload",
        action="store_true",
        help="restart automatically when source files change (development)",
    )

    digest = subparsers.add_parser(
        "digest",
        help="send the match digest now (no server needed)",
        description=(
            "Send one digest email covering every digest-decision match that "
            "has not been delivered yet. Falls back to in-app alerts when "
            "SMTP is not configured."
        ),
    )
    digest.add_argument(
        "--lookback-days",
        type=int,
        default=None,
        metavar="N",
        help="include matches first seen in the last N days "
        "(default: DIGEST_LOOKBACK_DAYS from .env, currently 7)",
    )

    judge = subparsers.add_parser(
        "judge",
        help="LLM-judge the top pending matches now",
        description=(
            "Have the LLM evaluate the highest-scoring unjudged alert/digest "
            "matches against your actual resume, within the daily LLM "
            "budget. Stops cleanly on budget exhaustion or provider rate "
            "limits; whatever is left stays pending for the next run."
        ),
    )
    judge.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help=f"judge at most N matches this run (default: JUDGE_TOP_K, "
        "currently 25)",
    )
    judge.add_argument(
        "--email-alerts",
        action="store_true",
        help="deliver promoted alerts over the normal channel (email if "
        "configured) instead of in-app only",
    )

    rescore = subparsers.add_parser(
        "rescore",
        help="score jobs that were never matched (baselined first polls)",
        description=(
            "Score every active job posting that has no match result for the "
            "active profile. First polls of new sources are baselined without "
            "scoring, so run this after adding sources or changing your "
            "profile. Alerts from a rescore are recorded in-app only; run "
            "`instaply digest` afterwards for an email summary."
        ),
    )
    rescore.add_argument(
        "--all",
        action="store_true",
        help="also recompute existing match results in place (use after "
        "scorer, threshold, or profile changes); history is preserved",
    )
    rescore.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="score at most N jobs this run (default: all unscored jobs)",
    )
    rescore.add_argument(
        "--llm",
        action="store_true",
        help="use the LLM for requirement extraction (slower, uses quota; "
        "default: fast heuristic extraction)",
    )
    rescore.add_argument(
        "--email-alerts",
        action="store_true",
        help="deliver strong-match alerts over the normal channel (email if "
        "configured) instead of in-app only",
    )

    discover = subparsers.add_parser(
        "discover",
        help="find new company job boards worth monitoring",
        description=(
            "Probe Greenhouse/Lever/Ashby for companies matching your "
            "profile and preferences, and stage relevant boards as "
            "suggestions. Review them in Settings (or via the API) — "
            "nothing is polled until you accept a suggestion."
        ),
    )
    discover.add_argument(
        "--no-llm",
        action="store_true",
        help="skip the LLM candidate provider; use the bundled seed list only",
    )

    subparsers.add_parser(
        "status",
        help="show configuration and database counts",
        description="Show SMTP/LLM configuration state and row counts "
        "for sources, jobs, matches, and alerts.",
    )

    return parser


def _quiet_logs() -> None:
    """Keep CLI output clean — only warnings and errors from the app."""
    import logging

    import structlog

    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING),
    )


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    print(f"Instaply starting on http://{args.host}:{args.port}/app")
    uvicorn.run(
        "src.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


async def _run_digest(lookback_days: int | None) -> dict:
    from src.alerts.service import send_digest
    from src.db.connection import close_db, init_db
    from src.db.migrations import run_migrations

    db = await init_db()
    try:
        await run_migrations(db)
        return await send_digest(db, "default", lookback_days=lookback_days)
    finally:
        await close_db()


def cmd_digest(args: argparse.Namespace) -> int:
    _quiet_logs()
    result = asyncio.run(_run_digest(args.lookback_days))
    if result["error"]:
        print(f"Digest failed: {result['error']}", file=sys.stderr)
        return 1
    if not result["sent"]:
        print("No new matches to digest.")
        return 0
    channel = "email" if result["channel"] == "email" else "in-app alerts"
    print(f"Digest sent: {result['sent']} matches via {channel}.")
    return 0


async def _run_judge(args: argparse.Namespace) -> dict:
    from src.db.connection import close_db, init_db
    from src.db.migrations import run_migrations
    from src.matching.judge import judge_pending_matches

    db = await init_db()
    try:
        await run_migrations(db)
        return await judge_pending_matches(
            db,
            "default",
            limit=args.limit,
            alert_channel=None if args.email_alerts else "in_app",
        )
    finally:
        await close_db()


def cmd_judge(args: argparse.Namespace) -> int:
    _quiet_logs()
    result = asyncio.run(_run_judge(args))
    if result["stopped_reason"] == "not_configured":
        print("No LLM configured — set an API key in .env first.", file=sys.stderr)
        return 1
    if result["pending"] == 0:
        print("Nothing to judge: every alert/digest match is already judged.")
        return 0
    print(f"Judged {result['judged']} of {result['pending']} pending matches.")
    if result["promoted"]:
        print(f"  promoted to alert: {result['promoted']}")
    if result["demoted"]:
        print(f"  demoted from alert: {result['demoted']}")
    if result["failed"]:
        print(f"  failed (will retry up to the attempt cap): {result['failed']}")
    if result["stopped_reason"] == "budget":
        print("Stopped: daily judge budget spent — the rest stays pending for tomorrow.")
    elif result["stopped_reason"] == "cooldown":
        print("Stopped: provider rate limit hit — cooldown active, rerun later.")
    return 0


async def _run_rescore(args: argparse.Namespace) -> dict:
    from src.db.connection import close_db, init_db
    from src.db.migrations import run_migrations
    from src.matching.service import rescore_backlog

    def show_progress(done: int, total: int) -> None:
        if done % 100 == 0 or done == total:
            print(f"  scored {done}/{total}", flush=True)

    db = await init_db()
    try:
        await run_migrations(db)
        return await rescore_backlog(
            db,
            "default",
            limit=args.limit,
            use_llm=args.llm,
            alert_channel=None if args.email_alerts else "in_app",
            rescore_all=args.all,
            progress_callback=show_progress,
        )
    finally:
        await close_db()


def cmd_rescore(args: argparse.Namespace) -> int:
    _quiet_logs()
    result = asyncio.run(_run_rescore(args))
    if result["error"] == "no_active_profile":
        print(
            "No active profile. Save a resume first (UI Profile page or "
            "POST /api/profile/resume).",
            file=sys.stderr,
        )
        return 1
    if result["total"] == 0:
        print("Nothing to do: every active job already has a match result.")
        return 0
    decisions = result["decisions"]
    print(f"Scored {result['scored']} of {result['total']} unscored jobs.")
    for decision in ("alert", "digest", "ignore", "rejected"):
        if decisions.get(decision):
            print(f"  {decision + ':':<10} {decisions[decision]}")
    if decisions.get("alert"):
        print("Strong matches were recorded as in-app alerts (see /app).")
    if decisions.get("digest"):
        print("Run `instaply digest` to email the digest-level matches.")
    return 0


async def _run_discover(args: argparse.Namespace):
    from src.db.connection import close_db, init_db
    from src.db.migrations import run_migrations
    from src.discovery.repository import count_by_status
    from src.discovery.service import run_discovery

    db = await init_db()
    try:
        await run_migrations(db)
        stats = await run_discovery(db, "default", use_llm=not args.no_llm)
        pending = await count_by_status(db, "default", "suggested")
        return stats, pending
    finally:
        await close_db()


def cmd_discover(args: argparse.Namespace) -> int:
    _quiet_logs()
    print("Discovering company job boards (this probes ATS endpoints politely"
          " — expect a minute or two)...")
    stats, pending = asyncio.run(_run_discover(args))
    if stats.candidates == 0:
        print(
            "Nothing to discover: set target roles in Preferences first, or "
            "review the suggestions already waiting in Settings."
        )
        return 0
    print(f"Checked {stats.candidates} candidate companies "
          f"({stats.probed} board probes, "
          f"LLM {'used' if stats.llm_used else 'not used'}).")
    if stats.suggested:
        print(f"  new suggestions:  {stats.suggested}")
    if stats.boards_found - stats.suggested > 0:
        print(f"  boards without matching roles: {stats.irrelevant}")
    if stats.not_found:
        print(f"  no public board found: {stats.not_found}")
    if stats.skipped_known:
        print(f"  already known/monitored: {stats.skipped_known}")
    print(f"{pending} suggestion(s) awaiting review in Settings (/app).")
    return 0


async def _collect_status() -> dict:
    from src.db.connection import close_db, init_db
    from src.db.migrations import run_migrations
    from src.llm import budget

    db = await init_db()
    try:
        await run_migrations(db)
        usage = await budget.usage_today()
        counts = {
            "LLM calls today": f"{usage['total']}/{usage['budget']}"
            + (f" ({', '.join(f'{k} {v}' for k, v in usage['categories'].items())})"
               if usage["categories"] else ""),
        }
        for label, sql in (
            ("sources", "SELECT COUNT(*) FROM sources"),
            (
                "suggested sources",
                "SELECT COUNT(*) FROM discovered_companies WHERE status = 'suggested'",
            ),
            ("jobs", "SELECT COUNT(*) FROM job_postings"),
            ("matches", "SELECT COUNT(*) FROM match_results"),
            ("alerts", "SELECT COUNT(*) FROM alerts"),
            (
                "undigested matches",
                """
                SELECT COUNT(*)
                FROM match_results mr
                LEFT JOIN alerts a ON a.match_result_id = mr.id
                WHERE mr.decision = 'digest' AND a.id IS NULL
                """,
            ),
            # ~50 labeled actions unlock learning personalized score weights
            ("feedback actions", "SELECT COUNT(*) FROM user_job_actions"),
        ):
            cursor = await db.execute(sql)
            row = await cursor.fetchone()
            counts[label] = row[0]
        return counts
    finally:
        await close_db()


def cmd_status(_args: argparse.Namespace) -> int:
    from src.config import settings

    _quiet_logs()
    counts = asyncio.run(_collect_status())

    rows = {
        "database": settings.database_path,
        "email (SMTP)": "configured" if settings.smtp_configured else "not configured",
        "LLM": "configured" if settings.llm_configured else "not configured (heuristic fallbacks)",
        "alert threshold": f"{settings.default_alert_threshold} (default; per-user value in Preferences)",
        "digest": f"every {settings.digest_interval}s, {settings.digest_lookback_days}d lookback",
        **counts,
    }
    print(f"instaply {VERSION}")
    for label, value in rows.items():
        print(f"  {label + ':':<20} {value}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "serve": cmd_serve,
        "digest": cmd_digest,
        "judge": cmd_judge,
        "rescore": cmd_rescore,
        "discover": cmd_discover,
        "status": cmd_status,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
