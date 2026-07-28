"""QA yield check script - queries SQLite DB for per-phrase hit counts.
This script is a temporary QA measurement tool, not product code.
"""
import json
import os
import sqlite3
from pathlib import Path


def get_db_path() -> str:
    local = os.environ.get("LOCALAPPDATA", "")
    return str(Path(local) / "TelegramLeadDiscovery" / "data" / "app.sqlite3")


def main():
    db_path = get_db_path()
    print(f"DB: {db_path}")

    # Use WAL mode read-only connection (connect as immutable to avoid blocking app)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=15)
    conn.row_factory = sqlite3.Row

    # 1. Get latest runs
    print("\n=== LATEST RUNS ===")
    runs = conn.execute("""
        SELECT id, state, phase, run_type, profile_version_id,
               counters_json, started_at, finished_at
        FROM discovery_runs
        ORDER BY id DESC LIMIT 5
    """).fetchall()
    for r in runs:
        ctrs = json.loads(r["counters_json"] or "{}")
        print(f"Run {r['id']}: state={r['state']}, phase={r['phase']}, "
              f"evidence={ctrs.get('evidence_count', '?')}, "
              f"sources={ctrs.get('unique_sources', '?')}, "
              f"started={r['started_at']}, finished={r['finished_at']}")

    if not runs:
        print("No runs found")
        conn.close()
        return

    run_id = runs[0]["id"]
    print(f"\n=== QUERIES FOR RUN {run_id} ===")

    # 2. Get per-query breakdown for latest run
    queries = conn.execute("""
        SELECT ordinal, query_kind, query_text, state, result_count, error_code,
               started_at, finished_at
        FROM discovery_run_queries
        WHERE run_id = ?
        ORDER BY ordinal ASC
    """, (run_id,)).fetchall()

    by_kind: dict[str, list] = {}
    for q in queries:
        kind = q["query_kind"]
        by_kind.setdefault(kind, []).append(q)

    for kind in ["global_message", "directory", "public_posts"]:
        qs = by_kind.get(kind, [])
        print(f"\n--- {kind.upper()} ({len(qs)} queries) ---")
        total_hits = 0
        for q in qs:
            hits = q["result_count"] or 0
            total_hits += hits
            status = q["state"]
            err = q["error_code"] or ""
            print(f"  [{q['ordinal']:3d}] {q['query_text'][:60]:60s} "
                  f"hits={hits:3d} state={status} {err}")
        print(f"  TOTAL hits for {kind}: {total_hits}")

    # 3. Evidence breakdown per query + DET qualification
    print(f"\n=== EVIDENCE BREAKDOWN FOR RUN {run_id} ===")
    evidence = conn.execute("""
        SELECT matched_query_ordinals_json, discovery_channels_json,
               detection_category, is_qualified, hard_exclusion,
               service_profiles_json, source_type, source_username
        FROM source_discovery_evidence
        WHERE run_id = ?
    """, (run_id,)).fetchall()

    print(f"Total evidence rows: {len(evidence)}")

    # Per-ordinal statistics
    ordinal_stats: dict[int, dict] = {}
    for e in evidence:
        ordinals = json.loads(e["matched_query_ordinals_json"] or "[]")
        for ord_num in ordinals:
            if ord_num not in ordinal_stats:
                ordinal_stats[ord_num] = {"total": 0, "qualified": 0, "excluded": 0}
            ordinal_stats[ord_num]["total"] += 1
            if e["is_qualified"]:
                ordinal_stats[ord_num]["qualified"] += 1
            if e["hard_exclusion"]:
                ordinal_stats[ord_num]["excluded"] += 1

    print("\nOrdinal -> evidence(total/qualified/excluded):")
    for ord_num in sorted(ordinal_stats.keys()):
        st = ordinal_stats[ord_num]
        # Get query text for this ordinal
        qt = next((q["query_text"] for q in queries if q["ordinal"] == ord_num), "?")
        print(f"  [{ord_num:3d}] {qt[:50]:50s} "
              f"ev={st['total']:3d} qual={st['qualified']:3d} excl={st['excluded']:3d}")

    # 4. Service profile distribution
    print(f"\n=== SERVICE PROFILES IN EVIDENCE ===")
    service_counts: dict[str, int] = {}
    qualified_by_service: dict[str, int] = {}
    for e in evidence:
        profiles = json.loads(e["service_profiles_json"] or "[]")
        for svc in profiles:
            service_counts[svc] = service_counts.get(svc, 0) + 1
            if e["is_qualified"]:
                qualified_by_service[svc] = qualified_by_service.get(svc, 0) + 1

    for svc in sorted(service_counts.keys()):
        print(f"  {svc}: total={service_counts[svc]}, qualified={qualified_by_service.get(svc, 0)}")

    # 5. Query the profile version to see current queries
    print(f"\n=== CURRENT PROFILE QUERIES ===")
    profile_version = conn.execute("""
        SELECT pv.version, pv.post_queries_json, pv.directory_queries_json,
               pv.additional_exclusions_json, p.name
        FROM keyword_discovery_profile_versions pv
        JOIN keyword_discovery_profiles p ON p.id = pv.profile_id
        ORDER BY pv.id DESC LIMIT 1
    """).fetchone()
    if profile_version:
        print(f"Profile: {profile_version['name']} v{profile_version['version']}")
        post_qs = json.loads(profile_version["post_queries_json"] or "[]")
        dir_qs = json.loads(profile_version["directory_queries_json"] or "[]")
        print(f"\nPost queries ({len(post_qs)}):")
        for i, q in enumerate(post_qs):
            print(f"  [{i+1:2d}] {q}")
        print(f"\nDirectory queries ({len(dir_qs)}):")
        for i, q in enumerate(dir_qs):
            print(f"  [{i+1:2d}] {q}")

    conn.close()
    print("\n=== DONE ===")


if __name__ == "__main__":
    main()
