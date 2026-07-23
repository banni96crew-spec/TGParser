---
name: landing-page-architecture
description: Convert a commercial brief into offer, user journey, and section sequence. Use when starting a landing page, repositioning, or fixing weak conversion structure. Do not use for visual styling, frontend code, or inventing testimonials.
---

# Назначение

Преобразовать бриф в оффер, user journey и последовательность секций.

# Обязательные входы

- `docs/project/brief.md`
- audience / JTBD / objections
- proof inventory
- constraints
- reference inventory (if any)

# Preconditions и non-goals

- Preconditions: brief exists or can be drafted with TBD owners.
- Non-goals: final visual style, frontend implementation, fabricated metrics.

# Пошаговый алгоритм

1. Проверить brief completeness.
2. Определить audience/JTBD.
3. Зафиксировать primary outcome и CTA.
4. Собрать objections и proof inventory.
5. Спроектировать narrative arc.
6. Создать section matrix.
7. Проверить повторы и шаблонность.
8. Сформировать content gaps.
9. Передать Art Director.

# Обязательный чек-лист

- один primary CTA
- каждый section имеет job
- claims подтверждены или hypothesis
- нет дублирования
- objection coverage полное

# Краткий пример

Перенести security proof перед demo CTA, если доверие — главный барьер.

# Типичные ошибки

- Шаблон hero → features → testimonials без обоснования
- Несколько competing primary CTA
- Неподтверждённые цифры как факты

# Критерии готовности

Маршрут от первого экрана до CTA объясним; у каждой секции измеримая цель.

# Ожидаемые артефакты

`strategy.md`, `content-plan.md`, `information-architecture.md`, CTA map.

# Команды проверки

`node scripts/validate-artifacts.mjs`; link/reference validation.

# Handoff следующему агенту

Для каждой секции: section ID, objective, message, proof, CTA, content status.
