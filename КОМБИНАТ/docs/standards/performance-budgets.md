# Performance Budgets

## Lighthouse (median of 3 production runs)

| Category | Minimum |
|---|---|
| Performance | ≥ 90 |
| Accessibility | ≥ 95 |
| Best Practices | ≥ 95 |
| SEO | ≥ 95 |

## Lab metrics

| Metric | Budget |
|---|---|
| LCP | ≤ 2.5 s |
| CLS | ≤ 0.1 |
| TBT | ≤ 200 ms |

## Field

- INP ≤ 200 ms when real field data exists
- Lighthouse must not be treated as proof of field INP

## Other

- No horizontal scroll on required viewports
- Unexpected failed network requests: `0`
- Deterministic visual regions: pixel diff ≤ 0.5% or manual sign-off per diff
- Image dimensions known; LCP candidate explicitly managed
- Font loading strategy documented

Breach requires fix or written waiver in `qa/waivers.md`.

Owner: Builder / QA
