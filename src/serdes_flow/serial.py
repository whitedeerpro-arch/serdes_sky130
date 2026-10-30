"""Bit-level checks of a serial data waveform against a known sequence.

Measurement contract (unchanged from the TX PVT and optimization campaigns, so
new results compare directly with docs/data/tx_pvt.json and tx_optimization.json):

* The sequence starts with 64 training bits: 32 alternating bits, then a
  32-bit marker that removes integer-UI ambiguity.
* The sampling phase is a single constant delay found from training bits
  only.  The UI is fixed (250 ps by default) and never fitted to payload.
* Each payload bit is sampled at its centre.  The signed margin is the sample
  voltage times the expected sign; it must be positive for a correct bit.
* Payload edges are matched to expected transitions within +/-0.45 UI; the
  spread is the peak-to-peak edge residual.  Unmatched expected transitions are
  "missing", unmatched crossings are "extra".
"""
from dataclasses import dataclass

import numpy as np

from .waves import crossings

TRAINING_BITS = 64
ALTERNATING_BITS = 32
EDGE_MATCH_HALF_WIDTH_UI = 0.45

# Spec thresholds (docs/overview/spec.md); "draft" is the serializer screen
# used since the TX PVT campaign.
DRAFT_MARGIN_V = 0.075
DRAFT_SPREAD_UI = 0.15


@dataclass(frozen=True)
class Sequence:
    bits: np.ndarray        # 0/1 per UI, training first
    start_s: float          # nominal leading edge of bit 0 at the observed node
    ui_s: float = 250e-12

    @classmethod
    def from_expected(cls, expected: dict) -> "Sequence":
        """Build from the campaigns' *_expected.json records."""
        return cls(np.asarray(expected["bits"], dtype=int), expected["start_s"], expected.get("ui_s", 250e-12))


def _training_delay(t, y, seq, edge_t, edge_pol):
    """Constant sampling delay in UI from training bits only."""
    ui, sgn = seq.ui_s, 2 * seq.bits - 1
    idx = np.arange(TRAINING_BITS)
    grid = np.arange(-1, 24, 0.01)
    times = seq.start_s + (idx[None, :] + 0.5 + grid[:, None]) * ui
    v = np.interp(times.ravel(), t, y).reshape(times.shape)
    wrong = v * sgn[:TRAINING_BITS] <= 0
    # Marker errors dominate: an alternating pattern alone is 2-UI ambiguous.
    cost = 100 * wrong[:, ALTERNATING_BITS:].sum(axis=1) + wrong[:, :ALTERNATING_BITS].sum(axis=1)
    best = np.where(cost == cost.min())[0]
    delay = float(grid[best[np.argmax(np.min(v[best] * sgn[:TRAINING_BITS], axis=1))]])
    # Refine from the alternating-section edges: median edge offset.
    offsets = []
    for k in range(1, ALTERNATING_BITS):
        target = seq.start_s + (k + delay) * ui
        hit = np.where((abs(edge_t - target) < EDGE_MATCH_HALF_WIDTH_UI * ui) & (edge_pol == sgn[k]))[0]
        if len(hit) == 1:
            offsets.append((edge_t[hit[0]] - seq.start_s) / ui - k)
    if len(offsets) >= 20:
        delay = float(np.median(offsets))
    return delay, len(offsets)


def check(t, y, seq: Sequence, payload_bits: int):
    """Measure one differential node.  Returns (metrics, details)."""
    ui, bits, start = seq.ui_s, seq.bits, seq.start_s
    end = TRAINING_BITS + payload_bits
    if len(bits) < end:
        raise ValueError(f"sequence has {len(bits)} bits, need {end}")
    sgn = 2 * bits - 1
    edge_t, edge_pol = crossings(t, y)
    delay, matched_training = _training_delay(t, y, seq, edge_t, edge_pol)

    sample_t = start + (np.arange(end) + 0.5 + delay) * ui
    samples = np.interp(sample_t, t, y)
    signed = samples * sgn[:end]
    payload = signed[TRAINING_BITS:end]
    training_errors = int(np.sum(signed[:ALTERNATING_BITS] <= 0))
    marker_errors = int(np.sum(signed[ALTERNATING_BITS:TRAINING_BITS] <= 0))

    used, residual, transition_bits, missing = set(), [], [], 0
    for k in range(TRAINING_BITS, end):
        if bits[k] == bits[k - 1]:
            continue
        target = start + (k + delay) * ui
        hit = np.where((abs(edge_t - target) < EDGE_MATCH_HALF_WIDTH_UI * ui) & (edge_pol == sgn[k]))[0]
        if len(hit):
            i = int(hit[np.argmin(abs(edge_t[hit] - target))])
            used.add(i)
            residual.append((edge_t[i] - target) / ui)
            transition_bits.append(k)
        else:
            missing += 1
    span = (edge_t >= start + (TRAINING_BITS + delay - EDGE_MATCH_HALF_WIDTH_UI) * ui) & \
           (edge_t < start + (end + delay - EDGE_MATCH_HALF_WIDTH_UI) * ui)
    extra = int(sum(i not in used for i in np.where(span)[0]))

    in_payload = (t >= start + (TRAINING_BITS + delay) * ui) & (t < start + (end + delay) * ui)
    hi = samples[TRAINING_BITS:end][bits[TRAINING_BITS:end] == 1]
    lo = samples[TRAINING_BITS:end][bits[TRAINING_BITS:end] == 0]
    errors = int(np.sum(payload <= 0))
    valid = bool(matched_training >= 20 and marker_errors == 0 and training_errors == 0)
    metrics = dict(
        training_delay_ui=delay,
        training_transitions_matched=matched_training,
        training_errors=training_errors,
        marker_errors=marker_errors,
        payload_bits=payload_bits,
        bit_errors=errors,
        minimum_signed_margin_v=float(np.min(payload)),
        sample_eye_height_v=float(np.min(hi) - np.max(lo)),
        differential_pp_v=float(np.ptp(y[in_payload])),
        transition_spread_ui=float(np.ptp(residual)) if residual else None,
        matched_transitions=len(residual),
        missing_transitions=missing,
        extra_crossings=extra,
        training_valid=valid,
        functional=bool(valid and errors == 0 and missing == 0 and extra == 0),
        edge_match_half_width_ui=EDGE_MATCH_HALF_WIDTH_UI,
        phase_from_training_only=True,
        UI_fitted_to_payload=False,
    )
    details = dict(
        bit_index=np.arange(end).tolist(),
        sample_time_s=sample_t.tolist(),
        sample_voltage_v=samples.tolist(),
        payload_transition_bits=transition_bits,
        edge_residual_ui=residual,
    )
    return metrics, details


def meets_draft(m: dict) -> bool:
    """Serializer spec screen: functional, margin >= 75 mV and spread <= 0.15 UI."""
    return bool(m["functional"] and m["minimum_signed_margin_v"] >= DRAFT_MARGIN_V
                and m["transition_spread_ui"] is not None and m["transition_spread_ui"] <= DRAFT_SPREAD_UI)
