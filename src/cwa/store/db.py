"""Small transactional SQLite store for the local API."""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4


class Database:
    def __init__(self, path: str | Path) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, session_id TEXT, question TEXT NOT NULL,
                    result_json TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (
                    turn_idx INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL, question TEXT NOT NULL, answer TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS session_lookup ON sessions(session_id, turn_idx);
                CREATE TABLE IF NOT EXISTS plans (
                    id TEXT PRIMARY KEY, run_id TEXT, title TEXT NOT NULL,
                    device TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL,
                    expected_kg_co2 REAL NOT NULL, notes TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected')),
                    created_at TEXT NOT NULL, approved_at TEXT);
            """)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def save_run(self, result: Any, session_id: str | None, question: str) -> None:
        data = result.model_dump(mode="json")
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO runs VALUES (?, ?, ?, ?, ?)",
                (data["run_id"], session_id, question, json.dumps(data), _now()),
            )
            if session_id:
                self._conn.execute(
                    "INSERT INTO sessions(session_id,question,answer) VALUES (?,?,?)",
                    (session_id, question, json.dumps(data["answer"])),
                )
                self._conn.execute(
                    "DELETE FROM sessions WHERE session_id=? AND turn_idx NOT IN "
                    "(SELECT turn_idx FROM sessions WHERE session_id=? "
                    "ORDER BY turn_idx DESC LIMIT 6)",
                    (session_id, session_id),
                )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            return None
        return {
            **json.loads(row["result_json"]),
            "question": row["question"],
            "session_id": row["session_id"],
            "created_at": row["created_at"],
        }

    def history(self, session_id: str | None) -> list[dict[str, str]]:
        if session_id is None:
            return []
        with self._lock:
            rows = self._conn.execute(
                "SELECT question,answer FROM sessions WHERE session_id=? ORDER BY turn_idx",
                (session_id,),
            ).fetchall()
        return [
            message
            for row in rows
            for message in (
                {"role": "user", "content": row["question"]},
                {"role": "assistant", "content": row["answer"]},
            )
        ]

    def create_plan(
        self,
        *,
        title: str,
        device: str,
        start: str | datetime,
        end: str | datetime,
        expected_kg_co2: float,
        notes: str,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        start_dt = datetime.fromisoformat(start) if isinstance(start, str) else start
        end_dt = datetime.fromisoformat(end) if isinstance(end, str) else end
        if (
            start_dt.tzinfo is None
            or end_dt.tzinfo is None
            or end_dt <= start_dt
            or not math.isfinite(expected_kg_co2)
            or expected_kg_co2 < 0
        ):
            raise ValueError("Invalid plan time range or emissions")
        if not title.strip() or not device.strip():
            raise ValueError("Plan title and device must be nonempty")
        plan = dict(
            id=str(uuid4()),
            run_id=run_id,
            title=title,
            device=device,
            start=start_dt.isoformat(),
            end=end_dt.isoformat(),
            expected_kg_co2=expected_kg_co2,
            notes=notes,
            status="pending",
            created_at=_now(),
            approved_at=None,
        )
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO plans VALUES (?,?,?,?,?,?,?,?,?,?,?)", tuple(plan.values())
            )
        return plan

    def list_plans(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                dict(row)
                for row in self._conn.execute("SELECT * FROM plans ORDER BY created_at DESC")
            ]

    def _transition(self, plan_id: str, status: str) -> dict[str, Any]:
        with self._lock, self._conn:
            row = self._conn.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
            if row is None:
                raise KeyError(plan_id)
            if row["status"] != "pending":
                raise ValueError("Only pending plans can be approved or rejected")
            self._conn.execute(
                "UPDATE plans SET status=?,approved_at=? WHERE id=?",
                (status, _now() if status == "approved" else None, plan_id),
            )
            return dict(self._conn.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone())

    def approve_plan(self, plan_id: str) -> dict[str, Any]:
        return self._transition(plan_id, "approved")

    def reject_plan(self, plan_id: str) -> dict[str, Any]:
        return self._transition(plan_id, "rejected")


def _now() -> str:
    return datetime.now(UTC).isoformat()
