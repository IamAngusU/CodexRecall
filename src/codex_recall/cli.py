from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Sequence

from . import __version__
from .mcp import main as mcp_main
from .server import serve
from .sources import CodexSource, active_thread_id, default_codex_home, default_index_path
from .storage import RecallStore


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codex-recall",
        description="Recover and search local Codex conversations without modifying Codex data.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--codex-home", type=Path, default=default_codex_home())
    parser.add_argument("--data", type=Path, default=default_index_path())
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("serve", help="Open the local browser UI")
    run.add_argument("--host", default="127.0.0.1")
    run.add_argument("--port", type=int, default=8765)
    run.add_argument("--thread", default=active_thread_id())
    run.add_argument("--no-browser", action="store_true")
    run.add_argument("--verbose", action="store_true")

    index = sub.add_parser("index", help="Refresh the local search index")
    index.add_argument("--full", action="store_true")
    index.add_argument("--thread")

    threads = sub.add_parser("tasks", help="List recent local tasks")
    threads.add_argument("query", nargs="?", default="")
    threads.add_argument("--limit", type=int, default=30)
    threads.add_argument("--archived", action="store_true")

    search = sub.add_parser("search", help="Search exact messages and work output")
    search.add_argument("query")
    search.add_argument("--thread")
    search.add_argument("--limit", type=int, default=20)

    recover = sub.add_parser("recover", help="Print a bounded recovery packet")
    recover.add_argument("--thread", default=active_thread_id())
    recover.add_argument("--item")
    recover.add_argument("--before", type=int, default=4)
    recover.add_argument("--after", type=int, default=4)
    recover.add_argument("--messages-only", action="store_true")

    sub.add_parser("doctor", help="Check the local data source and index")
    sub.add_parser("mcp", help="Run the MCP server over stdio")
    install = sub.add_parser("install-mcp", help="Register CodexRecall with the Codex CLI")
    install.add_argument("--name", default="codex-recall")
    install.add_argument("--dry-run", action="store_true")

    bench = sub.add_parser("bench", help="Measure incremental indexing and search latency")
    bench.add_argument("query", nargs="?", default="error")
    bench.add_argument("--runs", type=int, default=20)
    return parser


def _objects(args: argparse.Namespace) -> tuple[RecallStore, CodexSource]:
    store = RecallStore(args.data)
    source = CodexSource(args.codex_home, store)
    return store, source


def _sync(store: RecallStore, source: CodexSource, *, full: bool = False, thread: str | None = None) -> dict:
    result = source.sync(full=full, thread_id=thread)
    return result.as_dict()


def _format_bytes(value: int) -> str:
    number = float(value)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if number < 1024 or unit == "GiB":
            return f"{number:.1f} {unit}"
        number /= 1024
    return f"{number:.1f} GiB"


def _print_sync(result: dict) -> None:
    print(f"Indexed   {result['items_written']} changed items")
    print(f"Tasks     {result['threads_changed']} changed / {result['threads_seen']} seen")
    print(f"Tail      {_format_bytes(result['tail_bytes_read'])}")
    print(f"Elapsed   {result['elapsed_ms']} ms")
    print(f"Source    {result['source']}")


def main(argv: Sequence[str] | None = None) -> None:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="replace")
    parser = _parser()
    arguments = list(argv) if argv is not None else sys.argv[1:]
    if not arguments:
        arguments = ["serve"]
    args = parser.parse_args(arguments)

    if args.command == "mcp":
        os.environ["CODEX_RECALL_CODEX_HOME"] = str(args.codex_home)
        os.environ["CODEX_RECALL_INDEX"] = str(args.data)
        mcp_main()
        return

    store, source = _objects(args)

    if args.command == "serve":
        serve(
            store=store,
            source=source,
            host=args.host,
            port=args.port,
            current_thread=args.thread,
            open_browser=not args.no_browser,
            quiet=not args.verbose,
        )
        return

    if args.command == "index":
        _print_sync(_sync(store, source, full=args.full, thread=args.thread))
        return

    source.sync(thread_id=active_thread_id())
    source.sync()

    if args.command == "tasks":
        for task in store.list_threads(args.query, args.limit, args.archived):
            print(f"{task['id']}  {task['display_name']}  ({task['item_count']} items)")
        return

    if args.command == "search":
        results = store.search(args.query, thread_id=args.thread, limit=args.limit)
        for item in results:
            print(f"[{item['thread_id']}/{item['item_id']}] {item['display_name']} · {item['item_type']}")
            print(item["text"].strip()[:1200])
            print()
        return

    if args.command == "recover":
        thread = store.resolve_thread_id(args.thread)
        if not thread:
            parser.error("no matching local task")
        print(
            store.recovery_packet(
                thread,
                item_id=args.item,
                before=args.before,
                after=args.after,
                include_work=not args.messages_only,
            ),
            end="",
        )
        return

    if args.command == "doctor":
        stats = store.stats()
        checks = [
            ("Codex home", args.codex_home.exists(), str(args.codex_home)),
            ("State database", bool(source.state_db), str(source.state_db or "not found")),
            ("History database", bool(source.history_db), str(source.history_db or "not found")),
            ("Index integrity", store.integrity_check() == "ok", store.integrity_check()),
            ("SQLite FTS5", sqlite3.connect(":memory:").execute("SELECT sqlite_compileoption_used('ENABLE_FTS5')").fetchone()[0] == 1, sqlite3.sqlite_version),
            ("Active task", bool(active_thread_id()), active_thread_id() or "not launched from Codex"),
        ]
        print(f"CodexRecall {__version__}")
        for name, passed, detail in checks:
            print(f"{'OK' if passed else '--':>2}  {name:<18} {detail}")
        print(f"\n{stats['threads']} tasks · {stats['items']} items · {_format_bytes(stats['database_bytes'])}")
        if not all(check[1] for check in checks[:5]):
            raise SystemExit(1)
        return

    if args.command == "install-mcp":
        executable = shutil.which("codex-recall-mcp")
        environment = [
            "--env",
            f"CODEX_RECALL_CODEX_HOME={args.codex_home}",
            "--env",
            f"CODEX_RECALL_INDEX={args.data}",
        ]
        if executable:
            command = ["codex", "mcp", "add", args.name, *environment, "--", executable]
        else:
            command = [
                "codex",
                "mcp",
                "add",
                args.name,
                *environment,
                "--",
                sys.executable,
                "-m",
                "codex_recall.mcp",
            ]
        print("Command   " + subprocess.list2cmdline(command))
        if args.dry_run:
            return
        if not shutil.which("codex"):
            parser.error("Codex CLI was not found on PATH; run the printed command after installing it")
        completed = subprocess.run(command, check=False)
        raise SystemExit(completed.returncode)

    if args.command == "bench":
        index_started = time.perf_counter()
        result = source.sync()
        index_ms = (time.perf_counter() - index_started) * 1000
        samples = []
        for _ in range(max(1, min(args.runs, 200))):
            started = time.perf_counter()
            store.search(args.query, limit=20)
            samples.append((time.perf_counter() - started) * 1000)
        samples.sort()
        p50 = samples[len(samples) // 2]
        p95 = samples[min(len(samples) - 1, int(len(samples) * 0.95))]
        print(f"Incremental index   {index_ms:.2f} ms ({result.items_written} changed items)")
        print(f"Search p50          {p50:.2f} ms")
        print(f"Search p95          {p95:.2f} ms")
        print(f"Search max          {max(samples):.2f} ms")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
