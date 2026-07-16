# LLM Quality Recovery

## 1. Trigger

Recovery обязателен при scope violation, неподтверждённом claim, использовании недоступной capability, смешении local/CI evidence или конфликте с product hard invariant.

## 2. Порядок восстановления

1. Немедленно остановить затронутую mutation и не расширять scope.
2. Сохранить наблюдаемые факты как `fail`, `not_run` или `unsupported`; не создавать искусственный `pass`.
3. Определить последний подтверждённый compliant state без Git rollback и без изменения user-level configuration.
4. Классифицировать нарушение: `scope`, `capability`, `evidence`, `precedence` или `product_boundary`.
5. Составить минимальный recovery proposal с affected paths, сохранёнными пользовательскими изменениями и проверками.
6. Получить решение единственного локального оператора / владельца репозитория, если продолжение требует нового scope или exception.
7. Выполнить только одобренные corrective actions и повторить релевантные local checks.
8. Создать новые evidence claims и append-only recovery events; исходные записи не переписывать.

## 3. Stop conditions

Работа остаётся остановленной, если product invariant требует нарушения, отсутствует необходимое approval, нельзя отделить пользовательские изменения или capability остаётся неподтверждённой.

Recovery contract не разрешает Git/hosting operations, user-level configuration, product code или AI/LLM в product runtime. Для каждого такого действия требуется отдельный authorization, а product hard invariant не может быть отменён.

## 4. Independent gate rollback

Отключение одного gate не отключает остальные и не удаляет journal/evidence. Для `policy`, `journal`, `checkpoint`, `validator` и будущего `ci` фиксируются отдельные state и recovery event. Global fail-open запрещён.

Out-of-band восстановление project hooks выполняет только оператор явным запуском `tools/quality/recover-hooks.ps1` с known-good backup и ожидаемым SHA-256. Скрипт не зависит от Node, не запускается hooks автоматически и не изменяет user-level config. Несовпадение checksum или malformed backup завершает восстановление до замены `.cursor/hooks.json`.
