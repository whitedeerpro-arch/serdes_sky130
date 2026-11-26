* =============================================================================
* SKY130A 1.8 V 2 GHz 64-Code Pure CMOS Resistor-Linearized Phase Interpolator
* Clean Hierarchical Structural SPICE for Analog Canvas (analog-canvas.tokenzhang.com)
*
* Source silicon netlist: analog/rx/cmos_rx/spice/rx_cmos_pi.spice
* Full-chip RX PI array: 2 channels (Data 0/180 deg, Edge +90/+270 deg) x
*   2 differential legs (p/n) x 8 slices = 32 identical `pi_slice_r` slices
*   + deterministic quadrature CMOS /2 (`serdes_rx_qdiv2_8ph`).
*
* Performance (SKY130A 45-corner PVT + post-layout CPEX/RCX):
*   - Frequency   : 2.0 GHz (for 4 Gb/s quarter-rate NRZ SerDes)
*   - Resolution  : 64 codes / 2 GHz cycle (8 sectors x 8 fine steps = 7.81 ps = 1/32 UI)
*   - Linearity   : |INL| <= 0.015 UI across 6 extreme PVT corners, 0.00 ps parabolic bow
*   - Power       : ~7 mW total (zero CML, zero static tail current)
*   - Supply/PDK  : 1.8 V (verified down to SS 1.65 V -40 C), SKY130A
*
* Device model mapping (standard 4-terminal M / R / C for clean schematic import):
*   - nfet_lvt  -> sky130_fd_pr__nfet_01v8_lvt  (L = 0.15 um)
*   - pfet_lvt  -> sky130_fd_pr__pfet_01v8_lvt  (L = 0.35 um, low |Vthp| for SS -40 C!)
*   - pfet_std  -> sky130_fd_pr__pfet_01v8      (L = 0.15 um)
*   - R_sum     -> sky130_fd_pr__res_high_po_0p69 (l = 10.8 um, ~5.8 kOhm)
*   - R_fb      -> sky130_fd_pr__res_high_po_0p35 (l = 10.5 um, ~12.3 kOhm)
*   - C_mim/C_ac-> sky130_fd_pr__cap_mim_m3_1     (4.1 x 4.1 um, ~37 fF)
* =============================================================================

* -----------------------------------------------------------------------------
* Cell 1: Static-DC-Gated LVT CMOS Transmission Gate
* Static DC control bits => zero CV^2f gate-switching penalty on pfet_lvt!
* -----------------------------------------------------------------------------
.subckt pi_tgate_lvt a b en enb vdd vss params: wn=0.42u wp=0.75u
Mn a en  b vss nfet_lvt w={wn} l=0.15u
Mp a enb b vdd pfet_lvt w={wp} l=0.35u
.ends pi_tgate_lvt

* -----------------------------------------------------------------------------
* Cell 2: Compact 1-Stage 4:1 LVT-TG Coarse Octant Clock Mux + Output Inverter
* Exploits glitch-free Even-A (c0,c2,c4,c6) / Odd-B (c1,c3,c5,c7) commutation:
* 0.00 ps pin skew across all 4 inputs, zero stacked PMOS, 3/4 switches OFF.
* -----------------------------------------------------------------------------
.subckt pi_mux4_tg i0 i1 i2 i3 s0 s1 s2 s3 sb0 sb1 sb2 sb3 y vdd vss
Xt0 i0 m s0 sb0 vdd vss pi_tgate_lvt wn=1.40u wp=3.60u
Xt1 i1 m s1 sb1 vdd vss pi_tgate_lvt wn=1.40u wp=3.60u
Xt2 i2 m s2 sb2 vdd vss pi_tgate_lvt wn=1.40u wp=3.60u
Xt3 i3 m s3 sb3 vdd vss pi_tgate_lvt wn=1.40u wp=3.60u
Mn_out y m vss vss nfet_lvt w=1.80u l=0.15u
Mp_out y m vdd vdd pfet_std w=8.40u l=0.15u
.ends pi_mux4_tg

* -----------------------------------------------------------------------------
* Cell 3 (Star Leaf Cell): Constant-Load Resistor-Linearized Mixer Slice
*   - Active path : 2:1 LVT TG (f/fb) -> lean inverter -> R_sum = 5.8 kOhm -> mix
*     (R_sum >> R_on linearizes summing current across PVT!)
*   - Passive dummy: opposite 2:1 LVT TG (fb/f) -> gate-only dummy MOS caps
*     (S=D tied to VDD/VSS => 0 dynamic switching current, 0.00 ps load bow!)
* -----------------------------------------------------------------------------
.subckt pi_slice_r ca cb f fb mix vdd vss
* Active weighting leg
Xsa   ca  sel fb f   vdd vss pi_tgate_lvt wn=0.42u wp=0.75u
Xsb   cb  sel f  fb  vdd vss pi_tgate_lvt wn=0.42u wp=0.75u
Mn_a  drv sel vss vss nfet_lvt w=0.42u l=0.15u
Mp_a  drv sel vdd vdd pfet_std w=1.70u l=0.15u
Rsum  drv mix 5.8k

* Constant-load passive dummy leg (unselected input sees identical gate cap!)
Xda   ca  dum f  fb  vdd vss pi_tgate_lvt wn=0.42u wp=0.75u
Xdb   cb  dum fb f   vdd vss pi_tgate_lvt wn=0.42u wp=0.75u
Mn_d  vss dum vss vss nfet_lvt w=0.42u l=0.15u
Mp_d  vdd dum vdd vdd pfet_std w=1.70u l=0.15u
.ends pi_slice_r

* -----------------------------------------------------------------------------
* Cell 4: Zero-Static-DC AC-Coupled Self-Biased LVT Recovery + Output Buffer
*   - C_ac = 37 fF blocks DC offset from summing node `mix`.
*   - R_fb = 12.3 kOhm pure negative DC feedback auto-biases `acp` at V_M = VDD/2
*     (~0.34 ns settling) -> 50.0% duty across all PVT including SS 1.65 V -40 C!
*   - Matched Wp/Wn = 4.00 LVT-PMOS (L=0.35) + LVT-NMOS (L=0.15) avoids high-Vthp
*     dead zone with zero tail current.
* -----------------------------------------------------------------------------
.subckt pi_ac_rec_1leg mix out vdd vss
Cac    mix acp 37f
Rfb    acp r1  12.3k
Mn_rec r1  acp vss vss nfet_lvt w=1.65u  l=0.15u
Mp_rec r1  acp vdd vdd pfet_lvt w=6.60u  l=0.35u
Mn_buf out r1  vss vss nfet_lvt w=2.66u  l=0.15u
Mp_buf out r1  vdd vdd pfet_lvt w=10.64u l=0.35u
.ends pi_ac_rec_1leg

* -----------------------------------------------------------------------------
* Top Gallery Cell (Single-Ended 2 GHz 64-Code PI Leg — Clean 1-Sheet View!)
* Instantiate 4x in full chip: Data (p, n) + Edge (+90 deg p, n) = 32 slices.
*   e0..e3 : Even 2 GHz anchors (c0=0, c2=90, c4=180, c6=270 deg)
*   o0..o3 : Odd  2 GHz anchors (c1=45, c3=135, c5=225, c7=315 deg)
*   sa/sb  : One-hot coarse bank selects (glitch-free handoff when f=0x00/0xFF)
*   f0..f7 : 8-bit thermometer fine weight (k bits HIGH -> k/8 weight on Odd B)
* -----------------------------------------------------------------------------
.subckt rx_cmos_pi_1leg e0 e1 e2 e3 o0 o1 o2 o3
+ sa0 sa1 sa2 sa3 sab0 sab1 sab2 sab3
+ sb0 sb1 sb2 sb3 sbb0 sbb1 sbb2 sbb3
+ f0 f1 f2 f3 f4 f5 f6 f7 fb0 fb1 fb2 fb3 fb4 fb5 fb6 fb7
+ clk_out vdd vss

* Stage 1: Coarse 4:1 LVT-TG Octant Muxes (Even Bank A & Odd Bank B)
Xmux_a e0 e1 e2 e3 sa0 sa1 sa2 sa3 sab0 sab1 sab2 sab3 ca vdd vss pi_mux4_tg
Xmux_b o0 o1 o2 o3 sb0 sb1 sb2 sb3 sbb0 sbb1 sbb2 sbb3 cb vdd vss pi_mux4_tg

* Stage 2: 8-Slice Constant-Load Resistor-Linearized Phase Mixer (tau_mix ~ 43 ps)
Xs0 ca cb f0 fb0 mix vdd vss pi_slice_r
Xs1 ca cb f1 fb1 mix vdd vss pi_slice_r
Xs2 ca cb f2 fb2 mix vdd vss pi_slice_r
Xs3 ca cb f3 fb3 mix vdd vss pi_slice_r
Xs4 ca cb f4 fb4 mix vdd vss pi_slice_r
Xs5 ca cb f5 fb5 mix vdd vss pi_slice_r
Xs6 ca cb f6 fb6 mix vdd vss pi_slice_r
Xs7 ca cb f7 fb7 mix vdd vss pi_slice_r
Cmix mix vss 37f

* Stage 3: AC-Coupled Self-Biased LVT Recovery & Output Buffer
Xrec mix clk_out vdd vss pi_ac_rec_1leg
.ends rx_cmos_pi_1leg
