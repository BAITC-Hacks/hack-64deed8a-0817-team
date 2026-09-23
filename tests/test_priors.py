import math
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent_core import priors, priors_history as ph  # noqa: E402
from agent_core.bayes import Posterior  # noqa: E402

HEADER = "TIME_KEY,AVG_ARPU_PREV_3M,AVG_ARPU_NEXT_3M,ID_NUMBER,tariff_plan_code_from,tariff_plan_code_to\n"


def write_csv(rows):
    f = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False)
    f.write(HEADER)
    for i, (prev, nxt, frm, to) in enumerate(rows):
        f.write(f"2026-10-01,{prev},{nxt},{i},{frm},{to}\n")
    f.close()
    return f.name


class TestSegment(unittest.TestCase):
    def test_thresholds(self):
        self.assertEqual(ph.arpu_segment(999.99), "LOW")
        self.assertEqual(ph.arpu_segment(1000), "MID")
        self.assertEqual(ph.arpu_segment(5000), "MID")
        self.assertEqual(ph.arpu_segment(5000.01), "HIGH")


class TestLoadTable(unittest.TestCase):
    def test_missing_file_gives_empty(self):
        self.assertEqual(ph.load_table(ROOT / "no_such_file.csv"), {})

    def test_wrong_columns_gives_empty(self):
        f = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False)
        f.write("a,b\n1,2\n")
        f.close()
        self.assertEqual(ph.load_table(f.name), {})

    def test_stats(self):
        path = write_csv([
            (2000, 2200, "t_a", "t_b"),   # MID, +0.10
            (2000, 2600, "t_a", "t_b"),   # MID, +0.30
            (2000, 1000, "t_a", "t_c"),   # MID, -0.50
            (6000, 6000, "t_a", "t_b"),   # HIGH, 0.0
            (10, 5000, "t_a", "t_b"),     # dropped: prev ARPU below MIN_PREV_ARPU
            (100, 5000, "t_a", "t_c"),    # LOW, +49 -> clipped to PCT_CAP
        ])
        t = ph.load_table(path)
        n_targets = 2
        s = t[("t_a", "MID", "t_b")]
        self.assertEqual(s["n"], 2)
        self.assertAlmostEqual(s["mean"], 0.2)
        self.assertAlmostEqual(s["std"], math.sqrt(0.02))
        self.assertAlmostEqual(s["conv"], (2 + 1) / (3 + n_targets))
        self.assertAlmostEqual(t[("t_a", "MID", "t_c")]["conv"], (1 + 1) / (3 + n_targets))
        self.assertEqual(t[("t_a", "HIGH", "t_b")]["std"], 0.0)
        self.assertAlmostEqual(t[("t_a", "LOW", "t_c")]["mean"], ph.PCT_CAP)
        self.assertNotIn(("t_a", "LOW", "t_b"), t)


class TestPrior(unittest.TestCase):
    def test_shrinks_toward_zero_and_keeps_sign(self):
        for m in (0.5, -0.5):
            stats = {"n": 10, "mean": m, "std": 0.3, "conv": 0.4}
            mean, sd = ph.prior_from_stats(stats)
            raw = 0.4 * m
            self.assertEqual(math.copysign(1, mean), math.copysign(1, raw))
            self.assertLess(abs(mean), abs(raw))
            self.assertGreaterEqual(sd, abs(raw))

    def test_sd_floor(self):
        mean, sd = ph.prior_from_stats({"n": 500, "mean": 0.001, "std": 0.0, "conv": 0.1})
        self.assertEqual(sd, ph.SD_FLOOR)

    def test_unseen_and_empty_table(self):
        source = ph.make_prior_source({})
        self.assertEqual(source(("tariff_8", "HIGH"), "tariff_9"), (0.0, ph.UNSEEN_SD))

    def test_real_history(self):
        t = ph.load_table()
        self.assertTrue(t, "data/change_tariff.csv should load")
        for stats in t.values():
            mean, sd = ph.prior_from_stats(stats)
            self.assertTrue(math.isfinite(mean) and math.isfinite(sd))
            self.assertGreaterEqual(sd, ph.SD_FLOOR)


class TestPlugIn(unittest.TestCase):
    def tearDown(self):
        priors.set_prior_source(None)

    def test_posterior_uses_history_prior(self):
        key = next(iter(ph.load_table()))
        cell, target = (key[0], key[1]), key[2]
        priors.set_prior_source(ph.get_prior)
        mean, sd = Posterior().get(cell, target)
        exp_mean, exp_sd = ph.get_prior(cell, target)
        self.assertAlmostEqual(mean, exp_mean)
        self.assertAlmostEqual(sd, exp_sd)


class TestNoMockDependency(unittest.TestCase):
    def test_source_does_not_reference_mock(self):
        src = (ROOT / "agent_core" / "priors_history.py").read_text()
        self.assertNotIn("mock_environment", src)
        self.assertNotIn("_mock_", src)


if __name__ == "__main__":
    unittest.main()
