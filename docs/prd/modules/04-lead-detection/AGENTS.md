# Навигация: Lead Detection

Owner PRD: `PRD.md`  
Requirement prefix: `DET`  
Primary responsibility: immutable versioned rule engine, категория сообщения, service profiles и объяснимые signals.

## Read first

1. `../../README.md`
2. `../../shared/DOMAIN_MODEL.md`
3. `../../shared/INTEGRATION_CONTRACTS.md`
4. `../03-message-processing/PRD.md`
5. `PRD.md`, включая нормативное приложение `DET-A`
6. `../05-lead-scoring/PRD.md`

## Границы модуля

- Owned entities: `RuleSetVersion`, `ServiceProfile`, `KeywordGroup`, `MonitoringRule`, `DetectionResult`, `MatchedRule`.
- Consumed contracts: `MessageReadyForDetection` с `analysis_text` и revision identity.
- Published contracts: `LeadDetected`, `MessageExcluded`, `DetectionCompleted`, `DetectionRuleTimedOut`.
- Upstream modules: `03-message-processing`, `06-lead-storage`, `09-operator-settings`.
- Downstream modules: `05-lead-scoring`, `07-lead-dashboard`, `10-administration-observability`.
- Required acceptance suites: `AT-DET-*` и golden corpus `DET-A` из `PRD.md`.

## Out of scope

- AI/LLM и embedding-классификация.
- Score weights и score bands.
- Редактирование активной rule-set version.
- Выполнение regex без timeout.

## Change checklist

1. Любое изменение правила создаёт новую immutable version.
2. Обновить нормативное приложение `DET-A` и golden corpus вместе.
3. Проверить hard-exclusion и positive precedence.
4. Обновить shared contracts и `../../TRACEABILITY.md`.
5. Не помещать score weights в Detection.
