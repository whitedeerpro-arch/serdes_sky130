#!/usr/bin/env python3
"""Root-cause screening, 45-corner PVT, 200-sample MC, and CPEX MC verification
for hardening SAFF-TSPC /8 (`pll_saff_reclock_prescaler8_2g`) cold-corner mismatch yield (I-TOP-03).

Outputs strictly under `results/analog/pll/divider/tspc_harden_20261123/`.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import time

import numpy as np

from serdes_flow import bias, clock, corners, mc, spice, stats
from serdes_flow.project import ROOT

sys.path.insert(0, str(ROOT / "verification/layout"))
sys.path.insert(0, str(ROOT / "analog/pll/divider/tb/tspc_study"))
from review_sim import freeze_includes, save_analysis
import benchmark as bm

OUT_ROOT = ROOT / "results/analog/pll/divider/tspc_harden_20261123"
CAND_SPICE = ROOT / "analog/pll/divider/spice/tspc_reclock_prescaler8_2g_v2_cand.spice"
BASE_SPICE = ROOT / "analog/pll/divider/spice/tspc_reclock_prescaler8_2g.spice"
R5_PEX = bm.R5_PEX
R5_RCX = bm.R5_RCX

WORST5 = [
    ("ss_v1650_t-40", "hh"),
    ("fs_v1650_t85", "hh"),
    ("sf_v1650_t-40", "ll"),
    ("ff_v1950_t-40", "ll"),
    ("tt_v1800_t27", "tt"),
]


COMMON_SUBCKTS = """\
* Common helpers for SAFF-TSPC /8 hardening candidates
.subckt tspc_inv a y vdd vss params: wn=1.0 nfn=1 wp=2.2 nfp=1
Xn y a vss vss serdes_nfet w={wn} nf={nfn}
Xp y a vdd vdd serdes_pfet w={wp} nf={nfp}
.ends tspc_inv

.subckt tspc_inv_lvt a y vdd vss params: wn=1.0 nfn=1 wp=2.2 nfp=1
Xn y a vss vss serdes_nfet_lvt w={wn} nf={nfn}
Xp y a vdd vdd serdes_pfet w={wp} nf={nfp}
.ends tspc_inv_lvt

.subckt tspc_tgmux a b s sb y vdd vss params: wn=1.0 nfn=1 wp=2.0 nfp=1
Xna y sb a vss serdes_nfet w={wn} nf={nfn}
Xpa y s  a vdd serdes_pfet w={wp} nf={nfp}
Xnb y s  b vss serdes_nfet w={wn} nf={nfn}
Xpb y sb b vdd serdes_pfet w={wp} nf={nfp}
.ends tspc_tgmux

.subckt tspc_tgmux_lvt a b s sb y vdd vss params: wn=2.0 nfn=2 wp=3.6 nfp=2
Xna y sb a vss serdes_nfet_lvt w={wn} nf={nfn}
Xpa y s  a vdd serdes_pfet w={wp} nf={nfp}
Xnb y s  b vss serdes_nfet_lvt w={wn} nf={nfn}
Xpb y sb b vdd serdes_pfet w={wp} nf={nfp}
.ends tspc_tgmux_lvt

* Static Restoring LVT-CMOS Differential XOR/XNOR:
*   d2p = b1p ? b2n : b2p = ~( (b1p & b2p) | (b1n & b2n) )
*   d2n = b1p ? b2p : b2n = ~( (b1p & b2n) | (b1n & b2p) )
* Zero transmission gates, zero b2p<->b2n shorting, full rail-to-rail gain!
.subckt tspc_xor_diff b1p b1n b2p b2n d2p d2n vdd vss params: wn=1.5 nfn=1 wp=2.8 nfp=1
* d2p pull-down (LVT NMOS)
Xnp1a np1 b1p vss vss serdes_nfet_lvt w={wn} nf={nfn}
Xnp1b d2p b2p np1 vss serdes_nfet_lvt w={wn} nf={nfn}
Xnp2a np2 b1n vss vss serdes_nfet_lvt w={wn} nf={nfn}
Xnp2b d2p b2n np2 vss serdes_nfet_lvt w={wn} nf={nfn}
* d2p pull-up (PMOS)
Xpp1a pp1 b1p vdd vdd serdes_pfet w={wp} nf={nfp}
Xpp1b d2p b2n pp1 vdd serdes_pfet w={wp} nf={nfp}
Xpp2a pp2 b1n vdd vdd serdes_pfet w={wp} nf={nfp}
Xpp2b d2p b2p pp2 vdd serdes_pfet w={wp} nf={nfp}
* d2n pull-down (LVT NMOS)
Xnn1a nn1 b1p vss vss serdes_nfet_lvt w={wn} nf={nfn}
Xnn1b d2n b2n nn1 vss serdes_nfet_lvt w={wn} nf={nfn}
Xnn2a nn2 b1n vss vss serdes_nfet_lvt w={wn} nf={nfn}
Xnn2b d2n b2p nn2 vss serdes_nfet_lvt w={wn} nf={nfn}
* d2n pull-up (PMOS)
Xpn1a pn1 b1p vdd vdd serdes_pfet w={wp} nf={nfp}
Xpn1b d2n b2p pn1 vdd serdes_pfet w={wp} nf={nfp}
Xpn2a pn2 b1n vdd vdd serdes_pfet w={wp} nf={nfp}
Xpn2b d2n b2n pn2 vdd serdes_pfet w={wp} nf={nfp}
.ends tspc_xor_diff

.subckt tspc_outbuf qp_i qn_i qp qn vdd vss params: wn=2.4 nfn=2 wp=5.2 nfp=2 wkn=0.50 wkp=1.05
Xobp qp_i qp vdd vss tspc_inv wn={wn} nfn={nfn} wp={wp} nfp={nfp}
Xobn qn_i qn vdd vss tspc_inv wn={wn} nfn={nfn} wp={wp} nfp={nfp}
Xkp  qp   qn vdd vss tspc_inv wn={wkn} nfn=1 wp={wkp} nfp=1
Xkn  qn   qp vdd vss tspc_inv wn={wkn} nfn=1 wp={wkp} nfp=1
.ends tspc_outbuf

.subckt tspc_ckbuf clkp clkn ck_2g vdd vss params: wn1=2.4 wp1=6.0 wn2=10.8 wp2=24.0
X1p clkp ck1n vdd vss tspc_inv wn={wn1} nfn=2 wp={wp1} nfp=2
X1n clkn ck1p vdd vss tspc_inv wn={wn1} nfn=2 wp={wp1} nfp=2
Xk1p ck1p ck1n vdd vss tspc_inv wn=0.45 nfn=1 wp=1.00 nfp=1
Xk1n ck1n ck1p vdd vss tspc_inv wn=0.45 nfn=1 wp=1.00 nfp=1
X2p ck1n ck_2g vdd vss tspc_inv wn={wn2} nfn=4 wp={wp2} nfp=4
X2n_dum ck1p ck_dum vdd vss tspc_inv wn={wn2*0.25} nfn=2 wp={wp2*0.25} nfp=2
Xcdum vss ck_dum vss vss serdes_nfet w=4.0 l=0.5 nf=2
.ends tspc_ckbuf

.subckt saff_tspc_dff dp dn ck qp qn vdd vss
+ params: wt=4.4 nft=2 wd=2.8 nfd=2 wl=2.4 nfl=2 wlp=1.6 nflp=1 wpre=2.4 wmid=1.2 weq=1.8
+         wop=2.8 nfop=2 wdn=2.4 nfdn=2 winv_n=0.80 winv_p=1.75 wkp=0.70 wkn=0.60 seed_k=0.0
Xtail tail ck   vss  vss serdes_nfet_lvt w={wt}  nf={nft}
Xdp   n_sp dp   tail vss serdes_nfet_lvt w={wd}  nf={nfd}
Xdn   n_sn dn   tail vss serdes_nfet_lvt w={wd}  nf={nfd}
Xlnp  sp   sn   n_sp vss serdes_nfet_lvt w={wl}  nf={nfl}
Xlnn  sn   sp   n_sn vss serdes_nfet_lvt w={wl}  nf={nfl}
Xlpp  sp   sn   vdd  vdd serdes_pfet     w={wlp} nf={nflp}
Xlpn  sn   sp   vdd  vdd serdes_pfet     w={wlp} nf={nflp}
Xprep sp   ck   vdd  vdd serdes_pfet     w={wpre} nf=2
Xpren sn   ck   vdd  vdd serdes_pfet     w={wpre} nf=2
Xeq   sp   ck   sn   vdd serdes_pfet     w={weq}  nf=1
Xpmp  n_sp ck   vdd  vdd serdes_pfet     w={wmid} nf=1
Xpmn  n_sn ck   vdd  vdd serdes_pfet     w={wmid} nf=1
Xinvs sp   sb   vdd  vss tspc_inv        wn={winv_n} nfn=1 wp={winv_p} nfp=1
Xinvr sn   rb   vdd  vss tspc_inv        wn={winv_n} nfn=1 wp={winv_p} nfp=1
Xpp_s qp   sp   vdd  vdd serdes_pfet     w={wop} nf={nfop}
Xdp_d qp   rb   vss  vss serdes_nfet_lvt w={wdn} nf={nfdn}
Xpn_s qn   sn   vdd  vdd serdes_pfet     w={wop} nf={nfop}
Xdn_d qn   sb   vss  vss serdes_nfet_lvt w={wdn} nf={nfdn}
Xkp_p qp   qn   vdd  vdd serdes_pfet     w={wkp+seed_k} nf=1
Xkp_n qp   qn   vss  vss serdes_nfet     w={wkn}        nf=1
Xkn_p qn   qp   vdd  vdd serdes_pfet     w={wkp}        nf=1
Xkn_n qn   qp   vss  vss serdes_nfet     w={wkn+seed_k} nf=1
.ends saff_tspc_dff
"""


def _cand_body(kind: str, wire_caps: bool = False) -> str:
    """Return a full standalone candidate netlist for screening."""
    # Realistic CPEX wire capacitance model derived from Magic extraction of v2 PDK layout
    caps_direct = """\
C_w_ck  ck_2g 0 39f
C_w_b0n b0n   0 22f
C_w_b0p b0p   0 7f
C_w_b1p b1p   0 12f
C_w_b1n b1n   0 12f
C_w_b2p b2p   0 9f
C_w_b2n b2n   0 9f
C_w_d2p d2p   0 4f
C_w_d2n d2n   0 4f
""" if wire_caps else ""

    caps_ck1g = """\
C_w_ck   ck_2g 0 39f
C_w_b0n  b0n   0 8f
C_w_b0p  b0p   0 8f
C_w_ck1g ck_1g 0 18f
C_w_b1p  b1p   0 12f
C_w_b1n  b1n   0 12f
C_w_b2p  b2p   0 9f
C_w_b2n  b2n   0 9f
C_w_d2p  d2p   0 4f
C_w_d2n  d2n   0 4f
""" if wire_caps else ""

    if kind == "baseline":
        sub = f"""\
.subckt pll_saff_reclock_prescaler8_2g clkp clkn q2p q2n q4p q4n q8p q8n vdd vss
Xck clkp clkn ck_2g vdd vss tspc_ckbuf wn1=2.4 wp1=6.0 wn2=10.8 wp2=24.0
Xff0 b0n b0p ck_2g b0p b0n vdd vss saff_tspc_dff wt=5.4 nft=2 wd=3.4 nfd=2 wl=2.8 nfl=2 wlp=1.6 wpre=2.8 wmid=1.3 weq=2.2 wop=3.8 nfop=2 wdn=3.4 nfdn=2 wkp=0.65 wkn=0.55 seed_k=0.30
Xff1 b1n b1p b0n b1p b1n vdd vss saff_tspc_dff wt=4.4 nft=2 wd=2.8 nfd=2 wl=2.4 nfl=2 wlp=1.4 wpre=2.2 wmid=1.1 weq=1.8 wop=3.0 nfop=2 wdn=2.8 nfdn=2 wkp=0.60 wkn=0.50 seed_k=0.25
Xtg2p b2p b2n b1p b1n d2p vdd vss tspc_tgmux wn=1.3 nfn=1 wp=2.8 nfp=1
Xtg2n b2n b2p b1p b1n d2n vdd vss tspc_tgmux wn=1.3 nfn=1 wp=2.8 nfp=1
Xff2 d2p d2n b0n b2p b2n vdd vss saff_tspc_dff wt=4.4 nft=2 wd=2.8 nfd=2 wl=2.4 nfl=2 wlp=1.4 wpre=2.2 wmid=1.1 weq=1.8 wop=3.0 nfop=2 wdn=2.8 nfdn=2 wkp=0.60 wkn=0.50 seed_k=0.25
Xr0 b0p b0n ck_2g r0p r0n vdd vss saff_tspc_dff wt=4.4 nft=2 wd=2.8 nfd=2 wl=2.3 nfl=2 wlp=1.5 wpre=2.8 wmid=1.3 weq=2.0 wop=2.8 nfop=2 wdn=2.6 nfdn=2 wkp=0.65 wkn=0.55 seed_k=0.0
Xr1 b1p b1n ck_2g r1p r1n vdd vss saff_tspc_dff wt=4.4 nft=2 wd=2.8 nfd=2 wl=2.3 nfl=2 wlp=1.5 wpre=2.8 wmid=1.3 weq=2.0 wop=2.8 nfop=2 wdn=2.6 nfdn=2 wkp=0.65 wkn=0.55 seed_k=0.0
Xr2 b2p b2n ck_2g r2p r2n vdd vss saff_tspc_dff wt=4.4 nft=2 wd=2.8 nfd=2 wl=2.3 nfl=2 wlp=1.5 wpre=2.8 wmid=1.3 weq=2.0 wop=2.8 nfop=2 wdn=2.6 nfdn=2 wkp=0.65 wkn=0.55 seed_k=0.0
Xo0 r0n r0p q2p q2n vdd vss tspc_outbuf wn=2.6 nfn=2 wp=5.4 nfp=2 wkn=0.60 wkp=1.25
Xo1 r1n r1p q4p q4n vdd vss tspc_outbuf wn=2.6 nfn=2 wp=5.4 nfp=2 wkn=0.60 wkp=1.25
Xo2 r2n r2p q8p q8n vdd vss tspc_outbuf wn=3.0 nfn=2 wp=6.2 nfp=2 wkn=0.65 wkp=1.35
{caps_direct}.ends pll_saff_reclock_prescaler8_2g
"""
    elif kind == "cand1_lvt_tg_boost":
        sub = f"""\
.subckt pll_saff_reclock_prescaler8_2g clkp clkn q2p q2n q4p q4n q8p q8n vdd vss
Xck clkp clkn ck_2g vdd vss tspc_ckbuf wn1=2.4 wp1=6.0 wn2=10.8 wp2=24.0
Xff0 b0n b0p ck_2g b0p b0n vdd vss saff_tspc_dff wt=5.8 nft=2 wd=3.6 nfd=2 wl=3.0 nfl=2 wlp=1.8 wpre=3.0 wmid=1.4 weq=2.2 wop=5.6 nfop=2 wdn=4.8 nfdn=2 winv_n=1.0 winv_p=2.4 wkp=0.70 wkn=0.60 seed_k=0.45
Xff1 b1n b1p b0n b1p b1n vdd vss saff_tspc_dff wt=4.8 nft=2 wd=3.0 nfd=2 wl=2.6 nfl=2 wlp=1.5 wpre=2.4 wmid=1.2 weq=1.8 wop=3.4 nfop=2 wdn=3.2 nfdn=2 winv_n=0.95 winv_p=2.2 wkp=0.65 wkn=0.55 seed_k=0.40
Xtg2p b2p b2n b1p b1n d2p vdd vss tspc_tgmux_lvt wn=2.0 nfn=2 wp=3.8 nfp=2
Xtg2n b2n b2p b1p b1n d2n vdd vss tspc_tgmux_lvt wn=2.0 nfn=2 wp=3.8 nfp=2
Xff2 d2p d2n b0n b2p b2n vdd vss saff_tspc_dff wt=4.8 nft=2 wd=3.0 nfd=2 wl=2.6 nfl=2 wlp=1.5 wpre=2.4 wmid=1.2 weq=1.8 wop=3.4 nfop=2 wdn=3.2 nfdn=2 winv_n=0.95 winv_p=2.2 wkp=0.65 wkn=0.55 seed_k=0.40
Xr0 b0p b0n ck_2g r0p r0n vdd vss saff_tspc_dff wt=4.4 nft=2 wd=2.8 nfd=2 wl=2.3 nfl=2 wlp=1.5 wpre=2.8 wmid=1.3 weq=2.0 wop=2.8 nfop=2 wdn=2.6 nfdn=2 wkp=0.65 wkn=0.55 seed_k=0.0
Xr1 b1p b1n ck_2g r1p r1n vdd vss saff_tspc_dff wt=4.4 nft=2 wd=2.8 nfd=2 wl=2.3 nfl=2 wlp=1.5 wpre=2.8 wmid=1.3 weq=2.0 wop=2.8 nfop=2 wdn=2.6 nfdn=2 wkp=0.65 wkn=0.55 seed_k=0.0
Xr2 b2p b2n ck_2g r2p r2n vdd vss saff_tspc_dff wt=4.4 nft=2 wd=2.8 nfd=2 wl=2.3 nfl=2 wlp=1.5 wpre=2.8 wmid=1.3 weq=2.0 wop=2.8 nfop=2 wdn=2.6 nfdn=2 wkp=0.65 wkn=0.55 seed_k=0.0
Xo0 r0n r0p q2p q2n vdd vss tspc_outbuf wn=2.6 nfn=2 wp=5.4 nfp=2 wkn=0.60 wkp=1.25
Xo1 r1n r1p q4p q4n vdd vss tspc_outbuf wn=2.6 nfn=2 wp=5.4 nfp=2 wkn=0.60 wkp=1.25
Xo2 r2n r2p q8p q8n vdd vss tspc_outbuf wn=3.0 nfn=2 wp=6.2 nfp=2 wkn=0.65 wkp=1.35
{caps_direct}.ends pll_saff_reclock_prescaler8_2g
"""
    elif kind == "cand2_ck1g_lvt_tg":
        sub = f"""\
.subckt pll_saff_reclock_prescaler8_2g clkp clkn q2p q2n q4p q4n q8p q8n vdd vss
Xck clkp clkn ck_2g vdd vss tspc_ckbuf wn1=2.4 wp1=6.0 wn2=10.8 wp2=24.0
Xff0 b0n b0p ck_2g b0p b0n vdd vss saff_tspc_dff wt=5.4 nft=2 wd=3.4 nfd=2 wl=2.8 nfl=2 wlp=1.6 wpre=2.8 wmid=1.3 weq=2.2 wop=4.0 nfop=2 wdn=3.8 nfdn=2 winv_n=0.95 winv_p=2.3 wkp=0.65 wkn=0.55 seed_k=0.45
* Dedicated 1 GHz clock buffer (b0p -> ck_1g, full VDD rail-to-rail) + matched dummy on b0n
Xck1g     b0p ck_1g     vdd vss tspc_inv_lvt wn=4.8 nfn=4 wp=11.2 nfp=4
Xck1g_dum b0n ck_1g_dum vdd vss tspc_inv_lvt wn=4.8 nfn=4 wp=11.2 nfp=4
Xff1 b1n b1p ck_1g b1p b1n vdd vss saff_tspc_dff wt=4.4 nft=2 wd=2.8 nfd=2 wl=2.4 nfl=2 wlp=1.4 wpre=2.2 wmid=1.1 weq=1.8 wop=3.0 nfop=2 wdn=2.8 nfdn=2 winv_n=0.90 winv_p=2.2 wkp=0.60 wkn=0.50 seed_k=0.40
Xtg2p b2p b2n b1p b1n d2p vdd vss tspc_tgmux_lvt wn=2.0 nfn=2 wp=3.8 nfp=2
Xtg2n b2n b2p b1p b1n d2n vdd vss tspc_tgmux_lvt wn=2.0 nfn=2 wp=3.8 nfp=2
Xff2 d2p d2n ck_1g b2p b2n vdd vss saff_tspc_dff wt=4.4 nft=2 wd=2.8 nfd=2 wl=2.4 nfl=2 wlp=1.4 wpre=2.2 wmid=1.1 weq=1.8 wop=3.0 nfop=2 wdn=2.8 nfdn=2 winv_n=0.90 winv_p=2.2 wkp=0.60 wkn=0.50 seed_k=0.40
Xr0 b0p b0n ck_2g r0p r0n vdd vss saff_tspc_dff wt=4.4 nft=2 wd=2.8 nfd=2 wl=2.3 nfl=2 wlp=1.5 wpre=2.8 wmid=1.3 weq=2.0 wop=2.8 nfop=2 wdn=2.6 nfdn=2 wkp=0.65 wkn=0.55 seed_k=0.0
Xr1 b1p b1n ck_2g r1p r1n vdd vss saff_tspc_dff wt=4.4 nft=2 wd=2.8 nfd=2 wl=2.3 nfl=2 wlp=1.5 wpre=2.8 wmid=1.3 weq=2.0 wop=2.8 nfop=2 wdn=2.6 nfdn=2 wkp=0.65 wkn=0.55 seed_k=0.0
Xr2 b2p b2n ck_2g r2p r2n vdd vss saff_tspc_dff wt=4.4 nft=2 wd=2.8 nfd=2 wl=2.3 nfl=2 wlp=1.5 wpre=2.8 wmid=1.3 weq=2.0 wop=2.8 nfop=2 wdn=2.6 nfdn=2 wkp=0.65 wkn=0.55 seed_k=0.0
Xo0 r0n r0p q2p q2n vdd vss tspc_outbuf wn=2.6 nfn=2 wp=5.4 nfp=2 wkn=0.60 wkp=1.25
Xo1 r1n r1p q4p q4n vdd vss tspc_outbuf wn=2.6 nfn=2 wp=5.4 nfp=2 wkn=0.60 wkp=1.25
Xo2 r2n r2p q8p q8n vdd vss tspc_outbuf wn=3.0 nfn=2 wp=6.2 nfp=2 wkn=0.65 wkp=1.35
{caps_ck1g}.ends pll_saff_reclock_prescaler8_2g
"""
    elif kind == "cand3_ck1g_static_xor":
        sub = f"""\
.subckt pll_saff_reclock_prescaler8_2g clkp clkn q2p q2n q4p q4n q8p q8n vdd vss
Xck clkp clkn ck_2g vdd vss tspc_ckbuf wn1=2.4 wp1=6.0 wn2=10.8 wp2=24.0
Xff0 b0n b0p ck_2g b0p b0n vdd vss saff_tspc_dff wt=5.4 nft=2 wd=3.4 nfd=2 wl=2.8 nfl=2 wlp=1.6 wpre=2.8 wmid=1.3 weq=2.2 wop=4.0 nfop=2 wdn=3.8 nfdn=2 winv_n=0.95 winv_p=2.3 wkp=0.65 wkn=0.55 seed_k=0.45
* Dedicated 1 GHz clock buffer (b0p -> ck_1g, full VDD rail-to-rail) + matched dummy on b0n
Xck1g     b0p ck_1g     vdd vss tspc_inv_lvt wn=4.8 nfn=4 wp=11.2 nfp=4
Xck1g_dum b0n ck_1g_dum vdd vss tspc_inv_lvt wn=4.8 nfn=4 wp=11.2 nfp=4
Xff1 b1n b1p ck_1g b1p b1n vdd vss saff_tspc_dff wt=4.4 nft=2 wd=2.8 nfd=2 wl=2.4 nfl=2 wlp=1.4 wpre=2.2 wmid=1.1 weq=1.8 wop=3.0 nfop=2 wdn=2.8 nfdn=2 winv_n=0.90 winv_p=2.2 wkp=0.60 wkn=0.50 seed_k=0.40
* Static Restoring LVT-CMOS Differential XOR/XNOR (eliminates Xtg2 passive dead-zone & b2p/b2n shorting)
Xxor2 b1p b1n b2p b2n d2p d2n vdd vss tspc_xor_diff wn=1.5 nfn=1 wp=2.8 nfp=1
Xff2 d2p d2n ck_1g b2p b2n vdd vss saff_tspc_dff wt=4.4 nft=2 wd=2.8 nfd=2 wl=2.4 nfl=2 wlp=1.4 wpre=2.2 wmid=1.1 weq=1.8 wop=3.0 nfop=2 wdn=2.8 nfdn=2 winv_n=0.90 winv_p=2.2 wkp=0.60 wkn=0.50 seed_k=0.40
Xr0 b0p b0n ck_2g r0p r0n vdd vss saff_tspc_dff wt=4.4 nft=2 wd=2.8 nfd=2 wl=2.3 nfl=2 wlp=1.5 wpre=2.8 wmid=1.3 weq=2.0 wop=2.8 nfop=2 wdn=2.6 nfdn=2 wkp=0.65 wkn=0.55 seed_k=0.0
Xr1 b1p b1n ck_2g r1p r1n vdd vss saff_tspc_dff wt=4.4 nft=2 wd=2.8 nfd=2 wl=2.3 nfl=2 wlp=1.5 wpre=2.8 wmid=1.3 weq=2.0 wop=2.8 nfop=2 wdn=2.6 nfdn=2 wkp=0.65 wkn=0.55 seed_k=0.0
Xr2 b2p b2n ck_2g r2p r2n vdd vss saff_tspc_dff wt=4.4 nft=2 wd=2.8 nfd=2 wl=2.3 nfl=2 wlp=1.5 wpre=2.8 wmid=1.3 weq=2.0 wop=2.8 nfop=2 wdn=2.6 nfdn=2 wkp=0.65 wkn=0.55 seed_k=0.0
Xo0 r0n r0p q2p q2n vdd vss tspc_outbuf wn=2.6 nfn=2 wp=5.4 nfp=2 wkn=0.60 wkp=1.25
Xo1 r1n r1p q4p q4n vdd vss tspc_outbuf wn=2.6 nfn=2 wp=5.4 nfp=2 wkn=0.60 wkp=1.25
Xo2 r2n r2p q8p q8n vdd vss tspc_outbuf wn=3.0 nfn=2 wp=6.2 nfp=2 wkn=0.65 wkp=1.35
{caps_ck1g}.ends pll_saff_reclock_prescaler8_2g
"""
    elif kind == "cand4_ck1g_static_xor_fast":
        sub = f"""\
.subckt pll_saff_reclock_prescaler8_2g clkp clkn q2p q2n q4p q4n q8p q8n vdd vss
Xck clkp clkn ck_2g vdd vss tspc_ckbuf wn1=2.6 wp1=6.2 wn2=12.0 wp2=24.8
Xff0 b0n b0p ck_2g b0p b0n vdd vss saff_tspc_dff wt=5.8 nft=2 wd=3.6 nfd=2 wl=3.0 nfl=2 wlp=1.7 wpre=3.0 wmid=1.4 weq=2.2 wop=4.4 nfop=2 wdn=4.2 nfdn=2 winv_n=1.00 winv_p=2.4 wkp=0.65 wkn=0.55 seed_k=0.45
Xck1g     b0p ck_1g     vdd vss tspc_inv_lvt wn=5.2 nfn=4 wp=12.0 nfp=4
Xck1g_dum b0n ck_1g_dum vdd vss tspc_inv_lvt wn=5.2 nfn=4 wp=12.0 nfp=4
Xff1 b1n b1p ck_1g b1p b1n vdd vss saff_tspc_dff wt=4.8 nft=2 wd=3.0 nfd=2 wl=2.6 nfl=2 wlp=1.5 wpre=2.4 wmid=1.2 weq=2.0 wop=3.4 nfop=2 wdn=3.2 nfdn=2 winv_n=1.00 winv_p=2.4 wkp=0.60 wkn=0.50 seed_k=0.40
Xxor2 b1p b1n b2p b2n d2p d2n vdd vss tspc_xor_diff wn=1.5 nfn=1 wp=3.0 nfp=1
Xff2 d2p d2n ck_1g b2p b2n vdd vss saff_tspc_dff wt=4.8 nft=2 wd=3.0 nfd=2 wl=2.6 nfl=2 wlp=1.5 wpre=2.4 wmid=1.2 weq=2.0 wop=3.4 nfop=2 wdn=3.2 nfdn=2 winv_n=1.00 winv_p=2.4 wkp=0.60 wkn=0.50 seed_k=0.40
Xr0 b0p b0n ck_2g r0p r0n vdd vss saff_tspc_dff wt=4.4 nft=2 wd=2.8 nfd=2 wl=2.3 nfl=2 wlp=1.5 wpre=2.8 wmid=1.3 weq=2.0 wop=2.8 nfop=2 wdn=2.6 nfdn=2 winv_n=0.90 winv_p=2.1 wkp=0.65 wkn=0.55 seed_k=0.0
Xr1 b1p b1n ck_2g r1p r1n vdd vss saff_tspc_dff wt=4.4 nft=2 wd=2.8 nfd=2 wl=2.3 nfl=2 wlp=1.5 wpre=2.8 wmid=1.3 weq=2.0 wop=2.8 nfop=2 wdn=2.6 nfdn=2 winv_n=0.90 winv_p=2.1 wkp=0.65 wkn=0.55 seed_k=0.0
Xr2 b2p b2n ck_2g r2p r2n vdd vss saff_tspc_dff wt=4.4 nft=2 wd=2.8 nfd=2 wl=2.3 nfl=2 wlp=1.5 wpre=2.8 wmid=1.3 weq=2.0 wop=2.8 nfop=2 wdn=2.6 nfdn=2 winv_n=0.90 winv_p=2.1 wkp=0.65 wkn=0.55 seed_k=0.0
Xo0 r0n r0p q2p q2n vdd vss tspc_outbuf wn=2.6 nfn=2 wp=5.4 nfp=2 wkn=0.60 wkp=1.25
Xo1 r1n r1p q4p q4n vdd vss tspc_outbuf wn=2.6 nfn=2 wp=5.4 nfp=2 wkn=0.60 wkp=1.25
Xo2 r2n r2p q8p q8n vdd vss tspc_outbuf wn=3.0 nfn=2 wp=6.2 nfp=2 wkn=0.65 wkp=1.35
{caps_ck1g}.ends pll_saff_reclock_prescaler8_2g
"""
    else:
        raise ValueError(kind)
    return COMMON_SUBCKTS + "\n" + sub


def _make_mc_net(dut_sp: Path, subckt: str, c: corners.Condition, rc: str, vpp: float = 0.30) -> str:
    cv = spice.corner_values(c)
    net = "\n".join([
        f"{subckt} MC {c.tag}_mm",
        *bm._header(c.process, dut_sp, [], R5_PEX),
        f".param supply={cv['SUPPLY']} input_pp={vpp} freq=2e9",
        "Vdd vdd 0 PWL(0 0 0.5n {supply})",
        "Vrx vrx 0 PWL(0 0 0.5n {supply})",
        "Vdiv vdiv 0 PWL(0 0 0.5n {supply})",
        "Vreference vref 0 PWL(0 0 0.5n {supply})",
        "Iref vref vbias .85m",
        "Xref vbias vbias 0 0 serdes_nfet w=20 l=.5 nf=4",
        "Vp sp 0 SIN({supply-.15} {input_pp/4} {freq})",
        "Vn sn 0 SIN({supply-.15} {-input_pp/4} {freq})",
        "Xbuf sp sn bp bn vbias vdd 0 serdes_cml_buffer",
        "Cpre_p bp 0 45f", "Cpre_n bn 0 45f",
        "Xrx bp bn clkp clkn vbias vrx 0 serdes_cml_to_cmos_r5_pdk",
        f"Xdiv clkp clkn q2p q2n q4p q4n q8p q8n vdiv 0 {subckt}",
        "Cq2p q2p 0 15f", "Cq2n q2n 0 15f",
        "Cq4p q4p 0 15f", "Cq4n q4n 0 15f",
        "Cq8p q8p 0 20f", "Cq8n q8n 0 20f",
        f".temp {cv['TEMP_C']}",
        ".options reltol=1e-4 abstol=1p vntol=1u klu",
    ])
    net = bias.section(net, c.process, rc)
    net = re.sub(r'^(\.lib\s+"[^"]+"\s+)(\w+)\s*$', lambda m: f"{m[1]}{m[2]}_mm", net, count=1, flags=re.M | re.I)
    return net


def run_mc_suite(
    out_dir: Path,
    dut_sp: Path,
    subckt: str,
    corners_mm: list[tuple[str, str]],
    samples: int,
    workers: int,
    seed: int = 2026,
    per: int = 8,
) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    recs = []
    for lib_sec, rc in corners_mm:
        base_tag = lib_sec.removesuffix("_mm")
        c = corners.Condition.parse(base_tag)
        vmid = c.supply / 2.0
        cdir = out_dir / lib_sec
        cdir.mkdir(parents=True, exist_ok=True)
        net = freeze_includes(_make_mc_net(dut_sp, subckt, c, rc), cdir)
        lets = {
            "q2r1": "m_q2r1", "q2f1": "m_q2f1", "q2r2": "m_q2r2",
            "q2nr1": "m_q2nr1", "q2nf1": "m_q2nf1", "q2nr2": "m_q2nr2",
            "q4r1": "m_q4r1", "q4f1": "m_q4f1", "q4r2": "m_q4r2",
            "q8r1": "m_q8r1", "q8f1": "m_q8f1", "q8r2": "m_q8r2",
            "sk2": "m_sk2", "sk4": "m_sk4", "sk8": "m_sk8",
        }
        ana = "\n".join([
            *[f"let {k} = -1e30" for k in lets],
            "tran 2p 24n 0 2p uic",
            "let dq2 = v(q2p) - v(q2n)",
            "let dq4 = v(q4p) - v(q4n)",
            "let dq8 = v(q8p) - v(q8n)",
            f"meas tran m_q2r1 when v(q2p)={vmid:.4f} rise=1 td=14n",
            f"meas tran m_q2f1 when v(q2p)={vmid:.4f} fall=1 td=14n",
            f"meas tran m_q2r2 when v(q2p)={vmid:.4f} rise=2 td=14n",
            f"meas tran m_q2nr1 when v(q2n)={vmid:.4f} rise=1 td=14n",
            f"meas tran m_q2nf1 when v(q2n)={vmid:.4f} fall=1 td=14n",
            f"meas tran m_q2nr2 when v(q2n)={vmid:.4f} rise=2 td=14n",
            f"meas tran m_q4r1 when v(q4p)={vmid:.4f} rise=1 td=14n",
            f"meas tran m_q4f1 when v(q4p)={vmid:.4f} fall=1 td=14n",
            f"meas tran m_q4r2 when v(q4p)={vmid:.4f} rise=2 td=14n",
            f"meas tran m_q8r1 when v(q8p)={vmid:.4f} rise=1 td=14n",
            f"meas tran m_q8f1 when v(q8p)={vmid:.4f} fall=1 td=14n",
            f"meas tran m_q8r2 when v(q8p)={vmid:.4f} rise=2 td=14n",
            "meas tran m_sk2 when dq2=0 cross=1 td=14n",
            "meas tran m_sk4 when dq4=0 cross=1 td=14n",
            "meas tran m_sk8 when dq8=0 cross=1 td=14n",
        ])
        jobs = []
        for idx, ch_seed, ch_n in mc.chunks(samples, seed=seed, per=per):
            dk = mc.deck(net, samples=ch_n, seed=ch_seed, analysis=ana, lets=lets, t_end=24e-9)
            jobs.append((dk, cdir / f"ch_{idx:02d}", dict(meta=dict(tag=lib_sec, chunk=idx, seed=ch_seed))))
        dirs = mc.run_many(jobs, workers=min(workers, 2))
        rows = mc.read_all(dirs)
        d2p, d2n, d4p, d8p, sk4_ps, sk8_ps, max_sk_ps = [], [], [], [], [], [], []
        pass_30 = pass_35 = 0
        for row in rows:
            vals = [row[k] for k in lets]
            if np.isnan(vals).any() or min(vals) < 0:
                continue
            p2 = row["q2r2"] - row["q2r1"]
            p2n = row["q2nr2"] - row["q2nr1"]
            p4 = row["q4r2"] - row["q4r1"]
            p8 = row["q8r2"] - row["q8r1"]
            if not (900e-12 <= p2 <= 1100e-12 and 900e-12 <= p2n <= 1100e-12
                    and 1850e-12 <= p4 <= 2150e-12 and 3700e-12 <= p8 <= 4300e-12):
                continue
            dp2 = ((row["q2f1"] - row["q2r1"]) % p2) / p2
            dn2 = ((row["q2nf1"] - row["q2nr1"]) % p2n) / p2n
            dp4 = ((row["q4f1"] - row["q4r1"]) % p4) / p4
            dp8 = ((row["q8f1"] - row["q8r1"]) % p8) / p8
            e4 = ((row["sk4"] - row["sk2"] + 250e-12) % 500e-12 - 250e-12) * 1e12
            e8 = ((row["sk8"] - row["sk2"] + 250e-12) % 500e-12 - 250e-12) * 1e12
            d2p.append(dp2); d2n.append(dn2); d4p.append(dp4); d8p.append(dp8)
            sk4_ps.append(e4); sk8_ps.append(e8)
            ms = max(abs(e4), abs(e8))
            max_sk_ps.append(ms)
            duty_ok = (0.45 <= dp2 <= 0.55 and 0.45 <= dn2 <= 0.55
                       and 0.45 <= dp4 <= 0.55 and 0.45 <= dp8 <= 0.55)
            if duty_ok and ms <= 30.0:
                pass_30 += 1
            if duty_ok and ms <= 35.0:
                pass_35 += 1
        lo30, hi30 = stats.yield_ci(pass_30, len(rows))
        lo35, hi35 = stats.yield_ci(pass_35, len(rows))
        pct = lambda arr: {f"p{q}": round(float(np.percentile(arr, q)), 2) for q in (5, 50, 95, 99)} if arr else None
        rec = dict(
            subckt=subckt, corner_mm=lib_sec, samples=len(rows),
            func_toggle=len(d2p), pass_30ps=pass_30, pass_35ps=pass_35,
            yield_ci95_30ps=[lo30, hi30], yield_ci95_35ps=[lo35, hi35],
            sk4_ps=stats.summary(sk4_ps) if sk4_ps else None,
            sk8_ps=stats.summary(sk8_ps) if sk8_ps else None,
            max_abs_sk_ps=stats.summary(max_sk_ps) if max_sk_ps else None,
            max_abs_sk_pct=pct(max_sk_ps),
            d2p=stats.summary(d2p) if d2p else None,
            d4p=stats.summary(d4p) if d4p else None,
            d8p=stats.summary(d8p) if d8p else None,
        )
        recs.append(rec)
        print(
            f"[MC:{subckt}] {lib_sec:18s} func={len(d2p)}/{len(rows)} "
            f"pass(<30ps)={pass_30}/{len(rows)} CI95=[{lo30:.4f},{hi30:.4f}] | "
            f"max_sk pct={rec['max_abs_sk_pct']} max={rec['max_abs_sk_ps']['max'] if rec['max_abs_sk_ps'] else 'NA'}",
            flush=True,
        )
    save_analysis(out_dir, dict(stage="mc", dut=str(dut_sp), subckt=subckt, rows=recs))
    return recs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--stage",
        choices=["screen", "screen_mc", "pvt45", "mc", "cpex_corners", "cpex_mc", "cpex_pvt45"],
        required=True,
    )
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--samples", type=int, default=200)
    ap.add_argument("--dut", type=Path, default=CAND_SPICE)
    ap.add_argument("--subckt", type=str, default="pll_saff_reclock_prescaler8_2g")
    ap.add_argument("--tag", type=str, default="v2_cand")
    ap.add_argument("--cands", nargs="+", default=["baseline", "cand1_lvt_tg_boost", "cand2_ck1g_lvt_tg", "cand3_ck1g_static_xor", "cand4_ck1g_static_xor_fast"])
    args = ap.parse_args()

    workers = min(args.workers, 2)
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    if args.stage == "screen":
        sub = OUT_ROOT / "screen_corners"
        net_dir = sub / "netlists"
        net_dir.mkdir(parents=True, exist_ok=True)
        specs = []
        for kind in args.cands:
            for wcap in (False, True):
                lbl = f"{kind}{'_wcap' if wcap else '_sch'}"
                sp = net_dir / f"{lbl}.spice"
                sp.write_text(_cand_body(kind, wire_caps=wcap))
                pts = WORST5 if not wcap else [("ss_v1650_t-40", "hh"), ("fs_v1650_t85", "hh"), ("ff_v1950_t-40", "ll")]
                for tag, rc in pts:
                    specs.append(dict(
                        name=f"{lbl}__{tag}_{rc}", arch=lbl, cond=corners.Condition.parse(tag), rc=rc,
                        dut_spice=sp, subckt="pll_saff_reclock_prescaler8_2g", extra_inc=[],
                    ))
        rows = bm.run_batch(sub, specs, workers=workers)
        save_analysis(sub, dict(stage="screen", rows=rows))
        for kind in args.cands:
            for sfx in ("_sch", "_wcap"):
                lbl = kind + sfx
                ar = [r for r in rows if r["arch"] == lbl]
                print(f"\n=== {lbl} ===")
                for r in ar:
                    if "error" in r:
                        print(f"  {r['condition']:15s} ERROR")
                        continue
                    sk = r["skew_ps"]; pn = sk["pn_skew"]
                    fd = lambda v: f"{v:.3f}" if isinstance(v, (int, float)) else "NO"
                    print(
                        f"  {r['condition']:15s} {'PASS' if r['ok'] else ('FUNC' if r['func_ok'] else 'FAIL'):4s} "
                        f"bad={r['counter']['bad_steps']:2d} | sk(42/84/82)={sk['q4_q2']:5.2f}/{sk['q8_q4']:5.2f}/{sk['q8_q2']:5.2f}ps "
                        f"(max={sk['max_abs_interstage']:5.2f}ps) | pn={pn['q2']:4.1f}/{pn['q4']:4.1f}/{pn['q8']:4.1f}ps | "
                        f"duty={fd(r['q2']['duty'])}/{fd(r['q4']['duty'])}/{fd(r['q8']['duty'])} | P={r['pdiv_mw']:.2f}mW"
                    )

    elif args.stage == "screen_mc":
        sub = OUT_ROOT / "screen_mc_wcap"
        net_dir = sub / "netlists"
        net_dir.mkdir(parents=True, exist_ok=True)
        for kind in args.cands:
            sp = net_dir / f"{kind}_wcap.spice"
            sp.write_text(_cand_body(kind, wire_caps=True))
            run_mc_suite(
                sub / kind, sp, "pll_saff_reclock_prescaler8_2g",
                [("ss_v1650_t-40_mm", "hh")],
                samples=args.samples, workers=workers,
            )

    elif args.stage == "pvt45":
        sub = OUT_ROOT / f"pvt45_{args.tag}"
        sub.mkdir(parents=True, exist_ok=True)
        specs = []
        for c in corners.boundary_first(corners.grid45()):
            rc = "hh" if c.process in ("ss", "fs") else ("ll" if c.process in ("ff", "sf") else "tt")
            specs.append(dict(
                name=f"{c.tag}_{rc}", arch=args.tag, cond=c, rc=rc,
                dut_spice=args.dut.resolve(), subckt=args.subckt, extra_inc=[],
            ))
        rows = bm.run_batch(sub, specs, workers=workers)
        func_ok = sum(1 for r in rows if r.get("func_ok"))
        pass_30 = sum(1 for r in rows if r.get("func_ok") and r.get("skew_ps", {}).get("max_abs_interstage", 999) <= 30.0)
        pass_35 = sum(1 for r in rows if r.get("ok"))
        sks = [r["skew_ps"]["max_abs_interstage"] for r in rows if "skew_ps" in r]
        pns = [max(r["skew_ps"]["pn_skew"].values()) for r in rows if "skew_ps" in r]
        d2 = [r["q2"]["duty"] for r in rows if "q2" in r and r["q2"]["duty"] is not None]
        d4 = [r["q4"]["duty"] for r in rows if "q4" in r and r["q4"]["duty"] is not None]
        d8 = [r["q8"]["duty"] for r in rows if "q8" in r and r["q8"]["duty"] is not None]
        pw = [r["pdiv_mw"] for r in rows if "pdiv_mw" in r]
        worst = sorted([r for r in rows if "skew_ps" in r], key=lambda x: -x["skew_ps"]["max_abs_interstage"])[:5]
        summ = dict(
            tag=args.tag, dut=str(args.dut), subckt=args.subckt,
            total=len(rows), func_ok=func_ok, pass_30ps=pass_30, pass_35ps=pass_35,
            max_skew_ps=max(sks) if sks else None,
            median_skew_ps=float(np.median(sks)) if sks else None,
            max_pn_skew_ps=max(pns) if pns else None,
            q2_duty=[min(d2), max(d2)] if d2 else None,
            q4_duty=[min(d4), max(d4)] if d4 else None,
            q8_duty=[min(d8), max(d8)] if d8 else None,
            power_mw=[min(pw), max(pw)] if pw else None,
            worst5=[dict(cond=r["condition"], max_sk=r["skew_ps"]["max_abs_interstage"], sk=r["skew_ps"], p_mw=r["pdiv_mw"]) for r in worst],
            rows=rows,
        )
        save_analysis(sub, summ)
        print(
            f"[PVT45:{args.tag}] func={func_ok}/{len(rows)} <30ps={pass_30}/{len(rows)} | "
            f"max_sk={summ['max_skew_ps']:.2f}ps med_sk={summ['median_skew_ps']:.2f}ps max_pn={summ['max_pn_skew_ps']:.2f}ps | "
            f"q8_duty={summ['q8_duty']} P={summ['power_mw']}mW",
            flush=True,
        )
        for w in summ["worst5"]:
            print(f"  worst: {w['cond']:15s} max_sk={w['max_sk']:.2f}ps (42={w['sk']['q4_q2']:.2f} 84={w['sk']['q8_q4']:.2f} 82={w['sk']['q8_q2']:.2f}) P={w['p_mw']:.2f}mW")

    elif args.stage == "mc":
        run_mc_suite(
            OUT_ROOT / f"mc_{args.tag}", args.dut.resolve(), args.subckt,
            [("ss_v1650_t-40_mm", "hh"), ("fs_v1650_t85_mm", "hh")],
            samples=args.samples, workers=workers,
        )

    elif args.stage == "cpex_corners":
        sub = OUT_ROOT / f"cpex_corners_{args.tag}"
        sub.mkdir(parents=True, exist_ok=True)
        specs = []
        for tag, rc in WORST5 + [("ss_v1650_t85", "hh"), ("ff_v1950_t85", "ll")]:
            specs.append(dict(
                name=f"{tag}_{rc}", arch=args.tag, cond=corners.Condition.parse(tag), rc=rc,
                dut_spice=args.dut.resolve(), subckt=args.subckt, extra_inc=[],
            ))
        rows = bm.run_batch(sub, specs, workers=workers)
        save_analysis(sub, dict(stage="cpex_corners", tag=args.tag, dut=str(args.dut), rows=rows))
        for r in rows:
            sk = r.get("skew_ps", {})
            print(
                f"  {r['condition']:15s} {'PASS' if r.get('ok') else ('FUNC' if r.get('func_ok') else 'FAIL'):4s} "
                f"bad={r.get('counter',{}).get('bad_steps', -1):2d} | "
                f"sk(42/84/82)={sk.get('q4_q2',999):5.2f}/{sk.get('q8_q4',999):5.2f}/{sk.get('q8_q2',999):5.2f}ps "
                f"(max={sk.get('max_abs_interstage',999):5.2f}ps) | P={r.get('pdiv_mw',0):.2f}mW",
                flush=True,
            )

    elif args.stage == "cpex_mc":
        run_mc_suite(
            OUT_ROOT / f"cpex_mc_{args.tag}", args.dut.resolve(), args.subckt,
            [("ss_v1650_t-40_mm", "hh")],
            samples=args.samples, workers=workers,
        )

    elif args.stage == "cpex_pvt45":
        sub = OUT_ROOT / f"cpex_pvt45_{args.tag}"
        sub.mkdir(parents=True, exist_ok=True)
        specs = []
        for c in corners.boundary_first(corners.grid45()):
            rc = "hh" if c.process in ("ss", "fs") else ("ll" if c.process in ("ff", "sf") else "tt")
            specs.append(dict(
                name=f"{c.tag}_{rc}", arch=args.tag, cond=c, rc=rc,
                dut_spice=args.dut.resolve(), subckt=args.subckt, extra_inc=[],
            ))
        rows = bm.run_batch(sub, specs, workers=workers)
        func_ok = sum(1 for r in rows if r.get("func_ok"))
        pass_30 = sum(1 for r in rows if r.get("func_ok") and r.get("skew_ps", {}).get("max_abs_interstage", 999) <= 30.0)
        sks = [r["skew_ps"]["max_abs_interstage"] for r in rows if "skew_ps" in r]
        save_analysis(sub, dict(stage="cpex_pvt45", func_ok=func_ok, pass_30ps=pass_30, max_skew_ps=max(sks) if sks else None, rows=rows))
        print(f"[CPEX PVT45:{args.tag}] func={func_ok}/{len(rows)} <30ps={pass_30}/{len(rows)} max_sk={max(sks):.2f}ps", flush=True)


if __name__ == "__main__":
    main()
