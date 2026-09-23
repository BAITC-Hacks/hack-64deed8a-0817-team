# Запуск

Проверено на этой машине 23.09.2026: Python 3.11.14, pandas 3.0.6, numpy 2.4.6.
Все команды — из корня репозитория.

## Установка

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Проверка агента на мок-среде

```bash
python local_eval.py              # один прогон, seed 42
python local_eval.py --runs 10    # 10 прогонов с разными seed — смотреть на устойчивость знака
```

## Тесты

```bash
python -m pytest tests/ -v   # все тесты, в т.ч. tests/test_priors.py
```

## Сборка submission.csv

```bash
python make_submission.py
```
Перезаписывает `submission.csv` результатом текущего `agent.py` на мок-среде с
`SUBMISSION_SEED=42`. Запускать перед каждой сдачей, чтобы файл совпадал с кодом.

## Известное поведение агента (не баг)

Обновлено 23.09.2026 после аудита (docs/AUDIT.md) на текущей версии `agent.py`
(v2: confirmation gate, per-cell diversification, history priors):
`local_eval.py --runs 10` даёт 10 из 10 прогонов в плюс (медиана ≈575k,
минимум ≈60k). Механика (лимиты/бюджет/дедуп) отрабатывает идентично
судейству, но сами эффекты в мок-среде — заглушка (docs/MECHANICS.md,
раздел 5), поэтому конкретные числа здесь ничего не говорят о результате на
судействе — смотреть на устойчивость знака, а не на величину.
