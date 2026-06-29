import aiosqlite
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import config

log = logging.getLogger("zenvps.db")


class Database:
    def __init__(self):
        self._conn: Optional[aiosqlite.Connection] = None

    async def connect(self):
        self._conn = await aiosqlite.connect(config.DATABASE_PATH)
        self._conn.row_factory = aiosqlite.Row
        await self._migrate()
        log.info("Database connected: %s", config.DATABASE_PATH)

    async def close(self):
        if self._conn:
            await self._conn.close()
            log.info("Database closed")

    # ── schema ─────────────────────────────────────────────────
    async def _migrate(self):
        await self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id      TEXT    UNIQUE NOT NULL,
                username        TEXT,
                vps_count       INTEGER DEFAULT 0,
                max_vps         INTEGER DEFAULT 3,
                total_deployed  INTEGER DEFAULT 0,
                created_at      TEXT    DEFAULT (datetime('now')),
                is_admin        INTEGER DEFAULT 0,
                is_banned       INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS vps (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id        TEXT    NOT NULL,
                name            TEXT    UNIQUE NOT NULL,
                hostname        TEXT    NOT NULL,
                os_template     TEXT    NOT NULL,
                cpu             INTEGER DEFAULT 1,
                ram             INTEGER DEFAULT 512,
                disk            INTEGER DEFAULT 5,
                ip              TEXT,
                ssh_port        INTEGER,
                status          TEXT    DEFAULT 'creating',
                created_at      TEXT    DEFAULT (datetime('now')),
                expires_at      TEXT,
                notes           TEXT    DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS logs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id  TEXT,
                action      TEXT    NOT NULL,
                target      TEXT,
                details     TEXT,
                timestamp   TEXT    DEFAULT (datetime('now'))
            );
        """)
        await self._conn.commit()

    # ── helpers ────────────────────────────────────────────────
    async def _fetchone(self, sql, params=()):
        cur = await self._conn.execute(sql, params)
        return await cur.fetchone()

    async def _fetchall(self, sql, params=()):
        cur = await self._conn.execute(sql, params)
        return await cur.fetchall()

    async def _execute(self, sql, params=()):
        await self._conn.execute(sql, params)
        await self._conn.commit()

    # ── users ──────────────────────────────────────────────────
    async def get_or_create_user(self, discord_id: str, username: str = "") -> Dict:
        row = await self._fetchone("SELECT * FROM users WHERE discord_id=?", (discord_id,))
        if row:
            if username and row["username"] != username:
                await self._execute("UPDATE users SET username=? WHERE discord_id=?", (username, discord_id))
                row = await self._fetchone("SELECT * FROM users WHERE discord_id=?", (discord_id,))
            return dict(row)
        is_admin = 1 if int(discord_id) in config.ADMIN_DISCORD_IDS else 0
        await self._execute(
            "INSERT INTO users (discord_id,username,max_vps,is_admin) VALUES (?,?,?,?)",
            (discord_id, username, config.VPS_MAX_PER_USER, is_admin),
        )
        row = await self._fetchone("SELECT * FROM users WHERE discord_id=?", (discord_id,))
        return dict(row)

    async def set_ban(self, discord_id: str, banned: bool):
        await self._execute("UPDATE users SET is_banned=? WHERE discord_id=?", (int(banned), discord_id))

    async def set_max_vps(self, discord_id: str, limit: int):
        await self._execute("UPDATE users SET max_vps=? WHERE discord_id=?", (limit, discord_id))

    async def get_all_users(self) -> List[Dict]:
        rows = await self._fetchall("SELECT * FROM users ORDER BY id")
        return [dict(r) for r in rows]

    async def increment_vps_count(self, discord_id: str, delta: int = 1):
        await self._execute(
            "UPDATE users SET vps_count=vps_count+?, total_deployed=total_deployed+? WHERE discord_id=?",
            (delta, max(delta, 0), discord_id),
        )

    # ── vps ────────────────────────────────────────────────────
    async def create_vps(self, owner_id: str, name: str, hostname: str,
                         os_template: str, cpu: int, ram: int, disk: int,
                         expires_at: str) -> Dict:
        await self._execute(
            """INSERT INTO vps (owner_id,name,hostname,os_template,cpu,ram,disk,status,expires_at)
               VALUES (?,?,?,?,?,?,'creating',?)""",
            (owner_id, name, hostname, os_template, cpu, ram, disk, expires_at),
        )
        await self.increment_vps_count(owner_id, 1)
        row = await self._fetchone("SELECT * FROM vps WHERE name=?", (name,))
        return dict(row)

    async def get_vps(self, name: str) -> Optional[Dict]:
        row = await self._fetchone("SELECT * FROM vps WHERE name=?", (name,))
        return dict(row) if row else None

    async def get_vps_by_id(self, vps_id: int) -> Optional[Dict]:
        row = await self._fetchone("SELECT * FROM vps WHERE id=?", (vps_id,))
        return dict(row) if row else None

    async def get_user_vps(self, discord_id: str) -> List[Dict]:
        rows = await self._fetchall("SELECT * FROM vps WHERE owner_id=? ORDER BY id DESC", (discord_id,))
        return [dict(r) for r in rows]

    async def get_all_vps(self) -> List[Dict]:
        rows = await self._fetchall("SELECT * FROM vps ORDER BY id DESC")
        return [dict(r) for r in rows]

    async def update_vps(self, name: str, **kwargs):
        parts = ", ".join(f"{k}=?" for k in kwargs)
        vals = list(kwargs.values()) + [name]
        await self._execute(f"UPDATE vps SET {parts} WHERE name=?", vals)

    async def delete_vps(self, name: str):
        row = await self.get_vps(name)
        if row:
            await self._execute("DELETE FROM vps WHERE name=?", (name,))
            await self.increment_vps_count(row["owner_id"], -1)

    async def get_expired_vps(self) -> List[Dict]:
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        rows = await self._fetchall("SELECT * FROM vps WHERE expires_at<? AND status!='deleted'", (now,))
        return [dict(r) for r in rows]

    async def vps_count_for(self, discord_id: str) -> int:
        row = await self._fetchone("SELECT COUNT(*) as c FROM vps WHERE owner_id=? AND status!='deleted'", (discord_id,))
        return row["c"] if row else 0

    # ── logs ───────────────────────────────────────────────────
    async def add_log(self, discord_id: str, action: str, target: str = "", details: str = ""):
        await self._execute(
            "INSERT INTO logs (discord_id,action,target,details) VALUES (?,?,?,?)",
            (discord_id, action, target, details),
        )

    async def get_logs(self, limit: int = 50) -> List[Dict]:
        rows = await self._fetchall("SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    # ── stats ──────────────────────────────────────────────────
    async def stats(self) -> Dict[str, int]:
        total = await self._fetchone("SELECT COUNT(*) as c FROM vps WHERE status!='deleted'")
        active = await self._fetchone("SELECT COUNT(*) as c FROM vps WHERE status='running'")
        users = await self._fetchone("SELECT COUNT(*) as c FROM users")
        return {
            "total_vps": total["c"] if total else 0,
            "active_vps": active["c"] if active else 0,
            "total_users": users["c"] if users else 0,
        }


# global singleton
db = Database()
