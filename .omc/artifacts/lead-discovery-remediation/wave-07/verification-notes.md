# Wave 07 — Verification Notes

## Confirmed

- Bootstrap `seed_ruleset_ru_mvp_1` is idempotent and checksum-stable; processing path no longer seeds on missing active ruleset.
- Loader rejects checksum mismatch / missing version with `RULE_SET_INVALID`; pipeline marks envelope `failed_permanent`.
- Compile cache and loader cache are keyed by checksum; semantic detect result unchanged on cache hit.
- Re-score inserts a second `ProcessingResult` for another version; prior explanation JSON unchanged.
- Locked corpus is synthetic (template families), 520 rows, 12 sources, train/val split; no live DB scrape.
- Val-split calibration metrics meet NFR-QLT-006 / D-067: hot≥0.80, hot+warm≥0.70, purchase-intent recall≥0.75.

## Inference

- Perfect (1.0) val metrics reflect that the locked corpus only retains synthetic templates that DET-A currently classifies as labeled — this locks current rule behavior as a regression gate, not a noisy live-labeled set.

## Candidate / follow-ups

- Keyword scouting still defaults to explicit `seed_catalog_detect` when no `detect_fn` injected; product runs with DB should prefer loader-bound detect (Wave 08+ polish if needed).
- Envelope model has no dedicated `error_code` column; permanent failure uses `processing_state=failed_permanent` + result dict `error_code`.

## Not run

- Full repo-wide pytest suite (only Wave 07 focused + related regression subsets).
- Live Telegram / live product DB.
