# Wave 09 — Acceptance Matrix

## Part A (harness) — PASS

| ID | Criterion | Result | Evidence |
|---|---|---|---|
| NFR-PERF-006 | 100 monitoring sources / ≥1000 msg/day ingestion | **PASS** | `harness-report.json` steady: sources=100, messages=1000 |
| NFR-PERF-007 | Burst 6000 @ 10/s×10min profile; backlog drain ≤15 min | **PASS** | burst: 6000 events; post-inject drain≈0.8s ≤900s |
| NFR-PERF-008 | p95 received→processed ≤30s steady / ≤120s burst | **PASS** | steady p95≈10.5s; burst p95≈1.1s |
| NFR-REL-008 | Kill/restart from checkpoint no gap/dup; recovery ≤5 min | **PASS** | kill scenarios recovery <1s; envelope cardinality stable on replay |
| Correctness | Exact dedupe 100% on 10% replay | **PASS** | new_envelopes_on_replay=0; no lead/outbox growth |
| Edits/deletes | Event types handled | **PASS** | message_new/edited/deleted present |
| FloodWait | No retry before until | **PASS** | job retry_wait + available_at |
| Notify outage | No dup outbox; failure path | **PASS** | unique keys; bot_fail_calls≥1 |
| UI under write | Reads succeed | **PASS** | ui_reads_ok; sqlite_busy=0 |
| Isolation | Temp DB only; no live Telegram/Bot | **PASS** | LOCALAPPDATA→tmp_path guard test |

## Part B (live Windows pilot) — NOT_RUN

| Step | Status |
|---|---|
| Operator approval | **BLOCKED** |
| Stop runtime / lock release | NOT_RUN |
| integrity-check | NOT_RUN |
| backup + SHA-256 | NOT_RUN |
| Migration dry-run on copy | NOT_RUN |
| Live migrate | NOT_RUN |
| 3–5 source pilot → scale 5→100 | NOT_RUN |
| Discovery Jaccard / dismiss recurrence | NOT_RUN |

## Gate verdict

- **09A:** PASS
- **09B:** NOT_RUN / BLOCKED
- **READY_FOR_WAVE_10:** yes (Part B remains blocked; Wave 10 must not claim live pilot)
