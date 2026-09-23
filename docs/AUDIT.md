# Compliance-аудит

Дата: 23.09.2026. Проверено на: fresh clone в `/tmp/audit-clone-64deed8a` +
рабочая копия `~/hack-64deed8a-0817-team` (HEAD `aca319c`, "Agent v2 steps
1-2: confirmation gate, per-cell diversification, history priors").
Python 3.11.14, pandas 3.0.6, numpy 2.4.6, pytest 9.1.1.

## Итог: 1 находка требует решения капитана, остальное чисто

| # | Проверка | Статус |
|---|---|---|
| 1 | Запрещённые паттерны (MECHANICS.md §7) | ✅ чисто |
| 2 | Воспроизводимость с fresh clone | ⚠️ **submission.csv не совпадает** |
| 3 | Runtime + 5 must-have | ✅ все 5 выполняются |
| 4 | Гигиена (pycache/.pyc, секреты, авторы) | ✅ чисто |
| 5 | Устаревшие утверждения в README | ✅ исправлено (docs) |

---

## 1. Запрещённые паттерны

```bash
grep -rnE "__closure__|cell_contents|gc\.|inspect\.|__globals__|__code__|sys\._getframe|ctypes|_Internals|internals|executed_pilot_campaigns|_rng|_model\b|import (mock_environment|environment|scoring_core)|from (mock_environment|environment|scoring_core)" agent.py agent_core/
```
**0 совпадений.** `agent.py` и весь `agent_core/` не обращаются к внутренностям
среды/скоринга и не импортируют `environment`/`mock_environment`/`scoring_core`.

Единственное чтение файла организаторов вне `env` — `agent_core/priors_history.py`
читает `data/change_tariff.csv`. Это **разрешено явно**: MECHANICS.md §6 называет
именно этот файл рекомендованным источником априоров ("шаблон... рекомендует
`data/change_tariff.csv` для приоров"). Не нарушение.

## 2. Воспроизводимость (fresh clone → README буквально → make_submission.py ×2)

```bash
git clone https://github.com/BAITC-Hacks/hack-64deed8a-0817-team.git /tmp/audit-clone-64deed8a
cd /tmp/audit-clone-64deed8a
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt        # OK, без ошибок
python local_eval.py                   # OK, PASS
python -m pytest tests/ -v             # OK, 15/15
python make_submission.py              # run 1
python make_submission.py              # run 2
```

- Установка и `local_eval.py` по README (раздел 5, 6, 8) отрабатывают буквально
  командами из файла, без правок. ✅
- `make_submission.py` запуск 1 == запуск 2 (побайтово идентичны) — сам по себе
  воспроизводим при фиксированном `SUBMISSION_SEED=42`. ✅
- **Но закоммиченный `submission.csv` НЕ совпадает с тем, что выдаёт
  `make_submission.py` сейчас:**
  ```diff
  - tariff_8_HIGH_to_tariff_10_digital_ads,HIGH,,,tariff_8,tariff_10,digital_ads
  + tariff_8_MID_to_tariff_10_digital_ads,MID,,,tariff_8,tariff_10,digital_ads
  ```
  Это нарушает must-have #5 из `PARTICIPANT_GUIDE.md` ("файл есть и
  воспроизводится нашим запуском") **прямо сейчас, если сдавать как есть**.

**Причина (структурная, не баг воспроизводимости):** `submission.csv` был
собран коммитом `6b871bb` под тогдашним `agent.py` (v1, weak prior). С тех пор
`agent.py` дважды менялся (`7dd08a6` agent_core, `ee1ce29` history prior,
`aca319c` v2 — confirmation gate/диверсификация/history priors), а
`make_submission.py` после этого никто не перезапускал и файл не
перекоммитил — `docs/RUN.md` прямо просит это делать перед каждой сдачей, но
шаг был пропущен.

**→ Капитану:** нужно решить и сделать самому (не тривиальная docs-правка,
касается общего для команды артефакта):
1. Запустить `python make_submission.py` на финальной версии `agent.py` перед
   сдачей и закоммитить обновлённый `submission.csv` последним шагом.
2. До тех пор каждый пуш в `agent.py`/`agent_core/` без пересборки
   `submission.csv` будет держать репозиторий в этом несоответствии — стоит
   либо делать это частью чек-листа перед каждым пушем агента, либо (если
   останется время) добавить это как шаг в `tests/` или pre-push напоминание.

## 3. Runtime и 5 must-have (PARTICIPANT_GUIDE.md §7)

Все измерения — fresh clone, `time <команда>`:

| Команда | Runtime |
|---|---|
| `python local_eval.py` (1 прогон) | 0.60 с |
| `python local_eval.py --runs 10` | 3.44 с (≈0.34 с/прогон) |
| `python -m pytest tests/ -v` (15 тестов) | 1.46 с |
| `python make_submission.py` | 0.50 с |

Все далеко в пределах лимита 5 мин (docs/MECHANICS.md §7) и 10 мин (гайд).

| Must-have | Проверка | Результат |
|---|---|---|
| 1. `agent.py`/`Agent.act` работает без ошибок | `local_eval.py` отработал, `Статус: PASS` | ✅ |
| 2. От 1 до 10 корректных кампаний | 1 финальная кампания (`tariff_8_MID_to_tariff_10_digital_ads`), 0 строк «отброшена» | ✅ |
| 3. Агент использует пилоты, решения от них | `Пилотов проведено: 20 из 20`; `explorer.py`/`planner.py` работают через `Posterior`, обновляемый только из `env.run_pilot` (см. §1 — нет обходных путей к модели) | ✅ |
| 4. В пределах лимитов бюджета/охвата/пилотов | `remaining_budget=86,000` (≤100,000, ≥0), `remaining_contacts=11,500` (≤15,000, ≥0), 20/20 пилотов использовано, `pilots_left=0` | ✅ |
| 5. `submission.csv` воспроизводится | Команда воспроизводима сама с собой, но **закоммиченный файл устарел** — см. §2 | ⚠️ |

`tests/test_limits.py` (seeds 1–5) и `tests/test_priors.py` — все 15 тестов
зелёные, независимо подтверждают пункты 1–4.

## 4. Гигиена

- **Трекнутые pycache/.pyc:** `git ls-files | grep -E "__pycache__|\.pyc$"` →
  пусто. `.gitignore` содержит `__pycache__/`, `*.pyc`, `.venv/`,
  `.pytest_cache/`. Локальная копия: `git status --ignored` показывает
  `.venv/`, `__pycache__/` (везде), `.pytest_cache/` как `!!` (игнорируются,
  не трекнуты). ✅
- **Секреты:** grep по `api[_-]?key=`, `secret=`, `password=`, `sk-...`,
  AWS-ключам, приватным ключам по всем трекнутым файлам (кроме `*.csv`) —
  0 совпадений. `.env` не трекнут (и не существует). ✅
- **"Мёртвые" файлы:** не найдено — `agent_template.py` оставлен намеренно
  (README §2, сверка с шаблоном организаторов), `agent_core/priors.py`
  (weak-prior по умолчанию) активно используется как pluggable-интерфейс,
  который `priors_history.py` подключает через `set_prior_source` —
  не дублирование, а слой абстракции. Закомментированных блоков кода не
  найдено. ✅
- **Авторы git log ↔ GitHub-аккаунты** (`gh api repos/.../commits`):

  | Коммит | Автор (git) | GitHub login |
  |---|---|---|
  | `aca319c`, `7dd08a6`, `400447a` | Beka Raissov | `raissov01` |
  | `c1f40f1`, `bdba646`, `6b871bb` | Ernur | `Nurzhgtuly` |
  | `ee1ce29` | razhaksyg | `ramazanzhaksygul-bit` |
  | `9f8f952` | decentra-hackathon[bot] | `decentra-hackathon[bot]` (шаблон репо, не участник) |

  Все три участника команды резолвятся в реальные GitHub-аккаунты, ни одного
  "unknown author". ✅

## 5. Устаревшие утверждения в README — все найденные уже исправлены (docs, тривиально)

1. §2 «Архитектура»: список файлов и диаграмма не включали
   `agent_core/priors_history.py` и `docs/PRIORS.md` (появились в
   `ee1ce29`, после того как я писал README в `c1f40f1`) — **исправлено**,
   добавлены в список и диаграмму.
2. §8 «Пример реального вывода»: `net 60,265`, было снято на `agent.py` v1
   (коммит `6b871bb`). Текущий `agent.py` v2 (`aca319c`) на том же seed 42
   даёт `net 676,992` — **исправлено**, пример обновлён с пометкой версии
   агента.
3. §9 «Ограничения»: «≈3 из 10 прогонов в плюс» — было верно для v1, на v2
   сейчас **10 из 10 в плюс** (медиана ≈575k, минимум ≈60k) — **исправлено**,
   заодно это хорошая новость, стоит показать на защите.
4. §9: отсутствовало упоминание проблемы с `submission.csv` из §2 этого
   отчёта — **добавлено** как известное ограничение со ссылкой на этот файл
   (сам файл не трогал — не тривиальная правка, см. §2 выше).
5. `docs/RUN.md`: раздел «Тесты» указывал только `tests/test_limits.py`,
   без `tests/test_priors.py` (появился в `ee1ce29`) — **исправлено**,
   команда `pytest tests/ -v`. Раздел «Известное поведение агента» содержал
   ту же устаревшую статистику по знаку (см. п.3 выше) — **исправлено**.

Ничего в README/`docs/RUN.md`, кроме перечисленного выше, устаревшим не
найдено (секции 1, 3–7, 10, 11 сверены построчно с текущим кодом — актуальны).
