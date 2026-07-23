# Design system — AegisOps

**Gate G3:** accepted 2026-07-17

## Semantic tokens

See `src/styles/tokens.css` (created at implementation). Logical names:

- `--color-bg`, `--color-fg`, `--color-muted`, `--color-border`, `--color-accent`, `--color-focus`
- `--font-sans`, `--font-mono`
- `--text-display` … `--text-small`
- `--space-1` … `--space-12`
- `--radius-sm`, `--radius-md`
- `--shadow-none` (prefer borders over soft shadows)

## Component states

Buttons/inputs: default, hover, focus-visible, active, disabled, loading, success, error.

## Mobile

- Single column below 768px
- Sticky-free hero; CTA remains reachable without horizontal scroll
- Touch targets ≥ 44px

## Exceptions

None approved at G3.

## Hero control sample

Hero must prove type scale, accent CTA, and no-card composition before other sections ship.
