"""Check global_message hits across ALL runs."""
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]


def get_db_path() -> str:
    local = os.environ.get("LOCALAPPDATA", "")
    return str(Path(local) / "TelegramLeadDiscovery" / "data" / "app.sqlite3")


def main():
    db_path = get_db_path()
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=15)
    conn.row_factory = sqlite3.Row

    # All runs
    runs = conn.execute("""
        SELECT id, state, phase, run_type, profile_version_id,
               counters_json, started_at, finished_at
        FROM discovery_runs
        ORDER BY id ASC
    """).fetchall()

    print("=" * 80)
    print("ALL RUNS - GLOBAL_MESSAGE AND PUBLIC_POSTS HITS ACROSS HISTORY")
    print("=" * 80)

    for run in runs:
        run_id = run["id"]
        counters = json.loads(run["counters_json"] or "{}")

        # Per-kind totals
        kind_totals = conn.execute("""
            SELECT query_kind,
                   COUNT(*) as count,
                   SUM(result_count) as total_hits,
                   SUM(CASE WHEN state='succeeded' THEN 1 ELSE 0 END) as succeeded,
                   SUM(CASE WHEN state='quota_skipped' THEN 1 ELSE 0 END) as quota_skipped,
                   SUM(CASE WHEN state='failed' THEN 1 ELSE 0 END) as failed
            FROM discovery_run_queries
            WHERE run_id = ?
            GROUP BY query_kind
        """, (run_id,)).fetchall()

        totals_by_kind = {k["query_kind"]: k for k in kind_totals}

        gm = totals_by_kind.get("global_message", None)
        pp = totals_by_kind.get("public_posts", None)
        dr = totals_by_kind.get("directory", None)
        sv = totals_by_kind.get("source_verification", None)

        gm_hits = gm["total_hits"] if gm else 0
        pp_hits = pp["total_hits"] if pp else 0
        dr_hits = dr["total_hits"] if dr else 0
        sv_hits = sv["total_hits"] if sv else 0

        evidence_count = counters.get("evidence_count", "?")
        print(f"\nRun {run_id:3d} [{run['state']:20s}] started={str(run['started_at'])[:16]}")
        print(f"  global_msg={gm_hits:3d} hits  directory={dr_hits:3d} hits  "
              f"public_posts={pp_hits:3d} hits  source_verif={sv_hits:3d} hits  "
              f"evidence={evidence_count}")
        if pp and pp["quota_skipped"] > 0:
            print(f"  ⚠ public_posts quota_skipped: {pp['quota_skipped']}/{pp['count']}")

    # Check if global_message EVER returned > 0
    print("\n" + "=" * 80)
    print("GLOBAL MESSAGE: ANY QUERY EVER RETURNED > 0?")
    any_hits = conn.execute("""
        SELECT run_id, query_text, result_count, state, scope
        FROM discovery_run_queries
        WHERE query_kind = 'global_message' AND result_count > 0
        ORDER BY result_count DESC
        LIMIT 20
    """).fetchall()

    if not any_hits:
        print("  ❌ NO - global_message has NEVER returned any hits in any run")
    else:
        print(f"  ✅ YES - {len(any_hits)} queries returned hits:")
        for q in any_hits:
            print(f"  Run {q['run_id']}: '{q['query_text']}' scope={q['scope']} hits={q['result_count']}")

    # Check public_posts history
    print("\n" + "=" * 80)
    print("PUBLIC POSTS: ANY QUERY EVER RETURNED > 0?")
    pp_hits_ever = conn.execute("""
        SELECT run_id, query_text, result_count, state
        FROM discovery_run_queries
        WHERE query_kind = 'public_posts' AND result_count > 0
        ORDER BY result_count DESC
        LIMIT 20
    """).fetchall()

    if not pp_hits_ever:
        print("  ❌ NO - public_posts has NEVER returned any hits")
    else:
        print(f"  ✅ YES - {len(pp_hits_ever)} queries returned hits:")
        for q in pp_hits_ever:
            print(f"  Run {q['run_id']}: '{q['query_text']}' hits={q['result_count']}")

    # What runs had free quota available for public_posts?
    print("\n" + "=" * 80)
    print("PUBLIC POSTS QUOTA STATUS BY RUN")
    quota_rows = conn.execute("""
        SELECT DISTINCT r.id, r.quota_snapshot_json, r.started_at
        FROM discovery_runs r
        WHERE r.quota_snapshot_json IS NOT NULL
        ORDER BY r.id
    """).fetchall()
    for row in quota_rows:
        quota = json.loads(row["quota_snapshot_json"] or "{}")
        print(f"  Run {row['id']}: free_slot={quota.get('free_slot_available')} "
              f"premium_req={quota.get('premium_required')} "
              f"stars_amount={quota.get('stars_amount')}")

    conn.close()
    print("\n=== DONE ===")


if __name__ == "__main__":
    main()
