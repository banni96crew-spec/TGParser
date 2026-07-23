# Motion spec — AegisOps

**Gate G3 (motion):** accepted 2026-07-17

| Motion ID | Purpose | Behavior | Reduced motion |
|---|---|---|---|
| M-hero-in | Hierarchy | Opacity 0→1, 200ms ease-out on load | Instant show |
| M-section-in | Continuity | Subtle translateY 8px + fade once in view | Instant show |
| M-cta-press | Feedback | Scale 0.98 on active | Color/focus only |

Rules:

- No infinite decorative loops
- No scroll-jacking
- No content available only via animation
- Framer Motion only where listed
