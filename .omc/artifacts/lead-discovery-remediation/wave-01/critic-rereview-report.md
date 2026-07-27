# Wave 01 — Critic re-review (mandatory fixes 1–2 only)

- **Agent:** critic
- **Captured_at:** 2026-07-27
- **Prior:** `.omc/artifacts/lead-discovery-remediation/wave-01/critic-report.md` (Verdict **REVISE**)
- **Writer claim:** `.omc/artifacts/lead-discovery-remediation/wave-01/writer-revise-report.md` (Status **PASS**)
- **Scope:** ONLY Critic mandatory fixes 1–2 + no new dual-ownership / invented forks from revise
- **Product / PRD edits by this agent:** none (evidence only)
- **validate-prd.py:** not run (verifier owns fresh re-run; writer exit 0 untrusted for COMPLETE)

---

## Plan Review

### Verdict

**APPROVE**

Both mandatory REVISE fixes are closed in live PRD/contracts. Historical 80%/70% remain labeled superseded / non-live for remediation. Suppress reconsider audit is sole-channel `DismissSuppressReconsidered`. No new dual-ownership or invented forks introduced by the revise.

### Blocking findings

_None._

### Fix closure matrix

| Prior mandatory fix | Result | Evidence |
|---|---|---|
| 1. AT-OBS-016 ↔ D-067 / NFR-QLT-006 | **CLOSED** | Live AT uses hot ≥ 0.80, hot+warm ≥ 0.70, recall ≥ 0.75; historical 80%/70% superseded not live |
| 2. SRC-035 sole audit `DismissSuppressReconsidered` | **CLOSED** | Sole authoritative event; `SourceDiscoveryEvent` MUST NOT be alternate; no OR-path |
| 3. No new dual-ownership / invented forks | **PASS** | Ownership remains SRC event / OBS display vs QLT SoT; no second audit owner |

### Evidence quotes (independent of writer)

#### Fix 1 — AT-OBS-016 remediation thresholds

`docs/prd/modules/10-administration-observability/PRD.md:79`:

> Remediation release quality gate (D-067): corpus ≥ 500 messages from ≥ 10 sources; hot precision ≥ 0.80; hot+warm precision ≥ 0.70; purchase-intent / `direct_order` recall ≥ 0.75; false-positive rate for `vacancy/advertising/spam` ≤ 5%. Historical MVP wording hot+warm ≥ 80% / `direct_order` recall ≥ 70% is superseded for remediation and MUST NOT be treated as a live gate. Dashboard still displays the OBS-016 metric fields.

OBS-016 requirement remains **display-only** (metric fields), not a second live numeric gate:

`docs/prd/modules/10-administration-observability/PRD.md:53`:

> Dashboard MUST показывать размер calibration corpus, число источников, precision `hot + warm`, recall `direct_order` и false positive rate для `vacancy/advertising/spam`.

Consistency with SoT (spot-check):

- `docs/prd/shared/QUALITY_REQUIREMENTS.md` **NFR-QLT-006**: hot ≥ `0.80`; hot+warm ≥ `0.70`; purchase-intent/`direct_order` recall ≥ `0.75`
- `docs/prd/DECISION_LOG.md` **D-067**: QLT-002/003 superseded for remediation by QLT-006; OBS listed among modules

#### Fix 2 — SRC-035 sole audit channel

`docs/prd/modules/01-source-discovery/PRD.md:299`:

> the sole authoritative audit event for successful reconsider is `DismissSuppressReconsidered` (owner `SRC`); `SourceDiscoveryEvent` MUST NOT be used as an alternate or second authoritative reconsider channel;

`docs/prd/modules/01-source-discovery/PRD.md:304`:

> … MUST emit authoritative audit event `DismissSuppressReconsidered` (D-062 / SRC-035).

`docs/prd/modules/01-source-discovery/PRD.md:486` (AT-SRC-036):

> Opportunity may appear again; exactly one authoritative `DismissSuppressReconsidered`; distinct from `ReconsiderSource`

`docs/prd/shared/INTEGRATION_CONTRACTS.md:132`:

> removes suppress membership only; MUST emit authoritative `DismissSuppressReconsidered`; distinct from `ReconsiderSource`

`docs/prd/shared/INTEGRATION_CONTRACTS.md:141`:

> `DismissSuppressReconsidered` | sole authoritative audit for reconsider (owner `SRC`); …

Repo grep for prior OR-path phrasing (`SourceDiscoveryEvent` **or** dedicated dismiss-suppress audit): **no remaining dual-path wording**. Only the explicit MUST NOT alternate sentence remains.

#### No new dual-ownership / forks from revise

- Audit owner stays `SRC` via one named event; STO still owns physical suppress table (unchanged ownership split from Wave 01 freeze).
- Quality SoT remains `NFR-QLT-006` / D-067; OBS AT now cites those remediation numerics rather than competing with them.
- Entity alias `DismissedSource` / `DismissedKeywordSource` still dual-named (prior **non-blocking** #1) — not introduced by this revise; not a mandatory-fix reopen.
- Master README historical 80% bullet still present (prior soft improvement) — not a live AT gate; not a mandatory-fix reopen.

### Non-blocking improvements

Carry-forward from prior critic report (out of this re-review gate; do not reopen APPROVE):

1. Canonicalize suppress entity name (`DismissedSource` vs `DismissedKeywordSource`).
2. QLT-006 cross-ref corpus size → NFR-QLT-001.
3. Forward note on AT-STO-015 / migration `003` Wave 02 coverage.
4. Soft-align plan Wave 02 “dismissed/rejected” prose vs STO-017.
5. Optional master README calibration bullet sync after OBS fix (still soft).

### Missing verification or rollback

- **Verifier (not critic):** fresh `uv run python tools/quality/validate-prd.py`, unique ID lint, link check — still required for Wave 01 **COMPLETE**.
- Docs rollback path unchanged (git restore of PRD); no live DB impact in Wave 01.

### Decision challenge

- **Favored approach:** APPROVE freeze with QLT-006 remediation SoT + sole `DismissSuppressReconsidered` audit — matches architect intent and closed both REVISE blockers.
- **Strongest alternative:** Also rename OBS-016 requirement text to say “display metrics; gate owned by AT-OBS-016/NFR-QLT-006” — clarity only; not required because AT already separates display vs live gate.
- **Unresolved trade-off:** None for mandatory fixes 1–2.

### Coverage

#### Checklist (mandatory-fix re-scope)

| Check | Result |
|---|---|
| AT-OBS-016 hot≥0.80, hot+warm≥0.70, recall≥0.75 | **PASS** |
| Historical 80/70 superseded not live | **PASS** |
| SRC-035 sole `DismissSuppressReconsidered` | **PASS** |
| No OR-path for reconsider audit | **PASS** |
| No new dual-ownership / invented forks from revise | **PASS** |

#### Claims not independently verified

- Writer `validate-prd.py` exit 0 — verifier must re-run.
- Exhaustive scan of skim-only modules beyond targeted greps for this re-scope.

---

## Return schema

```text
Status: PASS
Verdict: APPROVE
Files changed: [.omc/artifacts/lead-discovery-remediation/wave-01/critic-rereview-report.md]
AC mapping:
  - Fix1 AT-OBS-016 D-067/NFR-QLT-006 thresholds — PASS
  - Fix1 historical 80/70 not live — PASS
  - Fix2 SRC-035 sole DismissSuppressReconsidered — PASS
  - Fix2 no OR-path — PASS
  - No new dual-ownership/forks from revise — PASS
Risks:
  - R-C03 (carry): trusting writer validate-prd without verifier re-run still applies for COMPLETE
Remaining gaps:
  - Verifier fresh validate-prd + ID/link pass still required for Wave 01 COMPLETE
  - Prior non-blocking improvements remain optional (not freeze blockers)
Mandatory fixes if REVISE:
  - none
```

### Compliance

- sequential-thinking: pass
- preflight-block: pass
- skills-used: [.cursor/skills/agent-preflight/SKILL.md, .cursor/skills/plan/SKILL.md]
- subagents-used: none
- hook-audit: not_run
- evidence-claim: not_run
