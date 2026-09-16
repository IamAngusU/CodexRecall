from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .storage import RecallStore


MAX_WORK_TEXT = 24_000
MAX_DETAILS_TEXT = 256_000


@dataclass(slots=True)
class SyncResult:
    threads_seen: int = 0
    threads_changed: int = 0
    items_written: int = 0
    tail_bytes_read: int = 0
    elapsed_ms: int = 0
    source: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "threads_seen": self.threads_seen,
            "threads_changed": self.threads_changed,
            "items_written": self.items_written,
            "tail_bytes_read": self.tail_bytes_read,
            "elapsed_ms": self.elapsed_ms,
            "source": self.source,
        }


def default_codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".codex"


def default_index_path() -> Path:
    configured = os.environ.get("CODEX_RECALL_DATA", "").strip()
    if configured:
        return Path(configured).expanduser() / "recall.sqlite"
    return Path.home() / ".codex-recall" / "recall.sqlite"


def active_thread_id() -> str | None:
    value = os.environ.get("CODEX_THREAD_ID", "").strip()
    return value or None


def _discover_numbered_database(root: Path, stem: str) -> Path | None:
    candidates = []
    for path in root.glob(f"{stem}_*.sqlite"):
        try:
            number = int(path.stem.rsplit("_", 1)[1])
        except (IndexError, ValueError):
            number = -1
        candidates.append((number, path.stat().st_mtime_ns, path))
    if not candidates:
        return None
    return max(candidates)[2]


def _read_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(
        f"file:{path.resolve().as_posix()}?mode=ro", uri=True, timeout=30
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


def _strip_extended_prefix(value: str) -> str:
    if value.startswith("\\\\?\\"):
        return value[4:]
    return value


def _milliseconds(value: Any) -> int:
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return number * 1000 if 0 < number < 10_000_000_000 else number


def _timestamp_ms(value: Any) -> int:
    if not value:
        return 0
    if isinstance(value, (int, float)):
        return _milliseconds(value)
    try:
        text = str(value).replace("Z", "+00:00")
        return int(datetime.fromisoformat(text).timestamp() * 1000)
    except (ValueError, TypeError):
        return 0


def _canonical_type(value: Any) -> str:
    text = str(value or "unknown")
    aliases = {
        "UserMessage": "userMessage",
        "AgentMessage": "agentMessage",
        "Reasoning": "reasoning",
        "CommandExecution": "commandExecution",
        "FileChange": "fileChange",
        "McpToolCall": "mcpToolCall",
        "MCPToolCall": "mcpToolCall",
        "WebSearch": "webSearch",
        "ContextCompaction": "contextCompaction",
    }
    if text in aliases:
        return aliases[text]
    return text[:1].lower() + text[1:] if text else "unknown"


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        text = block.get("text")
        if text is None:
            text = block.get("input_text") or block.get("output_text")
        if text:
            parts.append(str(text))
    return "\n".join(parts)


def _truncate(value: str, maximum: int) -> str:
    if len(value) <= maximum:
        return value
    omitted = len(value) - maximum
    return value[:maximum] + f"\n\n[CodexRecall truncated {omitted:,} characters from tool data]"


def _head_tail(value: str, maximum: int) -> str:
    if len(value) <= maximum:
        return value
    head = maximum // 2
    tail = maximum - head
    omitted = len(value) - maximum
    return (
        value[:head]
        + f"\n\n[CodexRecall omitted {omitted:,} middle characters from tool data]\n\n"
        + value[-tail:]
    )


def _sanitize(value: Any, *, depth: int = 0) -> Any:
    if depth > 12:
        return "[depth limit]"
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key in {
                "encrypted_content",
                "encryptedContent",
                "raw_content",
                "rawContent",
                "base_instructions",
                "developer_instructions",
            }:
                continue
            result[str(key)] = _sanitize(item, depth=depth + 1)
        return result
    if isinstance(value, list):
        return [_sanitize(item, depth=depth + 1) for item in value[:10_000]]
    if isinstance(value, str):
        return _truncate(value, MAX_DETAILS_TEXT)
    return value


def _normalize_item(
    *,
    thread_id: str,
    turn_id: str,
    ordinal: int,
    created_at_ms: int,
    raw: dict[str, Any],
    source: str,
    exact: bool = False,
) -> dict[str, Any] | None:
    item_type = _canonical_type(raw.get("type"))
    item_id = str(raw.get("id") or f"{turn_id}:{ordinal}:{item_type}")
    phase = str(raw.get("phase") or "")
    role = "work"
    text = ""

    if item_type == "userMessage":
        role = "user"
        text = _content_text(raw.get("content")) or str(raw.get("text") or "")
    elif item_type == "agentMessage":
        role = "assistant"
        text = str(raw.get("text") or "") or _content_text(raw.get("content"))
    elif item_type == "reasoning":
        role = "work"
        summary = raw.get("summary") or raw.get("summary_text") or []
        if isinstance(summary, list):
            text = "\n".join(
                str(entry.get("text") if isinstance(entry, dict) else entry)
                for entry in summary
                if entry
            )
        else:
            text = str(summary)
    elif item_type == "commandExecution":
        role = "tool"
        command = str(raw.get("command") or "")
        output = str(raw.get("aggregatedOutput") or raw.get("output") or "")
        if not exact:
            command = _head_tail(command, 8_000)
            output = _head_tail(output, 12_000)
        status = str(raw.get("status") or "")
        text = f"$ {command}"
        if status:
            text += f"\nstatus: {status}"
        if output:
            text += "\n\n" + output
    elif item_type == "fileChange":
        role = "tool"
        parts = []
        for change in raw.get("changes", []):
            if not isinstance(change, dict):
                continue
            path = str(change.get("path") or "unknown")
            diff = str(change.get("diff") or "")
            if not exact:
                diff = _head_tail(diff, 20_000)
            parts.append(f"FILE {path}\n{diff}")
        text = "\n\n".join(parts)
    elif item_type == "mcpToolCall":
        role = "tool"
        server = str(raw.get("server") or "")
        tool = str(raw.get("tool") or "")
        arguments = json.dumps(raw.get("arguments") or {}, ensure_ascii=False, indent=2)
        result = json.dumps(raw.get("result") or raw.get("error") or {}, ensure_ascii=False, indent=2)
        if not exact:
            arguments = _head_tail(arguments, 8_000)
            result = _head_tail(result, 16_000)
        text = f"MCP {server}.{tool}\n{arguments}\n\n{result}"
    elif item_type == "webSearch":
        role = "tool"
        text = str(raw.get("query") or "")
        results = raw.get("results") or []
        if results:
            text += "\n\n" + json.dumps(results, ensure_ascii=False, indent=2)
    elif item_type == "contextCompaction":
        role = "system"
        text = "Context window compacted"
    else:
        role = str(raw.get("role") or "work")
        text = str(raw.get("text") or "") or _content_text(raw.get("content"))

    if not text.strip() and item_type not in {"contextCompaction"}:
        return None

    if item_type in {"userMessage", "agentMessage"}:
        details: dict[str, Any] = {
            "type": item_type,
            "id": item_id,
            "phase": phase,
        }
    elif item_type == "fileChange":
        details = {"type": item_type, "id": item_id, "changes": []}
        for change in raw.get("changes", []):
            if not isinstance(change, dict):
                continue
            diff = str(change.get("diff") or "")
            additions = sum(
                1 for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")
            )
            deletions = sum(
                1 for line in diff.splitlines() if line.startswith("-") and not line.startswith("---")
            )
            record = {
                "path": str(change.get("path") or "unknown"),
                "kind": _sanitize(change.get("kind") or {}),
                "additions": additions,
                "deletions": deletions,
            }
            details["changes"].append(record)
    elif item_type == "commandExecution":
        details = {
            "type": item_type,
            "id": item_id,
            "status": raw.get("status"),
            "cwd": raw.get("cwd"),
            "exitCode": raw.get("exitCode"),
            "durationMs": raw.get("durationMs"),
        }
    elif item_type == "mcpToolCall":
        details = {
            "type": item_type,
            "id": item_id,
            "server": raw.get("server"),
            "tool": raw.get("tool"),
            "status": raw.get("status"),
            "durationMs": raw.get("durationMs"),
        }
    else:
        details = {
            "type": item_type,
            "id": item_id,
            "phase": phase,
        }
    details_json = json.dumps(details, ensure_ascii=False, separators=(",", ":"))
    if len(details_json) > MAX_DETAILS_TEXT:
        details_json = json.dumps(
            {"type": item_type, "id": item_id, "truncated": True},
            separators=(",", ":"),
        )

    return {
        "thread_id": thread_id,
        "item_id": item_id,
        "turn_id": turn_id,
        "ordinal": int(ordinal or 0),
        "created_at_ms": int(created_at_ms or 0),
        "item_type": item_type,
        "role": role,
        "phase": phase,
        "text": text
        if exact or item_type in {"userMessage", "agentMessage"}
        else _head_tail(text, MAX_WORK_TEXT),
        "details_json": details_json,
        "source": source,
    }


class CodexSource:
    def __init__(self, codex_home: Path, store: RecallStore) -> None:
        self.codex_home = codex_home.expanduser().resolve()
        self.store = store
        self.state_db = _discover_numbered_database(self.codex_home, "state")
        self.history_db = _discover_numbered_database(self.codex_home, "thread_history")

    @property
    def available(self) -> bool:
        return bool(self.state_db and self.state_db.exists())

    def exact_text(self, thread_id: str, item_id: str) -> str | None:
        if self.history_db and self.history_db.exists():
            history = _read_connection(self.history_db)
            try:
                row = history.execute(
                    """
                    SELECT turn_id,rollout_ordinal,created_at_ms,item_json
                    FROM thread_items WHERE thread_id=? AND item_id=? LIMIT 1
                    """,
                    (thread_id, item_id),
                ).fetchone()
                if row:
                    raw = json.loads(row["item_json"])
                    normalized = _normalize_item(
                        thread_id=thread_id,
                        turn_id=str(row["turn_id"] or ""),
                        ordinal=int(row["rollout_ordinal"] or 0),
                        created_at_ms=int(row["created_at_ms"] or 0),
                        raw=raw,
                        source="thread_history",
                        exact=True,
                    )
                    return str(normalized["text"]) if normalized else None
            finally:
                history.close()

        thread = self.store.get_thread(thread_id)
        path_text = str((thread or {}).get("rollout_path") or "")
        path = Path(path_text) if path_text else None
        if not path or not path.is_file():
            return None
        with path.open("rb") as handle:
            for line in handle:
                if item_id.encode("utf-8") not in line:
                    continue
                try:
                    event = json.loads(line.decode("utf-8", errors="replace"))
                except json.JSONDecodeError:
                    continue
                payload = event.get("payload") or {}
                raw = payload.get("item") if payload.get("type") == "item_completed" else None
                if not isinstance(raw, dict) or str(raw.get("id") or "") != item_id:
                    continue
                normalized = _normalize_item(
                    thread_id=thread_id,
                    turn_id=str(payload.get("turn_id") or ""),
                    ordinal=int(event.get("ordinal") or 0),
                    created_at_ms=_timestamp_ms(event.get("timestamp")),
                    raw=raw,
                    source="rollout_tail",
                    exact=True,
                )
                return str(normalized["text"]) if normalized else None
        return None

    def sync(
        self,
        *,
        full: bool = False,
        thread_id: str | None = None,
    ) -> SyncResult:
        started = time.perf_counter()
        if not self.available:
            result = self._sync_jsonl_fallback(full=full, thread_id=thread_id)
            result.elapsed_ms = int((time.perf_counter() - started) * 1000)
            return result

        result = SyncResult(source="codex-state+history+rollout-tail")
        state = _read_connection(self.state_db)  # type: ignore[arg-type]
        history = _read_connection(self.history_db) if self.history_db else None
        try:
            all_threads = self._load_threads(state, full=full, requested=thread_id)
            result.threads_seen = len(all_threads)
            if not all_threads:
                result.elapsed_ms = int((time.perf_counter() - started) * 1000)
                return result

            projection = self._load_projection_state(history)
            with self.store.writer() as destination:
                if full:
                    destination.execute("DELETE FROM turns")
                    destination.execute("DELETE FROM items")
                    destination.execute("DELETE FROM source_progress")
                    destination.execute("DELETE FROM threads")
                for record in all_threads:
                    RecallStore.upsert_thread(destination, record)

                changed_ids = [record["id"] for record in all_threads]
                result.threads_changed = len(changed_ids)

                if history:
                    self._sync_turns(history, destination, changed_ids)
                    result.items_written += self._sync_history_items(
                        history, destination, changed_ids, full=full
                    )

                for record in all_threads:
                    written, bytes_read = self._sync_rollout_tail(
                        destination,
                        record,
                        projection.get(record["id"], 0),
                        full=full,
                    )
                    result.items_written += written
                    result.tail_bytes_read += bytes_read

                RecallStore.mark_final_items(destination, changed_ids)
                RecallStore.update_item_counts(destination, changed_ids)
                newest = max(int(record.get("updated_at_ms") or 0) for record in all_threads)
                previous = int(self.store.get_meta("last_source_updated_ms", "0") or 0)
                self.store.set_meta(
                    destination, "last_source_updated_ms", max(previous, newest)
                )
                self.store.set_meta(destination, "last_sync_at_ms", int(time.time() * 1000))
        finally:
            state.close()
            if history:
                history.close()
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        if full:
            self.store.optimize(compact=True)
        return result

    def _load_threads(
        self,
        connection: sqlite3.Connection,
        *,
        full: bool,
        requested: str | None,
    ) -> list[dict[str, Any]]:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(threads)")}
        wanted = [
            "id",
            "name",
            "title",
            "preview",
            "cwd",
            "rollout_path",
            "source",
            "model",
            "created_at_ms",
            "updated_at_ms",
            "created_at",
            "updated_at",
            "archived",
        ]
        selected = [column for column in wanted if column in columns]
        last_updated = int(self.store.get_meta("last_source_updated_ms", "0") or 0)
        where: list[str] = []
        params: list[Any] = []
        if requested:
            where.append("id=?")
            params.append(requested)
        elif not full and last_updated and "updated_at_ms" in columns:
            where.append("updated_at_ms>=?")
            params.append(max(0, last_updated - 2_000))
        sql = f"SELECT {','.join(selected)} FROM threads"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY updated_at_ms DESC" if "updated_at_ms" in columns else ""
        rows = connection.execute(sql, params).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["created_at_ms"] = int(
                item.get("created_at_ms") or _milliseconds(item.get("created_at"))
            )
            item["updated_at_ms"] = int(
                item.get("updated_at_ms") or _milliseconds(item.get("updated_at"))
            )
            item["cwd"] = _strip_extended_prefix(str(item.get("cwd") or ""))
            item["rollout_path"] = _strip_extended_prefix(
                str(item.get("rollout_path") or "")
            )
            result.append(item)
        return result

    @staticmethod
    def _load_projection_state(
        history: sqlite3.Connection | None,
    ) -> dict[str, int]:
        if not history:
            return {}
        try:
            return {
                str(row[0]): int(row[1] or 0)
                for row in history.execute(
                    "SELECT thread_id,next_rollout_byte_offset FROM thread_history_projection_state"
                )
            }
        except sqlite3.OperationalError:
            return {}

    @staticmethod
    def _sync_turns(
        source: sqlite3.Connection,
        destination: sqlite3.Connection,
        thread_ids: Iterable[str],
    ) -> None:
        for current in thread_ids:
            try:
                rows = source.execute(
                    """
                    SELECT thread_id,turn_id,rollout_ordinal,status,started_at,
                           completed_at,duration_ms,final_agent_item_id
                    FROM thread_turns WHERE thread_id=?
                    """,
                    (current,),
                )
            except sqlite3.OperationalError:
                return
            for row in rows:
                RecallStore.upsert_turn(
                    destination,
                    {
                        "thread_id": row["thread_id"],
                        "turn_id": row["turn_id"],
                        "ordinal": row["rollout_ordinal"],
                        "status": row["status"],
                        "started_at_ms": _milliseconds(row["started_at"]),
                        "completed_at_ms": _milliseconds(row["completed_at"]),
                        "duration_ms": row["duration_ms"],
                        "final_agent_item_id": row["final_agent_item_id"],
                    },
                )

    def _sync_history_items(
        self,
        source: sqlite3.Connection,
        destination: sqlite3.Connection,
        thread_ids: Iterable[str],
        *,
        full: bool,
    ) -> int:
        count = 0
        for current in thread_ids:
            progress = RecallStore.get_progress(destination, current)
            after = 0 if full else int(progress.get("history_ordinal") or 0)
            maximum = after
            rows = source.execute(
                """
                SELECT thread_id,turn_id,item_id,rollout_ordinal,created_at_ms,
                       item_json,item_type,updated_at_ordinal
                FROM thread_items
                WHERE thread_id=? AND updated_at_ordinal>?
                ORDER BY updated_at_ordinal
                """,
                (current, after),
            )
            for row in rows:
                maximum = max(maximum, int(row["updated_at_ordinal"] or 0))
                try:
                    raw = json.loads(row["item_json"])
                except (json.JSONDecodeError, TypeError):
                    continue
                normalized = _normalize_item(
                    thread_id=current,
                    turn_id=str(row["turn_id"] or ""),
                    ordinal=int(row["rollout_ordinal"] or 0),
                    created_at_ms=int(row["created_at_ms"] or 0),
                    raw=raw,
                    source="thread_history",
                )
                if normalized:
                    RecallStore.upsert_item(destination, normalized)
                    count += 1
            progress["history_ordinal"] = maximum
            RecallStore.set_progress(destination, progress)
        return count

    def _sync_rollout_tail(
        self,
        destination: sqlite3.Connection,
        thread: dict[str, Any],
        projection_offset: int,
        *,
        full: bool,
    ) -> tuple[int, int]:
        thread_id = str(thread["id"])
        path_text = str(thread.get("rollout_path") or "")
        if not path_text:
            return 0, 0
        path = Path(path_text)
        if not path.exists() or not path.is_file():
            return 0, 0
        size = path.stat().st_size
        progress = RecallStore.get_progress(destination, thread_id)
        same_path = str(progress.get("rollout_path") or "") == str(path)
        previous_offset = int(progress.get("rollout_offset") or 0) if same_path else 0
        if previous_offset > size:
            previous_offset = 0
        start = max(0, int(projection_offset or 0), previous_offset)
        if full:
            start = max(0, int(projection_offset or 0))
        written = 0
        end_offset = start
        with path.open("rb") as handle:
            handle.seek(start)
            if start:
                handle.seek(start - 1)
                if handle.read(1) not in {b"\n", b"\r"}:
                    handle.readline()
                end_offset = handle.tell()
            while True:
                line_start = handle.tell()
                line = handle.readline()
                if not line:
                    end_offset = line_start
                    break
                if not line.endswith((b"\n", b"\r")):
                    end_offset = line_start
                    break
                end_offset = handle.tell()
                try:
                    event = json.loads(line.decode("utf-8", errors="replace"))
                except json.JSONDecodeError:
                    continue
                if event.get("type") != "event_msg":
                    continue
                payload = event.get("payload") or {}
                if payload.get("type") != "item_completed":
                    continue
                raw = payload.get("item")
                if not isinstance(raw, dict):
                    continue
                normalized = _normalize_item(
                    thread_id=thread_id,
                    turn_id=str(payload.get("turn_id") or ""),
                    ordinal=int(event.get("ordinal") or 0),
                    created_at_ms=_timestamp_ms(event.get("timestamp")),
                    raw=raw,
                    source="rollout_tail",
                )
                if normalized:
                    RecallStore.upsert_item(destination, normalized)
                    written += 1
        progress.update(
            {
                "thread_id": thread_id,
                "rollout_path": str(path),
                "rollout_offset": end_offset,
                "rollout_size": size,
                "updated_at_ms": int(time.time() * 1000),
            }
        )
        RecallStore.set_progress(destination, progress)
        return written, max(0, end_offset - start)

    def _sync_jsonl_fallback(
        self, *, full: bool, thread_id: str | None
    ) -> SyncResult:
        result = SyncResult(source="rollout-jsonl-fallback")
        session_root = self.codex_home / "sessions"
        if not session_root.exists():
            return result
        paths = sorted(session_root.rglob("*.jsonl"), key=lambda item: item.stat().st_mtime_ns)
        with self.store.writer() as destination:
            if full:
                destination.execute("DELETE FROM turns")
                destination.execute("DELETE FROM items")
                destination.execute("DELETE FROM source_progress")
                destination.execute("DELETE FROM threads")
            changed: list[str] = []
            for path in paths:
                metadata = self._read_session_metadata(path)
                if not metadata:
                    continue
                current = str(metadata["id"])
                if thread_id and current != thread_id:
                    continue
                result.threads_seen += 1
                metadata["rollout_path"] = str(path)
                RecallStore.upsert_thread(destination, metadata)
                changed.append(current)
                written, bytes_read = self._sync_rollout_tail(
                    destination, metadata, 0, full=full
                )
                result.items_written += written
                result.tail_bytes_read += bytes_read
            RecallStore.update_item_counts(destination, changed)
            result.threads_changed = len(changed)
        return result

    @staticmethod
    def _read_session_metadata(path: Path) -> dict[str, Any] | None:
        try:
            with path.open("rb") as handle:
                for _ in range(20):
                    line = handle.readline()
                    if not line:
                        break
                    event = json.loads(line.decode("utf-8", errors="replace"))
                    if event.get("type") != "session_meta":
                        continue
                    payload = event.get("payload") or {}
                    current = str(payload.get("id") or payload.get("session_id") or "")
                    if not current:
                        return None
                    stamp = _timestamp_ms(payload.get("timestamp"))
                    return {
                        "id": current,
                        "name": "",
                        "title": "",
                        "preview": "",
                        "cwd": str(payload.get("cwd") or ""),
                        "rollout_path": str(path),
                        "source": str(payload.get("source") or ""),
                        "model": "",
                        "created_at_ms": stamp,
                        "updated_at_ms": int(path.stat().st_mtime * 1000),
                        "archived": 0,
                    }
        except (OSError, json.JSONDecodeError):
            return None
        return None
