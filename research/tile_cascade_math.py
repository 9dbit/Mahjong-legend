#!/usr/bin/env python3
"""Reproducible virtual-credit math sandbox for an original cascading ways game.

Research only. No bets, deposits, external RNG, payments, accounts, or redemptions.
The math model is original and does not recreate PG Soft's proprietary reel strips.

Example: python tile_cascade_math.py --spins 200000 --seed 20261024 --base-scale 2.2 --bonus-scale 3.7
"""

import argparse
import json
import math
import random
import statistics
from collections import Counter
from dataclasses import dataclass
from typing import Optional

HEIGHTS = (4, 5, 5, 5, 4)
SYMBOL_WEIGHTS = {"A": 11, "B": 10, "C": 9, "D": 8, "E": 8, "F": 7,
                  "G": 7, "H": 7, "I": 7, "J": 6, "K": 6, "L": 5,
                  "M": 4, "N": 3, "O": 2}
# Returns per winning way, as multiples of ONE total paid-turn unit before scale.
PAYS = {
    "A": (0.045, 0.16, 0.46),
    "B": (0.055, 0.18, 0.51),
    "C": (0.060, 0.20, 0.57),
    "D": (0.070, 0.23, 0.65),
    "E": (0.075, 0.25, 0.70),
    "F": (0.085, 0.28, 0.80),
    "G": (0.095, 0.32, 0.89),
    "H": (0.105, 0.34, 0.93),
    "I": (0.115, 0.38, 1.05),
    "J": (0.125, 0.42, 1.15),
    "K": (0.135, 0.44, 1.22),
    "L": (0.160, 0.53, 1.50),
    "M": (0.200, 0.68, 1.95),
    "N": (0.270, 0.92, 2.70),
    "O": (0.440, 1.50, 4.30),
}
BASE_MULTIPLIERS = (1, 2, 3, 4)  # Original prototype, deliberately not a clone.
BONUS_MULTIPLIERS = (2, 3, 5, 8)
SCATTER_REEL_PROB = 0.08
GOLD_PROB = 0.085
FREE_SPINS_FOR_THREE = 8
ADDITIONAL_SPINS_PER_SCATTER = 2
SYMBOL_POOL = tuple(sym for sym, wt in SYMBOL_WEIGHTS.items() for _ in range(wt))
assert len(SYMBOL_POOL) == 100
assert len(PAYS) == len(SYMBOL_WEIGHTS)


@dataclass(frozen=True)
class Tile:
    symbol: str
    enhanced: bool = False


@dataclass
class SpinResult:
    win: float
    cascades: int
    scatters: int


def next_tile(rng: random.Random, reel: int, bonus: bool) -> Tile:
    symbol = SYMBOL_POOL[rng.randrange(len(SYMBOL_POOL))]
    gold = (reel in (1, 2, 3) and (bonus and reel == 2 or rng.random() < GOLD_PROB))
    return Tile(symbol, gold)


def initial_board(rng: random.Random, bonus: bool) -> list[list[Tile]]:
    cols = [[next_tile(rng, reel, bonus) for _ in range(height)]
            for reel, height in enumerate(HEIGHTS)]
    for reel, col in enumerate(cols):
        if rng.random() < SCATTER_REEL_PROB:
            col[rng.randrange(len(col))] = Tile("S")
    return cols


def find_wins(cols: list[list[Tile]]) -> tuple[float, list[set[int]]]:
    """Sum only the longest left-anchored run for each symbol, and mark winning cells.

    Reel 1 cannot contain Wild; therefore every paid path has a unique regular
    symbol on reel 1, avoiding all-Wild double-counting between symbol types.
    """
    winning_indices = [set() for _ in HEIGHTS]
    raw_pay = 0.0
    for symbol in SYMBOL_WEIGHTS:
        reel_indexes = []
        for reel, col in enumerate(cols):
            eligible = [i for i, tile in enumerate(col)
                        if tile.symbol == symbol or tile.symbol == "W"]
            if not eligible:
                break
            reel_indexes.append(eligible)
        length = len(reel_indexes)
        if length < 3:
            continue
        ways = math.prod(len(group) for group in reel_indexes)
        raw_pay += ways * PAYS[symbol][length - 3]
        for reel, indices in enumerate(reel_indexes):
            winning_indices[reel].update(indices)
    return raw_pay, winning_indices


def apply_cascade(rng: random.Random, cols: list[list[Tile]],
                  marked: list[set[int]], bonus: bool) -> None:
    """Enhanced winning symbols promote to one-use Wilds; other winners disappear."""
    for reel, col in enumerate(cols):
        survivors = []
        for row, tile in enumerate(col):
            if row not in marked[reel]:
                survivors.append(tile)
            elif tile.enhanced and tile.symbol not in ("W", "S"):
                survivors.append(Tile("W"))
        missing = HEIGHTS[reel] - len(survivors)
        cols[reel] = ([next_tile(rng, reel, bonus) for _ in range(missing)]
                      + survivors)


def run_spin(rng: random.Random, bonus: bool, scale: float) -> SpinResult:
    cols = initial_board(rng, bonus)
    scatters = sum(tile.symbol == "S" for col in cols for tile in col)
    multipliers = BONUS_MULTIPLIERS if bonus else BASE_MULTIPLIERS
    win = 0.0
    winning_steps = 0
    while True:
        pay, marked = find_wins(cols)
        if not any(marked):
            break
        multiplier = multipliers[min(winning_steps, len(multipliers) - 1)]
        win += pay * multiplier * scale
        winning_steps += 1
        if winning_steps >= 128:
            raise RuntimeError("Reached cascade guard; do not truncate payouts")
        apply_cascade(rng, cols, marked, bonus)
    return SpinResult(win, winning_steps, scatters)


def scatter_bonus_spins(n_scatter: int) -> int:
    if n_scatter < 3:
        return 0
    return FREE_SPINS_FOR_THREE + ADDITIONAL_SPINS_PER_SCATTER * (n_scatter - 3)


def exact_initial_screen_unscaled_rtp() -> float:
    """Exact no-cascade expected payout for independent-cell draw model."""
    expectation = 0.0
    p_scatter = SCATTER_REEL_PROB
    for symbol, weight in SYMBOL_WEIGHTS.items():
        q = weight / len(SYMBOL_POOL)
        means = [(h - p_scatter) * q for h in HEIGHTS]
        def zero(h):
            return ((1 - p_scatter) * (1 - q)**h
                    + p_scatter * (1 - q)**(h - 1))
        expected_ways = (
            math.prod(means[:3]) * zero(HEIGHTS[3]),
            math.prod(means[:4]) * zero(HEIGHTS[4]),
            math.prod(means),
        )
        expectation += sum(x * y for x, y in zip(PAYS[symbol], expected_ways))
    return expectation


def sample(rng: random.Random, n_spins: int, base_scale: float, bonus_scale: float) -> dict:
    base_sum = bonus_sum = 0.0
    base_hits = total_hits = trigger_count = 0
    sum_of_squares = 0.0
    sum_cascades = 0
    total_free_spins = 0
    max_win = 0.0
    win_bands = Counter()
    cascade_hist = Counter()
    for _ in range(n_spins):
        paid = run_spin(rng, bonus=False, scale=base_scale)
        base_sum += paid.win
        total = paid.win
        base_hits += paid.win > 0
        sum_cascades += paid.cascades
        cascade_hist[min(paid.cascades, 10)] += 1
        free_remaining = scatter_bonus_spins(paid.scatters)
        if free_remaining:
            trigger_count += 1
        n_visited = 0
        while free_remaining:
            free_remaining -= 1
            total_free_spins += 1
            n_visited += 1
            if n_visited > 2000:
                raise RuntimeError("Free-spin recursion guard reached")
            free = run_spin(rng, bonus=True, scale=bonus_scale)
            total += free.win
            bonus_sum += free.win
            free_remaining += scatter_bonus_spins(free.scatters)
        total_hits += total > 0
        sum_of_squares += total * total
        max_win = max(total, max_win)
        for threshold in (1, 5, 10, 20, 50, 100):
            if total >= threshold:
                win_bands[str(threshold)] += 1

    mean = (base_sum + bonus_sum) / n_spins
    variance = max(0.0, sum_of_squares / n_spins - mean ** 2)
    std = math.sqrt(variance)
    se = std / math.sqrt(n_spins)
    expected_awarded_spins_per_round = sum(
        math.comb(5, k) * SCATTER_REEL_PROB**k *
        (1 - SCATTER_REEL_PROB)**(5 - k) * scatter_bonus_spins(k)
        for k in range(3, 6)
    )
    trigger_probability = sum(
        math.comb(5, k) * SCATTER_REEL_PROB**k *
        (1 - SCATTER_REEL_PROB)**(5 - k) for k in range(3, 6)
    )
    # Every free spin may award more free spins. With independent identical
    # scatters and a subcritical branching process, this is an exact mean.
    expected_total_free_spins = (
        (expected_awarded_spins_per_round / trigger_probability) /
        (1 - expected_awarded_spins_per_round)
    )
    return {
        "model": "original_virtual_credit_cascade_v0.1",
        "n_paid_spins": n_spins,
        "base_payout_scale": base_scale,
        "bonus_payout_scale": bonus_scale,
        "symbol_weights": SYMBOL_WEIGHTS,
        "paytable_unscaled": {symbol: {"3": vals[0], "4": vals[1], "5": vals[2]} for symbol, vals in PAYS.items()},
        "grid": HEIGHTS,
        "nominal_ways": math.prod(HEIGHTS),
        "exact_initial_screen_rtp_before_scale": exact_initial_screen_unscaled_rtp(),
        "exact_initial_screen_rtp_with_base_scale": exact_initial_screen_unscaled_rtp() * base_scale,
        "scatter_probability_per_reel": SCATTER_REEL_PROB,
        "analytical_three_or_more_scatters": sum(
            math.comb(5, k) * SCATTER_REEL_PROB**k *
            (1 - SCATTER_REEL_PROB)**(5-k) for k in range(3, 6)),
        "base_rtp": base_sum / n_spins,
        "bonus_rtp": bonus_sum / n_spins,
        "total_rtp": mean,
        "total_rtp_95pct_ci_normal": [mean - 1.96 * se, mean + 1.96 * se],
        "rtp_standard_error": se,
        "paid_hit_rate": base_hits / n_spins,
        "overall_hit_rate_including_bonus": total_hits / n_spins,
        "bonus_trigger_rate": trigger_count / n_spins,
        "bonus_triggers": trigger_count,
        "analytical_expected_free_spins_per_trigger_including_retriggers": expected_total_free_spins,
        "avg_total_free_spins_per_trigger": (total_free_spins / trigger_count if trigger_count else None),
        "avg_bonus_return_per_trigger": (bonus_sum / trigger_count if trigger_count else None),
        "avg_cascades_per_paid_spin": sum_cascades / n_spins,
        "cascade_counts_capped_at_10": dict(sorted(cascade_hist.items())),
        "p_win_at_least_x_bet": {band: count / n_spins for band, count in win_bands.items()},
        "max_total_win_in_sample_x": max_win,
        "payout_std_per_spin_x": std,
        "notes": [
            "All outcomes are virtual-credit payouts in units of one paid turn.",
            "All cell draws are independently sampled from declared symbol weights.",
            "Exactly zero or one scatter appears per reel at initial draw; cascades never draw scatters.",
            "One-use enhanced winning tiles become Wild for next cascade, rather than disappearing.",
            "Gold symbols only appear on middle 3 reels; reel 1 has no Wild, preventing all-Wild path ambiguity.",
            "Free spins retrigger using the same independent scatter-reel process.",
            "95% CI uses the sample standard deviation and normal approximation; heavy tails need extra checks.",
            "This is NOT an implementation, math model, or RTP estimate for PG Soft Mahjong Ways.",
            "Random.Random reproducible PRNG is unsuitable for certified real-money gaming.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spins", type=int, default=200000)
    parser.add_argument("--seed", type=int, default=20261024)
    parser.add_argument("--base-scale", type=float, default=2.2)
    parser.add_argument("--bonus-scale", type=float, default=3.7)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    assert args.spins > 0 and args.base_scale > 0 and args.bonus_scale > 0
    result = sample(random.Random(args.seed), args.spins, args.base_scale, args.bonus_scale)
    result["seed"] = args.seed
    output = json.dumps(result, indent=2)
    print(output)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as file:
            file.write(output + "\n")


if __name__ == "__main__":
    main()
