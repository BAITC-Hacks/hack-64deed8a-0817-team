"""Final campaigns: greedy allocation of confident-positive cells under reach/money caps."""

MAX_PER_CAMPAIGN = 5000
MAX_CAMPAIGNS = 10
FINAL_K = 1.5  # final only if mean - FINAL_K * sd > 0


def _channel_options(base_mean, arpu, channels):
    """Expected net per contact on every channel for a given base effect."""
    return {ch: base_mean * c["conversion_multiplier"] * arpu - c["cost_per_contact"]
            for ch, c in channels.items()}


def _contacts(size, cost, reach_left, money_left):
    n = min(size, MAX_PER_CAMPAIGN, reach_left)
    if cost > 0:
        n = min(n, int(money_left // cost))
    return max(n, 0)


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

    def plan(self):
        channels = self.env.channels
        reach_left = self.env.max_total_contacts - sum(p["n"] for p in self.pilot_log)
        money_left = self.env.total_budget - sum(p["cost"] for p in self.pilot_log)

        options = []
        for cell, (target, mean) in self.qualifying().items():
            per_contact = _channel_options(mean, self.cells[cell]["arpu"], channels)
            best_pc = max(per_contact.values())
            if best_pc > 0:
                options.append((best_pc, cell, target, per_contact))
        options.sort(key=lambda x: x[0], reverse=True)

        campaigns = []
        for _, cell, target, per_contact in options:
            if len(campaigns) >= MAX_CAMPAIGNS or reach_left <= 0:
                break
            size = self.cells[cell]["size"]
            # channel with the best expected total net given what is left
            best = None
            for ch, pc in per_contact.items():
                if pc <= 0:
                    continue
                cost = channels[ch]["cost_per_contact"]
                n = _contacts(size, cost, reach_left, money_left)
                if n > 0 and (best is None or n * pc > best[0]):
                    best = (n * pc, ch, n, pc)
            if best is None:
                continue
            _, ch, n, pc = best
            reach_left -= n
            money_left -= n * channels[ch]["cost_per_contact"]
            campaigns.append({
                "campaign_name": f"{cell[0]}_{cell[1]}_to_{target}_{ch}",
                "filter_current_tariff": cell[0],
                "filter_arpu_segment": cell[1],
                "target_tariff": target,
                "channel": ch,
                "_per_contact": pc,
                "_contacts": n,
            })

        campaigns.sort(key=lambda c: c["_per_contact"], reverse=True)
        for c in campaigns:
            del c["_per_contact"], c["_contacts"]

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
