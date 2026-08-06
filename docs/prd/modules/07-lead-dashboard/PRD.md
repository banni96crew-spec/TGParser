# PRD модуля 07 — Lead Dashboard

## 1. Назначение и границы

Модуль предоставляет единственный пользовательский интерфейс MVP: локальный RU-first web UI для просмотра лидов, ручной обработки, проверки источников, управления rules/settings, наблюдения за jobs и ручного экспорта/удаления. Модуль вызывает application services других модулей и не реализует их business rules повторно.

## 2. Goals

- показывать свежие hot/warm/cold leads в одном Inbox;
- объяснять category, score, components, penalties и rule version;
- позволять одному оператору изменять lead status и сохранять feedback;
- предоставлять ручные действия для sources, rules, jobs, export и purge;
- отображать состояние collector, queues, notifications и database;
- работать без отдельного frontend build system.

## 3. Non-goals

- multi-user, registration, login, RBAC и organizations;
- remote access и mobile application;
- публичный JSON API;
- automatic outreach;
- отдельный SPA frontend;
- dashboards для нескольких операторов.

## 4. Принятый стек и запуск

- FastAPI;
- Uvicorn;
- Jinja2 templates;
- HTMX;
- обычный CSS без Node.js toolchain;
- bind только `127.0.0.1:8765`;
- основной адрес `http://127.0.0.1:8765/leads`;
- язык UI — русский;
- display timezone — `Europe/Moscow`, storage timestamps — UTC;
- login form отсутствует.

Uvicorn и UI работают в общем Python 3.12.x process с остальными async services. Web handler не вызывает Telegram и notification network clients напрямую.

## 5. Information architecture

| Page | Route | Назначение |
|---|---|---|
| Lead Inbox | `GET /leads` | Список и фильтры hot/warm/cold |
| Lead detail | `GET /leads/{lead_id}` | Текст, provenance, score и история |
| Sources | `GET /sources` | Approved/monitoring/paused/inaccessible sources |
| Source candidates | `GET /sources/candidates` | Ручное approve/reject |
| Разведка источников | `GET /discovery` | Keyword profiles, runs, results (`active_nav=discovery`) |
| Discovery runs (graph) | `GET /discovery-runs` | Результаты и counters graph discovery |
| Collector runs | `GET /collector-runs` | Backfill/reconciliation progress |
| Service profiles | `GET /service-profiles` | Профили услуг |
| Rule sets | `GET /rule-sets` | Draft validation и activation |
| Settings | `GET /settings` | Несекретные operator settings |
| Health | `GET /health` | Состояние runtime components |
| Logs | `GET /logs` | Structured operational events |
| Notifications | `GET /notifications` | Delivery attempts и dead events |
| Export/Purge | `GET /data-tools` | Ручной CSV export и manual delete |

`GET /` отвечает redirect `307` на `/leads`.

## 6. Lead Inbox

### 6.1. Состав строки

- band и score;
- category;
- excerpt до 240 символов;
- source title;
- published time;
- freshness label;
- current lead status;
- service profile;
- признак edit/delete;
- permalink indicator.

### 6.2. Сортировка и pagination

- default sort: `published_at DESC, lead_id DESC`;
- альтернативная сортировка: `score DESC, published_at DESC`;
- keyset pagination по полям выбранной сортировки;
- page size фиксирован на 50 rows;
- HTMX обновляет первую страницу каждые 5 секунд;
- polling сохраняет выбранные filters и не заменяет открытую detail page.

### 6.3. Filters

Filters комбинируются через AND:

- band: hot/warm/cold/irrelevant/all;
- category;
- source;
- lead status;
- service profile;
- published date range;
- edited/deleted flag;
- text query.

Default filter: bands `hot,warm,cold`, все non-terminal statuses, без ограничения source/profile/date. Text query выполняет case-insensitive escaped `LIKE` по текущему lead text и source title. Пустой query не добавляет условие.

## 7. Lead detail

Detail page показывает:

- полный сохранённый текст;
- category, band, total score и `scored_at`;
- каждую score dimension, contribution, penalty, matched rule ID и explanation;
- RuleSetVersion и checksum;
- source title, username, type и quality score;
- source permalink только при наличии корректного URL;
- author username/display name и сохранённые contact fields;
- published/edit/delete timestamps;
- message revisions;
- duplicate references и canonical marker;
- lead status history, notes и feedback;
- notification delivery history.

User-provided content всегда HTML-escaped. Permalink без подтверждённого URL отображается как «Ссылка недоступна» и не синтезируется.

## 8. Lead lifecycle и operator actions

Модуль владеет логическими сущностями `Lead`, `LeadStatusHistory` и `LeadFeedback`; Storage владеет их physical tables. Dashboard presentation вызывает application commands и не выполняет прямой SQL.

Statuses:

- `new`;
- `reviewed`;
- `contacted`;
- `won`;
- `lost`;
- `ignored`;
- `source_deleted`.

Основные переходы:

```text
new → reviewed → contacted → won
new → reviewed → contacted → lost
new/reviewed → ignored
new/reviewed/contacted → source_deleted
```

`won`, `lost`, `ignored` и `source_deleted` возвращаются в `reviewed` только кнопкой «Вернуть в работу» с обязательной note длиной `3–500` символов. Каждый переход использует optimistic version из формы и создаёт append-only history row.

Operator actions:

- изменить status;
- добавить note до 2000 символов;
- сохранить feedback `correct`, `false_positive`, `wrong_category` или `wrong_band`;
- при category/band error указать ожидаемое значение;
- открыть source message;
- выполнить manual re-score;
- выполнить manual delete с подтверждением.

## 9. Source, rules и settings surfaces

Dashboard предоставляет формы, но business transitions выполняют owning services.

### 9.1. Sources

- candidate approve/reject требует отдельного POST action и confirmation dialog;
- monitoring source может быть paused/resumed/disabled;
- source detail показывает provenance, lifecycle, last checkpoint, collector lag и error state;
- source quality изменяется integer input `0–5` с optimistic version.

### 9.1a. Keyword discovery (Разведка источников)

Навигация MUST размещать пункт «Разведка источников» между «Источники» и «Состояние».

Маршруты:

```text
GET  /discovery
GET  /discovery/profiles/new
POST /discovery/profiles
GET  /discovery/profiles/{id}
POST /discovery/profiles/{id}/versions
POST /discovery/runs
GET  /discovery/runs/{id}
GET  /discovery/runs/{id}/status-fragment
GET  /discovery/runs/{id}/results-fragment
POST /discovery/runs/{id}/cancel
GET  /discovery/results/{id}
POST /discovery/results/{id}/promote
POST /discovery/results/{id}/dismiss
```

UI MUST показывать: активный профиль/version, лимиты, Telegram connection state, free quota summary, постоянный текст `Максимальная стоимость: 0 Stars`, кнопку запуска, последние 20 runs, progress (HTMX каждые 5 с), filters результатов и до 5 evidence excerpts. Поля Stars/paid consent отсутствуют. Approval monitoring на странице result отсутствует; promote создаёт только candidate. HTMX MUST быть локально vendored (`2.0.10`); CDN в runtime запрещён.

### 9.2. Rule sets

- draft создаётся как новая version;
- validation показывает compile errors и test outcomes;
- activation доступна только для полностью valid version;
- active version и checksum всегда видны;
- bulk re-score запускается отдельной подтверждаемой action.

### 9.3. Settings

- формы читают и изменяют только несекретные SQLite settings;
- credentials и Telegram session содержимое не отображаются;
- invalid value возвращает field-level error и не изменяет stored value;
- каждое изменение показывает success/failure result на русском языке.

## 10. HTTP actions

| Method и route | Действие |
|---|---|
| `POST /leads/{id}/status` | Изменить status |
| `POST /leads/{id}/notes` | Добавить note |
| `POST /leads/{id}/feedback` | Сохранить feedback |
| `POST /leads/{id}/rescore` | Создать persisted re-score job |
| `POST /leads/{id}/delete` | Выполнить manual delete |
| `POST /sources/{id}/approve` | Approve candidate |
| `POST /sources/{id}/reject` | Reject candidate |
| `POST /sources/{id}/state` | Pause/resume/disable |
| `POST /discovery/profiles` | Создать keyword profile |
| `POST /discovery/profiles/{id}/versions` | Создать profile version |
| `POST /discovery/runs` | Запустить keyword discovery |
| `POST /discovery/runs/{id}/cancel` | Отменить keyword run |
| `POST /discovery/results/{id}/promote` | Promote opportunity → candidate |
| `POST /discovery/results/{id}/dismiss` | Скрыть opportunity |
| `POST /rule-sets/{id}/validate` | Запустить validation |
| `POST /rule-sets/{id}/activate` | Активировать valid version |
| `POST /rule-sets/{id}/rescore` | Создать bulk re-score job |
| `POST /jobs/{id}/retry` | Повторить failed job вручную |
| `POST /notifications/{id}/retry` | Явно повторить dead delivery |
| `POST /exports/leads/preview` | Рассчитать preview |
| `POST /exports/leads` | Создать CSV после confirmation |

State-changing request принимает CSRF token и entity `version`. Stale version возвращает HTTP `409` с сообщением «Данные изменились. Обновите страницу». Validation error возвращает `422`; отсутствующая entity — `404`; unexpected failure — `500` с correlation ID.

## 11. CSV export

- export запускается только вручную;
- preview показывает filters, columns и row count;
- максимальный export — 10 000 rows за один файл;
- columns имеют фиксированный порядок: `lead_id`, `published_at`, `category`, `score`, `band`, `status`, `source_title`, `source_username`, `author_username`, `text`, `permalink`, `reasons`;
- формат: CSV, UTF-8 with BOM, delimiter `;`, CRLF;
- значения защищаются от spreadsheet formula execution: первый символ `=`, `+`, `-` или `@` предваряется апострофом;
- файл создаётся во runtime temp directory и удаляется через 1 час;
- filename: `telegram-leads-YYYYMMDD-HHMMSS.csv`;
- automatic export отсутствует.

## 12. Manual delete UI

- кнопка находится только на Lead detail;
- confirmation показывает lead ID, source и irreversible result;
- оператор должен ввести слово `УДАЛИТЬ`;
- после успешной storage transaction UI redirect выполняется на `/leads`;
- при rollback detail остаётся доступной и показывает correlation ID ошибки.

## 13. Security requirements

- server bind только на `127.0.0.1`;
- Host header допускает `127.0.0.1`, `localhost` и `[::1]`; остальные значения получают `400`;
- state-changing actions используют synchronizer CSRF token;
- session cookie: `HttpOnly`, `SameSite=Strict`, path `/`; она хранит только случайный UI session ID;
- шаблоны autoescape включены;
- external links используют `rel="noopener noreferrer"`;
- secrets, bot token, API hash и session path не рендерятся;
- stack trace не возвращается в HTML response.

## 14. Functional requirements

| ID | Требование | Приоритет | Acceptance criteria |
|---|---|---:|---|
| UI-001 | UI доступен только на loopback `127.0.0.1:8765` | MUST | Remote interface не принимает connection |
| UI-002 | Основной язык интерфейса русский | MUST | Pages, forms, errors и statuses имеют русские labels |
| UI-003 | Inbox сортируется по freshness по умолчанию | MUST | Новые сообщения отображаются первыми |
| UI-004 | Filters комбинируются через AND | MUST | Результат соответствует всем выбранным filters |
| UI-005 | Pagination обрабатывает 50 rows | MUST | Между pages нет пропусков и повторов |
| UI-006 | Detail полностью объясняет score | MUST | Видны rules, components, penalties и version |
| UI-007 | Status history append-only | MUST | Старые transitions остаются видимыми |
| UI-008 | Stale form не перезаписывает данные | MUST | Возвращается 409 без write |
| UI-009 | Source approval является явным action | MUST | Просмотр candidate не включает monitoring |
| UI-010 | Rule activation доступна только valid version | MUST | Invalid version не становится active |
| UI-011 | Health показывает runtime state | MUST | Видны collector, jobs, outbox и DB status |
| UI-012 | CSV создаётся только после preview/confirmation | MUST | Прямой GET не создаёт файл |
| UI-013 | Manual delete требует ввода подтверждения | MUST | Неверное значение блокирует POST |
| UI-014 | User content HTML-escaped | MUST | HTML/script отображается как текст |
| UI-015 | UI обновляет Inbox каждые 5 секунд | MUST | Новый committed lead появляется без reload не позднее 10 секунд |
| UI-016 | Automatic outreach отсутствует | MUST | В UI нет send-to-author action |
| UI-017 | Keyword discovery surface доступен по `/discovery` | MUST | Profiles/runs/results routes работают; nav label «Разведка источников» |
| UI-018 | Discovery UI соблюдает Zero Stars и CSRF | MUST | Текст `0 Stars` виден; paid controls отсутствуют; POST без CSRF отклонён; promote/cancel используют optimistic version и `303` |
| UI-019 | Reconsider dismiss-suppress UI with confirmation | MUST | Action requires CSRF + confirmation; calls `ReconsiderDismissSuppress`; distinct from `ReconsiderSource` |
| UI-020 | Run detail shows funnel counters | MUST | Displays acquired/canonicalized/suppressed/qualified/presented/novel, `pool_exhausted`, reason, `novelty_ratio` |
| UI-021 | Discovery default band filter `promising,review` | MUST | **Superseded for keyword scouting run page by UI-025 (D-068).** Historical default for non-truth views may keep promising+review. |
| UI-022 | Source/opportunity card fields | MUST | Card shows identity, aliases, provenance, evidence, score components, eligibility reason codes |
| UI-023 | Lifecycle actions including reconsider-suppress | MUST | Opportunity: promote / dismiss / `ReconsiderDismissSuppress`; source: approve/reject/reconsider/pause/resume/disable; no auto-approve, send-to-author, or Stars controls |
| UI-024 | Monitoring coverage page signals | MUST | Checkpoint/backlog/errors visible for up to `100` monitoring sources |
| UI-025 | Keyword run truth UI (D-070) | MUST | Run page defaults to all truth buckets: качественные / почти / недоказанные / отклонённые; shows `gate_status` and real counters (`quality_sources/1`, countable requests/authors, scanned/run cap, current source, flood wait until); MUST NOT hide weak/non-quality by default |
| UI-026 | Open in Telegram + manual monitoring (D-068) | MUST | Opportunity detail: «Открыть в Telegram» (public_url/permalink); promote→candidate then existing Sources approve→monitoring path (CSRF + optimistic version); no direct SQL; no outreach |
| UI-027 | ActiveClientChat v1 evidence and explanation (D-070) | MUST | Result card/detail show six frozen counters, latest client request, qualification version, ordered reasons, truth/score/band and Telegram links; historical rows show `legacy`; raw/pseudonymous author identity is never rendered |

## 15. Observability

Обязательные metrics:

- HTTP request count/duration/status;
- template render errors;
- HTMX fragment refresh duration;
- Inbox query duration и row count;
- operator actions по type/outcome;
- export rows/files/duration;
- CSRF и optimistic conflict count.

Logs содержат route template, method, status, duration, correlation ID и internal entity ID. Query text, message text, contact values и secrets не логируются.

## 16. Dependencies

- backend: FastAPI, Uvicorn, Jinja2, HTMX, CSS;
- upstream services: Discovery, Collector, Detection, Scoring, Storage, Settings, Observability;
- security boundary: Security module;
- deployment: single local process.

## 17. Acceptance test catalogue

| Test ID | Проверка | Ожидаемый результат |
|---|---|---|
| AT-UI-001 | Connection через non-loopback interface | Connection недоступен |
| AT-UI-002 | Открыты основные pages и validation errors | Labels отображаются на русском |
| AT-UI-003 | Inbox содержит leads с разным published_at | Новейшие отображаются первыми |
| AT-UI-004 | Одновременно выбраны band/source/status filters | Возвращается intersection |
| AT-UI-005 | Inbox содержит 51 lead | 50 на первой page, один на второй, без дублей |
| AT-UI-006 | Lead имеет penalties и matched rules | Detail показывает полный breakdown и version |
| AT-UI-007 | Status меняется дважды | Обе history rows сохранены и видны |
| AT-UI-008 | Две формы меняют один status | Вторая получает 409 без write |
| AT-UI-009 | Candidate только открыт | Monitoring не запускается без approve POST |
| AT-UI-010 | Активируется invalid rule version | Action отклонён |
| AT-UI-011 | Открыта Health page | Видны collector, jobs, outbox и DB status |
| AT-UI-012 | Выполнен прямой GET export route | Файл не создан до preview и confirmation |
| AT-UI-013 | Manual delete отправлен с неверным confirm text | Данные не изменены |
| AT-UI-014 | Script находится в message text | Script отображается как текст и не исполняется |
| AT-UI-015 | Новый committed lead | Inbox fragment показывает его не позднее 10 секунд |
| AT-UI-016 | Просмотрены все lead actions | Send-to-author action отсутствует |
| AT-UI-017 | Открыт `/discovery`, создан profile, запущен run | Страницы и fragments отображают run/results на русском |
| AT-UI-018 | POST discovery без CSRF; UI без Stars controls | State не изменён; `0 Stars` текст присутствует; paid input отсутствует |
| AT-UI-019 | Reconsider dismiss-suppress with/without confirmation | Without confirmation blocked; with CSRF+confirm membership removed |
| AT-UI-020 | Completed keyword run detail | Funnel counters, pool_exhausted, novelty_ratio visible |
| AT-UI-021 | Open discovery results without changing filter | Historical promising+review default where UI-025 not applicable |
| AT-UI-022 | Opportunity card for verified and directory-only | Identity/aliases/provenance/evidence/components/reasons present |
| AT-UI-023 | Lifecycle action matrix on opportunity and source | Promote/dismiss/reconsider-suppress and source lifecycle actions present; no send-to-author/Stars |
| AT-UI-024 | Monitoring coverage with ≤100 sources | Checkpoint/backlog/error signals rendered per source |
| AT-UI-025 | Keyword run page default | All truth buckets visible; gate pass/fail and counters shown |
| AT-UI-026 | Opportunity detail actions | Open-in-Telegram link present; promote + Sources monitoring handoff with CSRF |
| AT-UI-027 | ActiveClientChat v1 and legacy fixtures | Exact counters/latest/version/reasons/links rendered; stable truth-score sort; no author key/ID/name/username in HTML |

## 18. DEFERRED

- remote access;
- multi-user/RBAC;
- SPA и mobile application;
- saved filter presets;
- charts и аналитические отчёты;
- public API.
