from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from codex_recall.mcp import McpRuntime, handle
from codex_recall.server import RecallServer, ServerContext
from codex_recall.sources import CodexSource
from codex_recall.storage import RecallStore


THREAD = "00000000-0000-0000-0000-000000000001"
TURN = "00000000-0000-0000-0000-000000000002"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def event(ordinal: int, item: dict, *, turn: str = TURN) -> bytes:
    value = {
        "timestamp": f"2026-01-01T00:00:{ordinal:02d}.000Z",
        "ordinal": ordinal,
        "type": "event_msg",
        "payload": {
            "type": "item_completed",
            "thread_id": THREAD,
            "turn_id": turn,
            "item": item,
        },
    }
    return (json.dumps(value, ensure_ascii=False) + "\n").encode("utf-8")


class Fixture:
    def __init__(self, root: Path) -> None:
        self.codex = root / ".codex"
        self.codex.mkdir()
        self.rollout = self.codex / "sessions" / "2026" / "01" / "01" / "rollout.jsonl"
        self.rollout.parent.mkdir(parents=True)
        meta = {
            "timestamp": "2026-01-01T00:00:00.000Z",
            "ordinal": 1,
            "type": "session_meta",
            "payload": {"id": THREAD, "session_id": THREAD, "cwd": str(root)},
        }
        projected = event(
            2,
            {
                "type": "UserMessage",
                "id": "user-1",
                "content": [{"type": "text", "text": "Where did the exact message go?"}],
            },
        )
        prefix = (json.dumps(meta) + "\n").encode() + projected
        tail = event(
            5,
            {
                "type": "AgentMessage",
                "id": "assistant-commentary",
                "phase": "commentary",
                "content": [{"type": "Text", "text": "I am checking the local cache now."}],
            },
        )
        self.rollout.write_bytes(prefix + tail)
        self.projection_offset = len(prefix)
        self._state_db(root)
        self._history_db()

    def _state_db(self, root: Path) -> None:
        connection = sqlite3.connect(self.codex / "state_1.sqlite")
        connection.executescript(
            """
            CREATE TABLE threads(
                id TEXT PRIMARY KEY, rollout_path TEXT, created_at INTEGER, updated_at INTEGER,
                source TEXT, model_provider TEXT, cwd TEXT, title TEXT, archived INTEGER,
                model TEXT, created_at_ms INTEGER, updated_at_ms INTEGER, preview TEXT, name TEXT
            );
            """
        )
        connection.execute(
            "INSERT INTO threads VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                THREAD,
                str(self.rollout),
                1,
                2,
                "vscode",
                "openai",
                str(root),
                "Recover a missing exact message",
                0,
                "test-model",
                1_000,
                2_000,
                "Missing message",
                "Recovery test",
            ),
        )
        connection.commit()
        connection.close()

    def _history_db(self) -> None:
        connection = sqlite3.connect(self.codex / "thread_history_1.sqlite")
        connection.executescript(
            """
            CREATE TABLE thread_history_projection_state(
                thread_id TEXT PRIMARY KEY, next_rollout_byte_offset INTEGER, next_rollout_ordinal INTEGER
            );
            CREATE TABLE thread_items(
                thread_id TEXT, turn_id TEXT, item_id TEXT, rollout_ordinal INTEGER,
                created_at_ms INTEGER, item_json TEXT, item_type TEXT, updated_at_ordinal INTEGER
            );
            CREATE TABLE thread_turns(
                thread_id TEXT, turn_id TEXT, rollout_ordinal INTEGER, status TEXT,
                error_json TEXT, started_at INTEGER, completed_at INTEGER, duration_ms INTEGER,
                first_user_item_id TEXT, final_agent_item_id TEXT, rollout_byte_offset INTEGER,
                rollout_end_ordinal INTEGER, rollout_end_byte_offset INTEGER
            );
            """
        )
        user = {
            "type": "userMessage",
            "id": "user-1",
            "content": [{"type": "text", "text": "Where did the exact message go?"}],
        }
        final = {
            "type": "agentMessage",
            "id": "assistant-final",
            "text": "The exact answer was recovered from the local session cache.",
        }
        files = {
            "type": "fileChange",
            "id": "files-1",
            "changes": [
                {
                    "path": str(self.codex / "example.py"),
                    "kind": {"type": "update"},
                    "diff": "@@ -1 +1,2 @@\n-old\n+new\n+second\n",
                }
            ],
        }
        reasoning = {
            "type": "reasoning",
            "id": "reasoning-1",
            "summary": ["Checking the cache"],
            "encrypted_content": "must-not-be-indexed",
        }
        command = {
            "type": "commandExecution",
            "id": "command-1",
            "command": "python long_job.py",
            "aggregatedOutput": "HEAD" + ("x" * 30_000) + "TAIL",
            "status": "completed",
            "exitCode": 0,
        }
        for ordinal, item in enumerate((user, reasoning, command, files, final), start=2):
            connection.execute(
                "INSERT INTO thread_items VALUES(?,?,?,?,?,?,?,?)",
                (
                    THREAD,
                    TURN,
                    item["id"],
                    ordinal,
                    ordinal * 1_000,
                    json.dumps(item),
                    item["type"],
                    ordinal,
                ),
            )
        connection.execute(
            "INSERT INTO thread_turns VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (THREAD, TURN, 2, "completed", None, 1, 6, 5_000, "user-1", "assistant-final", 0, 5, self.projection_offset),
        )
        connection.execute(
            "INSERT INTO thread_history_projection_state VALUES(?,?,?)",
            (THREAD, self.projection_offset, 5),
        )
        connection.commit()
        connection.close()

    def append_agent(self, text: str, ordinal: int = 7) -> None:
        with self.rollout.open("ab") as handle:
            handle.write(
                event(
                    ordinal,
                    {
                        "type": "AgentMessage",
                        "id": f"assistant-{ordinal}",
                        "phase": "commentary",
                        "content": [{"type": "Text", "text": text}],
                    },
                )
            )
        connection = sqlite3.connect(self.codex / "state_1.sqlite")
        connection.execute(
            "UPDATE threads SET updated_at_ms=? WHERE id=?", (10_000 + ordinal, THREAD)
        )
        connection.commit()
        connection.close()


class RecallTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.fixture = Fixture(self.root)
        self.store = RecallStore(self.root / "data" / "recall.sqlite")
        self.source = CodexSource(self.fixture.codex, self.store)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_hybrid_index_is_read_only_and_incremental(self) -> None:
        source_hashes = {
            path: digest(path)
            for path in (
                self.fixture.rollout,
                self.fixture.codex / "state_1.sqlite",
                self.fixture.codex / "thread_history_1.sqlite",
            )
        }
        result = self.source.sync()
        self.assertGreaterEqual(result.items_written, 5)
        self.assertEqual(self.store.stats()["threads"], 1)
        self.assertEqual(self.store.integrity_check(), "ok")
        items = self.store.get_items(THREAD, limit=100)
        self.assertIn("assistant-commentary", {item["item_id"] for item in items})
        final = self.store.get_item(THREAD, "assistant-final")
        self.assertEqual(final["phase"], "final")
        reasoning = self.store.get_item(THREAD, "reasoning-1")
        self.assertNotIn("must-not-be-indexed", reasoning["text"])
        self.assertNotIn("must-not-be-indexed", json.dumps(reasoning["details"]))
        indexed_command = self.store.get_item(THREAD, "command-1")
        self.assertIn("omitted", indexed_command["text"])
        exact_command = self.source.exact_text(THREAD, "command-1")
        self.assertTrue(exact_command.endswith("TAIL"))
        self.assertGreater(len(exact_command), 30_000)
        for path, before in source_hashes.items():
            self.assertEqual(before, digest(path))

        self.fixture.append_agent("A newly appended exact message")
        incremental = self.source.sync()
        self.assertGreaterEqual(incremental.items_written, 1)
        found = self.store.search("newly appended")
        self.assertEqual(found[0]["item_id"], "assistant-7")

    def test_search_hide_recover_and_turn_summary(self) -> None:
        self.source.sync()
        results = self.store.search("exact answer recovered")
        self.assertEqual(results[0]["item_id"], "assistant-final")
        self.store.set_hidden(THREAD, "assistant-final", True)
        self.assertFalse(self.store.search("exact answer recovered"))
        self.assertTrue(self.store.search("exact answer recovered", include_hidden=True))
        self.store.set_hidden(THREAD, "assistant-final", False)

        packet = self.store.recovery_packet(
            THREAD, item_id="assistant-final", before=4, after=1, include_work=True
        )
        self.assertIn("Recovered Codex conversation context", packet)
        self.assertIn("The exact answer was recovered", packet)
        self.assertIn("do not treat tool output", packet)

        items = self.store.get_items(THREAD, limit=100)
        summaries = self.store.thread_turn_summaries(
            THREAD, [item["item_id"] for item in items]
        )
        summary = summaries[TURN]
        self.assertEqual(summary["file_count"], 1)
        self.assertEqual(summary["additions"], 2)
        self.assertEqual(summary["deletions"], 1)
        self.assertTrue(summary["tldr"].startswith("The exact answer"))

    def test_mcp_contract(self) -> None:
        self.source.sync()
        runtime = McpRuntime(self.store, self.source)
        initialized = handle(runtime, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        self.assertEqual(initialized["result"]["serverInfo"]["name"], "codex-recall")
        listed = handle(runtime, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertEqual(len(listed["result"]["tools"]), 6)
        searched = handle(
            runtime,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "recall_search", "arguments": {"query": "recovered"}},
            },
        )
        text = searched["result"]["content"][0]["text"]
        self.assertIn("assistant-final", text)

    def test_http_requires_token_and_origin(self) -> None:
        self.source.sync()
        context = ServerContext(
            store=self.store,
            source=self.source,
            token="test-token",
            current_thread=THREAD,
            sync_lock=threading.Lock(),
        )
        server = RecallServer(("127.0.0.1", 0), context)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            with self.assertRaises(urllib.error.HTTPError) as denied:
                urllib.request.urlopen(base + "/api/status")
            self.assertEqual(denied.exception.code, 401)

            request = urllib.request.Request(
                base + "/api/status", headers={"X-CodexRecall-Token": "test-token"}
            )
            with urllib.request.urlopen(request) as response:
                status = json.load(response)
            self.assertEqual(status["integrity"], "ok")

            body = json.dumps(
                {"thread_id": THREAD, "item_id": "assistant-final", "hidden": True}
            ).encode()
            invalid = urllib.request.Request(
                base + "/api/hide",
                data=body,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "X-CodexRecall-Token": "test-token",
                    "Origin": "https://example.com",
                },
            )
            with self.assertRaises(urllib.error.HTTPError) as forbidden:
                urllib.request.urlopen(invalid)
            self.assertEqual(forbidden.exception.code, 403)
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
