# Wave 01 — Critic report (PRD / contract freeze)

- **Agent:** critic
- **Captured_at:** 2026-07-27
- **Inputs:** plan Wave 01 gate; `architect-contract-delta.md`; `writer-report.md`; spot-check of all writer-owned `docs/prd/*` IDs (D-061..D-067, SRC-033..045, COL-023..026, PROC-019, DET-016, STO-017/018, UI-019..024, OBS-019..021, INF-022, NFR-PERF-006..008, NFR-REL-008, NFR-QLT-006, TRACEABILITY §8)
- **Product / PRD edits by this agent:** none (evidence only)
- **validate-prd.py:** not run (verifier owns fresh re-run)

---

## Plan Review

### Verdict

**REVISE**

Freeze is largely coherent with architect areas 1–11 and does not invent MVP-breaking forks (no AI / outreach / private auto-join / Stars; bands stay `promising|review|weak`; Wave 02 still mandated). Fail-closed semantic gate does **not** pass while OBS still hard-codes superseded calibration thresholds and suppress audit channel remains dual-pathed.

### Blocking findings

1. **OBS-016 / AT-OBS-016 contradict D-067 / NFR-QLT-006 single remediation numeric source of truth**
   - Evidence: `docs/prd/modules/10-administration-observability/PRD.md` — OBS-016 display OK, but **AT-OBS-016** still requires precision `hot + warm` ≥ **80%** and recall `direct_order` ≥ **70%**. `DECISION_LOG` **D-067** and `QUALITY_REQUIREMENTS` **NFR-QLT-006** freeze remediation release at hot ≥ **0.80**, hot+warm ≥ **0.70**, purchase-intent/`direct_order` recall ≥ **0.75**; QLT-002/003 marked superseded for remediation. D-067 module list includes `OBS`.
   - Impact: Wave 07/09 / OBS quality gate can PASS one contract and FAIL the other; remediation “single SoT” claim is false.
   - Required revision: Update AT-OBS-016 (and any OBS-016 acceptance prose that implies old gates) to cite **NFR-QLT-006** for remediation release; keep historical MVP wording only if explicitly scoped as non-remediation / superseded, consistent with QLT-002/003 treatment.

2. **Suppress reconsider audit channel left open (dual path)**
   - Evidence: SRC-035 allows audit via `SourceDiscoveryEvent` **or** “dedicated dismiss-suppress audit”; `INTEGRATION_CONTRACTS` defines concrete event `DismissSuppressReconsidered`. Architect allowed either, but freeze must pick one owner channel for Wave 02/08.
   - Impact: Implementers can dual-emit or disagree on which event is authoritative → dual ownership / incomplete AT coverage.
   - Required revision: Close to one: e.g. reconsider MUST emit `DismissSuppressReconsidered` (and optionally also append `SourceDiscoveryEvent` only if explicitly non-authoritative); remove unbounded OR from SRC-035.

### Non-blocking improvements

1. **Canonical suppress entity name:** docs alternate `DismissedSource` / `DismissedKeywordSource`. Pick one physical/logical primary name in DOMAIN_MODEL + STO retention table to avoid dual-table temptation in Wave 02.
2. **NFR-QLT-006 vs corpus size:** plan §2 / architect Area 10 listed corpus ≥500 / ≥10 source types under remediation gates; QLT-006 omits it while **NFR-QLT-001** still holds. Add explicit cross-ref “corpus size remains NFR-QLT-001” inside QLT-006 acceptance text to prevent accidental supersession reading.
3. **AT-STO-015 still names migration `002` only:** STO-017 owns `003` backfill semantics for Wave 02; add a forward note that Wave 02 MUST extend migration AT coverage to head (empty DB + populated 002→003 + idempotent remigrate), without implementing code in Wave 01.
4. **Plan Wave 02 prose “dismissed/rejected” vs STO-017 “review_state=dismissed” only:** writer correctly followed architect Area 2; coordinator should soft-align plan Wave 02 wording or explicitly confirm rejected `TelegramSource` is covered by SRC-031 registry suppress, not suppress-ledger backfill.
5. **Optional skim consumers:** `docs/prd/README.md` / master calibration bullets still cite historical 80%/70% — not writer checklist-required, but can confuse operators; coordinator soft-sync after OBS fix.
6. **Cooldown 24h:** frozen as architect proposed; acceptable numeric close of plan underspec — no reopen unless owner rejects.

### Missing verification or rollback

- **Verifier (not critic):** fresh `uv run python tools/quality/validate-prd.py`, unique ID lint, link check — writer smoke exit 0 is **untrusted** for gate.
- **Suppress/identity migration:**
  - Backfill: **defined** (STO-017 + TRACEABILITY §8; Wave 02 mandatory; empty `003` head insufficient).
  - Failed-upgrade rollback: **covered** by existing STO §12 (pre-migration backup restore on error) — adequate for docs freeze.
  - Downgrade-during-runtime: already forbidden in STO out-of-scope — OK.
  - Gap (non-blocking): no explicit Wave 02 AT row yet for `002→003` suppress backfill / remigrate (see improvement #3).
- **Docs rollback:** architect path (git restore of PRD) remains valid; no live DB impact in Wave 01.

### Decision challenge

- **Favored approach:** Keep architect mapping — bands `promising|review|weak` with plan aliases; QLT-006 remediation SoT; depth=2; Wave 02 mandatory backfill.
- **Strongest alternative:** Amend NFR-QLT-002/003 in place to 80%/70%→80%/70% split and delete QLT-006 (architect Option rejected; would reopen D-034 narrative). Inferior: more churn, loses discovery novelty gates bundled in QLT-006.
- **Unresolved trade-off:** Whether OBS dashboard **display** of historical MVP metrics (OBS-016) remains forever alongside remediation gates — must be labeled, not dual-gated.

### Coverage

#### Checklist (critic ownership)

| Check | Result |
|---|---|
| 1. Dual ownership of entity/event/DTO | **FAIL soft → blocking #2** (suppress audit OR-path); otherwise ownership matrix respected (SRC logical / STO physical / COL peer DTO) |
| 2. Requirements without AC / missing TRACEABILITY | **PASS** on spot-check — new MUST IDs have AT rows; TRACEABILITY ranges + §8 list remediation IDs |
| 3. Open/ambiguous thresholds | **PASS** for architect-frozen numerics (novelty 0.80, Jaccard 0.60, cooldown 24h, batch 50, depth 2, capacity 100/1000, etc.); **FAIL** where OBS AT still uses superseded thresholds (blocking #1) |
| 4. Divergence / invented forks vs architect | **PASS** — D-061..067 and area IDs match delta; provisional representation chosen (`TelegramSource.telegram_id` nullable until resolve) |
| 5. AI / outreach / private auto-join leakage | **PASS** — new MUST text preserves exclusions; SRC/COL out-of-scope unchanged |
| 6. Migration/backfill/rollback for suppress/identity | **PASS with notes** — backfill + Wave 02 mandate + STO §12 failed-upgrade restore; Wave 02 AT extension still needed |
| 7. Band naming `promising\|review\|weak` | **PASS** — D-067, DOMAIN, SRC, UI-021; aliases only |
| 8. Wave 02 still mandated (historical backfill) | **PASS** — STO-017, TRACEABILITY §8, writer report |

#### Areas 1–11 vs writer

| Area | Critic |
|---|---|
| 1 Identity / provisional / merge | Present (SRC-033/034, D-061, DOMAIN) |
| 2 Suppress / reconsider / retention | Present; audit channel must close (blocking #2) |
| 3 Novelty / pool_exhausted | Present (SRC-037/038, OBS-019, UI-020) |
| 4 Acquisition / replacement / cooldown | Present (SRC-039..041; SRC-024 profile queries) |
| 5 Graph public-only depth=2 | Present (SRC-042) |
| 6 Eligibility / noise / profile / bands | Present (SRC-043..045, UI-021) |
| 7 TelegramPeerRef / continuation / live DTO | Present (COL-023..026, INTEGRATION) |
| 8 Jobs / leases / named loops | Present (STO-018, INF-022, OBS-020, D-066) |
| 9 Rule-set pin / seed | Present (DET-016, PROC-019, D-065) |
| 10 NFR capacity / QLT | Present; OBS AT conflict (blocking #1) |
| 11 UI defaults / lifecycle | Present (UI-019..024) |

#### Claims not independently verified

- Writer `validate-prd.py` exit 0 / requirement counts (254/254/67) — verifier must re-run.
- Exhaustive line-by-line uniqueness of every historical ID outside new ranges — spot-check only.
- Content of skim-only modules (SCR/NOT/SET/SEC) beyond targeted greps for leakage.

---

## Return schema

```text
Status: FAIL
Verdict: REVISE
Files changed: [.omc/artifacts/lead-discovery-remediation/wave-01/critic-report.md]
AC mapping:
  - Wave01 semantic: dual ownership — FAIL (suppress audit OR-path)
  - Wave01 semantic: every MUST has AC + TRACEABILITY — PASS (spot-check)
  - Wave01 semantic: thresholds concrete / single SoT — FAIL (AT-OBS-016 vs NFR-QLT-006)
  - Wave01 semantic: no invent vs architect — PASS
  - Wave01 semantic: no AI/outreach/private auto-join — PASS
  - Wave01 semantic: suppress/identity migration+backfill+rollback — PASS with Wave 02 AT note
  - Wave01 semantic: bands promising|review|weak — PASS
  - Wave01 semantic: Wave 02 historical backfill still mandatory — PASS
Risks:
  - R-C01: Shipping Wave 02 on REVISE freeze freezes dual quality gates into code/tests
  - R-C02: Open audit OR-path → duplicate or missing DismissSuppressReconsidered
  - R-C03: Trusting writer validate-prd smoke without verifier re-run
Remaining gaps:
  - Writer must apply mandatory fixes below; then critic/verifier re-gate
  - Verifier fresh validate-prd + ID/link pass still required for Wave 01 COMPLETE
Mandatory fixes if REVISE:
  1. Align AT-OBS-016 (and related OBS acceptance prose) with D-067 / NFR-QLT-006 remediation thresholds; label any historical 80%/70% as superseded/non-remediation only
  2. Close SRC-035 audit channel to a single authoritative event (`DismissSuppressReconsidered` recommended); remove unbounded SourceDiscoveryEvent OR dedicated dual-path
```

### Compliance

- sequential-thinking: pass
- preflight-block: pass
- skills-used: [.cursor/skills/agent-preflight/SKILL.md, .cursor/skills/plan/SKILL.md]
- subagents-used: none
- hook-audit: not_run
- evidence-claim: not_run
