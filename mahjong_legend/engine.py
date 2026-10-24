"""Deterministic, replayable Mahjong Legend math engine.

Educational local demo only. Original 2,000-ways cascade math; no financial
transactions, prize redemption, or real-money RNG certification.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import random
from typing import Any

CONFIG_PATH = Path(__file__).with_name('math_config.json')
MICRO = Decimal('0.000001')
MAX_CASCADE_STEPS = 128  # computation guard: raise, never silently cap a round
MAX_BONUS_SPINS = 4000   # computation guard: raise, never silently cap a round


def canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def display_decimal(value: Decimal) -> str:
    return format(value.quantize(MICRO, rounding=ROUND_HALF_UP), 'f')


def exact_decimal(value: Decimal) -> str:
    return format(value, 'f')


class GameConfig:
    def __init__(self, raw: dict[str, Any] | None = None):
        self.raw = (json.loads(CONFIG_PATH.read_text('utf-8')) if raw is None
                    else json.loads(canonical_json(raw)))
        self.digest = sha256(canonical_json(self.raw))
        self.heights = tuple(self.raw['grid'])
        self.weights = dict(self.raw['symbols'])
        self.pool = tuple(s for s, weight in self.weights.items() for _ in range(weight))
        self.pays = {s: tuple(Decimal(str(v)) for v in values)
                     for s, values in self.raw['paytable'].items()}
        self.base_mult = tuple(self.raw['base_multipliers'])
        self.bonus_mult = tuple(self.raw['bonus_multipliers'])
        self.scatter_prob = float(self.raw['scatter_probability_per_reel'])
        self.enhanced_prob = float(self.raw['enhanced_probability_reels_2_to_4'])
        self.base_scale = Decimal(self.raw['paytable_scale_base'])
        self.bonus_scale = Decimal(self.raw['paytable_scale_bonus'])
        self.cap = Decimal(self.raw['max_round_payout_x'])
        self.spin_price = Decimal(self.raw['spin_price_virtual_credits'])
        self.initial_balance = Decimal(self.raw['initial_balance_virtual_credits'])
        # Explicit validation (unlike assert, active under `python -O`).
        if self.heights != (4, 5, 5, 5, 4):
            raise ValueError('Expected a 4-5-5-5-4 grid')
        if len(self.pool) != 100 or len(self.weights) != 15:
            raise ValueError('Exactly 15 symbols and 100 weighted pool entries required')
        if set(self.pays) != set(self.weights):
            raise ValueError('Paytable symbols must equal weighted symbols')
        if not all(len(v) == 3 and all(x >= 0 for x in v) for v in self.pays.values()):
            raise ValueError('Paytable needs nonnegative 3-, 4-, and 5-way payouts')
        if not all(weight > 0 for weight in self.weights.values()):
            raise ValueError('All symbol weights must be positive')
        if not all(0 <= p <= 1 for p in (self.scatter_prob, self.enhanced_prob)):
            raise ValueError('Probabilities must fall between 0 and 1')
        if not all(m > 0 for m in self.base_mult + self.bonus_mult):
            raise ValueError('Multipliers must be positive')
        if (not self.base_scale.is_finite() or not self.bonus_scale.is_finite()
                or not self.cap.is_finite() or not self.spin_price.is_finite()
                or not self.initial_balance.is_finite()):
            raise ValueError('Payout scales, cap, spin price and balance must be finite')
        if (self.base_scale <= 0 or self.bonus_scale <= 0 or self.cap <= 0
                or self.spin_price <= 0 or self.initial_balance < 0):
            raise ValueError('Invalid payout scales, cap, spin price or balance')
        if self.raw['bonus_all_enhanced_reel'] not in (2, 3, 4):
            raise ValueError('Enhanced bonus reel must be a middle reel')
        if (not isinstance(self.raw['free_spins_for_3_scatters'], int) or
                self.raw['free_spins_for_3_scatters'] <= 0 or
                not isinstance(self.raw['extra_free_spins_per_additional_scatter'], int) or
                self.raw['extra_free_spins_per_additional_scatter'] < 0):
            raise ValueError('Invalid free-spin award rules')


def new_tile(rng: random.Random, reel: int, bonus: bool, cfg: GameConfig) -> dict:
    # Same random draw order as v0.1 reference for strict parity tests.
    symbol = cfg.pool[rng.randrange(len(cfg.pool))]
    enhanced = (reel in (1, 2, 3) and
                ((bonus and reel == cfg.raw['bonus_all_enhanced_reel']-1)
                 or rng.random() < cfg.enhanced_prob))
    return {'symbol': symbol, 'enhanced': bool(enhanced)}


def initial_board(rng: random.Random, bonus: bool, cfg: GameConfig) -> list[list[dict]]:
    board = [[new_tile(rng, reel, bonus, cfg) for _ in range(height)]
             for reel, height in enumerate(cfg.heights)]
    for reel, col in enumerate(board):
        if rng.random() < cfg.scatter_prob:
            col[rng.randrange(len(col))] = {'symbol': 'S', 'enhanced': False}
    return board


def clone_board(board: list[list[dict]]) -> list[list[dict]]:
    return [[tile.copy() for tile in col] for col in board]


def evaluate(board: list[list[dict]], cfg: GameConfig) -> tuple[Decimal, list[set[int]], list[dict]]:
    marked = [set() for _ in cfg.heights]
    raw = Decimal(0)
    groups = []
    for symbol in cfg.weights:
        index_groups = []
        for col in board:
            eligible = [i for i, tile in enumerate(col) if tile['symbol'] in (symbol, 'W')]
            if not eligible:
                break
            index_groups.append(eligible)
        n = len(index_groups)
        if n < 3:
            continue
        ways = 1
        for group in index_groups:
            ways *= len(group)
        payout = cfg.pays[symbol][n-3] * ways
        raw += payout
        groups.append({'symbol': symbol, 'matching_reels': n, 'ways': ways,
                       'raw_payout_x': exact_decimal(payout)})
        for reel, idxs in enumerate(index_groups):
            marked[reel].update(idxs)
    return raw, marked, groups


def cascade(rng: random.Random, board: list[list[dict]],
            marked: list[set[int]], bonus: bool, cfg: GameConfig) -> list[list[dict]]:
    out = []
    for reel, col in enumerate(board):
        survivors = []
        for row, tile in enumerate(col):
            if row not in marked[reel]:
                survivors.append(tile.copy())
            elif tile['enhanced'] and tile['symbol'] not in ('W', 'S'):
                survivors.append({'symbol': 'W', 'enhanced': False})
        missing = cfg.heights[reel] - len(survivors)
        out.append([new_tile(rng, reel, bonus, cfg) for _ in range(missing)] + survivors)
    return out


def free_spins_for_scatters(n: int, cfg: GameConfig) -> int:
    return (0 if n < 3 else cfg.raw['free_spins_for_3_scatters'] +
            cfg.raw['extra_free_spins_per_additional_scatter']*(n-3))


def validate_seed_hex(seed_hex: str) -> None:
    if not isinstance(seed_hex, str) or len(seed_hex) != 64:
        raise ValueError('Seed must be 32 bytes expressed as 64 hex characters')
    try:
        bytes.fromhex(seed_hex)
    except ValueError as exc:
        raise ValueError('Invalid seed hex') from exc
    if seed_hex != seed_hex.lower():
        raise ValueError('Seed must use lowercase hex')


def play_round(seed_hex: str, cfg: GameConfig | None = None) -> dict:
    """Return an auditable transcript, bounded award, and deterministic replay data.

    Every paid round uses a fresh independent seed. The cap is applied on the
    full paid-round payout (base plus all triggered free spins); reaching it
    terminates the round immediately. Failed computational guards raise before
    returning a result, so a caller must not debit a failed round.
    """
    validate_seed_hex(seed_hex)
    cfg = cfg or GameConfig()
    rng = random.Random(int(seed_hex, 16))
    events: list[dict] = []
    total = Decimal(0)
    base_total = Decimal(0)
    bonus_total = Decimal(0)
    bonus_played = 0
    capped = False
    base_scatter = 0

    def screen(phase: str, number: int) -> int:
        nonlocal total, base_total, bonus_total, capped
        is_bonus = phase == 'bonus'
        board = initial_board(rng, is_bonus, cfg)
        scatter_count = sum(tile['symbol'] == 'S' for col in board for tile in col)
        events.append({'type': 'screen_start', 'phase': phase, 'number': number,
                       'scatters': scatter_count, 'board': clone_board(board)})
        step = 0
        screen_total = Decimal(0)
        mults = cfg.bonus_mult if is_bonus else cfg.base_mult
        scale = cfg.bonus_scale if is_bonus else cfg.base_scale
        while True:
            raw, marked, groups = evaluate(board, cfg)
            if raw <= 0:
                break
            if step >= MAX_CASCADE_STEPS:
                raise RuntimeError('Cascade computation guard reached; round aborted')
            step += 1
            multiplier = mults[min(step-1, len(mults)-1)]
            offered = raw * Decimal(multiplier) * scale
            awarded = min(offered, cfg.cap-total)
            if awarded < 0:
                raise AssertionError('Negative remaining cap')
            total += awarded
            screen_total += awarded
            if is_bonus:
                bonus_total += awarded
            else:
                base_total += awarded
            cap_on_step = total >= cfg.cap
            next_board = None if cap_on_step else cascade(rng, board, marked, is_bonus, cfg)
            events.append({
                'type': 'cascade', 'phase': phase, 'number': number,
                'step': step, 'multiplier': multiplier,
                'raw_payout_x': exact_decimal(raw),
                'full_step_payout_x': exact_decimal(offered),
                'awarded_x': exact_decimal(awarded),
                'win_groups': groups,
                'marked': [sorted(indices) for indices in marked],
                'before': clone_board(board), 'after': clone_board(next_board) if next_board else None,
                'cap_reached': cap_on_step,
            })
            if cap_on_step:
                capped = True
                events.append({'type': 'cap_reached', 'cap_x': exact_decimal(cfg.cap),
                               'phase': phase, 'number': number})
                break
            board = next_board
        events.append({'type': 'screen_end', 'phase': phase, 'number': number,
                       'winning_cascades': step, 'screen_payout_x': exact_decimal(screen_total),
                       'board': clone_board(board), 'terminated_by_cap': capped})
        return scatter_count

    base_scatter = screen('base', 0)
    remaining = 0 if capped else free_spins_for_scatters(base_scatter, cfg)
    if remaining:
        events.append({'type': 'bonus_trigger', 'scatters': base_scatter,
                       'awarded_spins': remaining})
    while remaining > 0 and not capped:
        if bonus_played >= MAX_BONUS_SPINS:
            raise RuntimeError('Free-spin computation guard reached; round aborted')
        remaining -= 1
        bonus_played += 1
        scatters = screen('bonus', bonus_played)
        if not capped:
            extra = free_spins_for_scatters(scatters, cfg)
            if extra:
                remaining += extra
                events.append({'type': 'bonus_retrigger', 'number': bonus_played,
                               'scatters': scatters, 'added_spins': extra,
                               'pending_spins': remaining})
    events.append({'type': 'round_end', 'payout_x': exact_decimal(total),
                   'base_payout_x': exact_decimal(base_total),
                   'bonus_payout_x': exact_decimal(bonus_total),
                   'free_spins_played': bonus_played, 'capped': capped})
    commitment = sha256(bytes.fromhex(seed_hex))
    result = {
        'game': 'Mahjong Legend', 'version': cfg.raw['version'],
        'config_sha256': cfg.digest,
        'seed_hex': seed_hex, 'seed_commitment_sha256': commitment,
        'round_id': commitment[:20],
        'payout_cap_x': exact_decimal(cfg.cap),
        'total_payout_x': exact_decimal(total),
        'base_payout_x': exact_decimal(base_total),
        'bonus_payout_x': exact_decimal(bonus_total),
        'base_scatters': base_scatter,
        'free_spins_played': bonus_played,
        'capped': capped,
        'events': events,
        'events_sha256': sha256(canonical_json(events)),
    }
    return result


def verify_round(result: dict, cfg: GameConfig | None = None) -> dict:
    """Check commitment, config, and full event/payout replay, not hashes alone."""
    cfg = cfg or GameConfig()
    try:
        if result['config_sha256'] != cfg.digest:
            return {'valid': False, 'reason': 'Config hash mismatch'}
        expected = play_round(result['seed_hex'], cfg)
        if result != expected:
            differences = [k for k in expected if result.get(k) != expected[k]]
            return {'valid': False, 'reason': 'Replay mismatch', 'different_fields': differences}
        return {'valid': True, 'reason': 'Seed commitment and every event/payout verified',
                'round_id': result['round_id']}
    except (KeyError, TypeError, ValueError, AssertionError, RuntimeError) as exc:
        return {'valid': False, 'reason': f'Invalid replay input: {exc}'}


def analytic_bonus_trigger_probability(cfg: GameConfig | None = None) -> float:
    import math
    cfg = cfg or GameConfig()
    p = cfg.scatter_prob
    return sum(math.comb(5, k) * p**k * (1-p)**(5-k) for k in (3,4,5))
