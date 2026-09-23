"""Final campaigns: greedy allocation of confident-positive cells under reach/money caps."""

from itertools import product

MAX_PER_CAMPAIGN = 5000
MAX_CAMPAIGNS = 10
FINAL_K = 1.5  # final only if mean - FINAL_K * sd > 0


# Sub-segment splits (("data_segment", "call_segment")) are off: on stress_eval they
# amplified a false positive (39/50 positive vs 40/50 without, same worst case).
SPLIT_COLUMNS = ()

# Legal filter values of the scorer (scoring_core.FILTER_VALUES), for schema-valid
# campaigns that deliberately match nobody.
SEGMENT_VALUES = {
    "filter_arpu_segment": ("LOW", "MID", "HIGH"),
    "filter_data_segment": ("NON_USER", "LITE", "HEAVY"),
    "filter_call_segment": ("LOW", "MEDIUM", "HIGH"),
}


def _other_tariff(tariffs, tariff):
    return next((t for t in tariffs if t != tariff), tariffs[0])


def zero_customer_campaign(env):
    """Schema-valid push campaign whose legal filters match no customer; None if impossible."""
    profile = env.customer_profile
    tariffs = list(env.tariffs["tariff_plan_code"])
    keys = ["current_tariff", "arpu_segment", "data_segment", "call_segment"]
    counts = profile.groupby(keys, observed=True).size() if len(profile) else None
    for tariff in tariffs:
        for arpu in SEGMENT_VALUES["filter_arpu_segment"]:
            for data in SEGMENT_VALUES["filter_data_segment"]:
                for call in SEGMENT_VALUES["filter_call_segment"]:
                    if counts is None or counts.get((tariff, arpu, data, call), 0) == 0:
                        return {
                            "campaign_name": "no_contact_fallback",
                            "filter_current_tariff": tariff,
                            "filter_arpu_segment": arpu,
                            "filter_data_segment": data,
                            "filter_call_segment": call,
                            "target_tariff": _other_tariff(tariffs, tariff),
                            "channel": "push",
                        }
    return None


def safety_campaign(env):
    """One valid campaign that costs nothing: matches nobody if possible, else the
    globally smallest slice on push. Never raises."""
    try:
        campaign = zero_customer_campaign(env)
        if campaign is not None:
            return campaign
    except Exception:  # noqa: BLE001 - keep falling back
        pass
    tariffs = list(env.tariffs["tariff_plan_code"])
    try:
        profile = env.customer_profile
        keys = ["current_tariff", "arpu_segment", "data_segment", "call_segment"]
        tariff, arpu, data, call = profile.groupby(keys, observed=True).size().idxmin()
        return {
            "campaign_name": "smallest_slice_fallback",
            "filter_current_tariff": tariff, "filter_arpu_segment": arpu,
            "filter_data_segment": data, "filter_call_segment": call,
            "target_tariff": _other_tariff(tariffs, tariff), "channel": "push",
        }
    except Exception:  # noqa: BLE001
        return {"campaign_name": "safety_net", "filter_arpu_segment": "LOW",
                "filter_data_segment": "NON_USER", "filter_call_segment": "HIGH",
                "target_tariff": tariffs[0], "channel": "push"}


def _channel_options(base_mean, arpu, channels):
    """Expected net per contact on every channel for a given base effect."""
    return {ch: base_mean * c["conversion_multiplier"] * arpu - c["cost_per_contact"]
            for ch, c in channels.items()}


def _contacts(size, cost, reach_left, money_left):
    n = min(size, MAX_PER_CAMPAIGN, reach_left)
    if cost > 0:
        n = min(n, int(money_left // cost))
    return max(n, 0)


def _best_assignment(parts, base_mean, channels, reach_left, money_left):
    """Pick a channel (or none) for every disjoint part; maximise expected total net.

    parts: [(filters, arpu_cumsum)] with ARPU sorted by ID_NUMBER, because scoring
    truncates each campaign to its lowest IDs. Parts are allocated in the order of
    their net per contact, which is also the order they are returned in.
    """
    best = (0.0, [])
    for choice in product([None] + list(channels), repeat=len(parts)):
        reach, money = reach_left, money_left
        picked = []
        for (filters, cums), ch in zip(parts, choice):
            if ch is None:
                continue
            c = channels[ch]
            pc = base_mean * c["conversion_multiplier"] * cums[-1] / len(cums) - c["cost_per_contact"]
            picked.append((pc, filters, cums, ch))
        picked.sort(key=lambda x: x[0], reverse=True)
        total, plan = 0.0, []
        for _, filters, cums, ch in picked:
            cost = channels[ch]["cost_per_contact"]
            n = _contacts(len(cums), cost, reach, money)
            if n <= 0:
                continue
            net = base_mean * channels[ch]["conversion_multiplier"] * cums[n - 1] - n * cost
            if net <= 0:
                continue
            reach -= n
            money -= n * cost
            total += net
            plan.append((filters, ch, n, net))
        if total > best[0]:
            best = (total, plan)
    return best


class Planner:
    def __init__(self, env, cells, posterior, pilot_log):
        self.env = env
        self.cells = cells
        self.post = posterior
        self.pilot_log = pilot_log

    def _tested(self):
        return {((p["current_tariff"], p["arpu_segment"]), p["target_tariff"])
                for p in self.pilot_log}

    def qualifying(self):
        """Per cell: the confirmed target with LCB > 0 and the highest posterior mean."""
        best = {}
        for cell, target in sorted(self._tested()):
            mean, sd = self.post.get(cell, target)
            if not self.post.confirmed_enough(cell, target) or mean - FINAL_K * sd <= 0:
                continue
            if cell not in best or mean > best[cell][1]:
                best[cell] = (target, mean)
        return best

    def _rank_value(self, cell, mean, best_pc):
        """Allocation order of qualifying cells: best expected net per contact."""
        return best_pc

    def _parts(self, cell, column):
        """Disjoint sub-segments of a cell ([whole cell] when column is None)."""
        profile = self.env.customer_profile
        sub = profile[(profile["current_tariff"] == cell[0])
                      & (profile["arpu_segment"] == cell[1])].sort_values("ID_NUMBER")
        groups = [({}, sub)] if column is None else [
            ({f"filter_{column}": value}, g) for value, g in sub.groupby(column, observed=True)]
        return [(filters, g["predicted_arpu"].cumsum().to_numpy())
                for filters, g in groups if len(g)]

    def plan(self):
        channels = self.env.channels
        # public counters already include every pilot, also ones run before this act()
        reach_left, money_left = self.env.remaining_contacts, self.env.remaining_budget

        options = []
        for cell, (target, mean) in sorted(self.qualifying().items()):
            per_contact = _channel_options(mean, self.cells[cell]["arpu"], channels)
            best_pc = max(per_contact.values())
            if best_pc > 0:
                options.append((self._rank_value(cell, mean, best_pc), cell, target, mean))
        options.sort(key=lambda x: x[0], reverse=True)

        campaigns = []
        for _, cell, target, mean in options:
            if len(campaigns) >= MAX_CAMPAIGNS or reach_left <= 0:
                break
            # whole cell vs disjoint splits; a split wins only if expected total net improves
            best = (0.0, [])
            for column in (None,) + SPLIT_COLUMNS:
                parts = self._parts(cell, column)
                if len(campaigns) + len(parts) > MAX_CAMPAIGNS:
                    continue
                cand = _best_assignment(parts, mean, channels, reach_left, money_left)
                if cand[0] > best[0]:
                    best = cand
            for filters, ch, n, _ in best[1]:
                reach_left -= n
                money_left -= n * channels[ch]["cost_per_contact"]
                suffix = "_".join(str(v) for v in filters.values())
                campaigns.append({
                    "campaign_name": "_".join(x for x in (cell[0], cell[1], suffix, "to", target, ch) if x),
                    "filter_current_tariff": cell[0],
                    "filter_arpu_segment": cell[1],
                    **filters,
                    "target_tariff": target,
                    "channel": ch,
                })

        if not campaigns:
            campaigns = [self._fallback()]
        return campaigns

    def _smallest_slice(self, cell):
        """Smallest (data_segment, call_segment) slice of a cell: filters and its ARPU sum."""
        profile = self.env.customer_profile
        sub = profile[(profile["current_tariff"] == cell[0])
                      & (profile["arpu_segment"] == cell[1])]
        if not len(sub):
            return {}, 0.0
        g = sub.groupby(["data_segment", "call_segment"], observed=True)["predicted_arpu"]
        sizes = g.size()
        data, call = sizes.idxmin()
        return ({"filter_data_segment": data, "filter_call_segment": call},
                float(g.sum()[(data, call)]))

    def _fallback(self):
        """Nothing passed the gate. Best posterior mean > 0: push on the smallest slice of
        that arm's cell. Otherwise (or nothing tested / empty audience): a schema-valid
        campaign that contacts nobody, so the mandatory campaign costs nothing."""
        tested = sorted(self._tested())
        if not self.cells or not tested:
            return safety_campaign(self.env)
        cell, target = max(tested, key=lambda ct: self.post.get(*ct)[0])
        if self.post.get(cell, target)[0] <= 0:
            return safety_campaign(self.env)
        filters, _ = self._smallest_slice(cell)
        return {
            "campaign_name": f"fallback_{cell[0]}_{cell[1]}_to_{target}_push",
            "filter_current_tariff": cell[0],
            "filter_arpu_segment": cell[1],
            **filters,
            "target_tariff": target,
            "channel": "push",
        }
