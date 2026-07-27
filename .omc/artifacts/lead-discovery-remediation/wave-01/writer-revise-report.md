# Wave 01 — Writer REVISE report (Critic mandatory fixes)

- **Agent:** writer
- **Captured_at:** 2026-07-27
- **Input:** `.omc/artifacts/lead-discovery-remediation/wave-01/critic-report.md` (Verdict REVISE)
- **Scope:** ONLY Critic mandatory fixes 1–2; no src/; no non-blocking improvements
- **Status:** **PASS**
- **validate-prd.py:** exit `0`

---

## Files changed

| File | Change |
|---|---|
| `docs/prd/modules/10-administration-observability/PRD.md` | AT-OBS-016 aligned to D-067 remediation thresholds; historical 80%/70% labeled superseded / not a live gate |
| `docs/prd/modules/01-source-discovery/PRD.md` | SRC-035/SRC-036 closed to sole authoritative `DismissSuppressReconsidered`; AT-SRC-036 expected result updated |
| `docs/prd/shared/INTEGRATION_CONTRACTS.md` | `ReconsiderDismissSuppress` + `DismissSuppressReconsidered` marked sole authoritative audit |
| `.omc/artifacts/lead-discovery-remediation/wave-01/writer-revise-report.md` | This evidence |

**Not changed:** TRACEABILITY.md, QUALITY_REQUIREMENTS.md (not required for these two fixes; QLT-006 already holds SoT numerics).

---

## Fixes applied

### 1. AT-OBS-016 ↔ D-067 / NFR-QLT-006 SoT

**Location:** `docs/prd/modules/10-administration-observability/PRD.md` §5 acceptance table, row `AT-OBS-016`

**New text (quote):**
> Remediation release quality gate (D-067): corpus ≥ 500 messages from ≥ 10 sources; hot precision ≥ 0.80; hot+warm precision ≥ 0.70; purchase-intent / `direct_order` recall ≥ 0.75; false-positive rate for `vacancy/advertising/spam` ≤ 5%. Historical MVP wording hot+warm ≥ 80% / `direct_order` recall ≥ 70% is superseded for remediation and MUST NOT be treated as a live gate. Dashboard still displays the OBS-016 metric fields.

Note: AT cell cites **D-067** and concrete numerics matching `NFR-QLT-006` without embedding `NFR-QLT-006`/`QLT-006` shorthand (prior validate-prd false-positive on undefined `QLT-006`).

### 2. SRC-035 audit channel closed to `DismissSuppressReconsidered`

**Locations:**
- `docs/prd/modules/01-source-discovery/PRD.md` — SRC-035, SRC-036, AT-SRC-036
- `docs/prd/shared/INTEGRATION_CONTRACTS.md` — keyword command/event tables

**New SRC-035 bullet (quote):**
> the sole authoritative audit event for successful reconsider is `DismissSuppressReconsidered` (owner `SRC`); `SourceDiscoveryEvent` MUST NOT be used as an alternate or second authoritative reconsider channel;

**New SRC-036 sentence (quote):**
> … and MUST emit authoritative audit event `DismissSuppressReconsidered` (D-062 / SRC-035).

**INTEGRATION (quote):**
> removes suppress membership only; MUST emit authoritative `DismissSuppressReconsidered`
> `DismissSuppressReconsidered` | sole authoritative audit for reconsider (owner `SRC`); …

Removed unbounded “`SourceDiscoveryEvent` or dedicated dismiss-suppress audit” OR-path.

---

## Verification

| Check | Result |
|---|---|
| `uv run python tools/quality/validate-prd.py` | **pass** (exit 0) |
| Dual live quality gates in AT-OBS-016 | Removed |
| Suppress audit dual-path | Closed |

---

## Return schema

```text
Status: PASS
Files changed: [
  docs/prd/modules/10-administration-observability/PRD.md,
  docs/prd/modules/01-source-discovery/PRD.md,
  docs/prd/shared/INTEGRATION_CONTRACTS.md,
  .omc/artifacts/lead-discovery-remediation/wave-01/writer-revise-report.md
]
Commands: [validate-prd exit 0]
Fixes applied: [1 AT-OBS-016 D-067 gates, 2 SRC-035/036 + INTEGRATION DismissSuppressReconsidered]
```
