"""Back-to-back word stream: real TX r2 -> C2 -> RX termination + CTLE -> recorded far end -> RX readout
deser16 -> RTL words.  TT only, open loop (fixed PI code).

    uv run python analog/rx/top/tb/b2b_stream/run.py tx [--payload 16]      # new campaign: TX run + BC registration
    uv run python analog/rx/top/tb/b2b_stream/run.py rx CAMPAIGN [--code C]  # RX replay of the recorded far end
    uv run python analog/rx/top/tb/b2b_stream/run.py decode CAMPAIGN         # RTL on the read words, stream check
    uv run python analog/rx/top/tb/b2b_stream/run.py view CAMPAIGN|latest [--open]
    uv run python analog/rx/top/tb/b2b_stream/run.py all [--payload 16]      # tx, rx, decode, view

Stream (no gaps between words, one word per 4 ns): 2 x 0xaaaa (TX warm-up, as the r2 record), 8 x b5e3
(RX training), `payload` PRBS7 words (LSB first) and 3 tail words that are sent but not required.
TX: the r2 configuration of tb/clock_replay (recorded TT PLL edge sources, r2 trims, lowvt-enable driver,
real CMOS->CML ingress, real clock distribution) with the data words of this stream at the r2 word
edges; far end replaced by C2_loss6, the RX split termination to 1.05 V and the real CTLE (EQ3, 20 fF
per output leg).  The far-end difference is registered as boundary condition
rx_c2_far_txr2_stream_<campaign>@ctle_rc (load = CTLE input stage) and replayed into the readout bench
(tb/readout_deser, deser16).  PI code: the circular-mean phase of the far-end zero crossings against
the reference recording rx_c2_far_nominal@ctle_rc, whose eye centre is near code 20 (one code =
7.8125 ps; a later stream needs a later clock = a lower code).
Decode: the 32 readout outputs at every w rising edge -> digital/rx/tb/tb_rx_word_replay.sv (iverilog:
rx_word_map, bbpd_window_vote, rx_word_align16; training released after 3 aligned words).  Pass: every
required payload word appears once, in order, without gaps, after the training words.
"""
import argparse
import importlib.util
import json
import os
import subprocess
import time
from pathlib import Path

import numpy as np

from serdes_flow import boundary, eye, spice, vcd
from serdes_flow.corners import NOMINAL
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings

HERE = Path(__file__).resolve().parent
RESULTS = ROOT / "results/analog/rx/top/b2b_stream"
EXPECTED_TX = ROOT / "analog/tx/serializer/tb/clock_states/serializer_expected.json"
R2_STIMULI = ROOT / "analog/tx/serializer/tb/clock_states/r2_stimuli.inc"
RTL = ["digital/rx/tb/tb_rx_word_replay.sv", "digital/rx/rtl/rx_word_map.sv", "digital/rx/rtl/rx_word_align16.sv",
       "digital/rx/rtl/bbpd_window_vote.sv"]
WARM, TRAIN, TAIL = [0xAAAA] * 2, [0xB5E3] * 8, 3
REF_BC, REF_CODE, CODE_S, UI = "rx_c2_far_nominal@ctle_rc", 20, 500e-12 / 64, 250e-12


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


cr = _load("tx_clock_replay", ROOT / "analog/tx/serializer/tb/clock_replay/run.py")
rdx = _load("readout_deser", ROOT / "analog/rx/sampler/tb/readout_deser/run.py")
sp = rdx.sp

# --------------------------------------------------------------------------- stream and TX


def stream(payload):
    bits = eye.prbs7(16 * (payload + TAIL))
    pay = [sum(int(bits[16 * n + j]) << j for j in range(16)) for n in range(payload + TAIL)]
    return WARM + TRAIN + pay, pay[:payload]


def tx_stimuli(words):
    edges = json.loads(EXPECTED_TX.read_text())["word_edges_s"]
    assert len(words) <= len(edges), f"at most {len(edges)} words (r2 edge record)"
    lines = []
    for j in range(16):
        v = lambda w: "{supply}" if (w >> j) & 1 else "0"
        pts = ["0", v(words[0])]
        for n in range(1, len(words)):
            if (words[n] ^ words[n - 1]) >> j & 1:
                pts += [f"{edges[n] - 10e-12:.13e}", v(words[n - 1]), f"{edges[n] + 10e-12:.13e}", v(words[n])]
        lines.append(f"Vd{j} d{j} 0 PWL(" + " ".join(pts) + ")")
    clocks = [l for l in R2_STIMULI.read_text().splitlines() if l.startswith("Vsrc")]
    assert len(clocks) == 8
    return "\n".join(lines + clocks) + "\n", edges[:len(words)]


FAR_OLD = """Xchannel ltp ltn lxp lxn 0 serdes_diff_rlc16
Rlc0 lxp lrp .01
Rlc1 lxn lrn .01
Clc0 lrp 0 100f
Clc1 lrn 0 100f
Vlcm lcm 0 .9
Rlterm0 lrp lcm 50
Rlterm1 lrn lcm 50"""
FAR_NEW = """* b2b: C2 PCB, RX split termination to 1.05 V, real CTLE input (EQ3), 20 fF sampler budget per output leg
Xchannel ltp ltn lxp lxn 0 pcb_c2_loss6
Rlc0 lxp lrp .01
Rlc1 lxn lrn .01
Vlcm lcm 0 1.05
Xtermination lrp lrn lcm serdes_rx_input_termination
Vrxdd rxdd 0 {supply}
Irxref rxdd rxbias 50u
Xrxref rxbias rxbias 0 0 serdes_nfet_lvt w=8 l=0.5 nf=4
Vrxeq rxeq 0 {supply}
Xrxeq lrp lrn rxop rxon rxeq rxeq rxbias rxdd 0 serdes_rx_ctle_rc
Crxop rxop 0 20f
Crxon rxon 0 20f"""


def tx_deck(stop):
    d = cr.deck(NOMINAL, stop=f"{stop * 1e9:.0f}n")
    assert FAR_OLD in d
    d = d.replace(FAR_OLD, FAR_NEW)
    inc = '.include "' + str(ROOT / "verification/models/channel/diff_rlc16.spice") + '"'
    assert inc in d
    extra = ["verification/models/channel/pcb_family/pcb_foster_cells.spice", "verification/models/channel/pcb_family/C2_loss6.spice",
             "analog/rx/input/spice/rx_input_termination.spice", "analog/rx/ctle/spice/rx_ctle_rc.spice"]
    d = d.replace(inc, inc + "\n" + "\n".join(f'.include "{ROOT / e}"' for e in extra))
    d = d.replace(".control\n", ".save v(rxop) v(rxon)\n.control\n", 1)
    i = d.index("set filetype=binary\nwrite waveforms.raw ")
    d = d[:i] + "let rx_diff=v(lrp)-v(lrn)\nlet ctle_out=v(rxop)-v(rxon)\n" + d[i:]
    return d.replace("write waveforms.raw ", "write waveforms.raw rx_diff ctle_out ", 1)


def run_tx(camp, payload):
    words, pay = stream(payload)
    stim, edges = tx_stimuli(words)
    stop = edges[-1] + 12e-9
    d = camp / "tx"
    (camp / "stimuli_tx.inc").write_text(stim)
    (camp / "stream.json").write_text(json.dumps(dict(words_hex=[f"{w:04x}" for w in words], payload_hex=[f"{w:04x}" for w in pay],
                                                      word_edges_s=edges, warm=len(WARM), train=len(TRAIN), tail=TAIL, stop_s=stop), indent=1))
    print(f"TX: {len(words)} words, stop {stop * 1e9:.1f} ns", flush=True)
    ex = spice.run(tx_deck(stop), d, files={"stimuli.inc": camp / "stimuli_tx.inc"}, timeout_s=4 * 3600,
                   meta=dict(stage="b2b_tx", words=len(words), payload=payload))
    if not ex.ok:
        raise SystemExit(f"TX failed: exit {ex.exit_code} {ex.log_failures[:3]}")
    bc_id = f"rx_c2_far_txr2_stream_{camp.name}@ctle_rc"
    exr = json.loads((d / "execution.json").read_text())
    boundary.register(dict(
        id=bc_id, kind="recorded_node_voltage",
        description=f"Far-end differential voltage of C2_loss6 driven by the real TX r2 (clock_replay r2 configuration, "
                    f"recorded TT PLL edges) with the b2b word stream of {camp.relative_to(ROOT)} ({len(words)} words), "
                    f"terminated 2 x 50 ohm to 1.05 V and loaded by the real CTLE input (EQ3) at tt_v1800_t27.",
        upstream=dict(module="TX r2 + verification/models/channel C2_loss6 + rx termination", revision="b2b_stream/run.py",
                      provenance=str(d.relative_to(ROOT))),
        nodes={"rx_diff": "CTLE inputs rxp/rxn (legs vcm +- rx_diff/2)"},
        load=sp.replay.signature(),
        points={"tt_v1800_t27": dict(condition="tt_v1800_t27", run=str(d.relative_to(ROOT)), case="waveforms", vcm=1.05,
                                     git_revision=exr.get("git_revision"), deck_sha256=exr.get("deck_sha256"))},
        processing="rx_diff resampled, Douglas-Peucker 0.2 mV (link_eye/replay.stimuli); output saved from 12 ns, held at "
                   "its first saved value before; common mode taken as vcm.",
        validation=None,
        valid_while=["CTLE input stage == load.sha (serdes_rx_ctle_rc inp/inn)", "termination 2 x 50 ohm to 1.05 V",
                     "TX r2 sources/trims and channel C2_loss6 unchanged"]))
    print("registered", bc_id, flush=True)
    return bc_id

# --------------------------------------------------------------------------- RX


def crossing_phase(raw, vec, t0):
    w = spice.Waves(raw)
    sel = w.t > t0
    e, _ = crossings(w.t[sel], w[vec][sel])
    return float(np.angle(np.mean(np.exp(2j * np.pi * e / UI))) / (2 * np.pi) * UI), len(e)


def pick_code(camp):
    ref = boundary.get(REF_BC)["points"]["tt_v1800_t27"]
    p_ref, _ = crossing_phase(ROOT / ref["run"] / f"{ref['case']}.raw", "rx_diff", sp.link.T0 + sp.link.WARM * UI)
    p_new, n = crossing_phase(camp / "tx/waveforms.raw", "rx_diff", 30e-9)
    delta = (p_new - p_ref + UI / 2) % UI - UI / 2
    code = int(round(REF_CODE - delta / CODE_S)) % 64
    return code, dict(ref_phase_ps=p_ref * 1e12, stream_phase_ps=p_new * 1e12, delta_ps=delta * 1e12, crossings=n, code=code)


def rx_deck(code, stop):
    c = NOMINAL
    d = rdx.deck(c, code, {"rk_wn": "8", "rk_nfin": "2"}, "serdes_rx_readout_deser16")
    old = f"tran 2p {sp.link.STOP:.4e} {sp.link.SAVE_FROM:.4e} 4p"
    assert old in d
    d = d.replace(old, f"tran 2p {stop:.4e} {sp.link.SAVE_FROM:.4e} 4p")
    d = d.replace(".save ", ".save v(op) v(on) v(d0p) v(d0n) v(d1p) v(d1n) v(e0p) v(e0n) v(e1p) v(e1n) ", 1)
    lets = "let ctle=v(op)-v(on)\nlet sd0=v(d0p)-v(d0n)\nlet sd1=v(d1p)-v(d1n)\nlet se0=v(e0p)-v(e0n)\nlet se1=v(e1p)-v(e1n)\n"
    d = d.replace("let power=-v(vdd)*i(Vdd)\n", "let power=-v(vdd)*i(Vdd)\n" + lets, 1)
    name = rdx.rd.case_name(c, code)
    return d.replace(f"write {name}.raw ", f"write {name}.raw ctle sd0 sd1 se0 se1 ", 1), name


def run_rx(camp, code=None):
    info = json.loads((camp / "stream.json").read_text())
    bc_id = info.get("bc") or f"rx_c2_far_txr2_stream_{camp.name}@ctle_rc"
    boundary.check_load(bc_id, sp.replay.signature())
    if code is None:
        code, why = pick_code(camp)
        print(f"PI code {code}: stream crossings {why['delta_ps']:+.1f} ps against {REF_BC}", flush=True)
    else:
        why = dict(code=code, chosen="--code")
    stim, npts = sp.replay.stimuli(bc_id)
    (camp / "stimuli_rx.inc").write_text(stim)
    deck, name = rx_deck(code, info["stop_s"])
    ex = spice.run(deck, spice.next_run_dir(camp, "rx"), files={"stimuli.inc": camp / "stimuli_rx.inc"}, timeout_s=4 * 3600,
                   meta=dict(stage="b2b_rx", bc=bc_id, code=code, pwl_points=npts))
    info.update(bc=bc_id, code=code, code_choice=why, rx_case=name)
    (camp / "stream.json").write_text(json.dumps(info, indent=1))
    if not ex.ok:
        raise SystemExit(f"RX failed: exit {ex.exit_code} {ex.log_failures[:3]}")

# --------------------------------------------------------------------------- decode


def rx_raw(camp):
    info = json.loads((camp / "stream.json").read_text())
    return spice.case_output(camp, "rx", f"{info['rx_case']}.raw"), info


def read_words(raw, t_min=10e-9):
    w = spice.Waves(raw)
    t = w.t
    vdd = float(np.median(w["v(vdd)"]))
    we, wp = crossings(t, w["v(w)"], level=vdd / 2)
    wr = we[(wp > 0) & (we > t_min)]
    lv = {o: vcd.Bit(o, w[f"v({o})"], vdd).levels() for o in rdx.outputs()}
    phys = []
    for x in wr:
        i = min(np.searchsorted(t, x), len(t) - 1)
        phys.append(sum(int(lv[f"{lane}_{k}"][i]) << (4 * L + k) for L, lane in enumerate(rdx.LANES) for k in range(4)))
    return wr, phys


def decode(camp):
    raw, info = rx_raw(camp)
    wr, phys = read_words(raw)
    d = camp / "decode"
    d.mkdir(exist_ok=True)
    (d / "phys.hex").write_text("\n".join(f"{p:08x}" for p in phys) + "\n")
    exe = d / "tb.vvp"
    subprocess.run(["iverilog", "-g2012", "-o", str(exe)] + [str(ROOT / f) for f in RTL], check=True)
    subprocess.run(["vvp", str(exe), f"+vec={d / 'phys.hex'}", f"+n={len(phys)}", f"+out={d / 'rtl.tsv'}"], check=True,
                   stdout=subprocess.DEVNULL)
    rows = [l.split() for l in (d / "rtl.tsv").read_text().splitlines()]
    pay = [int(x, 16) for x in info["payload_hex"]]
    tail = [int(x, 16) for x in info["words_hex"][-info["tail"]:]]
    allpay = pay + tail
    out, k, errors, started, train_out = [], 0, [], False, 0
    for i, r in enumerate(rows):
        if r[5] != "1":
            continue
        word = int(r[8], 16)
        if not started and word == 0xB5E3:
            train_out += 1
            continue
        started = True
        exp = allpay[k] if k < len(allpay) else None
        if word != exp:
            errors.append(dict(index=k, got=f"{word:04x}", expected=None if exp is None else f"{exp:04x}"))
        out.append(dict(read=i, t_s=float(wr[i]), word=f"{word:04x}", payload_index=k))
        k += 1
    got_required = min(k, len(pay))
    edges = info["word_edges_s"]
    first_tx = edges[len(WARM) + len(TRAIN)]
    votes = [int(r[7]) for r in rows if r[6] == "1"]
    res = dict(reads=len(phys), training_words_out=train_out, payload_words_out=k, required=len(pay),
               required_received=got_required, errors=errors, passed=bool(not errors and got_required == len(pay)),
               release_read=next((i for i, r in enumerate(rows) if r[2] == "0"), None),
               latency_ns=(out[0]["t_s"] - first_tx) * 1e9 if out else None, votes=votes, words=out)
    (d / "result.json").write_text(json.dumps(res, indent=1))
    print(f"stream: {k} payload words out ({got_required}/{len(pay)} required), {len(errors)} errors, "
          f"training words out {train_out}, TX->RX word latency {res['latency_ns']:.1f} ns" if out else
          f"stream: no payload words; training words out {train_out}", flush=True)
    return res

# --------------------------------------------------------------------------- view


def view(camp, open_=False):
    raw, info = rx_raw(camp)
    res = json.loads((camp / "decode/result.json").read_text())
    rows = [l.split() for l in (camp / "decode/rtl.tsv").read_text().splitlines()]
    tx = spice.Waves(camp / "tx/waveforms.raw")
    rx = spice.Waves(raw)
    t0, t1 = 8e-9, info["stop_s"]
    t = np.arange(t0, t1, 2e-12)
    at = lambda w, k: np.interp(t, w.t, w[k])
    vdd = float(np.median(rx["v(vdd)"]))
    edges, words = info["word_edges_s"], [int(x, 16) for x in info["words_hex"]]
    txw = np.zeros(len(t), np.int64)
    for e, x in zip(edges, words):
        txw[t >= e] = x
    wr, phys = read_words(raw)
    data_bits = {i: o for o, i in rdx.EXPECTED.items()}
    lv = {o: vcd.Bit(o, at(rx, f"v({o})"), vdd).levels() for o in rdx.outputs()}
    data = sum(lv[data_bits[i]] << i for i in range(16))
    rtl_word, rtl_al, rtl_off, rtl_vote, exp, match = (np.zeros(len(t), np.int64) for _ in range(6))
    allpay = [int(x, 16) for x in info["payload_hex"]] + words[-info["tail"]:]
    k, started = 0, False
    for i, r in enumerate(rows):
        x = wr[i] + 20e-12
        sel = t >= x
        rtl_al[sel], rtl_off[sel] = int(r[3]), int(r[4], 16)
        if r[6] == "1":
            rtl_vote[sel] = int(r[7]) & 0x3F
        if r[5] == "1":
            word = int(r[8], 16)
            rtl_word[sel] = word
            if started or word != 0xB5E3:
                started = True
                e = allpay[k] if k < len(allpay) else 0
                exp[sel], match[sel] = e, int(word == e)
                k += 1
    sig = [vcd.Bus("tx_word", 16, txw), vcd.Real("tx_dout", at(tx, "dout")), vcd.Real("tx_line", at(tx, "line_tx")),
           vcd.Real("far_rx_diff", at(tx, "rx_diff")), vcd.Real("ctle_out", at(rx, "ctle")),
           vcd.Real("samp_d0", at(rx, "sd0")), vcd.Real("samp_e1", at(rx, "se1")), vcd.Real("samp_d1", at(rx, "sd1")),
           vcd.Real("samp_e0", at(rx, "se0")), vcd.Bit("w", at(rx, "v(w)"), vdd), vcd.Bus("rx_data_window", 16, data),
           vcd.Bus("rtl_aligned", 1, rtl_al), vcd.Bus("rtl_offset", 4, rtl_off), vcd.Bus("rtl_vote", 6, rtl_vote),
           vcd.Bus("rtl_word", 16, rtl_word), vcd.Bus("expected_word", 16, exp), vcd.Bus("match", 1, match)]
    d = camp / "view"
    d.mkdir(exist_ok=True)
    path = vcd.write(d / "b2b_stream.vcd", t, sig)
    first_tx = edges[len(WARM) + len(TRAIN)] * 1e12
    first_rx = res["words"][0]["t_s"] * 1e12 if res["words"] else first_tx
    groups = [("TX: word in (4 ns each, no gaps), serializer out, pad", [("tx_word", "hex"), ("tx_dout", "analog"), ("tx_line", "analog")]),
              ("channel C2 far end, CTLE out", [("far_rx_diff", "analog"), ("ctle_out", "analog")]),
              ("RX samplers D0 E1 D1 E0", [(s, "analog") for s in ("samp_d0", "samp_e1", "samp_d1", "samp_e0")]),
              ("RX readout: word clock, 16-UI window (bit0 oldest)", [("w", None), ("rx_data_window", "hex")]),
              ("RTL: aligner, vote, aligned word vs TX payload", [("rtl_aligned", None), ("rtl_offset", "dec"), ("rtl_vote", "signed"),
                                                                   ("rtl_word", "hex"), ("expected_word", "hex"), ("match", None)])]
    tcl = d / "view.tcl"
    tcl.write_text(vcd.tcl_view(groups, markers=[("A", first_tx, "first payload word into TX"),
                                                 ("B", first_rx, "first payload word out of RX")]))
    print(f"{path.relative_to(ROOT)} ({path.stat().st_size / 1e6:.1f} MB)", flush=True)
    if open_:
        env = {k: v for k, v in os.environ.items() if k != "GTK_PATH"}
        env.update(GTK_MODULES="", GTK2_RC_FILES="/dev/null")
        with open(d / "gtkwave.log", "w") as log:
            subprocess.Popen(["gtkwave", str(path), "--script", str(tcl)], env=env, stdout=log, stderr=subprocess.STDOUT,
                             start_new_session=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=("tx", "rx", "decode", "view", "all"))
    ap.add_argument("campaign", nargs="?")
    ap.add_argument("--payload", type=int, default=16)
    ap.add_argument("--code", type=int)
    ap.add_argument("--open", action="store_true")
    a = ap.parse_args()
    if a.step in ("tx", "all"):
        camp = RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        camp.mkdir(parents=True)
        bc = run_tx(camp, a.payload)
        info = json.loads((camp / "stream.json").read_text())
        (camp / "stream.json").write_text(json.dumps(dict(info, bc=bc), indent=1))
    else:
        if not a.campaign:
            raise SystemExit("campaign required")
        camp = sorted(RESULTS.glob("2*"))[-1] if a.campaign == "latest" else ROOT / a.campaign
    if a.step in ("rx", "all"):
        run_rx(camp, a.code)
    if a.step in ("decode", "all"):
        decode(camp)
    if a.step in ("view", "all"):
        view(camp, a.open)
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
