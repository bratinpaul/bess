"""Signature / Bayesian diagnosis engine - works with zero training data.

For each fault class f with signatures S_f evaluated on a window (soft match m_i in [0, 1], weight w_i):

    logit_f = log prior_f + κ · Σ_{i ∈ S_f, available} w_i · (m_i − λ · (1 − m_i))   (weighted evidence, naive-Bayes style)
    logit_f = log prior_f − κ · unknown_penalty                                       (no signature of f is observable)
    logit_F-NONE = log prior_NONE + κ · none_bias
    P(f | symptoms) = softmax(logit)

A present symptom pushes its fault up by its diagnostic weight; an absent one pushes it down by λ × weight (λ < 1: the
library lists symptoms that CAN appear, not ones that always do). The F-NONE prior is a setting (the share of healthy
windows is a sampling choice, not a base rate); faults share the rest by episode count (Laplace) or uniformly. The
matched signatures are the explanation shown with each candidate.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

NONE = "F-NONE"


@dataclass
class EngineSettings:
    kappa: float = 1.5            # evidence sharpness
    absent_penalty: float = 0.25  # λ: weight of an absent symptom relative to a present one
    none_prior: float = 0.5       # prior probability of F-NONE
    none_bias: float = 0.0        # extra log-odds for F-NONE
    unknown_penalty: float = 1.0  # faults with no observable signature
    mute_rate: float = 0.5        # mute a signature that matches more than this share of healthy windows (0 = off)
    prior: str = "empirical"      # empirical (training labels, Laplace) | uniform


def priors(classes: list[str], labels: pd.Series | None, mode: str, none_prior: float = 0.5) -> np.ndarray:
    faults = [c != NONE for c in classes]
    if mode == "uniform" or labels is None or labels.empty:
        p = np.ones(len(classes))
    else:
        vc = labels.value_counts()
        p = np.array([vc.get(c, 0) + 1.0 for c in classes])
    p = np.where(faults, p, 0.0)
    p = p / p.sum() * (1 - none_prior if NONE in classes else 1.0)
    if NONE in classes:
        p[classes.index(NONE)] = none_prior
    return p


def posterior(evidence: list[dict], classes: list[str], prior: np.ndarray, s: EngineSettings,
              muted: frozenset = frozenset()) -> np.ndarray:
    ix = {c: i for i, c in enumerate(classes)}
    score = np.zeros(len(classes))
    seen = np.zeros(len(classes), bool)
    for e in evidence:
        i = ix.get(e["fault_code"])
        if i is None or e["match"] is None or e["signature_id"] in muted:
            continue
        score[i] += e["weight"] * (e["match"] - s.absent_penalty * (1 - e["match"]))
        seen[i] = True
    logit = np.log(prior) + s.kappa * score
    unseen = ~seen
    if NONE in ix:
        unseen[ix[NONE]] = False
        logit[ix[NONE]] = np.log(prior[ix[NONE]]) + s.kappa * s.none_bias
    logit[unseen] = np.log(prior[unseen]) - s.kappa * s.unknown_penalty
    z = np.exp(logit - logit.max())
    return z / z.sum()


def explain(evidence: list[dict], fault_code: str) -> list[dict]:
    """The signatures of one fault, matched first (for the diagnosis panel)."""
    rows = [e for e in evidence if e["fault_code"] == fault_code]
    return sorted(rows, key=lambda e: (-(e["match"] if e["match"] is not None else -1) * e["weight"]))


def always_on(evidence: list[list[dict]], healthy: list[bool], rate: float) -> tuple[frozenset, list[dict]]:
    """Signatures matching on more than `rate` of the healthy windows carry no diagnostic information here (usually a
    threshold that doesn't fit this plant's units or ranges); the engine ignores them."""
    hits: dict[int, list] = {}
    meta: dict[int, dict] = {}
    for ev, h in zip(evidence, healthy):
        if not h:
            continue
        for e in ev:
            if e["match"] is None or e["kind"] == "ALARM":
                continue
            hits.setdefault(e["signature_id"], []).append(e["match"] >= 0.5)
            meta[e["signature_id"]] = e
    out, report = set(), []
    for sid, v in hits.items():
        r = float(np.mean(v))
        e = meta[sid]
        row = {"signature_id": sid, "fault_code": e["fault_code"], "signal": e["signal"], "operator": e["operator"],
               "threshold": e["threshold"], "healthy_match_rate": r, "muted": bool(rate > 0 and r > rate)}
        report.append(row)
        if row["muted"]:
            out.add(sid)
    report.sort(key=lambda x: -x["healthy_match_rate"])
    return frozenset(out), report
