# Mahjong Legend math 0.8.0 — current-configuration validation

Audit date: **25 October 2026 (WIB)**.

The current configuration was sampled for **5,000,000 complete paid rounds**:
an initial 1,000,000-round audit and a separate 4,000,000-round validation using
a different seed domain. No parameters were calibrated or changed between runs.

The **independent 4,000,000-round validation** estimates RTP at **97.1153%**.
Its approximate 95% interval is **96.3931–97.8375%** using the sample standard
error, and **96.4007–97.8233%** using an equal-batch percentile bootstrap.
These are current-configuration Monte Carlo estimates, not exact theoretical
RTP, a new target setting, or certification. Historical v0.1/v0.2/v0.3 estimates
must not be presented as measurements of this configuration.

## Configuration and source identity

| Setting | Value audited |
|---|---|
| Math version | 0.8.0 |
| Grid | 4 / 5 / 5 / 5 / 4; 2,000 five-reel ways |
| Base multipliers | ×1 → ×2 → ×3 → ×5 |
| Bonus multipliers | ×2 → ×3 → ×5 → ×8 |
| Maximum award | 1,000× the paid-round stake, cumulative across base and bonus |
| Engine path | `mahjong_legend/engine.py`, function `play_round` |
| Python used | 3.12.14 |

Canonical configuration SHA-256:
`693e3cce085387b33e663706836d8c6f2b9d69fd2a7f4f6d467f80554d8c9592`.

Engine file SHA-256:
`08bde22d157336872cdcfa4aaa77d3f056db150dfc0e432bdfaaf2275935ea8d`.

Audit runner SHA-256:
`e128cbf40752e087f293589b1012d8fd86636108ab0c7d5afccb791e2c3f3644`.

Both runs used these same identities. The source files remained unchanged
throughout sampling. This audit changes no symbol weights, pays, multipliers,
stake options, cap, balance logic, artwork, or server behavior.

## Experiment design

One observation is one call to the actual engine's `play_round`, starting with
one paid base spin and continuing through every awarded and retriggered free
spin. The engine's cumulative 1,000× cap applies immediately; once reached,
the engine terminates remaining cascades and free spins. A computational-guard
exception fails the audit instead of silently omitting that round.

RTP is the sum of complete paid-round payout multiples divided by the number
of paid rounds. Free-spin screens add payout but **do not add stake to the
denominator**. No player bankroll or balance cutoff is used; sampling cannot
stop because a virtual player runs out of credits.

Each paid round receives a deterministic, separately derived 256-bit seed:

```text
sha256(UTF-8(seed_domain + "\n" + zero_based_paid_round_index))
```

The initial audit uses domain
`Mahjong-Legend/math-0.8.0/validation-20261025-A`; the independent validation
uses domain `Mahjong-Legend/math-0.8.0/validation-20261025-B`.
The bootstrap uses a separate domain-derived seed. These are reproducible
pseudorandom samples, not an independently certified RNG or an independently
implemented game evaluator.

Exact decimal payout totals are accumulated separately from the floating-point
sample-variance calculation. The runner checks every round's base-plus-bonus
decomposition, payout bound, and cap flag. Each JSON receipt includes a digest
of the ordered engine transcripts and a seed/transcript hash for the largest
observed award, so the sample and that round can be reconstructed.

## Results

The four-million-round column is the primary independent validation.

| Measure | Initial audit A | Independent validation B |
|---|---:|---:|
| Complete paid rounds | 1,000,000 | 4,000,000 |
| Free spins played | 38,386 | 152,836 |
| Total screens, including free spins | 1,038,386 | 4,152,836 |
| Estimated RTP | 97.7948% | **97.1153%** |
| Base RTP contribution | 69.5510% | 69.5456% |
| Bonus RTP contribution | 28.2438% | 27.5697% |
| Approximate normal 95% RTP interval | 96.3420–99.2476% | 96.3931–97.8375% |
| Equal-batch bootstrap 95% RTP interval | 96.3664–99.2913% | 96.4007–97.8233% |
| RTP standard error, percentage points | 0.7413 | 0.3685 |
| Paid rounds with a positive payout | 33.4034% | 33.4287% |
| Paid rounds returning at least their stake | 13.1945% | 13.1980% |
| Paid rounds entering free spins | 4,576 | 18,162 |
| Observed bonus-entry frequency | 0.4576% | 0.4541% |
| Observed rounds reaching the cap | 1 | 2 |
| Largest observed award | 1,000× | 1,000× |
| Maximum free spins in one paid round | 24 | 26 |
| Maximum winning cascade step in one screen | 13 | 14 |
| Share of all payout from largest 1% of rounds | 46.7904% | 46.3979% |

The combined five-million-round sample contains 191,222 free spins and three
cap hits. Its pooled estimated RTP is **97.2512%**, with a normal-approximation
95% interval of **96.6045–97.8979%**. This pooled summary does not replace the
separate independent validation receipt. Its variance combines within-run and
between-run sums of squares; the confidence-interval endpoints are not averaged.
No pooled bootstrap interval was calculated.

The positive-payout rate counts returns below the original stake. It is not a
profit rate. The return-at-least-stake rate includes break-even rounds. The
observed maximum equals the configured cap; observing that maximum alone does
not estimate its rare-event frequency precisely.

## Independent analytic cross-check

The initial screen permits at most one scatter per reel, with nominal per-reel
probability 0.08. The ideal independent-draw model therefore gives:

```text
P(at least 3 scatters) = Σ[k=3..5] choose(5,k) × 0.08^k × 0.92^(5-k)
                      = 0.0045252608
                      = 0.45252608%
```

The four-million-round sample has 18,162 such screens, or 0.45405%. Its Wilson
95% interval is **0.447509–0.460686%**, containing the analytic value.
Scatter eligibility and actual bonus entry are counted separately because a
base-game cap could end a round before its awarded bonus is entered. Their
counts happened to be equal in both samples.

Before applying the payout cap, the mean free-spin award per screen is
`a = 0.0365920256`. Since free spins can themselves retrigger, the corresponding
expected number of free spins per paid round is `a/(1-a) ≈ 0.03798185875`.
The cap can truncate those future spins, so this is a pre-cap analytic check,
not an assertion that the capped game's expectation is identical.

## Uncertainty and limits of the result

The normal interval uses the unbiased sample variance and
`mean ± 1.959963984540054 × sample_sd / sqrt(paid_rounds)`.
The bootstrap resamples equal-size batches of 1,000 complete paid rounds,
using 2,000 replicates. There are 1,000 batches for A and 4,000 for B.
Its interval is the 2.5th and 97.5th percentile of the resampled batch means.

Both intervals rely on observed samples and may underrepresent rare,
unobserved tails. The payout is dispersed: the independent sample's standard
deviation is approximately 7.3696× per paid round, and its largest 1% of rounds
contribute about 46.4% of all payout. Three cap hits across the full sample are
not enough to measure the cap-hit probability precisely.

This work provides a reproducible estimate for the current ×5 configuration.
It does not establish an exact theoretical RTP or validate an intended 96%
target. Any future calibration should be a separately versioned decision and
be followed by validation on fresh, untouched seeds. The game remains a
virtual-credit prototype without a claim of real-money readiness.

## Reproduce

Run from the repository root using the source/configuration identities above:

```sh
python -m unittest discover -s tests -p 'test_math_validation.py' -v

python tools/validate_math_v080.py \
  --rounds 1000000 \
  --seed-domain Mahjong-Legend/math-0.8.0/validation-20261025-A \
  --output research/math_v080_validation_1m.json

python tools/validate_math_v080.py \
  --rounds 4000000 \
  --seed-domain Mahjong-Legend/math-0.8.0/validation-20261025-B \
  --output research/math_v080_validation_4m_independent.json
```

The seven focused tests passed. They cover the paid-round denominator,
known-sample variance and normal interval, cap/decomposition rejection, cap
timing versus bonus eligibility, deterministic seeds and audit output,
incomplete batches, and uncertainty-helper boundaries. The maximum-award
round in each sample was regenerated and passed `verify_round` with the same
transcript hash. A separate read-only statistical review found no substantive
error in the fixed-configuration estimator.

The normal CI for the pooled summary can be reproduced from the two receipts:

```text
N = n_A + n_B
mean = (exact_total_A + exact_total_B) / N
M2 = Σ[i=A,B] ((n_i-1) × sample_sd_i² + n_i × (mean_i-mean)²)
SE = sqrt(M2 / (N-1) / N)
pooled RTP interval = 100 × (mean ± 1.959963984540054 × SE)
```

CI runs the quick focused tests; it does not run millions of Monte Carlo rounds
on every source push. Audit receipts omit wall-clock timings so a repeated run
under the recorded source and Python version can produce identical JSON.

## Evidence files

- [Audit runner](../tools/validate_math_v080.py)
- [Focused tests](../tests/test_math_validation.py)
- [Initial one-million-round receipt](../research/math_v080_validation_1m.json)
- [Independent four-million-round receipt](../research/math_v080_validation_4m_independent.json)
- [Combined five-million-round sufficient-statistics summary](../research/math_v080_validation_5m_aggregate.json)

Receipt SHA-256 values:

- A: `0278a4607c5fbd0f721286f3ea3562dbc3b6ae3a027bf5982bebc8c1c69b4360`
- B: `91f5682401f52625c3481a99500872e9b89b82091cf61990fdd8081ec63db4a6`
