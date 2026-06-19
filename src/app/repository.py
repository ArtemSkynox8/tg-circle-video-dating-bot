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
ALTER TABLE users ADD COLUMN IF NOT EXISTS source_tag TEXT NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS restriction_expires_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS restriction_penalty_stars INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS premium_source TEXT NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS videos (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    file_id TEXT NOT NULL,
    media_type TEXT NOT NULL DEFAULT 'video_note',
    duration INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE videos ADD COLUMN IF NOT EXISTS is_anonymous BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS actions (
    id BIGSERIAL PRIMARY KEY,
    from_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    to_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    video_id BIGINT REFERENCES videos(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (from_user_id, to_user_id)
);

CREATE TABLE IF NOT EXISTS viewed_videos (
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    video_id BIGINT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    owner_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, video_id)
);

INSERT INTO viewed_videos (user_id, video_id, owner_id, action, created_at)
SELECT from_user_id, video_id, to_user_id, action, created_at
FROM actions
WHERE video_id IS NOT NULL
ON CONFLICT (user_id, video_id) DO NOTHING;

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

ALTER TABLE reports ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'open';
ALTER TABLE reports ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ;
ALTER TABLE reports ADD COLUMN IF NOT EXISTS resolved_by_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE reports ADD COLUMN IF NOT EXISTS resolution TEXT NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS referral_contact_opens (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    opened_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tag_events (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    source_tag TEXT NOT NULL DEFAULT '',
    event TEXT NOT NULL,
    amount INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS tag_events_source_event_idx ON tag_events (source_tag, event);

CREATE TABLE IF NOT EXISTS source_tags (
    source_tag TEXT PRIMARY KEY,
    created_by_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS admin_users (
    telegram_id BIGINT PRIMARY KEY,
    added_by_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS push_logs (
    id BIGSERIAL PRIMARY KEY,
    kind TEXT NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    requested_by_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    recipients INTEGER NOT NULL DEFAULT 0,
    sent INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bot_errors (
    id BIGSERIAL PRIMARY KEY,
    error TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS yookassa_payments (
    id BIGSERIAL PRIMARY KEY,
    order_id TEXT NOT NULL UNIQUE,
    payment_id TEXT NOT NULL UNIQUE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    plan_code TEXT NOT NULL,
    days INTEGER NOT NULL,
    amount_rub INTEGER NOT NULL,
    video_id BIGINT,
    owner_id BIGINT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
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

    async def ensure_admins(self, telegram_ids: set[int]) -> None:
        if not telegram_ids:
            return
        async with self.pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO admin_users (telegram_id)
                VALUES ($1)
                ON CONFLICT DO NOTHING
                """,
                [(telegram_id,) for telegram_id in telegram_ids],
            )

    async def admin_ids(self) -> set[int]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT telegram_id FROM admin_users ORDER BY telegram_id")
            return {int(row["telegram_id"]) for row in rows}

    async def add_admin(self, telegram_id: int, added_by_user_id: int | None = None) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                INSERT INTO admin_users (telegram_id, added_by_user_id)
                VALUES ($1, $2)
                ON CONFLICT DO NOTHING
                """,
                telegram_id,
                added_by_user_id,
            )
            return result.endswith("1")

    async def del_admin(self, telegram_id: int) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute("DELETE FROM admin_users WHERE telegram_id = $1", telegram_id)
            return result.endswith("1")

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

    async def set_source_tag(self, user_id: int, source_tag: str) -> asyncpg.Record | None:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO source_tags (source_tag)
                    VALUES ($1)
                    ON CONFLICT DO NOTHING
                    """,
                    source_tag,
                )
                return await conn.fetchrow(
                    """
                    UPDATE users
                    SET source_tag = $2, updated_at = now()
                    WHERE id = $1 AND source_tag = ''
                    RETURNING *
                    """,
                    user_id,
                    source_tag,
                )

    async def add_source_tag(self, source_tag: str, created_by_user_id: int) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                INSERT INTO source_tags (source_tag, created_by_user_id)
                VALUES ($1, $2)
                ON CONFLICT DO NOTHING
                """,
                source_tag,
                created_by_user_id,
            )
            return result.endswith("1")

    async def get_user_by_telegram_id(self, telegram_id: int) -> asyncpg.Record | None:
        async with self.pool.acquire() as conn:
            return await conn.fetchrow("SELECT * FROM users WHERE telegram_id = $1", telegram_id)

    async def get_user(self, user_id: int) -> asyncpg.Record | None:
        async with self.pool.acquire() as conn:
            return await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)

    async def refresh_user_access(self, user_id: int) -> asyncpg.Record | None:
        async with self.pool.acquire() as conn:
            user = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
            if user and user["status"] == "restricted" and user["restriction_expires_at"] and user["restriction_expires_at"] <= await conn.fetchval("SELECT now()"):
                user = await conn.fetchrow(
                    """
                    UPDATE users
                    SET status = 'active',
                        restriction_expires_at = NULL,
                        restriction_penalty_stars = 0,
                        updated_at = now()
                    WHERE id = $1
                    RETURNING *
                    """,
                    user_id,
                )
            return user

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

    async def restrict_user(self, user_id: int, hours: int, penalty_stars: int) -> asyncpg.Record | None:
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(
                """
                UPDATE users
                SET status = 'restricted',
                    restriction_expires_at = now() + make_interval(hours => $2::int),
                    restriction_penalty_stars = $3,
                    updated_at = now()
                WHERE id = $1
                RETURNING *
                """,
                user_id,
                hours,
                penalty_stars,
            )

    async def block_user(self, user_id: int) -> asyncpg.Record | None:
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(
                """
                UPDATE users
                SET status = 'blocked',
                    restriction_expires_at = NULL,
                    restriction_penalty_stars = 0,
                    updated_at = now()
                WHERE id = $1
                RETURNING *
                """,
                user_id,
            )

    async def unblock_user(self, user_id: int) -> asyncpg.Record | None:
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(
                """
                UPDATE users
                SET status = 'active',
                    restriction_expires_at = NULL,
                    restriction_penalty_stars = 0,
                    updated_at = now()
                WHERE id = $1
                RETURNING *
                """,
                user_id,
            )

    async def set_premium(self, user_id: int, is_premium: bool) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE users SET is_premium = $2, updated_at = now() WHERE id = $1", user_id, is_premium)

    async def grant_premium_days(self, user_id: int, days: int, source: str = "") -> asyncpg.Record | None:
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(
                """
                UPDATE users
                SET is_premium = TRUE,
                    premium_expires_at = greatest(coalesce(premium_expires_at, now()), now()) + make_interval(days => $2::int),
                    premium_source = CASE WHEN $3 <> '' THEN $3 ELSE premium_source END,
                    updated_at = now()
                WHERE id = $1
                RETURNING *
                """,
                user_id,
                days,
                source,
            )

    async def cancel_ruble_subscription(self, user_id: int) -> asyncpg.Record | None:
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(
                """
                UPDATE users
                SET premium_source = '',
                    updated_at = now()
                WHERE id = $1
                RETURNING *
                """,
                user_id,
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

    async def save_video(self, user_id: int, file_id: str, media_type: str, duration: int, active: bool, is_anonymous: bool = False) -> asyncpg.Record:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                if active:
                    await conn.execute("UPDATE videos SET is_active = FALSE WHERE user_id = $1", user_id)
                return await conn.fetchrow(
                    """
                    INSERT INTO videos (user_id, file_id, media_type, duration, is_active, is_anonymous)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    RETURNING *
                    """,
                    user_id,
                    file_id,
                    media_type,
                    duration,
                    active,
                    is_anonymous,
                )

    async def activate_video(self, user_id: int, video_id: int) -> None:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("UPDATE videos SET is_active = FALSE WHERE user_id = $1", user_id)
                await conn.execute("UPDATE videos SET is_active = TRUE WHERE id = $1 AND user_id = $2", video_id, user_id)

    async def active_video(self, user_id: int) -> asyncpg.Record | None:
        async with self.pool.acquire() as conn:
            return await conn.fetchrow("SELECT * FROM videos WHERE user_id = $1 AND is_active = TRUE ORDER BY id DESC LIMIT 1", user_id)

    async def active_videos_for_face_audit(self) -> list[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetch(
                """
                SELECT
                    v.id AS video_id,
                    v.file_id,
                    v.media_type,
                    v.duration,
                    u.id AS owner_id,
                    u.telegram_id,
                    u.chat_id,
                    u.username,
                    u.first_name,
                    u.name
                FROM videos v
                JOIN users u ON u.id = v.user_id
                WHERE v.is_active = TRUE
                  AND v.is_anonymous = FALSE
                  AND u.status = 'active'
                ORDER BY v.id
                """
            )

    async def delete_video(self, video_id: int, owner_id: int) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM videos WHERE id = $1 AND user_id = $2",
                video_id,
                owner_id,
            )
            return result.endswith("1")

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
                    SELECT 1 FROM viewed_videos vv
                    WHERE vv.user_id = $1 AND vv.video_id = v.id
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM reports r
                    WHERE r.reporter_id = $1 AND r.target_user_id = u.id
                  )
                ORDER BY v.created_at DESC, random()
                LIMIT 1
                """,
                user["id"],
                preferred or "any",
            )

    async def record_action(self, from_user_id: int, to_user_id: int, video_id: int, action: str, mark_viewed: bool = True) -> None:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                if mark_viewed:
                    await conn.execute(
                        """
                        INSERT INTO viewed_videos (user_id, video_id, owner_id, action)
                        VALUES ($1, $2, $3, $4)
                        ON CONFLICT (user_id, video_id) DO UPDATE SET
                            action = EXCLUDED.action,
                            created_at = now()
                        """,
                        from_user_id,
                        video_id,
                        to_user_id,
                        action,
                    )
                if action == "next":
                    return
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
            async with conn.transaction():
                await conn.execute("DELETE FROM viewed_videos WHERE user_id = $1", user_id)
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

    async def next_moderation_report(self) -> asyncpg.Record | None:
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(
                """
                WITH target AS (
                    SELECT video_id, target_user_id, min(created_at) AS first_report_at
                    FROM reports
                    WHERE status = 'open' AND video_id IS NOT NULL
                    GROUP BY video_id, target_user_id
                    ORDER BY first_report_at
                    LIMIT 1
                )
                SELECT
                    t.video_id,
                    t.target_user_id AS owner_id,
                    t.first_report_at,
                    count(r.id)::int AS reports_count,
                    string_agg(DISTINCT r.reason, ', ' ORDER BY r.reason) AS reasons,
                    v.file_id,
                    v.media_type,
                    v.duration,
                    u.telegram_id,
                    u.chat_id,
                    u.username,
                    u.first_name,
                    u.name,
                    u.status,
                    u.restriction_expires_at
                FROM target t
                JOIN reports r ON r.video_id = t.video_id AND r.target_user_id = t.target_user_id AND r.status = 'open'
                JOIN videos v ON v.id = t.video_id
                JOIN users u ON u.id = t.target_user_id
                GROUP BY
                    t.video_id, t.target_user_id, t.first_report_at,
                    v.file_id, v.media_type, v.duration,
                    u.telegram_id, u.chat_id, u.username, u.first_name, u.name, u.status, u.restriction_expires_at
                """
            )

    async def resolve_reports(self, video_id: int, target_user_id: int, moderator_user_id: int, resolution: str) -> int:
        async with self.pool.acquire() as conn:
            count = int(
                await conn.fetchval(
                    """
                    SELECT count(*)
                    FROM reports
                    WHERE status = 'open' AND video_id = $1 AND target_user_id = $2
                    """,
                    video_id,
                    target_user_id,
                )
                or 0
            )
            await conn.execute(
                """
                UPDATE reports
                SET status = 'resolved',
                    resolved_at = now(),
                    resolved_by_user_id = $3,
                    resolution = $4
                WHERE status = 'open' AND video_id = $1 AND target_user_id = $2
                """,
                video_id,
                target_user_id,
                moderator_user_id,
                resolution,
            )
            return count

    async def record_tag_event(self, user_id: int, event: str, amount: int = 0) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO tag_events (user_id, source_tag, event, amount)
                SELECT id, source_tag, $2, $3
                FROM users
                WHERE id = $1
                """,
                user_id,
                event,
                amount,
            )

    async def create_yookassa_payment(
        self,
        order_id: str,
        payment_id: str,
        user_id: int,
        plan_code: str,
        days: int,
        amount_rub: int,
        video_id: int | None,
        owner_id: int | None,
    ) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO yookassa_payments (
                    order_id, payment_id, user_id, plan_code, days, amount_rub, video_id, owner_id
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (order_id) DO UPDATE SET
                    payment_id = EXCLUDED.payment_id,
                    updated_at = now()
                """,
                order_id,
                payment_id,
                user_id,
                plan_code,
                days,
                amount_rub,
                video_id,
                owner_id,
            )

    async def get_yookassa_payment(self, payment_id: str) -> asyncpg.Record | None:
        async with self.pool.acquire() as conn:
            return await conn.fetchrow("SELECT * FROM yookassa_payments WHERE payment_id = $1", payment_id)

    async def get_yookassa_payment_by_order(self, order_id: str) -> asyncpg.Record | None:
        async with self.pool.acquire() as conn:
            return await conn.fetchrow("SELECT * FROM yookassa_payments WHERE order_id = $1", order_id)

    async def set_yookassa_payment_status(self, payment_id: str, status: str) -> asyncpg.Record | None:
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(
                """
                UPDATE yookassa_payments
                SET status = $2,
                    updated_at = now()
                WHERE payment_id = $1
                RETURNING *
                """,
                payment_id,
                status,
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
                await conn.execute("TRUNCATE push_logs, bot_errors, tag_events, referral_contact_opens, reports, hidden_matches, viewed_videos, actions, videos, users RESTART IDENTITY CASCADE")

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

    async def tag_stats(self, source_tag: str | None = None) -> list[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetch(
                """
                WITH user_stats AS (
                    SELECT source_tag, count(*)::int AS users
                    FROM users
                    GROUP BY source_tag
                ),
                event_stats AS (
                    SELECT
                        source_tag,
                        count(*) FILTER (WHERE event = 'offer')::int AS offer,
                        count(DISTINCT user_id) FILTER (WHERE event = 'purchase')::int AS buyers,
                        coalesce(sum(amount) FILTER (WHERE event = 'purchase'), 0)::int AS sum
                    FROM tag_events
                    GROUP BY source_tag
                ),
                all_tags AS (
                    SELECT source_tag FROM source_tags
                    UNION
                    SELECT source_tag FROM user_stats
                    UNION
                    SELECT source_tag FROM event_stats
                )
                SELECT
                    all_tags.source_tag,
                    coalesce(user_stats.users, 0)::int AS users,
                    coalesce(event_stats.offer, 0)::int AS offer,
                    coalesce(event_stats.buyers, 0)::int AS buyers,
                    coalesce(event_stats.sum, 0)::int AS sum
                FROM all_tags
                LEFT JOIN user_stats USING (source_tag)
                LEFT JOIN event_stats USING (source_tag)
                WHERE $1::text IS NULL OR all_tags.source_tag = $1
                ORDER BY users DESC, all_tags.source_tag
                """,
                source_tag,
            )

    async def subscription_stats(self) -> dict[str, int]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    (SELECT count(*) FROM users WHERE is_premium = TRUE AND (premium_expires_at IS NULL OR premium_expires_at > now()))::int AS active,
                    (SELECT count(*) FROM users WHERE is_premium = TRUE AND premium_expires_at <= now())::int AS expired,
                    (SELECT count(*) FROM tag_events WHERE event = 'purchase')::int AS payments,
                    (SELECT coalesce(sum(amount), 0) FROM tag_events WHERE event = 'purchase')::int AS sum
                """
            )
            return dict(row)

    async def choice_stats(self) -> list[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetch(
                """
                SELECT coalesce(nullif(preferred_gender, ''), 'empty') AS choice, count(*)::int AS users
                FROM users
                GROUP BY 1
                ORDER BY users DESC, choice
                """
            )

    async def push_targets_without_premium(self, limit: int) -> list[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetch(
                """
                SELECT *
                FROM users
                WHERE status = 'active'
                  AND (is_premium = FALSE OR premium_expires_at <= now())
                ORDER BY updated_at DESC
                LIMIT $1
                """,
                limit,
            )

    async def active_users(self) -> list[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetch("SELECT * FROM users WHERE status = 'active' ORDER BY updated_at DESC")

    async def save_push_log(self, kind: str, text: str, requested_by_user_id: int, recipients: int, sent: int, failed: int) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO push_logs (kind, text, requested_by_user_id, recipients, sent, failed)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                kind,
                text,
                requested_by_user_id,
                recipients,
                sent,
                failed,
            )

    async def push_stats(self) -> dict[str, int | str]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    (SELECT count(*) FROM users)::int AS users,
                    (SELECT count(*) FROM users WHERE status = 'active')::int AS active_users,
                    (SELECT count(*) FROM users WHERE is_premium = TRUE AND (premium_expires_at IS NULL OR premium_expires_at > now()))::int AS active_premium,
                    coalesce((SELECT kind FROM push_logs ORDER BY id DESC LIMIT 1), '') AS last_kind,
                    coalesce((SELECT sent FROM push_logs ORDER BY id DESC LIMIT 1), 0)::int AS last_sent,
                    coalesce((SELECT failed FROM push_logs ORDER BY id DESC LIMIT 1), 0)::int AS last_failed
                """
            )
            return dict(row)

    async def recent_payments(self, limit: int = 20) -> list[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetch(
                """
                SELECT e.*, u.telegram_id, u.username, u.name
                FROM tag_events e
                LEFT JOIN users u ON u.id = e.user_id
                WHERE e.event = 'purchase'
                ORDER BY e.id DESC
                LIMIT $1
                """,
                limit,
            )

    async def reset_payments(self, user_id: int | None = None) -> int:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                if user_id is None:
                    count = int(await conn.fetchval("SELECT count(*) FROM tag_events WHERE event = 'purchase'") or 0)
                    await conn.execute("DELETE FROM tag_events WHERE event = 'purchase'")
                    await conn.execute("UPDATE users SET is_premium = FALSE, premium_expires_at = NULL, premium_source = ''")
                    return count
                count = int(await conn.fetchval("SELECT count(*) FROM tag_events WHERE event = 'purchase' AND user_id = $1", user_id) or 0)
                await conn.execute("DELETE FROM tag_events WHERE event = 'purchase' AND user_id = $1", user_id)
                await conn.execute("UPDATE users SET is_premium = FALSE, premium_expires_at = NULL, premium_source = '' WHERE id = $1", user_id)
                return count

    async def record_error(self, error: str) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute("INSERT INTO bot_errors (error) VALUES ($1)", error[-4000:])

    async def recent_errors(self, limit: int = 20) -> list[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetch("SELECT * FROM bot_errors ORDER BY id DESC LIMIT $1", limit)

    async def list_users(self, limit: int = 20) -> list[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetch("SELECT * FROM users ORDER BY id DESC LIMIT $1", limit)
