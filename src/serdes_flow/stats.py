"""Statistics for Monte Carlo and yield (sizing flow: random part of a budget).

summary(x)                      n, mean, std, extremes, skewness, excess kurtosis
k_factor(n, p, conf, sided)     tolerance-interval factor: a fraction p of the population lies within
                                mean +- k*std (two-sided) or below mean + k*std (one-sided) with confidence
                                conf, for a normal sample of size n.  With n = 200, p = 0.9973 (3 sigma),
                                conf = 0.95 -> k = 3.28 two-sided, i.e. estimating sigma from 200 samples costs
                                ~10 % extra margin.
tolerance(x, p, conf, sided)    (low, high) interval from the sample
yield_ci(passed, n, conf)       Clopper-Pearson interval of a pass fraction (for pass/fail metrics that are
                                not normal: start-up, metastability); 997 / 1000 -> [0.991, 0.999] at 95 %.
pelgrom(sigma, area)            A of sigma = A / sqrt(W L) by least squares, and the fit residual
budget_rss(terms)               sqrt(sum (s_i * sigma_i)^2) with the share of each term in the variance

Normal-theory factors are only as good as the normality of the metric: check `summary` (|skew| and
|excess kurtosis| well below 1) before extrapolating to 3 sigma and beyond.
"""
from __future__ import annotations

import numpy as np
from scipy import stats as st


def summary(x) -> dict:
    x = np.asarray(x, float)
    return dict(n=int(len(x)), mean=float(np.mean(x)), std=float(np.std(x, ddof=1)), min=float(np.min(x)),
                max=float(np.max(x)), skew=float(st.skew(x)), excess_kurtosis=float(st.kurtosis(x)))


def k_factor(n: int, p: float = 0.9973, conf: float = 0.95, sided: int = 2) -> float:
    if sided == 1:
        zp = st.norm.ppf(p)
        return float(st.nct.ppf(conf, df=n - 1, nc=zp * np.sqrt(n)) / np.sqrt(n))
    # Howe's approximation for the two-sided normal tolerance interval
    z = st.norm.ppf((1 + p) / 2)
    chi = st.chi2.ppf(1 - conf, n - 1)
    return float(z * np.sqrt((n - 1) * (1 + 1 / n) / chi))


def tolerance(x, p: float = 0.9973, conf: float = 0.95, sided: int = 2):
    s = summary(x)
    k = k_factor(s["n"], p, conf, sided)
    return s["mean"] - k * s["std"], s["mean"] + k * s["std"]


def yield_ci(passed: int, n: int, conf: float = 0.95):
    a = 1 - conf
    lo = st.beta.ppf(a / 2, passed, n - passed + 1) if passed > 0 else 0.0
    hi = st.beta.ppf(1 - a / 2, passed + 1, n - passed) if passed < n else 1.0
    return float(lo), float(hi)


def pelgrom(sigma, area):
    """A (same unit as sigma times um) from sigma_i = A / sqrt(area_i), area in um^2."""
    sigma, area = np.asarray(sigma, float), np.asarray(area, float)
    u = 1 / np.sqrt(area)
    a = float(np.sum(sigma * u) / np.sum(u * u))
    resid = sigma - a * u
    return a, float(np.sqrt(np.mean(resid ** 2)) / np.mean(sigma))


def budget_rss(terms: dict[str, tuple[float, float]]):
    """terms: name -> (sensitivity, sigma).  Returns total sigma and each term's share of the variance."""
    var = {k: (s * g) ** 2 for k, (s, g) in terms.items()}
    tot = sum(var.values())
    return float(np.sqrt(tot)), {k: v / tot for k, v in var.items()}
