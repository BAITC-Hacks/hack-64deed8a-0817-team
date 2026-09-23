"""Explain one seed-42 mock run in Russian; evaluation harness only.

Run ``python tools/explain_plan.py --write`` to print and refresh
``docs/PLAN_EXAMPLE.md``. The submission agent never imports this module.
"""

import argparse
from collections import defaultdict
from datetime import datetime
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent import Agent
from mock_environment import _mock_fallback, _mock_impact_model, make_mock_env
from scoring_core import MAX_CAMPAIGNS, sanitize_campaigns, score_campaigns


SEED = 42
OUTPUT = ROOT / "docs" / "PLAN_EXAMPLE.md"
FILTER_COLUMNS = (
    "filter_arpu_segment", "filter_data_segment", "filter_call_segment",
    "filter_current_tariff", "explicit_ids",
)
ARPU = {"LOW": "низкий", "MID": "средний", "HIGH": "высокий"}
DATA = {"NON_USER": "без мобильного интернета", "LITE": "редко используют интернет",
        "HEAVY": "активно используют интернет"}
CALL = {"LOW": "мало звонят", "MEDIUM": "умеренно звонят", "HIGH": "много звонят"}
CHANNEL = {"push": "push-уведомление", "sms": "SMS",
           "digital_ads": "цифровая реклама", "call": "звонок"}


def number(value):
    return f"{value:,.0f}".replace(",", " ")


def signal(value):
    percentage = value * 100
    return "около 0%" if abs(percentage) < 0.05 else f"{percentage:+.1f}%"


def present(value):
    return value is not None and not pd.isna(value)


def segment_description(filters):
    parts = []
    tariff = filters.get("filter_current_tariff")
    if present(tariff):
        parts.append(f"текущий тариф {tariff}")
    segment = filters.get("filter_arpu_segment")
    if present(segment):
        parts.append(f"{ARPU.get(segment, segment)} уровень ARPU")
    data = filters.get("filter_data_segment")
    if present(data):
        parts.append(DATA.get(data, str(data)))
    call = filters.get("filter_call_segment")
    if present(call):
        parts.append(CALL.get(call, str(call)))
    return ", ".join(parts) if parts else "вся доступная аудитория"


def run_once():
    """Use the same mock model, seed, campaign order and scorer as local_eval."""
    env, internals = make_mock_env(
        seed=SEED, data_dir=str(ROOT / "data"),
        profile_path=str(ROOT / "customer_profile.csv"),
    )
    agent = Agent()
    finals = sanitize_campaigns(agent.act(env), env.tariffs)[:MAX_CAMPAIGNS]
    pilots = internals.executed_pilot_campaigns()
    campaigns = pd.DataFrame(pilots + finals)
    if campaigns.empty:
        raise RuntimeError("Агент не провёл пилоты и не вернул кампании")
    for column in FILTER_COLUMNS:
        if column not in campaigns:
            campaigns[column] = None
    effects = _mock_impact_model(pd.read_csv(ROOT / "data" / "change_tariff.csv"))
    result = score_campaigns(
        campaigns, env.customer_profile, effects, env.tariffs,
        env.customer_profile["predicted_arpu"].sum(), _mock_fallback,
        team_id="plan_example",
    )
    return env, agent, pilots, finals, result


def explain_pilots(agent, env, finals):
    grouped = defaultdict(list)
    if len(agent.pilot_log) != len(env.pilot_history):
        raise RuntimeError("Журнал агента не совпал с журналом пилотов среды")
    for log, observation in zip(agent.pilot_log, env.pilot_history, strict=True):
        key = (log["current_tariff"], log["arpu_segment"], log["target_tariff"])
        grouped[key].append((log, observation))
    launched = {(c.get("filter_current_tariff"), c.get("filter_arpu_segment"),
                 c["target_tariff"]) for c in finals}

    lines = [
        "| Проверенная аудитория | Целевой тариф | Пилоты / абоненты | Что показали пилоты | Решение |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for key, trials in grouped.items():
        tariff, segment, target = key
        slices = []
        for log, _ in trials:
            description = segment_description(log.get("slice", {}))
            if description != "вся доступная аудитория" and description not in slices:
                slices.append(description)
        audience = segment_description({"filter_current_tariff": tariff,
                                        "filter_arpu_segment": segment})
        if slices:
            audience += "; пилоты: " + ", ".join(slices)
        signals = ", ".join(signal(obs["observed_lift_ratio"])
                            for _, obs in trials)
        count = sum(obs["n_customers"] for _, obs in trials)
        decision = "запущена" if key in launched else "не запущена"
        lines.append(f"| {audience} | {target} | {len(trials)} / {number(count)} | "
                     f"{signals} | {decision} |")
    return lines


def render(env, agent, pilots, finals, result):
    revision = subprocess.run(
        ["git", "log", "-1", "--format=%h", "--", "agent.py", "agent_core"], cwd=ROOT,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    timestamp = datetime.now(ZoneInfo("Asia/Almaty")).strftime("%Y-%m-%d %H:%M")
    prices = env.tariffs.set_index("tariff_plan_code")["price_tariff"].to_dict()
    total_pilot_cost = sum(p["cost"] for p in env.pilot_history)
    total_pilot_contacts = sum(p["n_customers"] for p in env.pilot_history)
    positive = sum(p["observed_lift_ratio"] > 0 for p in env.pilot_history)
    final_details = result["campaigns_detail"][len(pilots):]
    if len(final_details) != len(finals):
        raise RuntimeError("Детализация скоринга не совпала с финальными кампаниями")

    lines = [
        "# Пример плана кампаний: локальный мок, seed 42",
        "",
        f"Сформировано {timestamp} (Алматы) из кода коммита `{revision}`. "
        "Это один воспроизводимый локальный прогон, а не прогноз результата на "
        "скрытой судейской модели. Прирост ниже рассчитан скорером по мок-эффектам. "
        "ARPU — средняя выручка на абонента.",
        "",
        "## Что предложено запустить",
        "",
    ]
    if finals:
        lines += [
            "| Аудитория | Абонентов | Новый тариф | Канал | Прирост выручки, у.е. | Стоимость, у.е. |",
            "| --- | ---: | --- | --- | ---: | ---: |",
        ]
        for campaign, detail in zip(finals, final_details, strict=True):
            audience = segment_description(campaign)
            target = campaign["target_tariff"]
            price = prices.get(target)
            target_label = (f"{target} ({number(price)} у.е./мес.)"
                            if price is not None else target)
            channel = CHANNEL.get(campaign["channel"], campaign["channel"])
            lines.append(
                f"| {audience} | {number(detail['n_contacts'])} | {target_label} | "
                f"{channel} | {number(detail['gross_lift'])} | {number(detail['cost'])} |"
            )
        lines += [
            "",
            "Абоненты в таблице — фактически охваченные финальными кампаниями "
            "после лимитов. Прирост по строкам указан до учёта повторных контактов "
            "с пилотами; итог ниже учитывает каждого абонента только один раз.",
        ]
    else:
        lines.append("Финальных кампаний нет; в зачёт идут только уже проведённые пилоты.")

    lines += [
        "",
        "## Что выяснили пилоты",
        "",
        f"Проведено **{len(pilots)} пилотов** на **{number(total_pilot_contacts)} "
        f"контактов** за **{number(total_pilot_cost)} у.е.** "
        f"Положительный зашумлённый сигнал получен в {positive} из {len(pilots)} "
        "пилотов. Значения в таблице — наблюдаемый относительный прирост ARPU; "
        "один пилот сам по себе не доказывает прибыльность перехода.",
        "",
    ]
    lines.extend(explain_pilots(agent, env, finals))

    gross = result["gross_arpu_lift"]
    cost = result["total_cost"]
    net = result["net_arpu_gain"]
    roi = result["roi"]
    lines += [
        "",
        "## Общий экономический итог",
        "",
        f"Всего: **{number(result['total_contacts'])} контактов**, "
        f"**{number(result['unique_customers_targeted'])} уникальных абонентов** "
        "с учётом пересечений пилотов и финальных кампаний. "
        f"Валовой прирост выручки — **{number(gross)} у.е.**, "
        f"стоимость контактов — **{number(cost)} у.е.**, "
        f"чистый результат — **{number(net)} у.е.**",
        "",
        f"**ROI по формуле скорера: {roi:.2f}×** (валовой прирост / затраты). "
        f"Чистая отдача на затраты: {(net / cost * 100) if cost else 0:.1f}% "
        "(чистый результат / затраты).",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true",
                        help="обновить docs/PLAN_EXAMPLE.md")
    args = parser.parse_args()
    report = render(*run_once())
    print(report, end="")
    if args.write:
        OUTPUT.write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
