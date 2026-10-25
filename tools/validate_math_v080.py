#!/usr/bin/env python3
"""Reproduce an offline Monte Carlo audit of the authoritative math engine.

One observation is one paid round including all awarded/retriggered free spins.
The engine applies its existing cumulative round cap. This script never changes
game parameters and never contacts the game server or a payment system.
"""
from __future__ import annotations

import argparse
from array import array
from decimal import Context, Decimal
import hashlib
import json
import math
from pathlib import Path
import platform
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mahjong_legend.engine import GameConfig, play_round

DEFAULT_SEED_DOMAIN = "Mahjong-Legend/math-0.8.0/validation-20261025-A"
ACCUMULATION = Context(prec=60)
Z95 = 1.959963984540054


def round_seed(seed_domain: str, index: int) -> str:
    """Domain-separated deterministic 256-bit seeds, independent of payout."""
    if not seed_domain or index < 0:
        raise ValueError("A nonempty seed domain and nonnegative index are required")
    return hashlib.sha256(f"{seed_domain}\n{index}".encode("utf-8")).hexdigest()


def percentile(sorted_values, probability: float) -> float:
    if not sorted_values or not 0 <= probability <= 1:
        raise ValueError("Nonempty values and a probability in [0,1] are required")
    position = (len(sorted_values) - 1) * probability
    left = math.floor(position)
    right = math.ceil(position)
    return (sorted_values[left] * (right - position)
            + sorted_values[right] * (position - left)
            if left != right else sorted_values[left])


def wilson_interval(successes: int, observations: int) -> list[float]:
    if observations < 1 or not 0 <= successes <= observations:
        raise ValueError("Invalid binomial counts")
    p = successes / observations
    divisor = 1 + Z95 * Z95 / observations
    center = (p + Z95 * Z95 / (2 * observations)) / divisor
    half = Z95 * math.sqrt(p * (1 - p) / observations
                          + Z95 * Z95 / (4 * observations ** 2)) / divisor
    return [max(0.0, center - half), min(1.0, center + half)]


class RoundStatistics:
    """Summarize complete paid rounds; bonus screens never enter the denominator."""
    def __init__(self, cap: Decimal, batch_size: int):
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self.cap = cap
        self.batch_size = batch_size
        self.count = 0
        self.base = Decimal(0)
        self.bonus = Decimal(0)
        self.total = Decimal(0)
        self.mean = 0.0
        self.m2 = 0.0
        self.hits = self.base_hits = self.return_at_least_stake = 0
        self.eligible_triggers = self.bonus_rounds = self.capped = 0
        self.free_spins = self.max_free_spins = self.max_cascade = 0
        self.batch_total = Decimal(0)
        self.batch_means = []
        self.payouts = array("d")
        self.transcript_digest = hashlib.sha256()
        self.max_record = None

    def add(self, result: dict) -> None:
        payout = Decimal(result["total_payout_x"])
        base = Decimal(result["base_payout_x"])
        bonus = Decimal(result["bonus_payout_x"])
        if payout != base + bonus or not Decimal(0) <= payout <= self.cap:
            raise ValueError("Payout decomposition or round cap is inconsistent")
        if bool(result["capped"]) != (payout == self.cap):
            raise ValueError("Cap flag does not match the round payout")
        self.count += 1
        self.base = ACCUMULATION.add(self.base, base)
        self.bonus = ACCUMULATION.add(self.bonus, bonus)
        self.total = ACCUMULATION.add(self.total, payout)
        value = float(payout)
        delta = value - self.mean
        self.mean += delta / self.count
        self.m2 += delta * (value - self.mean)
        self.hits += payout > 0
        self.base_hits += base > 0
        self.return_at_least_stake += payout >= 1
        self.eligible_triggers += result["base_scatters"] >= 3
        self.bonus_rounds += result["free_spins_played"] > 0
        self.capped += bool(result["capped"])
        self.free_spins += result["free_spins_played"]
        self.max_free_spins = max(self.max_free_spins, result["free_spins_played"])
        self.max_cascade = max(self.max_cascade, max(
            (event["step"] for event in result["events"]
             if event["type"] == "cascade"), default=0))
        self.payouts.append(value)
        self.batch_total = ACCUMULATION.add(self.batch_total, payout)
        if self.count % self.batch_size == 0:
            self.batch_means.append(float(self.batch_total / self.batch_size))
            self.batch_total = Decimal(0)
        self.transcript_digest.update(bytes.fromhex(result["events_sha256"]))
        if self.max_record is None or payout > Decimal(self.max_record["payout_x"]):
            self.max_record = {
                "paid_round_index": self.count - 1,
                "seed_hex": result["seed_hex"],
                "payout_x": str(payout),
                "base_payout_x": str(base),
                "bonus_payout_x": str(bonus),
                "free_spins_played": result["free_spins_played"],
                "capped": bool(result["capped"]),
                "events_sha256": result["events_sha256"],
            }

    def summary(self, bootstrap_seed: str, replicates: int) -> dict:
        n = self.count
        if n < 2 or n % self.batch_size or len(self.batch_means) < 2:
            raise ValueError("Require at least two complete equal-size batches")
        if replicates < 100:
            raise ValueError("Require at least 100 bootstrap replicates")
        mean = float(self.total / n)
        deviation = math.sqrt(self.m2 / (n - 1))
        standard_error = deviation / math.sqrt(n)
        bootstrap_rng = random.Random(int(bootstrap_seed, 16))
        batch_count = len(self.batch_means)
        bootstrap_means = sorted(
            math.fsum(bootstrap_rng.choices(self.batch_means, k=batch_count)) / batch_count
            for _ in range(replicates))
        ordered = sorted(self.payouts)
        top_count = max(1, math.ceil(n * 0.01))
        return {
            "paid_rounds": n,
            "free_spins_played": self.free_spins,
            "total_screens": n + self.free_spins,
            "denominator": "paid_rounds; triggered and retriggered free spins have zero added stake",
            "sum_payout_x": str(self.total),
            "sum_base_payout_x": str(self.base),
            "sum_bonus_payout_x": str(self.bonus),
            "rtp_percent": 100 * mean,
            "base_rtp_contribution_percent": 100 * float(self.base / n),
            "bonus_rtp_contribution_percent": 100 * float(self.bonus / n),
            "payout_sample_standard_deviation_x": deviation,
            "rtp_standard_error_percentage_points": 100 * standard_error,
            "rtp_normal_95_interval_percent": [100 * (mean - Z95 * standard_error),
                                                100 * (mean + Z95 * standard_error)],
            "rtp_equal_batch_bootstrap_95_interval_percent": [
                100 * percentile(bootstrap_means, 0.025),
                100 * percentile(bootstrap_means, 0.975)],
            "bootstrap": {"batch_size": self.batch_size, "batch_count": batch_count,
                          "replicates": replicates, "seed_hex": bootstrap_seed,
                          "method": "percentile bootstrap of equal-size paid-round batch means"},
            "rounds_with_positive_payout": self.hits,
            "hit_rate_percent": 100 * self.hits / n,
            "base_hit_rate_percent": 100 * self.base_hits / n,
            "rounds_returning_at_least_stake": self.return_at_least_stake,
            "return_at_least_stake_percent": 100 * self.return_at_least_stake / n,
            "base_screens_with_at_least_3_scatters": self.eligible_triggers,
            "scatter_eligibility_rate_percent": 100 * self.eligible_triggers / n,
            "scatter_eligibility_wilson_95_interval_percent": [
                100 * value for value in wilson_interval(self.eligible_triggers, n)],
            "paid_rounds_entering_bonus": self.bonus_rounds,
            "bonus_entry_rate_percent": 100 * self.bonus_rounds / n,
            "cap_hits": self.capped,
            "cap_hit_rate_percent": 100 * self.capped / n,
            "max_observed_payout_x": ordered[-1],
            "max_observed_free_spins_per_paid_round": self.max_free_spins,
            "max_observed_cascade_step_per_screen": self.max_cascade,
            "payout_quantiles_x": {str(p): percentile(ordered, p)
                                    for p in (0.5, 0.9, 0.95, 0.99, 0.999)},
            "largest_1_percent_payout_share_percent": (
                100 * math.fsum(ordered[-top_count:]) / float(self.total)
                if self.total else 0.0),
            "maximum_round_replay": self.max_record,
            "ordered_round_transcripts_sha256": self.transcript_digest.hexdigest(),
        }


def simulate(rounds: int, seed_domain: str = DEFAULT_SEED_DOMAIN,
             batch_size: int = 1000, bootstrap_replicates: int = 2000,
             progress: bool = False) -> dict:
    if rounds < 2 * batch_size or rounds % batch_size:
        raise ValueError("rounds must be an exact multiple of batch_size and at least twice it")
    if bootstrap_replicates < 100:
        raise ValueError("bootstrap_replicates must be at least 100")
    cfg = GameConfig()
    stats = RoundStatistics(cfg.cap, batch_size)
    started = time.monotonic()
    for index in range(rounds):
        stats.add(play_round(round_seed(seed_domain, index), cfg))
        if progress and (index + 1) % 100000 == 0:
            print(f"{index + 1:,}/{rounds:,} paid rounds; "
                  f"{time.monotonic() - started:.1f}s", file=sys.stderr, flush=True)
    bootstrap_seed = hashlib.sha256(f"{seed_domain}\nbootstrap".encode()).hexdigest()
    p = Decimal(str(cfg.raw["scatter_probability_per_reel"]))
    trigger_probability = sum(Decimal(math.comb(5, k)) * p**k * (1-p)**(5-k)
                              for k in (3, 4, 5))
    return {
        "audit_schema": "mahjong-legend-monte-carlo-v1",
        "game": "Mahjong Legend",
        "math_version": cfg.raw["version"],
        "config_sha256": cfg.digest,
        "engine_file_sha256": hashlib.sha256((ROOT / "mahjong_legend/engine.py").read_bytes()).hexdigest(),
        "audit_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "python_version": platform.python_version(),
        "seed_domain": seed_domain,
        "round_seed_derivation": "sha256(UTF-8(seed_domain + newline + zero_based_paid_round_index))",
        "base_multipliers": list(cfg.base_mult),
        "bonus_multipliers": list(cfg.bonus_mult),
        "round_payout_cap_x": str(cfg.cap),
        "analytic_pre_cap_scatter_eligibility_probability": str(trigger_probability),
        "method": "Unmodified authoritative engine.play_round for every paid round; complete bonus/retriggers; existing cumulative cap",
        "limitations": [
            "Monte Carlo intervals estimate sampling uncertainty; they are not an exact theoretical RTP or independent certification.",
            "Both RTP intervals use observed samples and may underrepresent rare unobserved tails.",
            "RTP is mean paid-round payout divided by one paid-round stake; it is not a probability of profit.",
            "No parameter calibration or economics change was performed.",
            "Virtual-credit prototype only; this audit does not establish real-money readiness.",
        ],
        "results": stats.summary(bootstrap_seed, bootstrap_replicates),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=1_000_000)
    parser.add_argument("--seed-domain", default=DEFAULT_SEED_DOMAIN)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--bootstrap-replicates", type=int, default=2000)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "research/math_v080_validation_1m.json")
    args = parser.parse_args()
    result = simulate(args.rounds, args.seed_domain, args.batch_size,
                      args.bootstrap_replicates, progress=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False,
                                     allow_nan=False) + "\n", encoding="utf-8")
    metrics = result["results"]
    print(json.dumps({"output": str(args.output), "paid_rounds": metrics["paid_rounds"],
                      "rtp_percent": metrics["rtp_percent"],
                      "normal_95_percent": metrics["rtp_normal_95_interval_percent"],
                      "bootstrap_95_percent": metrics["rtp_equal_batch_bootstrap_95_interval_percent"],
                      "config_sha256": result["config_sha256"]}, indent=2))


if __name__ == "__main__":
    main()
