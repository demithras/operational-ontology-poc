# Open Operational Ontology — краткая навигация

Это пакет ТЗ для **фальсифицируемого локального POC**, который должен не продемонстрировать красивую ontology, а атаковать тезис ролика: может ли semantic graph стать operational infrastructure, если решение моделируется как first-class object, действия проходят формальные gates, результат проверяется по изменению внешнего мира, а историческое решение можно воспроизвести спустя изменение ontology/policy/action contracts.

## Что именно проверяем

Два итоговых вопроса:

```text
Can it decide now?              PASS / FAIL
Can we prove why later?         PASS / FAIL
```

Внутри зафиксированы 14 гипотез. Важнейшие из них:

- Decision как полноценный объект данных действительно улучшает audit/replay.
- OpenFGA + OPA + SHACL не дают запрещённому действию породить внешний side effect.
- `HTTP 200` не считается успехом: успех наступает только после независимого наблюдения изменения WMS через CDC.
- Temporal + idempotency выдерживают crash/retry/timeout без дублирования бизнес-эффекта.
- V1-решения можно корректно replay после миграции ontology/policy/action contracts до V3.
- Hot projections дают operational latency, не разрывая provenance.
- LLM не нужен для core correctness и не может обходить server-side gates.
- Operational ontology сравнивается с честным relational baseline, а не со специально слабой системой.

## Стек

Reference stack:

```text
RDF4J + SHACL + PROV-O
PostgreSQL hot projections
OpenFGA
OPA/Rego
Temporal
Debezium
Kafka
pytest + Hypothesis stateful testing
OpenTelemetry
MCP — только после deterministic acceptance
```

## Сценарий

Synthetic factory с ERP/MES/WMS. Supplier delay создаёт shortage для WorkOrder. Система должна найти mitigation, создать Decision + evidence snapshot, проверить authority/policy/conformance, выполнить `transfer_inventory`, увидеть реальный transfer через CDC, сопоставить expected/observed effect и записать Outcome.

## Как пользоваться пакетом

Начать с:

1. `README.md`
2. `00_thesis.md`
3. `01_hypotheses.md`
4. `11_acceptance_criteria.md`
5. `12_implementation_plan.md`
6. `13_repository_contract.md`

После этого архитектура и тесты подробно описаны в остальных файлах.

Технические документы намеренно написаны на английском: пакет рассчитан на прямой handoff инженеру или coding agent.
