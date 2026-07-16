# PRD модуля 05 — Lead Scoring

## 1. Назначение и границы

Модуль преобразует результат rule-based классификации в воспроизводимый рейтинг `0–100`, band и объяснение для оператора. Он не ищет сигналы в тексте, не создаёт правила и не отправляет уведомления.

## 2. Goals

- одинаковый вход всегда даёт одинаковый score;
- каждый балл и штраф объясняется с указанием rule ID;
- исторический результат воспроизводится по сохранённой версии правил;
- изменение сообщения или явный re-score создаёт новую запись, не уничтожая предыдущую;
- band однозначно определяет появление сообщения в Lead Inbox.

## 3. Non-goals

- AI/LLM, embeddings и вероятностные модели;
- автоматическая оптимизация весов;
- скрытое изменение score с течением времени;
- fuzzy или semantic deduplication;
- автоматический контакт с автором сообщения.

## 4. Принятые решения

### 4.1. Score dimensions

| Dimension | Максимум | Источник значения |
|---|---:|---|
| `intent` | 25 | Сумма совпавших intent rules |
| `service_fit` | 20 | Сумма совпавших service rules |
| `specificity` | 15 | Сумма совпавших specificity rules |
| `budget` | 10 | Сумма совпавших budget rules |
| `deadline` | 5 | Сумма совпавших deadline rules |
| `urgency` | 5 | Сумма совпавших urgency rules |
| `readiness` | 5 | Сумма совпавших readiness rules |
| `contactability` | 5 | Сумма совпавших contact rules |
| `freshness` | 5 | Возраст сообщения на `scored_at` |
| `source_quality` | 5 | Сохранённый рейтинг источника |
| **Итого** | **100** | До применения penalties |

Каждое rule contribution является целым числом от `0` до cap своего dimension. Один `stable_rule_id` учитывается не более одного раза. Сумма внутри dimension ограничивается его максимумом.

### 4.2. Freshness

Возраст рассчитывается как `scored_at - published_at` в UTC.

| Возраст | Баллы |
|---|---:|
| не более 1 часа | 5 |
| более 1 часа, не более 6 часов | 4 |
| более 6 часов, не более 24 часов | 3 |
| более 24 часов, не более 72 часов | 2 |
| более 72 часов, не более 14 дней | 1 |
| более 14 дней | 0 |

Значение фиксируется в `LeadScoreComponent` и не изменяется без нового scoring run.

### 4.3. Source quality

`TelegramSource.quality_score` является целым числом `0–5`; начальное значение нового approved source равно `2`. Оператор может изменить его в карточке источника. Изменение влияет только на новые scoring runs и не запускает массовый re-score автоматически.

### 4.4. Penalties и hard exclusions

- совпавшие `soft_penalty` rules дают отрицательные целые contributions;
- сумма soft penalties ограничивается значением `−30`;
- категории `vacancy`, `advertising`, `spam` и `irrelevant` являются hard exclusions;
- hard exclusion устанавливает `total=0` и `band=irrelevant` независимо от положительных сигналов;
- причина hard exclusion сохраняется отдельно от soft penalties.

### 4.5. Формула

```text
positive_total = sum(capped_dimension_values)
penalty_total = max(-30, sum(unique_soft_penalties))
total = clamp(positive_total + penalty_total, 0, 100)
```

Для hard exclusion формула не применяется: `total=0`.

### 4.6. Score bands

| Score | Band | Поведение MVP |
|---:|---|---|
| 70–100 | `hot` | Lead Inbox и немедленное уведомление при входе в band |
| 50–69 | `warm` | Lead Inbox |
| 30–49 | `cold` | Lead Inbox |
| 0–29 | `irrelevant` | Только processing outcome |

Thresholds входят в immutable `RuleSetVersion`: `hot_min=70`, `warm_min=50`, `cold_min=30`.

## 5. Входные и выходные контракты

### 5.1. `ScoreInput`

| Поле | Тип | Правило |
|---|---|---|
| `message_id` | integer | Обязательное |
| `lead_id` | integer/null | null при первом расчёте |
| `processing_result_id` | integer | Ссылка на immutable processing result |
| `category` | enum | Одна из восьми категорий detection |
| `matched_rules` | list | `stable_rule_id`, dimension, weight, explanation |
| `published_at` | datetime UTC | Обязательное |
| `source_quality_score` | integer | `0–5` |
| `rule_set_version` | integer | Активная версия, применённая detection |
| `scored_at` | datetime UTC | Устанавливается scoring worker |

### 5.2. `ScoreResult`

| Поле | Тип |
|---|---|
| `lead_score_id` | integer |
| `score_version` | integer, начиная с 1 внутри Lead |
| `total` | integer `0–100` |
| `band` | `hot/warm/cold/irrelevant` |
| `positive_total` | integer `0–100` |
| `penalty_total` | integer `−30–0` |
| `hard_exclusion_rule_id` | string/null |
| `components` | ordered list |
| `rule_set_version` | integer |
| `scored_at` | datetime UTC |

Components сортируются по фиксированному порядку dimensions из §4.1, затем по `stable_rule_id`. Explanation строится только из шаблонов активной rule version.

## 6. Functional requirements

| ID | Требование | Приоритет | Acceptance criteria |
|---|---|---:|---|
| SCR-001 | Итоговый score ограничен диапазоном `0–100` | MUST | БД и application validation отклоняют значение вне диапазона |
| SCR-002 | Каждый dimension имеет установленный cap | MUST | Несколько правил не позволяют превысить cap |
| SCR-003 | Один stable rule учитывается один раз | MUST | Повтор rule ID во входе не увеличивает результат |
| SCR-004 | Soft penalties ограничены суммой `−30` | MUST | Сумма `−45` сохраняется как `−30` |
| SCR-005 | Hard exclusions принудительно дают irrelevant | MUST | Положительные signals не меняют результат |
| SCR-006 | Score breakdown сохраняется полностью | MUST | Сумма components и penalty объясняет total |
| SCR-007 | Score связан с immutable RuleSetVersion | MUST | У записи присутствуют version и checksum |
| SCR-008 | Re-score создаёт новую запись | MUST | Предыдущая запись остаётся доступна |
| SCR-009 | Freshness фиксируется на scored_at | MUST | Чтение старого score не пересчитывает возраст |
| SCR-010 | Текущий score выбирается явно | MUST | `Lead.current_score_id` указывает на последнюю committed запись |
| SCR-011 | Создаётся Lead только для hot/warm/cold | MUST | irrelevant отсутствует в основном Inbox |
| SCR-012 | Вход в hot создаёт outbox event | MUST | Event и current score committed атомарно |
| SCR-013 | Повторный score внутри hot не создаёт alert | MUST | Alert возникает только при переходе из не-hot в hot или при первом hot score |
| SCR-014 | Падение из hot обновляет Dashboard без Telegram correction | MUST | Correction event отсутствует |
| SCR-015 | Bulk re-score запускается отдельной persisted job | MUST | Активация rules сама не изменяет историю |
| SCR-016 | Score version монотонно увеличивается внутри Lead | MUST | Unique `(lead_id, score_version)` исключает повтор версии |

## 7. Data ownership

Модуль владеет:

- `LeadScore`, включая монотонный `score_version` внутри Lead;
- `LeadScoreComponent`;
- вычислением `Lead.current_score_id` и `Lead.band`;
- scoring частью immutable `RuleSetVersion`.

Модуль читает `ProcessingResult`, `MonitoringRule`, `TelegramMessage.published_at` и `TelegramSource.quality_score`. Физические таблицы и migrations принадлежат модулю Lead Storage.

## 8. Состояния и переходы

```text
queued → running → succeeded
running → retry_wait → queued
running → failed
running/retry_wait → dead
```

- claim выполняется атомарно;
- transient DB errors повторяются persisted job worker;
- invalid input, отсутствующая rule version или нарушенный invariant завершаются `failed` без частичного score;
- текущий score меняется только в той же транзакции, где сохранены score и components.

## 9. Re-score behavior

Новый scoring run создаётся при:

1. первом положительном processing result;
2. edit сообщения;
3. ручном запуске bulk re-score после активации новой RuleSetVersion;
4. ручном re-score одного lead.

Lead identity и операторский status сохраняются. Если новый результат становится irrelevant, lead остаётся в истории, получает текущий band `irrelevant` и исчезает из стандартного Inbox; он доступен через фильтр «Все результаты».

## 10. Observability

Обязательные metrics:

- `scoring_runs_total{outcome}`;
- `scoring_duration_seconds`;
- `score_band_total{band}`;
- `hard_exclusions_total{category}`;
- `score_invariant_failures_total`;
- `bulk_rescore_queue_depth`.

Structured log содержит IDs, version, total, band, duration и outcome. Текст сообщения и секреты в log не записываются.

## 11. Dependencies

- upstream: Message Processing, Lead Detection, Source Discovery;
- storage: Lead Storage;
- downstream: Lead Dashboard, Notifications, Administration/Observability;
- shared: domain model, integration contracts, quality requirements.

## 12. Acceptance test catalogue

| Test ID | Проверка | Ожидаемый результат |
|---|---|---|
| AT-SCR-001 | Расчёт или write пытается сохранить score вне `0–100` | Значение отклонено |
| AT-SCR-002 | Contributions превышают cap dimension | Итог по dimension равен cap |
| AT-SCR-003 | Один stable rule ID передан дважды | Contribution учтён один раз |
| AT-SCR-004 | Soft penalties дают `−45` | Сохранено `−30` |
| AT-SCR-005 | Vacancy имеет положительные signals | `total=0`, `band=irrelevant` |
| AT-SCR-006 | Breakdown пересчитан независимо | Components, penalty и total совпадают |
| AT-SCR-007 | Исторический score открыт после смены rules | Сохранены исходные version и checksum |
| AT-SCR-008 | Lead edit повторно оценён | Создан новый score, предыдущий сохранён |
| AT-SCR-009 | Старый score читается через сутки | Freshness component не изменён |
| AT-SCR-010 | Новый score committed | `current_score_id` указывает на него |
| AT-SCR-011 | Score равен 29 | Lead не появляется в основном Inbox |
| AT-SCR-012 | Warm lead становится hot | Score и hot event committed атомарно |
| AT-SCR-013 | Hot lead остаётся hot после edit | Второй alert event не создан |
| AT-SCR-014 | Re-score снижает hot до warm | Dashboard обновлён, correction event отсутствует |
| AT-SCR-015 | Активирована новая RuleSetVersion | History не меняется до запуска persisted bulk re-score job |
| AT-SCR-016 | Lead рассчитан три раза | Score versions равны 1, 2 и 3 |

## 13. DEFERRED

- автоматическая калибровка весов;
- персональные scoring profiles;
- time-decay re-score по расписанию;
- ML/LLM scoring.
