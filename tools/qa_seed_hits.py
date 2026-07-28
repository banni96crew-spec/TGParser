"""Check runs 3-4 global hits and seed profile details."""
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

    # Runs 3 and 4 had global_message hits - check what happened
    for run_id in [3, 4]:
        print(f"\n{'='*70}")
        print(f"RUN {run_id} - global_message hits detail")
        gm_hits = conn.execute("""
            SELECT ordinal, query_text, scope, result_count, state, error_code,
                   cursor_json
            FROM discovery_run_queries
            WHERE run_id = ? AND query_kind = 'global_message' AND result_count > 0
        """, (run_id,)).fetchall()

        for q in gm_hits:
            print(f"  ord={q['ordinal']} '{q['query_text']}' scope={q['scope']} "
                  f"hits={q['result_count']} state={q['state']}")

        # Check evidence for this run
        ev = conn.execute("""
            SELECT COUNT(*) as cnt, SUM(is_qualified) as qualified
            FROM source_discovery_evidence
            WHERE run_id = ?
        """, (run_id,)).fetchone()
        print(f"  Evidence: {ev['cnt']} rows, {ev['qualified']} qualified")

        # Check run counters
        run = conn.execute("SELECT counters_json, state, phase FROM discovery_runs WHERE id=?",
                           (run_id,)).fetchone()
        ctrs = json.loads(run["counters_json"] or "{}")
        print(f"  Run state={run['state']} phase={run['phase']}")
        print(f"  Counters: {ctrs}")

    # All profile versions
    print(f"\n{'='*70}")
    print("ALL PROFILE VERSIONS")
    versions = conn.execute("""
        SELECT pv.id, pv.version, pv.created_at, p.name,
               pv.post_queries_json, pv.directory_queries_json
        FROM keyword_discovery_profile_versions pv
        JOIN keyword_discovery_profiles p ON p.id = pv.profile_id
        ORDER BY pv.id ASC
    """).fetchall()

    for pv in versions:
        post_qs = json.loads(pv["post_queries_json"] or "[]")
        dir_qs = json.loads(pv["directory_queries_json"] or "[]")
        print(f"\nVersion {pv['version']} (id={pv['id']}, created={str(pv['created_at'])[:16]})")
        print(f"  Profile: {pv['name']}")
        print(f"  Post queries ({len(post_qs)}):")
        for q in post_qs:
            print(f"    - {q}")
        print(f"  Directory queries ({len(dir_qs)}):")
        for q in dir_qs:
            print(f"    - {q}")

    conn.close()
    print("\n=== DONE ===")


if __name__ == "__main__":
    main()
