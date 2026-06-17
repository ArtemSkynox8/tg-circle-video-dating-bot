from __future__ import annotations

import re
from typing import Any

import asyncpg

SCHEMA_RE = re.compile(r"^[a-z_][a-z0-9_]*$")

MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    telegram_id BIGINT NOT NULL UNIQUE,
    chat_id BIGINT NOT NULL,
    username TEXT NOT NULL DEFAULT '',
    first_name TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL DEFAULT '',
    gender TEXT NOT NULL DEFAULT '',
    preferred_gender TEXT NOT NULL DEFAULT '',
    flow_state TEXT NOT NULL DEFAULT '',
    contact_phone TEXT NOT NULL DEFAULT '',
    is_premium BOOLEAN NOT NULL DEFAULT FALSE,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE users ADD COLUMN IF NOT EXISTS referrer_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_contact_credits INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_rewarded_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS premium_expires_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS videos (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    file_id TEXT NOT NULL,
    media_type TEXT NOT NULL DEFAULT 'video_note',
    duration INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS actions (
    id BIGSERIAL PRIMARY KEY,
    from_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    to_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    video_id BIGINT REFERENCES videos(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (from_user_id, to_user_id)
);

CREATE TABLE IF NOT EXISTS hidden_matches (
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    matched_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, matched_user_id)
);

CREATE TABLE IF NOT EXISTS reports (
    id BIGSERIAL PRIMARY KEY,
    reporter_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    target_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    video_id BIGINT REFERENCES videos(id) ON DELETE SET NULL,
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS referral_contact_opens (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    opened_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


class Repository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    @classmethod
    async def connect(cls, database_url: str, schema: str) -> "Repository":
        schema = schema.strip()
        if not SCHEMA_RE.fullmatch(schema):
            raise ValueError("DATABASE_SCHEMA must contain only lowercase letters, digits, and underscores")

        setup_conn = await asyncpg.connect(database_url)
        try:
            await setup_conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        finally:
            await setup_conn.close()

        pool = await asyncpg.create_pool(
            database_url,
            min_size=1,
            max_size=10,
            server_settings={"search_path": f"{schema},public"},
        )
        repo = cls(pool)
        async with pool.acquire() as conn:
            await conn.execute(MIGRATION_SQL)
        return repo

    async def close(self) -> None:
        await self.pool.close()

    async def upsert_user(self, tg_user: dict[str, Any], chat_id: int) -> asyncpg.Record:
        telegram_id = int(tg_user["id"])
        username = tg_user.get("username") or ""
        first_name = tg_user.get("first_name") or ""
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(
                """
                INSERT INTO users (telegram_id, chat_id, username, first_name)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (telegram_id) DO UPDATE SET
                    chat_id = EXCLUDED.chat_id,
                    username = EXCLUDED.username,
                    first_name = EXCLUDED.first_name,
                    updated_at = now()
                RETURNING *
                """,
                telegram_id,
                chat_id,
                username,
                first_name,
            )

    async def get_user_by_telegram_id(self, telegram_id: int) -> asyncpg.Record | None:
        async with self.pool.acquire() as conn:
            return await conn.fetchrow("SELECT * FROM users WHERE telegram_id = $1", telegram_id)

    async def get_user(self, user_id: int) -> asyncpg.Record | None:
        async with self.pool.acquire() as conn:
            return await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)

    async def set_flow(self, user_id: int, state: str) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE users SET flow_state = $2, updated_at = now() WHERE id = $1", user_id, state)

    async def update_profile_field(self, user_id: int, field: str, value: str) -> asyncpg.Record:
        allowed = {"name", "gender", "preferred_gender", "flow_state", "contact_phone", "status"}
        if field not in allowed:
            raise ValueError(f"field {field} cannot be updated")
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(
                f"UPDATE users SET {field} = $2, updated_at = now() WHERE id = $1 RETURNING *",
                user_id,
                value,
            )

    async def set_premium(self, user_id: int, is_premium: bool) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE users SET is_premium = $2, updated_at = now() WHERE id = $1", user_id, is_premium)

    async def grant_premium_days(self, user_id: int, days: int) -> asyncpg.Record | None:
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(
                """
                UPDATE users
                SET is_premium = TRUE,
                    premium_expires_at = greatest(coalesce(premium_expires_at, now()), now()) + ($2::text || ' days')::interval,
                    updated_at = now()
                WHERE id = $1
                RETURNING *
                """,
                user_id,
                days,
            )

    async def set_referrer(self, user_id: int, referrer_user_id: int) -> None:
        if user_id == referrer_user_id:
            return
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE users
                SET referrer_user_id = $2, updated_at = now()
                WHERE id = $1 AND referrer_user_id IS NULL
                """,
                user_id,
                referrer_user_id,
            )

    async def save_video(self, user_id: int, file_id: str, media_type: str, duration: int, active: bool) -> asyncpg.Record:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                if active:
                    await conn.execute("UPDATE videos SET is_active = FALSE WHERE user_id = $1", user_id)
                return await conn.fetchrow(
                    """
                    INSERT INTO videos (user_id, file_id, media_type, duration, is_active)
                    VALUES ($1, $2, $3, $4, $5)
                    RETURNING *
                    """,
                    user_id,
                    file_id,
                    media_type,
                    duration,
                    active,
                )

    async def activate_video(self, user_id: int, video_id: int) -> None:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("UPDATE videos SET is_active = FALSE WHERE user_id = $1", user_id)
                await conn.execute("UPDATE videos SET is_active = TRUE WHERE id = $1 AND user_id = $2", video_id, user_id)

    async def active_video(self, user_id: int) -> asyncpg.Record | None:
        async with self.pool.acquire() as conn:
            return await conn.fetchrow("SELECT * FROM videos WHERE user_id = $1 AND is_active = TRUE ORDER BY id DESC LIMIT 1", user_id)

    async def next_candidate(self, user: asyncpg.Record) -> asyncpg.Record | None:
        preferred = user["preferred_gender"]
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(
                """
                SELECT
                    v.id AS video_id, v.file_id, v.media_type, v.duration,
                    u.id AS owner_id, u.telegram_id, u.chat_id, u.username, u.name,
                    u.gender, u.contact_phone, u.is_premium
                FROM videos v
                JOIN users u ON u.id = v.user_id
                WHERE v.is_active = TRUE
                  AND u.id <> $1
                  AND u.status = 'active'
                  AND ($2 = 'any' OR u.gender = $2)
                  AND NOT EXISTS (
                    SELECT 1 FROM actions a
                    WHERE a.from_user_id = $1 AND a.to_user_id = u.id
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM reports r
                    WHERE r.reporter_id = $1 AND r.target_user_id = u.id
                  )
                ORDER BY random()
                LIMIT 1
                """,
                user["id"],
                preferred or "any",
            )

    async def record_action(self, from_user_id: int, to_user_id: int, video_id: int, action: str) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO actions (from_user_id, to_user_id, video_id, action)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (from_user_id, to_user_id) DO UPDATE SET
                    video_id = EXCLUDED.video_id,
                    action = EXCLUDED.action,
                    created_at = now()
                """,
                from_user_id,
                to_user_id,
                video_id,
                action,
            )

    async def reset_browse(self, user_id: int) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM actions WHERE from_user_id = $1 AND action = 'next'", user_id)

    async def complete_referral_if_needed(self, user_id: int) -> asyncpg.Record | None:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                user = await conn.fetchrow(
                    """
                    SELECT referrer_user_id, referral_rewarded_at
                    FROM users
                    WHERE id = $1
                    FOR UPDATE
                    """,
                    user_id,
                )
                if not user or not user["referrer_user_id"] or user["referral_rewarded_at"]:
                    return None
                referrer = await conn.fetchrow(
                    """
                    UPDATE users
                    SET referral_contact_credits = referral_contact_credits + 1,
                        updated_at = now()
                    WHERE id = $1
                    RETURNING *
                    """,
                    user["referrer_user_id"],
                )
                await conn.execute(
                    "UPDATE users SET referral_rewarded_at = now(), updated_at = now() WHERE id = $1",
                    user_id,
                )
                return referrer

    async def mutual_like(self, user_id: int, other_id: int) -> bool:
        async with self.pool.acquire() as conn:
            return bool(
                await conn.fetchval(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM actions
                        WHERE from_user_id = $1 AND to_user_id = $2 AND action IN ('like', 'like_only')
                    )
                    """,
                    other_id,
                    user_id,
                )
            )

    async def matches(self, user_id: int, limit: int = 10, offset: int = 0) -> list[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetch(
                """
                SELECT u.*
                FROM users u
                WHERE u.id <> $1
                  AND NOT EXISTS (
                    SELECT 1 FROM hidden_matches h
                    WHERE h.user_id = $1 AND h.matched_user_id = u.id
                  )
                  AND EXISTS (
                    SELECT 1 FROM actions a
                    WHERE a.from_user_id = $1 AND a.to_user_id = u.id AND a.action IN ('like', 'like_only')
                  )
                  AND EXISTS (
                    SELECT 1 FROM actions a
                    WHERE a.from_user_id = u.id AND a.to_user_id = $1 AND a.action IN ('like', 'like_only')
                  )
                ORDER BY u.updated_at DESC
                LIMIT $2 OFFSET $3
                """,
                user_id,
                limit,
                offset,
            )

    async def matches_count(self, user_id: int) -> int:
        async with self.pool.acquire() as conn:
            return int(
                await conn.fetchval(
                    """
                    SELECT count(*)
                    FROM users u
                    WHERE u.id <> $1
                      AND NOT EXISTS (
                        SELECT 1 FROM hidden_matches h
                        WHERE h.user_id = $1 AND h.matched_user_id = u.id
                      )
                      AND EXISTS (
                        SELECT 1 FROM actions a
                        WHERE a.from_user_id = $1 AND a.to_user_id = u.id AND a.action IN ('like', 'like_only')
                      )
                      AND EXISTS (
                        SELECT 1 FROM actions a
                        WHERE a.from_user_id = u.id AND a.to_user_id = $1 AND a.action IN ('like', 'like_only')
                      )
                    """,
                    user_id,
                )
                or 0
            )

    async def hide_match(self, user_id: int, matched_user_id: int) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO hidden_matches (user_id, matched_user_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                user_id,
                matched_user_id,
            )

    async def report(self, reporter_id: int, target_user_id: int, video_id: int | None, reason: str) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO reports (reporter_id, target_user_id, video_id, reason) VALUES ($1, $2, $3, $4)",
                reporter_id,
                target_user_id,
                video_id,
                reason,
            )

    async def random_contact_candidate(self, user_id: int) -> asyncpg.Record | None:
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(
                """
                WITH latest AS (
                    SELECT
                        u.id AS owner_id, u.telegram_id, u.chat_id, u.username, u.first_name,
                        u.name, u.contact_phone, v.file_id, v.media_type, v.created_at
                    FROM videos v
                    JOIN users u ON u.id = v.user_id
                    WHERE v.is_active = TRUE
                      AND u.id <> $1
                      AND u.status = 'active'
                      AND NOT EXISTS (
                        SELECT 1 FROM referral_contact_opens o
                        WHERE o.user_id = $1 AND o.opened_user_id = u.id
                      )
                    ORDER BY v.created_at DESC
                    LIMIT 10
                )
                SELECT * FROM latest
                ORDER BY random()
                LIMIT 1
                """,
                user_id,
            )

    async def consume_referral_credit(self, user_id: int, opened_user_id: int) -> bool:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                credits = await conn.fetchval(
                    "SELECT referral_contact_credits FROM users WHERE id = $1 FOR UPDATE",
                    user_id,
                )
                if not credits or credits <= 0:
                    return False
                await conn.execute(
                    """
                    UPDATE users
                    SET referral_contact_credits = referral_contact_credits - 1,
                        updated_at = now()
                    WHERE id = $1
                    """,
                    user_id,
                )
                await conn.execute(
                    """
                    INSERT INTO referral_contact_opens (user_id, opened_user_id)
                    VALUES ($1, $2)
                    """,
                    user_id,
                    opened_user_id,
                )
                return True

    async def reset_all(self) -> None:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("TRUNCATE referral_contact_opens, reports, hidden_matches, actions, videos, users RESTART IDENTITY CASCADE")

    async def stats(self) -> dict[str, int]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    (SELECT count(*) FROM users) AS users,
                    (SELECT count(*) FROM videos WHERE is_active = TRUE) AS active_videos,
                    (SELECT count(*) FROM actions WHERE action IN ('like', 'like_only')) AS likes,
                    (SELECT count(*) FROM reports) AS reports
                """
            )
            return dict(row)

    async def list_users(self, limit: int = 20) -> list[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetch("SELECT * FROM users ORDER BY id DESC LIMIT $1", limit)
