# Change Evidence

## 1. Назначение

Evidence фиксирует, что именно было проверено, где это было проверено и какой результат наблюдался. Формат claim задаёт [evidence-claim.schema.json](../../schemas/quality/evidence-claim.schema.json).

## 2. Evidence scopes

- `local` — команда или read-only validation выполнена в текущем workspace. Claim содержит точную проверку и локальный artifact/path либо воспроизводимое описание результата.
- `ci` — claim ссылается на завершившийся CI run и конкретный job/check. Отсутствующий, ожидающий или недоступный run получает `not_run`, но не `pass`.

Local evidence не является CI evidence и всегда считается untrusted agent-controlled claim. Сводный вывод обязан сохранять отдельные claims, даже если обе проверки относятся к одному requirement. Claim не может самостоятельно повысить verdict до `PASS`: hashes и checks должны быть пересчитаны независимой trusted boundary.

## 3. Status semantics

- `pass` — проверка выполнена и положительный результат подтверждён непустым `evidence_refs`;
- `fail` — проверка выполнена и наблюдалось несоответствие;
- `not_run` — проверка не запускалась;
- `unsupported` — текущая capability не позволяет выполнить или подтвердить проверку.

Нельзя выводить `pass` из declaration, предполагаемого runtime payload, отсутствия ошибки или результата другого scope.

## 4. Минимальная запись

Каждый claim содержит `schema_version`, `claim_id`, `conversation_id`, `task_id`, `requirement_ids`, `claim`, `trust`, `evidence_scope`, `status`, `evidence_refs`, `observed_files`, `requested_checks`, `unresolved_failures` и `recorded_at`. `base_sha`/`head_sha` записываются только при фактическом наличии Git identity; отсутствие Git не заполняется placeholder-значениями. Каждый `observed_file` содержит repository-relative path и наблюдавшийся SHA-256. References указывают только на существующие локальные artifacts или доступные CI runs; secrets и чувствительный product text запрещены.

Переходы evidence могут отражаться отдельными append-only events по [journal-event.schema.json](../../schemas/quality/journal-event.schema.json). Исправление ошибочного claim создаёт новый claim и ссылку `supersedes_claim_id`, а не переписывает историю.
