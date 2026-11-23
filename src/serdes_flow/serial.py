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

`check` assumes the expected bit order.  `bit_mapping` separates the two
questions it mixes: is the eye healthy on the UI grid, and which input bit
does each output slot carry.  A wrong divider start state permutes the bits
of a word (sometimes with a neighbouring word) while leaving the eye intact;
`check` reports that as bit errors, `bit_mapping` reports the permutation.
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


def _match_edges(edge_t, edge_pol, seq, delay, first, end):
    """The historical matching and half-open extra-crossing span."""
    ui, bits, start = seq.ui_s, seq.bits, seq.start_s
    sgn = 2 * bits - 1
    used, residual, transition_bits, missing = set(), [], [], 0
    for k in range(first, end):
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
    span = (edge_t >= start + (first + delay - EDGE_MATCH_HALF_WIDTH_UI) * ui) & \
           (edge_t < start + (end + delay - EDGE_MATCH_HALF_WIDTH_UI) * ui)
    extra = int(sum(i not in used for i in np.where(span)[0]))
    return residual, transition_bits, missing, extra


def fixed_phase_window(t, y, seq: Sequence, *, delay_ui, first_bit, end_bit):
    """Measure [first_bit, end_bit) using a supplied phase; never fit payload.

    The supplied delay is typically measured from training in a complete run.
    All sample times and the complete +/-0.45 UI transition-matching domain,
    including the half-open extra-crossing span, must be covered by the actual
    waveform. Returns (metrics, details) for this local interval only; local
    functionality does not qualify a complete serializer or link.
    """
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    bits = np.asarray(seq.bits)
    if (t.ndim != 1 or y.shape != t.shape or len(t) < 2 or
            not np.all(np.isfinite(t)) or not np.all(np.isfinite(y)) or
            not np.all(np.diff(t) > 0)):
        raise ValueError('waveform must be finite, aligned and strictly increasing')
    if bits.ndim != 1:
        raise ValueError('sequence bits must be a one-dimensional array')
    if (type(first_bit) is not int or type(end_bit) is not int or
            first_bit < 1 or end_bit <= first_bit or end_bit > len(bits)):
        raise ValueError('invalid bit interval: requires 1 <= first_bit < end_bit <= sequence length')
    if (not np.isfinite(delay_ui) or not np.isfinite(seq.start_s) or
            not np.isfinite(seq.ui_s) or seq.ui_s <= 0 or
            not np.all((bits == 0) | (bits == 1))):
        raise ValueError('invalid sequence or fixed delay')
    bits = bits.astype(np.int64, copy=False)
    signed_seq = Sequence(bits, seq.start_s, seq.ui_s)
    ui, start = seq.ui_s, seq.start_s
    indices = np.arange(first_bit, end_bit)
    sample_t = start + (indices + .5 + delay_ui) * ui
    # Match windows for every bit, even those without expected transitions;
    # the latter contribute to the historical extra-crossing span.
    window_start = start + (first_bit + delay_ui - EDGE_MATCH_HALF_WIDTH_UI) * ui
    window_end = start + (end_bit + delay_ui - EDGE_MATCH_HALF_WIDTH_UI) * ui
    last_match_end = start + (end_bit - 1 + delay_ui + EDGE_MATCH_HALF_WIDTH_UI) * ui
    if (min(window_start, sample_t[0]) < t[0] or
            max(window_end, last_match_end, sample_t[-1]) > t[-1]):
        raise ValueError('sample or complete matching window exceeds waveform coverage')
    samples = np.interp(sample_t, t, y)
    signed = samples * (2 * bits[indices] - 1)
    edge_t, edge_pol = crossings(t, y)
    residual, transition_bits, missing, extra = _match_edges(edge_t, edge_pol, signed_seq, delay_ui, first_bit, end_bit)
    errors = int(np.sum(signed <= 0))
    metrics = dict(scope='local_window_only', delay_ui=float(delay_ui), first_bit=first_bit, end_bit=end_bit,
                   bit_errors=errors, minimum_signed_margin_v=float(np.min(signed)),
                   transition_spread_ui=float(np.ptp(residual)) if residual else None,
                   matched_transitions=len(residual), missing_transitions=missing, extra_crossings=extra,
                   functional=bool(errors == 0 and missing == 0 and extra == 0),
                   edge_match_half_width_ui=EDGE_MATCH_HALF_WIDTH_UI, phase_fitted=False)
    details = dict(bit_index=indices.tolist(), sample_time_s=sample_t.tolist(), sample_voltage_v=samples.tolist(),
                   signed_margin_v=signed.tolist(), payload_transition_bits=transition_bits, edge_residual_ui=residual)
    return metrics, details


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

    residual, transition_bits, missing, extra = _match_edges(
        edge_t, edge_pol, seq, delay, TRAINING_BITS, end)

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


def bit_mapping(t, y, seq: Sequence, *, first_bit=TRAINING_BITS, end_margin_s=2e-9):
    """Order-agnostic eye health plus the bit permutation of a serial node.

    The sampling phase is the circular mean of all crossings in the payload
    span relative to the UI grid anchored at seq.start_s (no training, no
    knowledge of the order).  Returns:

    eye_min_abs_v   smallest |sample| over payload slots (eye opening)
    edge_spread_ui  peak-to-peak crossing residual on the UI grid
    mapping         per 16-UI output frame, mapping[j] = index of the input bit
                    carried by slot j, relative to the start of the matching
                    input word (<0 or >=16: bit of a neighbouring word);
                    None when no consistent one-to-one mapping exists
    in_order        mapping is a pure latency (j -> j + const)
    """
    ui, bits = seq.ui_s, seq.bits
    stop = t[-1] - end_margin_s
    t0 = seq.start_s + first_bit * ui
    e, _ = crossings(t, y)
    e = e[(e > t0) & (e < stop)]
    frac = (e - seq.start_s) / ui
    phase = float(np.angle(np.mean(np.exp(2j * np.pi * frac))) / (2 * np.pi))
    residual = (frac - phase + 0.5) % 1.0 - 0.5
    n = np.arange(int((stop - seq.start_s) / ui))
    samples = np.interp(seq.start_s + (n + phase + 0.5) * ui, t, y)
    out = (samples > 0).astype(int)
    payload = samples[first_bit:]

    # Find a frame offset o and per-slot sources m_j with out[16k+o+j] == bits[16k+m_j]
    # for every usable word k.  Marker and payload words only: alternating
    # training cannot disambiguate.  Prefer the frame that keeps most slots
    # inside one input word.
    best = None
    for o in range(16):
        words = [k for k in range(ALTERNATING_BITS // 16 + 1, len(bits) // 16 - 1)
                 if 16 * k + o + 15 < len(out)]
        if len(words) < 6:
            continue
        m = []
        for j in range(16):
            cands = [s for s in range(-16, 32)
                     if all(out[16 * k + o + j] == bits[16 * k + s] for k in words)]
            if len(cands) != 1:
                break
            m.append(cands[0])
        if len(m) == 16 and len(set(m)) == 16:
            inside = sum(0 <= s < 16 for s in m)
            if best is None or inside > best[0]:
                best = (inside, o, m, len(words))
    mapping = best[2] if best else None
    return dict(
        eye_min_abs_v=float(np.min(np.abs(payload))),
        edge_spread_ui=float(np.ptp(residual)) if len(residual) else None,
        sampling_phase_ui=phase,
        mapping=mapping,
        frame_offset_ui=best[1] if best else None,
        words_used=best[3] if best else 0,
        in_order=bool(mapping is not None and len({s - j for j, s in enumerate(mapping)}) == 1),
    )
