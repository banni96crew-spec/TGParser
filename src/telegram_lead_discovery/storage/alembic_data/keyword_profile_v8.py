"""Operator keyword profile v8 catalogs (D-074 / STO-024)."""

from __future__ import annotations

import json

from sqlalchemy import inspect, text

from telegram_lead_discovery.storage.alembic_data.active_client_chat_v1_profile import (
    ADDITIONAL_EXCLUSIONS,
    POST_QUERIES,
)

PROFILE_NAME = "ecommerce-development-ru"
ACTIVE_KEYWORD = (
    "run_type = 'keyword_scouting' AND "
    "state IN ('queued','running','retry_wait_flood','cancelling')"
)


def _tables(bind) -> set[str]:
    return set(inspect(bind).get_table_names())


def _active_keyword_ids(bind) -> list[int]:
    if "discovery_runs" not in _tables(bind):
        return []
    rows = bind.execute(
        text("SELECT id FROM discovery_runs WHERE " + ACTIVE_KEYWORD + " ORDER BY id")
    )
    return [int(row[0]) for row in rows]


def _profile(bind):
    required = {"keyword_discovery_profiles", "keyword_discovery_profile_versions"}
    if not required <= _tables(bind):
        return None
    return bind.execute(
        text(
            "SELECT id, current_version FROM keyword_discovery_profiles WHERE name=:name"
        ),
        {"name": PROFILE_NAME},
    ).fetchone()


def _has_version(bind, profile_id: int, version: int) -> bool:
    row = bind.execute(
        text(
            "SELECT id FROM keyword_discovery_profile_versions "
            "WHERE profile_id=:pid AND version=:ver"
        ),
        {"pid": profile_id, "ver": version},
    ).fetchone()
    return row is not None


def _insert_v8(bind, profile_id: int) -> None:
    bind.execute(
        text(
            "INSERT INTO keyword_discovery_profile_versions "
            "(profile_id,version,post_queries_json,directory_queries_json,"
            "replacement_directory_queries_json,required_service_profiles_json,"
            "additional_exclusions_json,source_scope,created_at) "
            "VALUES (:pid,8,:posts,'[]','[]','[]',:exclusions,'groups',CURRENT_TIMESTAMP)"
        ),
        {
            "pid": profile_id,
            "posts": json.dumps(list(POST_QUERIES), ensure_ascii=False),
            "exclusions": json.dumps(list(ADDITIONAL_EXCLUSIONS), ensure_ascii=False),
        },
    )


def upgrade_profile(bind) -> None:
    profile = _profile(bind)
    if profile is None:
        return
    profile_id, current_version = int(profile[0]), int(profile[1])
    if current_version == 8:
        if not _has_version(bind, profile_id, 8):
            _insert_v8(bind, profile_id)
        return
    if current_version != 7:
        raise RuntimeError(
            f"seed_profile_upgrade_requires_version_7:found={current_version}"
        )
    if not _has_version(bind, profile_id, 8):
        _insert_v8(bind, profile_id)
    bind.execute(
        text(
            "UPDATE keyword_discovery_profiles SET current_version=8, "
            "updated_at=CURRENT_TIMESTAMP WHERE id=:pid"
        ),
        {"pid": profile_id},
    )


def downgrade_profile(bind) -> None:
    profile = _profile(bind)
    if profile is None:
        return
    profile_id, current_version = int(profile[0]), int(profile[1])
    if current_version != 8:
        return
    active = _active_keyword_ids(bind)
    if active:
        joined = ",".join(str(item) for item in active)
        raise RuntimeError(f"seed_profile_downgrade_blocked_active_keyword_run:{joined}")
    bind.execute(
        text(
            "UPDATE keyword_discovery_profiles SET current_version=7, "
            "updated_at=CURRENT_TIMESTAMP WHERE id=:pid"
        ),
        {"pid": profile_id},
    )
