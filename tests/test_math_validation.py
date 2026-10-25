from decimal import Decimal
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.validate_math_v080 import RoundStatistics, percentile, round_seed, simulate, wilson_interval


def record(index, base, bonus, free_spins=0, capped=False, scatters=0):
    return {"seed_hex": f"{index:064x}", "events_sha256": f"{index:064x}",
            "total_payout_x": str(Decimal(base) + Decimal(bonus)),
            "base_payout_x": base, "bonus_payout_x": bonus,
            "free_spins_played": free_spins, "capped": capped,
            "base_scatters": scatters, "events": []}


class MathValidationTests(unittest.TestCase):
    def test_bonus_screens_do_not_dilute_paid_stake_denominator(self):
        stats = RoundStatistics(Decimal(1000), 1)
        stats.add(record(0, "0", "0"))
        stats.add(record(1, "1", "2", free_spins=8, scatters=3))
        result = stats.summary("01" * 32, 100)
        self.assertEqual(result["paid_rounds"], 2)
        self.assertEqual(result["total_screens"], 10)
        self.assertEqual(result["rtp_percent"], 150)
        self.assertEqual(result["base_rtp_contribution_percent"], 50)
        self.assertEqual(result["bonus_rtp_contribution_percent"], 100)
        self.assertEqual(result["bonus_entry_rate_percent"], 50)
        # The known sample [0,3] has sample variance 4.5 and SE(mean)=1.5.
        # This detects accidentally using population variance or total screens.
        self.assertAlmostEqual(result["payout_sample_standard_deviation_x"],
                               2.1213203435596424)
        self.assertAlmostEqual(result["rtp_standard_error_percentage_points"], 150)
        low, high = result["rtp_normal_95_interval_percent"]
        self.assertAlmostEqual(low, -143.9945976810081)
        self.assertAlmostEqual(high, 443.9945976810081)

    def test_inconsistent_cap_or_total_fails_instead_of_biasing_the_sample(self):
        for result in (record(1, "1001", "0"), record(1, "1000", "0"),
                       {**record(1, "1", "2"), "total_payout_x": "4"}):
            with self.assertRaises(ValueError):
                RoundStatistics(Decimal(1000), 1).add(result)

    def test_cap_and_scatter_eligibility_are_distinct_from_bonus_entry(self):
        stats = RoundStatistics(Decimal(1000), 1)
        stats.add(record(0, "1000", "0", capped=True, scatters=3))
        stats.add(record(1, "0", "0"))
        result = stats.summary("02" * 32, 100)
        self.assertEqual(result["cap_hits"], 1)
        self.assertEqual(result["base_screens_with_at_least_3_scatters"], 1)
        self.assertEqual(result["paid_rounds_entering_bonus"], 0)

    def test_seed_namespaces_and_index_do_not_overlap(self):
        seeds = {round_seed(namespace, index)
                 for namespace in ("audit-A", "audit-B") for index in range(200)}
        self.assertEqual(len(seeds), 400)
        with self.assertRaises(ValueError):
            round_seed("audit-A", -1)

    def test_same_audit_is_exactly_reproducible(self):
        first = simulate(200, "math-validation-test", 10, 100)
        self.assertEqual(first, simulate(200, "math-validation-test", 10, 100))
        self.assertEqual(first["base_multipliers"], [1, 2, 3, 5])
        self.assertEqual(first["bonus_multipliers"], [2, 3, 5, 8])
        self.assertEqual(first["analytic_pre_cap_scatter_eligibility_probability"], "0.0045252608")

    def test_incomplete_batches_are_rejected(self):
        with self.assertRaises(ValueError):
            simulate(101, "test", 10, 100)

    def test_uncertainty_helpers_cover_boundaries(self):
        self.assertEqual(percentile([0, 2, 4], 0.5), 2)
        self.assertEqual(percentile([0, 2, 4], 0.25), 1)
        low, high = wilson_interval(0, 100)
        self.assertAlmostEqual(low, 0)
        self.assertGreater(high, 0)
        low, high = wilson_interval(100, 100)
        self.assertLess(low, 1)
        self.assertAlmostEqual(high, 1)


if __name__ == "__main__":
    unittest.main()
