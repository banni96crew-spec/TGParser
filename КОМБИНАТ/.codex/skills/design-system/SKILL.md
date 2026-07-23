---
name: design-system
description: Create or verify a unified visual system (tokens, grid, type, color, states, motion) for a commercial site. Use after visual direction is approved. Do not use to change the offer or invent unsupported brand claims.
---

# Назначение

Создать или проверить единую визуальную систему коммерческого сайта.

# Обязательные входы

- Approved `design-direction.md`
- Content density notes
- Performance / a11y constraints from `docs/standards/`

# Preconditions и non-goals

- Preconditions: G2 visual direction accepted.
- Non-goals: mass section implementation; changing strategy.

# Пошаговый алгоритм

1. Проверить visual direction и контентную плотность.
2. Зафиксировать сетку и responsive container rules.
3. Определить semantic tokens.
4. Определить type scale и line lengths.
5. Определить spacing/radius/shadow rules.
6. Описать состояния компонентов.
7. Описать image и motion principles.
8. Проверить hero как контрольный образец.
9. Сформировать Builder handoff.

# Обязательный чек-лист

цвета/контраст; typography; spacing; grids; focus; states; reduced motion; image ratios; exceptions.

# Краткий пример

Преобразовать «editorial, strict, tech» в проверяемые token и composition rules.

# Типичные ошибки

AI-defaults без основания: glassmorphism, generic gradients, floating cards, scroll animation spam.

# Критерии готовности

Нет необъяснённых visual values; critical states определены; mobile rules присутствуют.

# Ожидаемые артефакты

`design-system.md`, `tokens.css`, token schema, `motion-spec.md`.

# Команды проверки

До кода — `validate-artifacts`; после — lint, typecheck, build, visual QA.

# Handoff следующему агенту

Обязательные tokens, component contracts, недопустимые отклонения.
