"""SQLite 저장 계층. 공유기별 기기 목록/온라인 이력을 보관한다."""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
-- 실마다 있는 개별 공유기. label은 "청소년부실" 처럼 사용자가 바꿀 수 있다.
CREATE TABLE IF NOT EXISTS routers (
    id TEXT PRIMARY KEY,       -- config.yaml에서 지정한 고유 id (예: 'router1')
    label TEXT                 -- 화면에 보여줄 이름
);

CREATE TABLE IF NOT EXISTS devices (
    mac TEXT PRIMARY KEY,
    router_id TEXT,
    ip TEXT,
    hostname TEXT,              -- 공유기가 보고하는 원래 단말명 (기기 자체 설정 이름)
    alias TEXT,                 -- 사용자가 직접 수정한 이름. 있으면 hostname보다 항상 우선
    latency_ms INTEGER,         -- 가장 최근 측정한 응답 지연시간 (ms), 오프라인이면 NULL
    approved INTEGER DEFAULT 0, -- 0=미승인(차단 대상), 1=승인됨
    first_seen INTEGER,
    last_seen INTEGER,
    is_online INTEGER DEFAULT 0,
    is_blocked INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mac TEXT,
    event TEXT,          -- 'online' | 'offline'
    ts INTEGER
);

-- 메인 공유기에 적용할 'MAC 허용 목록'을 여기서 관리한다.
CREATE TABLE IF NOT EXISTS whitelist (
    mac TEXT PRIMARY KEY,
    label TEXT,
    added_at INTEGER
);
"""


class Database:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)

    def _migrate(self, conn) -> None:
        """기존에 만들어둔 DB 파일에 새 컬럼이 없으면 추가한다 (기존 데이터 보존)."""
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(devices)")}
        additions = {
            "router_id": "TEXT",
            "latency_ms": "INTEGER",
            "approved": "INTEGER DEFAULT 0",
        }
        for col, coltype in additions.items():
            if col not in cols:
                conn.execute(f"ALTER TABLE devices ADD COLUMN {col} {coltype}")

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 공유기(라우터) 관리
    # ------------------------------------------------------------------
    def upsert_router(self, router_id: str, default_label: str) -> None:
        """공유기를 등록한다. 이미 사용자가 이름을 바꿔둔 적 있으면 그 이름을 유지한다."""
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM routers WHERE id = ?", (router_id,)).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO routers (id, label) VALUES (?, ?)", (router_id, default_label)
                )

    def rename_router(self, router_id: str, label: str) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE routers SET label = ? WHERE id = ?", (label, router_id))

    def list_routers(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM routers ORDER BY id").fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # 기기 관리
    # ------------------------------------------------------------------
    def upsert_device(self, mac: str, router_id: str, ip: str, hostname: str,
                       is_online: bool) -> bool:
        """기기 정보를 갱신한다. 온라인 상태가 바뀌었으면 True를 반환(이벤트 기록용).

        alias(사용자가 수정한 이름)가 있으면 hostname이 바뀌어도 alias는 건드리지 않는다.
        """
        now = int(time.time())
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM devices WHERE mac = ?", (mac,)).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO devices (mac, router_id, ip, hostname, first_seen, last_seen, "
                    "is_online, approved) VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
                    (mac, router_id, ip, hostname, now, now, int(is_online)),
                )
                if is_online:
                    conn.execute(
                        "INSERT INTO events (mac, event, ts) VALUES (?, 'online', ?)", (mac, now)
                    )
                return True

            changed = bool(row["is_online"]) != is_online
            conn.execute(
                "UPDATE devices SET router_id = ?, ip = ?, hostname = ?, last_seen = ?, "
                "is_online = ? WHERE mac = ?",
                (router_id, ip, hostname, now, int(is_online), mac),
            )
            if changed:
                conn.execute(
                    "INSERT INTO events (mac, event, ts) VALUES (?, ?, ?)",
                    (mac, "online" if is_online else "offline", now),
                )
            return changed

    def set_latency(self, mac: str, latency_ms: int | None) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE devices SET latency_ms = ? WHERE mac = ?", (latency_ms, mac))

    def set_approved(self, mac: str, approved: bool) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE devices SET approved = ? WHERE mac = ?", (int(approved), mac))

    def mark_all_offline_except(self, seen_macs: set[str]) -> None:
        now = int(time.time())
        with self._conn() as conn:
            rows = conn.execute("SELECT mac FROM devices WHERE is_online = 1").fetchall()
            for row in rows:
                if row["mac"] not in seen_macs:
                    conn.execute(
                        "UPDATE devices SET is_online = 0, latency_ms = NULL, last_seen = ? "
                        "WHERE mac = ?",
                        (now, row["mac"]),
                    )
                    conn.execute(
                        "INSERT INTO events (mac, event, ts) VALUES (?, 'offline', ?)",
                        (row["mac"], now),
                    )

    def list_devices(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM devices ORDER BY is_online DESC, last_seen DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def list_devices_grouped_by_router(self) -> list[dict]:
        """공유기별로 그룹화된 기기 목록. 화면에서 바로 쓰기 좋은 형태로 반환."""
        routers = {r["id"]: r["label"] for r in self.list_routers()}
        devices = self.list_devices()
        groups: dict[str, dict] = {}
        for d in devices:
            rid = d["router_id"] or "unknown"
            if rid not in groups:
                groups[rid] = {
                    "router_id": rid,
                    "label": routers.get(rid, rid),
                    "devices": [],
                }
            groups[rid]["devices"].append(d)
        return list(groups.values())

    def set_alias(self, mac: str, alias: str) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE devices SET alias = ? WHERE mac = ?", (alias, mac))

    def add_to_whitelist(self, mac: str, label: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO whitelist (mac, label, added_at) VALUES (?, ?, ?)",
                (mac, label, int(time.time())),
            )

    def remove_from_whitelist(self, mac: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM whitelist WHERE mac = ?", (mac,))

    def list_whitelist(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM whitelist ORDER BY added_at DESC").fetchall()
            return [dict(r) for r in rows]

    def recent_events(self, limit: int = 50) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT events.*, devices.hostname, devices.alias FROM events "
                "LEFT JOIN devices ON devices.mac = events.mac "
                "ORDER BY ts DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
