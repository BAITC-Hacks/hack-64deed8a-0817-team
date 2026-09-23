# Запуск

Проверено 23.09.2026: pandas 3.0.6, numpy 2.4.6, pytest 9.1.1. Разработка: Python 3.12.3
(Linux); чистая проверка: Python 3.13.9 (macOS arm64, docs/JUDGE_CHECK.md).
Все команды — из корня репозитория.

## Установка

```bash
python3 -m venv .venv
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
python -m pytest tests/ -v   # 31 тест: лимиты, приоры, без истории, hardening, LLM-гардрейлы, актуальность сборки
```

## Сборка submission.csv

```bash
python make_submission.py
```
Перезаписывает `submission.csv` результатом текущего `agent.py` на мок-среде с
`SUBMISSION_SEED=42`. Запускать перед каждой сдачей, чтобы файл совпадал с кодом.

## Известное поведение агента (не баг)

На замороженном коде `f11ae2d` (policy v4): `local_eval.py` на seed 42 даёт
3 170 330 (20 пилотов, 10 финальных кампаний); `local_eval.py --runs 10` — 10 из 10
прогонов в плюс (медиана 3 541 278, минимум 1 759 226); `tools/stress_eval.py` —
60 из 60 в плюс, худший прогон +604 754 (docs/ROBUSTNESS.md, docs/BENCHMARK.md). Механика (лимиты/бюджет/дедуп) отрабатывает идентично
судейству, но сами эффекты в мок-среде — заглушка (docs/MECHANICS.md,
раздел 5), поэтому конкретные числа здесь ничего не говорят о результате на
судействе — смотреть на устойчивость знака, а не на величину.
