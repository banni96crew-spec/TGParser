---
name: seo-performance
description: Check indexability, metadata, content semantics, and performance budgets on production builds. Use when routes/metadata/assets exist or at release candidate. Do not propose optimizations without measurement or confuse metadata defects with performance defects.
---

# Назначение

Проверить indexability, metadata, content semantics и performance budgets.

# Обязательные входы

Route inventory, metadata/assets, `docs/standards/performance-budgets.md`.

# Preconditions и non-goals

- Preconditions: routes defined; prefer production build for Lighthouse.
- Non-goals: inventing structured data without justification; field INP claims from Lighthouse alone.

# Пошаговый алгоритм

1. Проверить route inventory.
2. Проверить title, description, canonical и social metadata.
3. Проверить robots и sitemap.
4. Проверить headings и internal links.
5. Проверить semantic HTML и structured data только при основании.
6. Проверить image/font strategy.
7. Запустить production build и Lighthouse.
8. Анализировать bundle/render-blocking только при нарушении budget.
9. Передать точечные исправления.

# Обязательный чек-лист

metadata uniqueness; crawlability; no accidental noindex; image dimensions; font loading; LCP asset; CLS; JS budget.

# Краткий пример

Hero image как LCP — зафиксировать размеры/формат/стратегию загрузки вместо глобального preload без измерений.

# Типичные ошибки

Оптимизации без baseline; смешение SEO и perf findings; Lighthouse как field INP.

# Критерии готовности

SEO/Performance gates pass или есть одобренный waiver.

# Ожидаемые артефакты

Lighthouse reports, SEO matrix, performance findings.

# Команды проверки

build, Lighthouse, route smoke; bundle analysis only on budget breach.

# Handoff следующему агенту

metric → cause → change → expected improvement → retest.
