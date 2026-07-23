"""The statistics that make a pass rate honest.

"19 out of 20 passed" is a point estimate from a sample of twenty, reported as
if it were the truth. Two things are wrong with treating it that way, and both
matter the moment someone acts on the number:

**A pass rate is an estimate, not a measurement.** 19/20 and 190/200 are both
"95%", but one of them is a coin you have flipped ten times as often, and you
should believe it ten times as much. :func:`wilson_interval` puts a confidence
interval around the rate — the Wilson score interval, which unlike the textbook
normal approximation does not produce nonsense (bounds below 0, above 1, or a
zero-width interval at 100%) exactly when eval suites are smallest and you need
it most. A suite that scores 100% on 3 cases has a lower bound near 44%; saying
so out loud is the difference between evidence and a vibe.

**A model is not a function.** Run the same case twice at temperature and it can
pass once and fail once. A single run cannot see that; it records whichever
outcome it happened to get and calls the case settled. :func:`agreement`
quantifies how consistent repeated trials were, and the run engine uses it to
mark a case *flaky* — passed some trials, failed others — which is a third state
the gate treats as failing, because a check that only sometimes holds is not a
check you can ship behind.

Everything here is closed-form and standard-library: no sampling, no
dependency, and the same inputs always produce the same interval, because an
evidence tool whose numbers wobble between runs is answering the wrong question.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

#: z for a two-sided 95% interval. The one distributional constant this module
#: needs; everything else is arithmetic.
Z95 = 1.959963984540054


@dataclass(frozen=True)
class Interval:
    """A proportion with a confidence interval, on the 0..1 scale."""
    point: float
    low: float
    high: float
    n: int
    level: float = 0.95

    @property
    def width(self) -> float:
        return self.high - self.low

    @property
    def margin(self) -> float:
        """Half-width — the ± a reader expects after the point estimate."""
        return self.width / 2.0

    def format(self, pct: bool = True) -> str:
        if pct:
            return (f"{self.point * 100:.0f}% "
                    f"(95% CI {self.low * 100:.0f}–{self.high * 100:.0f}%)")
        return f"{self.point:.3f} (95% CI {self.low:.3f}–{self.high:.3f})"

    def as_dict(self) -> dict:
        return {"point": round(self.point, 4), "low": round(self.low, 4),
                "high": round(self.high, 4), "n": self.n, "level": self.level}


def z_for(level: float) -> float:
    """The two-sided normal quantile for a confidence level.

    Closed at the common levels so the usual reports are exact, and otherwise
    an Acklam rational approximation good to ~1e-9 — far tighter than a pass
    rate over a few dozen cases can justify, but it keeps the function total.
    """
    common = {0.90: 1.6448536269514722, 0.95: Z95, 0.99: 2.5758293035489004}
    if level in common:
        return common[level]
    return _norm_ppf(1.0 - (1.0 - level) / 2.0)


def wilson_interval(passed: int, n: int, level: float = 0.95) -> Interval:
    """Wilson score interval for a binomial proportion.

    Chosen over the Wald (normal-approximation) interval on purpose. Wald is the
    one everyone writes down — ``p ± z·sqrt(p(1-p)/n)`` — and it falls apart in
    exactly the regime eval suites live in: near 0% or 100%, and at small n, it
    hands back bounds outside [0, 1] and collapses to zero width at the extremes,
    reporting a 3/3 pass as "100%, no uncertainty." Wilson stays inside [0, 1],
    keeps a sensible width at the extremes, and is the interval statisticians
    actually recommend for this.
    """
    if n <= 0:
        return Interval(0.0, 0.0, 1.0, 0, level)
    passed = max(0, min(passed, n))
    z = z_for(level)
    p = passed / n
    z2 = z * z
    denom = 1.0 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))) / denom
    return Interval(point=p, low=max(0.0, centre - half),
                    high=min(1.0, centre + half), n=n, level=level)


def wilson_lower_bound(passed: int, n: int, level: float = 0.95) -> float:
    """Just the lower bound — the number to gate on when you want a floor you can
    defend. "We are 95% confident the true pass rate is at least X" is a claim;
    the observed rate alone is not."""
    return wilson_interval(passed, n, level).low


@dataclass(frozen=True)
class Agreement:
    """How consistent repeated trials of one case were."""
    trials: int
    passes: int

    @property
    def failures(self) -> int:
        return self.trials - self.passes

    @property
    def consistency(self) -> float:
        """Fraction of trials that agreed with the majority verdict. 1.0 means
        every trial reached the same answer; 0.5 is a coin flip."""
        if self.trials <= 0:
            return 1.0
        majority = max(self.passes, self.failures)
        return majority / self.trials

    @property
    def flaky(self) -> bool:
        """The case did not always land the same way — some trials passed and
        some failed. A flaky check is not a check."""
        return 0 < self.passes < self.trials

    @property
    def verdict(self) -> bool:
        """The case's canonical pass, under the strict rule: it must pass every
        trial. A single failed trial fails the case, because a safety check that
        holds four times in five does not hold."""
        return self.passes == self.trials and self.trials > 0

    def majority_verdict(self) -> bool:
        """The lenient rule: pass if more trials passed than failed. Offered for
        callers who explicitly want majority voting; the run engine defaults to
        the strict rule above."""
        return self.passes * 2 > self.trials


def agreement(trial_passes: list[bool]) -> Agreement:
    return Agreement(trials=len(trial_passes), passes=sum(1 for p in trial_passes if p))


def flakiness_rate(agreements: list[Agreement]) -> float:
    """Share of cases whose repeated trials disagreed. Zero means the suite was
    deterministic across the run; anything above it is a measurement of how much
    the model's nondeterminism is leaking into your pass rate."""
    if not agreements:
        return 0.0
    return sum(1 for a in agreements if a.flaky) / len(agreements)


def two_proportion_p(passed_a: int, n_a: int, passed_b: int, n_b: int) -> float:
    """Two-sided p-value that two runs' pass rates differ (pooled z-test).

    Used to answer the question a diff cannot: is this run *actually* worse than
    the last one, or did a couple of cases flip inside the noise? A pass rate
    that dropped from 96% to 94% on 50 cases has a p-value that will not
    impress anyone, and Assay would rather say that than raise a false alarm.
    """
    if n_a <= 0 or n_b <= 0:
        return 1.0
    p_a, p_b = passed_a / n_a, passed_b / n_b
    pool = (passed_a + passed_b) / (n_a + n_b)
    se = math.sqrt(pool * (1 - pool) * (1.0 / n_a + 1.0 / n_b))
    if se == 0:
        return 1.0 if p_a == p_b else 0.0
    z = abs(p_a - p_b) / se
    return 2.0 * (1.0 - _norm_cdf(z))


# --- distribution helpers ------------------------------------------------- #
def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


# Acklam's inverse-normal-CDF approximation. Only reached for non-standard
# confidence levels; the 90/95/99 cases are tabulated above.
_A = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
      1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
_B = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
      6.680131188771972e+01, -1.328068155288572e+01)
_C = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
      -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
_D = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
      3.754408661907416e+00)


def _norm_ppf(p: float) -> float:
    if p <= 0.0:
        return -math.inf
    if p >= 1.0:
        return math.inf
    plow = 0.02425
    if p < plow:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / \
               ((((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1.0)
    if p <= 1.0 - plow:
        q = p - 0.5
        r = q * q
        return (((((_A[0] * r + _A[1]) * r + _A[2]) * r + _A[3]) * r + _A[4]) * r + _A[5]) * q / \
               (((((_B[0] * r + _B[1]) * r + _B[2]) * r + _B[3]) * r + _B[4]) * r + 1.0)
    q = math.sqrt(-2.0 * math.log(1.0 - p))
    return -(((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / \
            ((((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1.0)
