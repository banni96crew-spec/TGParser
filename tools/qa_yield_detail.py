"""Detailed QA yield analysis with proper UTF-8 output."""
import json
import os
import sqlite3
import sys
from pathlib import Path

# Force UTF-8 output
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]


def get_db_path() -> str:
    local = os.environ.get("LOCALAPPDATA", "")
    return str(Path(local) / "TelegramLeadDiscovery" / "data" / "app.sqlite3")


def main():
    db_path = get_db_path()
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=15)
    conn.row_factory = sqlite3.Row

    # Get run 11 data specifically
    run_id = 11

    # Get all queries for run 11
    queries = conn.execute("""
        SELECT ordinal, query_kind, query_text, state, result_count, error_code, scope
        FROM discovery_run_queries
        WHERE run_id = ?
        ORDER BY ordinal ASC
    """, (run_id,)).fetchall()

    print("=" * 80)
    print(f"RUN {run_id} - PER-QUERY YIELD BREAKDOWN")
    print("=" * 80)

    # Group by kind
    global_qs = [q for q in queries if q["query_kind"] == "global_message"]
    dir_qs = [q for q in queries if q["query_kind"] == "directory"]
    pub_qs = [q for q in queries if q["query_kind"] == "public_posts"]
    verif_qs = [q for q in queries if q["query_kind"] == "source_verification"]

    print(f"\nQuery counts: global={len(global_qs)}, directory={len(dir_qs)}, "
          f"public_posts={len(pub_qs)}, source_verification={len(verif_qs)}")

    print("\n--- GLOBAL MESSAGE SEARCH (Phase B) ---")
    total_global = 0
    # Deduplicate same query text (different scope variants)
    seen_texts: set[str] = set()
    for q in global_qs:
        text = q["query_text"]
        hits = q["result_count"] or 0
        total_global += hits
        key = f"{text}|{q['scope'] or 'all'}"
        if key not in seen_texts:
            seen_texts.add(key)
            scope = q["scope"] or "all"
            print(f"  [{q['ordinal']:3d}] scope={scope:8s} '{text}' -> {hits} hits  [{q['state']}]")
    print(f"  TOTAL raw hits global_message: {total_global}")

    print("\n--- DIRECTORY SEARCH (Phase C) ---")
    total_dir = 0
    for q in dir_qs:
        hits = q["result_count"] or 0
        total_dir += hits
        text = q["query_text"]
        print(f"  [{q['ordinal']:3d}] '{text}' -> {hits} channels  [{q['state']}]")
    print(f"  TOTAL channels from directory: {total_dir}")

    print("\n--- PUBLIC POSTS SEARCH (Phase D) ---")
    total_pub = 0
    for q in pub_qs:
        hits = q["result_count"] or 0
        total_pub += hits
        text = q["query_text"]
        print(f"  [{q['ordinal']:3d}] '{text}' -> {hits} hits  [{q['state']}] err={q['error_code']}")
    print(f"  TOTAL raw hits public_posts: {total_pub}")

    print("\n--- SOURCE VERIFICATION (Phase H) ---")
    total_verif = 0
    for q in verif_qs[:30]:  # show first 30
        hits = q["result_count"] or 0
        total_verif += hits
        text = q["query_text"]
        print(f"  [{q['ordinal']:3d}] '{text}' -> {hits} hits  [{q['state']}]")
    if len(verif_qs) > 30:
        rest_hits = sum(q["result_count"] or 0 for q in verif_qs[30:])
        total_verif += rest_hits
        print(f"  ... ({len(verif_qs) - 30} more, {rest_hits} additional hits)")
    else:
        print(f"  Total source verification hits: {total_verif}")

    # Evidence breakdown
    evidence = conn.execute("""
        SELECT matched_query_ordinals_json, discovery_channels_json,
               detection_category, is_qualified, hard_exclusion,
               service_profiles_json, source_type, source_username,
               excerpt, published_at
        FROM source_discovery_evidence
        WHERE run_id = ?
    """, (run_id,)).fetchall()

    print("\n" + "=" * 80)
    print(f"EVIDENCE: {len(evidence)} total rows")
    qualified_count = sum(1 for e in evidence if e["is_qualified"])
    excluded_count = sum(1 for e in evidence if e["hard_exclusion"])
    print(f"  Qualified (DET=lead): {qualified_count}")
    print(f"  Hard excluded: {excluded_count}")
    print(f"  Unqualified (pass-through): {len(evidence) - qualified_count - excluded_count}")

    print("\nEvidence details (excerpts sanitized - first 80 chars only):")
    for i, e in enumerate(evidence):
        ordinals = json.loads(e["matched_query_ordinals_json"] or "[]")
        channels = json.loads(e["discovery_channels_json"] or "[]")
        services = json.loads(e["service_profiles_json"] or "[]")
        excerpt_preview = (e["excerpt"] or "")[:80].replace("\n", " ")
        print(f"\n  Evidence {i+1}:")
        print(f"    ordinals={ordinals} channels={channels}")
        print(f"    category={e['detection_category']} qualified={e['is_qualified']} "
              f"excluded={e['hard_exclusion']}")
        print(f"    services={services}")
        print(f"    published={e['published_at']}")
        print(f"    excerpt[0:80]: '{excerpt_preview}'")

    # Get current profile version details
    print("\n" + "=" * 80)
    print("CURRENT PROFILE VERSION")
    pv = conn.execute("""
        SELECT pv.id, pv.version, pv.post_queries_json, pv.directory_queries_json,
               pv.required_service_profiles_json, p.name
        FROM keyword_discovery_profile_versions pv
        JOIN keyword_discovery_profiles p ON p.id = pv.profile_id
        ORDER BY pv.id DESC LIMIT 1
    """).fetchone()
    if pv:
        print(f"Profile: '{pv['name']}' version={pv['version']}")
        post_qs = json.loads(pv["post_queries_json"] or "[]")
        dir_qs_profile = json.loads(pv["directory_queries_json"] or "[]")
        svc = json.loads(pv["required_service_profiles_json"] or "[]")
        print(f"\nPost queries ({len(post_qs)}):")
        for i, q in enumerate(post_qs):
            print(f"  [{i+1:2d}] {q}")
        print(f"\nDirectory queries ({len(dir_qs_profile)}):")
        for i, q in enumerate(dir_qs_profile):
            print(f"  [{i+1:2d}] {q}")
        print(f"\nRequired services: {svc}")

    conn.close()
    print("\n=== ANALYSIS COMPLETE ===")


if __name__ == "__main__":
    main()
