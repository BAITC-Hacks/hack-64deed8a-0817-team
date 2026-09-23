"""Final campaigns: greedy allocation of confident-positive cells under reach/money caps."""

from itertools import product

MAX_PER_CAMPAIGN = 5000
MAX_CAMPAIGNS = 10
FINAL_K = 1.5  # final only if mean - FINAL_K * sd > 0


# Sub-segment splits (("data_segment", "call_segment")) are off: on stress_eval they
# amplified a false positive (39/50 positive vs 40/50 without, same worst case).
SPLIT_COLUMNS = ()


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
        for cell, target in self._tested():
            mean, sd = self.post.get(cell, target)
            if not self.post.confirmed_enough(cell, target) or mean - FINAL_K * sd <= 0:
                continue
            if cell not in best or mean > best[cell][1]:
                best[cell] = (target, mean)
        return best

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
        reach_left = self.env.max_total_contacts - sum(p["n"] for p in self.pilot_log)
        money_left = self.env.total_budget - sum(p["cost"] for p in self.pilot_log)

        options = []
        for cell, (target, mean) in self.qualifying().items():
            per_contact = _channel_options(mean, self.cells[cell]["arpu"], channels)
            best_pc = max(per_contact.values())
            if best_pc > 0:
                options.append((best_pc, cell, target, mean))
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

    def _fallback(self):
        """Nothing is confident: one small push campaign on the best-posterior cell."""
        tested = self._tested()
        if tested:
            cell, target = max(tested, key=lambda ct: self.post.get(*ct)[0])
        else:
            cell = max(self.cells, key=lambda c: self.cells[c]["size"])
            targets = [t for t in self.env.tariffs["tariff_plan_code"] if t != cell[0]]
            target = targets[0]
        profile = self.env.customer_profile
        sub = profile[(profile["current_tariff"] == cell[0])
                      & (profile["arpu_segment"] == cell[1])]
        smallest = sub["data_segment"].value_counts().idxmin() if len(sub) else None
        return {
            "campaign_name": f"fallback_{cell[0]}_{cell[1]}_to_{target}_push",
            "filter_current_tariff": cell[0],
            "filter_arpu_segment": cell[1],
            "filter_data_segment": smallest,
            "target_tariff": target,
            "channel": "push",
        }
