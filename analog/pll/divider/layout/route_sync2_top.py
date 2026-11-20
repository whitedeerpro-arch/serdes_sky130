#!/usr/bin/env python3
"""Top-level physical router for pll_sync_prescaler8_2stack_pdk (v2: Bit-Sliced + Centered Shielded T-Tree Clock).

Floorplan eliminates v1 horizontal bus congestion and 6.08 fF ckp/ckn mismatch by
combining side-by-side mirror-symmetric MIMs in sync2_ck_frontend_pdk with:
  - Row 0 (Bottom): [Xrep (replica bias)] | [Xckfe (centered under Xff1)]
  - Clock Bay:      Balanced equal-length (35.5 um) M4/M3 T-tree for ckp/ckn flanked by M4 VSS shields
  - Row 1 (Slices): [Xff0 | Xq2buf]   [Xff1 | Xq4buf]   [Xff2 | Xq8buf]  (exact 35.0 um slice pitch)
  - Signal Channel: Clean orthogonal M2 horizontal tracks (b0..b2, q2..q8) + M3 vertical taps
  - Row 2 (Muxes):  [Xx1 (over Xff1)]  [Xt2 | Xx2 (over Xff2)] feeding d1/d2 straight down via M3

Verifies full-chip DRC=0, LVS=True, PROP_ERR=False, float_a=0, extracts native RCX parasitics,
plots an annotated PNG, and installs into analog/pll/divider/layout/variants/sync2_routed/.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "verification/layout"))
sys.path.insert(0, str(REPO / "analog/pll/divider/layout"))

import place_sync2_blocks as pb  # noqa: E402
import review_cell  # noqa: E402
import route_sync2_blocks as rb  # noqa: E402
from build_prescaler8_pdk import run_signoff  # noqa: E402
from check import exported_ports  # noqa: E402
from geometry import Cell  # noqa: E402
from summarize_parasitics import summarize_pex_spice  # noqa: E402

grid = pb.grid


def place_routed_sub(
    c: Cell, sub: Cell, target_x1: float, target_y1: float, mirror_y: bool = False,
) -> tuple[float, float, dict[str, tuple[str, float, float]]]:
    bx1, by1, _, by2 = sub.bbox()
    dx = grid(target_x1 - bx1)
    dy = grid(target_y1 + by2) if mirror_y else grid(target_y1 - by1)
    c.include(sub, dx=dx, dy=dy, mirror_y=mirror_y)
    ports = {
        name: (layer, grid(x + dx), grid((-y if mirror_y else y) + dy))
        for layer, x, y, name in sub.labels
    }
    return dx, dy, ports


def flatten_subckt_instances(subckt_texts: list[str], instances: list[tuple[str, str, list[str]]], top_name: str, top_ports: list[str]) -> str:
    """Recursively expand subcell _ref.spice definitions into one flat .subckt matching flat Magic extraction."""
    parsed: dict[str, tuple[list[str], list[str]]] = {}
    for stxt in subckt_texts:
        cur_name, cur_pins, cur_body = None, [], []
        for raw in stxt.splitlines():
            ln = raw.strip()
            if not ln or ln.startswith("*"):
                continue
            toks = ln.split()
            if toks[0].lower() == ".subckt":
                cur_name, cur_pins, cur_body = toks[1], toks[2:], []
            elif toks[0].lower() == ".ends":
                parsed[cur_name] = (cur_pins, cur_body)
                cur_name = None
            elif cur_name is not None:
                cur_body.append(ln)

    out_lines = [f".subckt {top_name} " + " ".join(top_ports)]

    def emit(inst_prefix: str, sname: str, conn: list[str]) -> None:
        pins, body = parsed[sname]
        assert len(pins) == len(conn), f"{inst_prefix} ({sname}): {len(pins)} pins vs {len(conn)} conns"
        pmap = dict(zip(pins, conn))
        for ln in body:
            toks = ln.split()
            dname = toks[0]
            param_idx = next((i for i, t in enumerate(toks) if "=" in t), len(toks))
            model_idx = param_idx - 1
            model = toks[model_idx]
            mapped_nets = [pmap.get(n, f"{inst_prefix}_{n}") for n in toks[1:model_idx]]
            if model in parsed:
                emit(f"{inst_prefix}_{dname}", model, mapped_nets)
            else:
                out_lines.append(" ".join([f"{dname}_{inst_prefix}"] + mapped_nets + toks[model_idx:]))

    for inst_name, sname, conn in instances:
        emit(inst_name, sname, conn)
    out_lines.extend([f".ends {top_name}", ""])
    return "\n".join(out_lines)


def drop_m3_to_dff_in(
    c: Cell,
    src_p: tuple[float, float],
    src_n: tuple[float, float],
    dp_pt: tuple[str, float, float],
    dn_pt: tuple[str, float, float],
    x_dp_drop: float,
    x_dn_drop: float,
    y_jog_p: float | None = None,
    y_jog_n: float | None = None,
) -> None:
    """Route differential signal down on M3 in left gap of a DFF into dp (M2) and dn (M3), well above ckp/ckn."""
    _, xdp, ydp = dp_pt
    _, xdn, ydn = dn_pt
    sxp, syp = src_p
    sxn, syn = src_n

    # p branch: src(M2)->via2->M3 -> x_dp_drop -> down to ydp -> via2 -> M2 to xdp
    c.via2(sxp, syp)
    if y_jog_p is not None:
        c.wire("metal3", [(sxp, syp), (sxp, y_jog_p), (x_dp_drop, y_jog_p), (x_dp_drop, ydp)], 0.34)
    else:
        c.wire("metal3", [(sxp, syp), (x_dp_drop, syp), (x_dp_drop, ydp)], 0.34)
    c.via2(x_dp_drop, ydp)
    c.wire("metal2", [(x_dp_drop, ydp), (xdp, ydp)], 0.32)

    # n branch: src(M2)->via2->M3 -> x_dn_drop -> down to ydn -> M3 straight into dn
    c.via2(sxn, syn)
    if y_jog_n is not None:
        c.wire("metal3", [(sxn, syn), (sxn, y_jog_n), (x_dn_drop, y_jog_n), (x_dn_drop, ydn), (xdn, ydn)], 0.34)
    else:
        c.wire("metal3", [(sxn, syn), (x_dn_drop, syn), (x_dn_drop, ydn), (xdn, ydn)], 0.34)


def tap_mux_from_m2_track(c: Cell, pin_pt: tuple[str, float, float], port_name: str, y_track: float, kind: str) -> float:
    """Drop cleanly from an M2 channel track UP into a Row-2 mux pin using non-crossing M3 lanes."""
    _, px, py = pin_pt
    is_left = port_name in ("sn", "ap", "bp")
    sgn = -1.0 if is_left else +1.0
    if kind == "spn":
        x_m3 = px
    elif kind == "apn":
        x_m3 = grid(px + sgn * 0.75)
    else:  # bpn
        x_m3 = grid(px + sgn * 1.50)
    c.via2(x_m3, y_track)
    c.wire("metal3", [(x_m3, y_track), (x_m3, py)], 0.34)
    c.via2(x_m3, py)
    if x_m3 != px:
        c.wire("metal2", [(x_m3, py), (px, py)], 0.32)
    return x_m3


def build_top(out: Path, sub_dir: Path, inst_dir: Path | None) -> dict:
    name = "pll_sync_prescaler8_2stack_pdk"
    w = out / name
    w.mkdir(parents=True, exist_ok=True)
    c = Cell()

    sub_names = (
        "sync2_ck_replica_bias_pdk",
        "sync2_ck_frontend_pdk",
        "sync2_mux2_pdk",
        "sync2_buf_out_pdk",
        "sync2_dff_pdk",
    )
    subs = {sn: Cell.read(sub_dir / f"{sn}.mag") for sn in sub_names}

    # 1. v3b Ultra-Compact 2-Row VSS — VDD (Head-to-Head) — VSS Floorplan
    # Narrowed Xckfe (24.55 um, elongated 8.4x26.8 MIM caps) pushes total width down by ~14 um!
    # Row A (y_top = 42.840, Foot=VSS at bottom, Head=VDD at top):
    #   [Xrep (0..42.485)] | 2.20 | [Xckfe (44.685..69.235, ctr=56.865)] | 2.80 | [Xx1 | Xt2 | Xx2 (72.035..105.250)]
    _, _, p_rep   = place_routed_sub(c, subs["sync2_ck_replica_bias_pdk"], 0.000,   4.100)
    _, _, p_ckfe  = place_routed_sub(c, subs["sync2_ck_frontend_pdk"],    44.685,   0.000)
    _, _, p_x1    = place_routed_sub(c, subs["sync2_mux2_pdk"],           72.035,   5.050)
    _, _, p_t2    = place_routed_sub(c, subs["sync2_mux2_pdk"],           84.000,   5.050)
    _, _, p_x2    = place_routed_sub(c, subs["sync2_mux2_pdk"],           96.500,   5.050)

    # Row B (y1 = 49.000, mirror_y=True -> Head=VDD aligned at y=50.575, Foot=VSS aligned at top y=76.425):
    #   33.40 um tight slice pitch: [Xff0(10.725..28.475)|Xq2buf(30.475..39.625)] [Xff1(44.125..61.875)|Xq4buf] [Xff2|Xq8buf(97.275..106.425)]
    _, _, p_ff0   = place_routed_sub(c, subs["sync2_dff_pdk"],            10.725,  49.000, mirror_y=True)
    _, _, p_q2buf = place_routed_sub(c, subs["sync2_buf_out_pdk"],        30.475,  49.000, mirror_y=True)
    _, _, p_ff1   = place_routed_sub(c, subs["sync2_dff_pdk"],            44.125,  49.000, mirror_y=True)
    _, _, p_q4buf = place_routed_sub(c, subs["sync2_buf_out_pdk"],        63.875,  49.000, mirror_y=True)
    _, _, p_ff2   = place_routed_sub(c, subs["sync2_dff_pdk"],            77.525,  49.000, mirror_y=True)
    _, _, p_q8buf = place_routed_sub(c, subs["sync2_buf_out_pdk"],        97.275,  49.000, mirror_y=True)

    # 2. Bias & Clock Input Distribution
    # vbias_ck: Xrep (42.185, 32.490 M2) -> Xckfe (44.865, 41.555 M2) inside gap x=43.20
    _, rvc_x, rvc_y = p_rep["vbias_ck"]
    _, fvc_x, fvc_y = p_ckfe["vbias_ck"]
    c.wire("metal2", [(rvc_x, rvc_y), (43.200, rvc_y), (43.200, fvc_y), (fvc_x, fvc_y)], 0.36)

    # vbias: Xrep -> Xckfe -> bottom M2 bus (y=-1.30) -> Xx1/t2/x2 -> right perimeter spine (x=108.10) -> top M2 bus (y=77.50) -> Xq2/4/8buf
    _, rvb_x, rvb_y = p_rep["vbias"]
    _, fvb_x, fvb_y = p_ckfe["vbias"]
    c.wire("metal2", [(rvb_x, rvb_y), (43.200, rvb_y), (43.200, fvb_y), (fvb_x, fvb_y)], 0.36)
    c.wire("metal2", [(43.200, fvb_y), (43.200, -1.300), (108.500, -1.300), (108.500, 77.500), (p_q2buf["vbias"][1], 77.500)], 0.36)
    for m_vb in (p_x1["vbias"], p_t2["vbias"], p_x2["vbias"]):
        c.wire("metal2", [(m_vb[1], -1.300), (m_vb[1], m_vb[2])], 0.34)
    for b_vb in (p_q2buf["vbias"], p_q4buf["vbias"], p_q8buf["vbias"]):
        c.wire("metal2", [(b_vb[1], 77.500), (b_vb[1], b_vb[2])], 0.34)
    c.port("vbias", "metal2", 108.500, 40.000)

    # clkp / clkn straight down on M3 to bottom edge (y=-2.00), passing over vss (M1@-0.50) and vbias (M2@-1.30)
    _, clkp_x, clkp_y = p_ckfe["clkp"]
    _, clkn_x, clkn_y = p_ckfe["clkn"]
    c.wire("metal3", [(clkp_x, clkp_y), (43.900, clkp_y), (43.900, -2.000)], 0.38)
    c.wire("metal3", [(clkn_x, clkn_y), (70.000, clkn_y), (70.000, -2.000)], 0.38)
    c.port("clkp", "metal3", 43.900, -2.000)
    c.port("clkn", "metal3", 70.000, -2.000)

    # 3. Shielded Symmetric M4 T-Tree Clock in Tight Central Bay [46.15 .. 47.85]
    x_ctr = 56.865
    _, fckp_x, fckp_y = p_ckfe["ckp"]
    _, fckn_x, fckn_y = p_ckfe["ckn"]
    y_ckn_m4, y_gnd_m4, y_ckp_m4, y_hop_m4 = 46.150, 47.000, 47.850, 48.850

    # Step Xckfe.ckn stem slightly left from 58.965 to 57.500 at y=43.65 (0.62um above Xccn@42.84) to clear Xff1.qp (59.05)
    c.wire("metal3", [(fckn_x, fckn_y), (fckn_x, 43.650), (57.500, 43.650), (57.500, y_ckn_m4)], 0.38); rb.via3(c, 57.500, y_ckn_m4)
    c.wire("metal3", [(fckp_x, fckp_y), (fckp_x, y_ckp_m4)], 0.38); rb.via3(c, fckp_x, y_ckp_m4)

    # Tap all 3 DFFs symmetrically at their LEFT edges (Xff0: 11.80/12.80, Xff1: 45.20/46.20, Xff2: 79.60/80.60)
    c.wire("metal4", [(11.800, y_ckn_m4), (79.600, y_ckn_m4)], 0.40)
    c.wire("metal4", [(12.800, y_ckp_m4), (80.600, y_ckp_m4)], 0.40)
    for pf, x_tn, x_tp in (
        (p_ff0, 11.800, 12.800),
        (p_ff1, 45.200, 46.200),
        (p_ff2, 79.600, 80.600),
    ):
        rb.via3(c, x_tp, pf["ckp"][2])
        c.wire("metal4", [(x_tp, y_ckp_m4), (x_tp, pf["ckp"][2])], 0.38)
        rb.via3(c, x_tn, y_ckn_m4)
        c.wire("metal3", [(x_tn, y_ckn_m4), (x_tn, y_hop_m4)], 0.36)
        rb.via3(c, x_tn, y_hop_m4)
        c.wire("metal4", [(x_tn, y_hop_m4), (x_tn, pf["ckn"][2])], 0.38)
        rb.via3(c, x_tn, pf["ckn"][2])

    # M4 shield GND strip between ckn and ckp spines tied at left/right VSS perimeter spines
    c.wire("metal4", [(-1.300, y_gnd_m4), (109.500, y_gnd_m4)], 0.30)
    for x_sh in (-1.300, 109.500):
        rb.via3(c, x_sh, y_gnd_m4); c.via2(x_sh, y_gnd_m4); c.via1(x_sh, y_gnd_m4)

    # 4. Compact Central M2 Channel [43.35 .. 48.25] + Local Row-A/Row-B Data Links
    y_b0p, y_b0n = 48.250, 47.550
    y_b1p, y_b1n = 46.850, 46.150
    y_d1p, y_d1n = 45.450, 44.750  # shares track height with b2 (d1 ends x=78.36 < Xt2.ap x=83.30!)
    y_b2p, y_b2n = 45.450, 44.750
    y_d2p, y_d2n = 44.050, 43.350

    def rise_dff_left_in(pf, y_dp_trk, y_dn_trk, x_dp_out, x_dn_in):
        _, xdp, ydp = pf["dp"]
        _, xdn, ydn = pf["dn"]
        c.via2(x_dp_out, y_dp_trk)
        c.wire("metal3", [(x_dp_out, y_dp_trk), (x_dp_out, ydp)], 0.34)
        c.via2(x_dp_out, ydp)
        c.wire("metal2", [(x_dp_out, ydp), (xdp, ydp)], 0.32)
        c.via2(x_dn_in, y_dn_trk)
        c.wire("metal3", [(x_dn_in, y_dn_trk), (x_dn_in, ydn), (xdn, ydn)], 0.34)

    # Xff0 feedback: b0n -> Xff0.dp (x=8.70), b0p -> Xff0.dn (x=9.70)
    rise_dff_left_in(p_ff0, y_b0n, y_b0p, 8.700, 9.700)
    # Xx1 -> Xff1: d1p -> Xff1.dp (x=42.15), d1n -> Xff1.dn (x=43.05) + M2 central track
    rise_dff_left_in(p_ff1, y_d1p, y_d1n, 42.150, 43.050)
    c.via2(p_x1["qp"][1], p_x1["qp"][2]); c.wire("metal3", [(p_x1["qp"][1], p_x1["qp"][2]), (p_x1["qp"][1], y_d1p)], 0.34); c.via2(p_x1["qp"][1], y_d1p)
    c.via2(p_x1["qn"][1], p_x1["qn"][2]); c.wire("metal3", [(p_x1["qn"][1], p_x1["qn"][2]), (p_x1["qn"][1], y_d1n)], 0.34); c.via2(p_x1["qn"][1], y_d1n)
    c.wire("metal2", [(42.150, y_d1p), (p_x1["qp"][1], y_d1p)], 0.32)
    c.wire("metal2", [(43.050, y_d1n), (p_x1["qn"][1], y_d1n)], 0.32)
    # Xx2 -> Xff2: d2p -> Xff2.dp (x=75.75), d2n -> Xff2.dn (x=76.55) + M2 central track
    rise_dff_left_in(p_ff2, y_d2p, y_d2n, 75.750, 76.550)
    c.via2(p_x2["qp"][1], p_x2["qp"][2]); c.wire("metal3", [(p_x2["qp"][1], p_x2["qp"][2]), (p_x2["qp"][1], y_d2p)], 0.34); c.via2(p_x2["qp"][1], y_d2p)
    c.via2(p_x2["qn"][1], p_x2["qn"][2]); c.wire("metal3", [(p_x2["qn"][1], p_x2["qn"][2]), (p_x2["qn"][1], y_d2n)], 0.34); c.via2(p_x2["qn"][1], y_d2n)
    c.wire("metal2", [(75.750, y_d2p), (p_x2["qp"][1], y_d2p)], 0.32)
    c.wire("metal2", [(76.550, y_d2n), (p_x2["qn"][1], y_d2n)], 0.32)

    # Xt2 -> Xx2 local links above mux load outputs (M2 free band y=[29.0..40.0])
    _, t2qp_x, t2qp_y = p_t2["qp"]
    _, x2bp_x, x2bp_y = p_x2["bp"]
    c.via2(t2qp_x, t2qp_y); c.wire("metal3", [(t2qp_x, t2qp_y), (t2qp_x, 31.200)], 0.34); c.via2(t2qp_x, 31.200)
    c.wire("metal2", [(t2qp_x, 31.200), (95.950, 31.200)], 0.34)
    c.via2(95.950, 31.200); c.wire("metal3", [(95.950, 31.200), (95.950, x2bp_y)], 0.34); c.via2(95.950, x2bp_y)
    c.wire("metal2", [(95.950, x2bp_y), (x2bp_x, x2bp_y)], 0.32)

    _, t2qn_x, t2qn_y = p_t2["qn"]
    _, x2bn_x, x2bn_y = p_x2["bn"]
    c.wire("metal2", [(t2qn_x, t2qn_y), (t2qn_x, 30.200), (x2bn_x, 30.200)], 0.34)
    c.via2(x2bn_x, 30.200); c.wire("metal3", [(x2bn_x, 30.200), (x2bn_x, x2bn_y)], 0.34); c.via2(x2bn_x, x2bn_y)

    # Xff0/1/2 qp/qn -> straight DOWN on M3 out of Xff bottom to M2 channel tracks
    for pf, ytp, ytn in ((p_ff0, y_b0p, y_b0n), (p_ff1, y_b1p, y_b1n), (p_ff2, y_b2p, y_b2n)):
        for (_, px, py), yt in ((pf["qp"], ytp), (pf["qn"], ytn)):
            c.via2(px, py)
            c.wire("metal3", [(px, py), (px, yt)], 0.34)
            c.via2(px, yt)

    # Xq2/4/8buf inputs (b0/1/2) rise cleanly on M3 up to y=65.965 (Xq8.inp shares x=96.800 with Xx2.ap!)
    for pbuf, ytp, ytn, x_in_p, x_in_n in (
        (p_q2buf, y_b0p, y_b0n, 29.400, 40.250),
        (p_q4buf, y_b1p, y_b1n, 62.800, 73.700),
        (p_q8buf, y_b2p, y_b2n, p_x2["ap"][1], 107.750),
    ):
        for b_pt, yt, x_r in ((pbuf["inp"], ytp, x_in_p), (pbuf["inn"], ytn, x_in_n)):
            _, bx, by = b_pt
            c.via2(x_r, yt); c.wire("metal3", [(x_r, yt), (x_r, by)], 0.34); c.via2(x_r, by)
            c.wire("metal2", [(x_r, by), (bx, by)], 0.32)

    def mux_drop(mux_pt: tuple[str, float, float], x_lane: float, y_trk: float) -> float:
        _, px, py = mux_pt
        c.via2(x_lane, y_trk)
        c.wire("metal3", [(x_lane, y_trk), (x_lane, py)], 0.34)
        c.via2(x_lane, py)
        if x_lane != px:
            c.wire("metal2", [(x_lane, py), (px, py)], 0.32)
        return x_lane

    # b0p (48.25): 9.70 .. Xx2.sp(106.90)
    x_b0p_xs = [p_ff0["qp"][1], 9.700, 29.400, mux_drop(p_x1["sp"], 81.800, y_b0p), mux_drop(p_x2["sp"], 106.900, y_b0p)]
    c.wire("metal2", [(min(x_b0p_xs), y_b0p), (max(x_b0p_xs), y_b0p)], 0.32)
    # b0n (47.55): 8.70 .. Xx2.sn(95.25)
    x_b0n_xs = [p_ff0["qn"][1], 8.700, 40.250, mux_drop(p_x1["sn"], 70.750, y_b0n), mux_drop(p_x2["sn"], 95.250, y_b0n)]
    c.wire("metal2", [(min(x_b0n_xs), y_b0n), (max(x_b0n_xs), y_b0n)], 0.32)

    # b1p (46.85): Xff1(59.05) .. Xt2.sp(93.80) + Xx1.ap(71.50) <-> Xx1.bn crossbar @ y=21.00 M3
    x_b1p_xs = [p_ff1["qp"][1], 62.800, mux_drop(p_x1["ap"], 71.500, y_b1p), mux_drop(p_t2["sp"], 93.800, y_b1p)]
    c.wire("metal2", [(min(x_b1p_xs), y_b1p), (max(x_b1p_xs), y_b1p)], 0.32)
    c.via2(p_x1["ap"][1], p_x1["ap"][2]); c.via2(p_x1["bn"][1], p_x1["bn"][2])
    c.wire("metal3", [(p_x1["ap"][1], p_x1["ap"][2]), (p_x1["ap"][1], 21.000), (p_x1["bn"][1], 21.000), (p_x1["bn"][1], p_x1["bn"][2])], 0.34)

    # b1n (46.15): Xff1(55.55) .. Xt2.sn(82.55) + M2 bridge @ y=32.50 across Xx1 to Xx1.bp(72.335, 23.955)
    x_b1n_xs = [p_ff1["qn"][1], 73.700, mux_drop(p_x1["an"], 82.550, y_b1n), mux_drop(p_t2["sn"], 82.550, y_b1n)]
    c.wire("metal2", [(min(x_b1n_xs), y_b1n), (max(x_b1n_xs), y_b1n)], 0.32)
    c.via2(82.550, 32.500)
    c.wire("metal2", [(82.550, 32.500), (p_x1["bp"][1], 32.500)], 0.34)
    c.via2(p_x1["bp"][1], 32.500)
    c.wire("metal3", [(p_x1["bp"][1], 32.500), (p_x1["bp"][1], p_x1["bp"][2])], 0.34)
    c.via2(p_x1["bp"][1], p_x1["bp"][2])

    # b2p (45.45): Xt2.ap(83.30) .. Xx2.ap(96.80, shared with Xq8.inp!) + Xt2.ap <-> Xt2.bn crossbar @ y=21.00 M3
    x_b2p_xs = [p_ff2["qp"][1], mux_drop(p_t2["ap"], 83.300, y_b2p), mux_drop(p_x2["ap"], p_x2["ap"][1], y_b2p)]
    c.wire("metal2", [(min(x_b2p_xs), y_b2p), (max(x_b2p_xs), y_b2p)], 0.32)
    c.via2(p_t2["ap"][1], p_t2["ap"][2]); c.via2(p_t2["bn"][1], p_t2["bn"][2])
    c.wire("metal3", [(p_t2["ap"][1], p_t2["ap"][2]), (p_t2["ap"][1], 21.000), (p_t2["bn"][1], 21.000), (p_t2["bn"][1], p_t2["bn"][2])], 0.34)

    # b2n (44.75): Xt2.an(94.55) .. Xx2.an(106.15) .. Xq8.inn(107.75) + M2 bridge @ y=32.50 across Xt2 to Xt2.bp(84.300, 23.955)
    x_b2n_xs = [p_ff2["qn"][1], 107.750, mux_drop(p_t2["an"], 94.550, y_b2n), mux_drop(p_x2["an"], 106.150, y_b2n)]
    c.wire("metal2", [(min(x_b2n_xs), y_b2n), (max(x_b2n_xs), y_b2n)], 0.32)
    c.via2(94.550, 32.500)
    c.wire("metal2", [(94.550, 32.500), (p_t2["bp"][1], 32.500)], 0.34)
    c.via2(p_t2["bp"][1], 32.500)
    c.wire("metal3", [(p_t2["bp"][1], 32.500), (p_t2["bp"][1], p_t2["bp"][2])], 0.34)
    c.via2(p_t2["bp"][1], p_t2["bp"][2])

    # 5. Outputs q2p/n, q4p/n, q8p/n straight UP on M3 out of top chip edge (y=78.70)
    for out_nm, buf_pt in (
        ("q2p", p_q2buf["outp"]), ("q2n", p_q2buf["outn"]),
        ("q4p", p_q4buf["outp"]), ("q4n", p_q4buf["outn"]),
        ("q8p", p_q8buf["outp"]), ("q8n", p_q8buf["outn"]),
    ):
        _, bx, by = buf_pt
        c.via2(bx, by)
        c.wire("metal3", [(bx, by), (bx, 78.700)], 0.36)
        c.port(out_nm, "metal3", bx, 78.700)

    # 6. Head-to-Head Shared Central VDD (y=50.575 M2) & Perimeter Foot-to-Foot VSS Ring (y=-0.50 / 76.425 M1)
    y_mid_vdd = p_ff0["vdd"][2]  # 50.575
    c.wire("metal2", [(10.725, y_mid_vdd), (106.425, y_mid_vdd)], 0.80)
    # Row A VDD taps rise straight UP on M3 to shared y_mid_vdd (Xckfe steps out to x=69.950 to clear right MIM cap!)
    _, rvdd_x, rvdd_y = p_rep["vdd"]
    c.via2(41.150, rvdd_y); c.wire("metal3", [(41.150, rvdd_y), (41.150, y_mid_vdd)], 0.42); c.via2(41.150, y_mid_vdd)
    c.wire("metal2", [(p_ckfe["vdd"][1], p_ckfe["vdd"][2]), (69.950, p_ckfe["vdd"][2])], 0.42)
    for x_tap, y_tap in (
        (69.950, p_ckfe["vdd"][2]),
        (77.450, p_x1["vdd"][2]),  # shifts between d2n(76.55) and Xx1.qp(78.36)
        (87.300, p_t2["vdd"][2]),  # shifts left of Xff2.qn(88.95)
        (p_x2["vdd"][1], p_x2["vdd"][2]),
    ):
        c.via2(x_tap, y_tap); c.wire("metal3", [(x_tap, y_tap), (x_tap, y_mid_vdd)], 0.40); c.via2(x_tap, y_mid_vdd)
    c.port("vdd", "metal2", x_ctr, y_mid_vdd)

    # VSS M1 perimeter & Foot rails (bottom=-0.50, top=76.425, left=-1.30, right=109.50)
    y_bot_vss, y_top_vss = -0.500, p_ff0["vss"][2]  # 76.425
    c.wire("metal1", [(-1.300, y_bot_vss), (109.500, y_bot_vss)], 0.65)
    c.wire("metal1", [(-1.300, y_top_vss), (109.500, y_top_vss)], 0.65)
    for xv_sp in (-1.300, 109.500):
        c.wire("metal1", [(xv_sp, y_bot_vss), (xv_sp, y_top_vss)], 0.65)
    for vs_pt in (p_rep["vss"], p_ckfe["vss"], p_x1["vss"], p_t2["vss"], p_x2["vss"]):
        c.wire("metal1", [(vs_pt[1], vs_pt[2]), (vs_pt[1], y_bot_vss)], 0.55)
    for bx_buf, vs_pt in ((p_q2buf["vss"][1], p_q2buf["vss"]), (p_q4buf["vss"][1], p_q4buf["vss"]), (p_q8buf["vss"][1], p_q8buf["vss"])):
        c.wire("metal1", [(bx_buf, vs_pt[2]), (bx_buf, y_top_vss)], 0.55)
    c.port("vss", "metal1", x_ctr, y_bot_vss)

    c.write(w / f"{name}.mag")

    # Flatten subcell ref SPICE into top-level to match flat Magic extraction 1:1
    subckt_texts = [(out / sn / f"{sn}_ref.spice").read_text() for sn in sub_names]
    instances = [
        ("Xrep",   "sync2_ck_replica_bias_pdk", ["vbias", "vbias_ck", "vdd", "vss"]),
        ("Xckfe",  "sync2_ck_frontend_pdk",     ["clkp", "clkn", "ck_pre_p", "ck_pre_n", "ckp", "ckn", "vbias", "vbias_ck", "vdd", "vss"]),
        ("Xff0",   "sync2_dff_pdk",             ["b0n", "b0p", "b0p", "b0n", "ckp", "ckn", "vdd", "vss"]),
        ("Xff1",   "sync2_dff_pdk",             ["d1p", "d1n", "b1p", "b1n", "ckp", "ckn", "vdd", "vss"]),
        ("Xff2",   "sync2_dff_pdk",             ["d2p", "d2n", "b2p", "b2n", "ckp", "ckn", "vdd", "vss"]),
        ("Xx1",    "sync2_mux2_pdk",            ["b1p", "b1n", "b1n", "b1p", "b0p", "b0n", "d1p", "d1n", "vbias", "vdd", "vss"]),
        ("Xt2",    "sync2_mux2_pdk",            ["b2p", "b2n", "b2n", "b2p", "b1p", "b1n", "t2p", "t2n", "vbias", "vdd", "vss"]),
        ("Xx2",    "sync2_mux2_pdk",            ["b2p", "b2n", "t2p", "t2n", "b0p", "b0n", "d2p", "d2n", "vbias", "vdd", "vss"]),
        ("Xq2buf", "sync2_buf_out_pdk",         ["b0p", "b0n", "q2p", "q2n", "vbias", "vdd", "vss"]),
        ("Xq4buf", "sync2_buf_out_pdk",         ["b1p", "b1n", "q4p", "q4n", "vbias", "vdd", "vss"]),
        ("Xq8buf", "sync2_buf_out_pdk",         ["b2p", "b2n", "q8p", "q8n", "vbias", "vdd", "vss"]),
    ]
    top_ref = flatten_subckt_instances(
        subckt_texts,
        instances,
        name,
        ["clkp", "clkn", "q2p", "q2n", "q4p", "q4n", "q8p", "q8n", "vbias", "vdd", "vss"],
    )

    subprocess.run(
        [sys.executable, str(REPO / "verification/layout/plot_mag.py"),
         str(w / f"{name}.mag"), str(w / f"{name}.png")],
        cwd=REPO, check=True, capture_output=True,
    )
    for stale in (w / f"{name}.res.ext", w / f"{name}.ext", w / f"{name}_rcx.spice"):
        if stale.exists():
            stale.unlink()
    info = run_signoff(w, name, top_ref)
    rcx = w / f"{name}_rcx.spice"
    if rcx.exists():
        rcx.unlink()
    float_a: list[str] = []
    try:
        rc = review_cell.extract_rc(w, name)
        rc_note = f"ok (R={rc['resistor_count']})"
    except Exception as e:
        rc_note = str(e)
    pex_txt = (w / f"{name}_pex.spice").read_text()
    non_cap = set()
    for ln in pex_txt.splitlines():
        toks = ln.split()
        if toks and not toks[0].startswith(("*", ".", "+")) and not toks[0].lower().startswith("c"):
            non_cap.update(toks[1:])
    float_a = sorted({
        t for ln in pex_txt.splitlines() if ln.lower().startswith("c")
        for t in ln.split()[1:3] if t.startswith("a_") and t not in non_cap
    })
    ports = exported_ports(w / f"{name}_lvs.spice", name)
    pex = summarize_pex_spice(w / f"{name}_pex.spice", ports)
    info["rc_note"] = rc_note
    info["floating_a_nodes"] = float_a
    info["port_caps_fF"] = {k: round(v["total_node_fF"], 3) for k, v in pex["port_caps_fF"].items()}

    if inst_dir is not None:
        inst_dir.mkdir(parents=True, exist_ok=True)
        for ext in (".mag", ".png"):
            shutil.copy2(w / f"{name}{ext}", inst_dir / f"{name}{ext}")
        sum_p = inst_dir / "summary.json"
        if sum_p.exists():
            cur = json.loads(sum_p.read_text())
            cur[name] = info
            sum_p.write_text(json.dumps(cur, indent=2))
    print(json.dumps(info, indent=2))
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=REPO / "results/layout/sync2_divider/compact_routed")
    ap.add_argument("--sub-dir", type=Path, default=REPO / "analog/pll/divider/layout/variants/sync2_routed")
    ap.add_argument("--install-dir", type=Path, default=REPO / "analog/pll/divider/layout/variants/sync2_routed")
    a = ap.parse_args()
    build_top(a.out.resolve(), a.sub_dir.resolve(), a.install_dir.resolve())


if __name__ == "__main__":
    main()
