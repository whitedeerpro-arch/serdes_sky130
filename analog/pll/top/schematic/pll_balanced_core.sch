G {}
V {}
S {}
E {}
T {PLL BALANCED CORE} 100 45 0 0 0.48 0.48 {}
T {Source: analog/pll/top/spice/pll_balanced_core.spice} 100 100 0 0 0.21 0.21 {}
T {Editable circuit view | W is total width in um | external models/bias; no layout extraction} 100 133 0 0 0.2 0.2 {}
C {serdes/pll_pfd} 950 450 0 0 {name=Xpfd}
N 750 410 705 410 {lab=ref}
C {devices/lab_pin} 705 410 0 0 {name=l1 lab=ref}
N 750 450 705 450 {lab=fb0}
C {devices/lab_pin} 705 450 0 0 {name=l2 lab=fb0}
N 750 490 705 490 {lab=rst_b}
C {devices/lab_pin} 705 490 0 0 {name=l3 lab=rst_b}
N 1150 430 1195 430 {lab=up}
C {devices/lab_pin} 1195 430 0 1 {name=l4 lab=up}
N 1150 470 1195 470 {lab=dn}
C {devices/lab_pin} 1195 470 0 1 {name=l5 lab=dn}
N 900 305 900 270 {lab=vdd}
C {devices/lab_pin} 900 270 0 0 {name=l6 lab=vdd}
N 950 595 950 630 {lab=vss}
C {devices/lab_pin} 950 630 0 0 {name=l7 lab=vss}
C {serdes/pll_cp} 1650 450 0 0 {name=Xcp}
N 1450 390 1405 390 {lab=up}
C {devices/lab_pin} 1405 390 0 0 {name=l8 lab=up}
N 1450 430 1405 430 {lab=dn}
C {devices/lab_pin} 1405 430 0 0 {name=l9 lab=dn}
N 1850 450 1895 450 {lab=out}
C {devices/lab_pin} 1895 450 0 1 {name=l10 lab=out}
N 1450 470 1405 470 {lab=vbn}
C {devices/lab_pin} 1405 470 0 0 {name=l11 lab=vbn}
N 1450 510 1405 510 {lab=vbp}
C {devices/lab_pin} 1405 510 0 0 {name=l12 lab=vbp}
N 1600 305 1600 270 {lab=vdd}
C {devices/lab_pin} 1600 270 0 0 {name=l13 lab=vdd}
N 1650 595 1650 630 {lab=vss}
C {devices/lab_pin} 1650 630 0 0 {name=l14 lab=vss}
C {serdes/V} 2000 450 3 0 {name=Vsense value=0}
N 1970 450 1970 415 {lab=out}
C {devices/lab_pin} 1970 415 0 0 {name=l15 lab=out}
N 2030 450 2030 485 {lab=filt}
C {devices/lab_pin} 2030 485 0 0 {name=l16 lab=filt}
C {serdes/pll_loop_filter} 2350 450 0 0 {name=Xlf}
N 2150 450 2105 450 {lab=filt}
C {devices/lab_pin} 2105 450 0 0 {name=l17 lab=filt}
N 2550 450 2595 450 {lab=ctrl}
C {devices/lab_pin} 2595 450 0 1 {name=l18 lab=ctrl}
N 2350 590 2350 625 {lab=vss}
C {devices/lab_pin} 2350 625 0 0 {name=l19 lab=vss}
C {serdes/pll_clock_frontend_balanced} 2350 1100 0 0 {name=Xclock cwire="\{cwire\}"}
N 2150 1000 2105 1000 {lab=ctrl}
C {devices/lab_pin} 2105 1000 0 0 {name=l20 lab=ctrl}
N 2150 1040 2105 1040 {lab=cfg0}
C {devices/lab_pin} 2105 1040 0 0 {name=l21 lab=cfg0}
N 2150 1080 2105 1080 {lab=cfg1}
C {devices/lab_pin} 2105 1080 0 0 {name=l22 lab=cfg1}
N 2150 1120 2105 1120 {lab=cfg2}
C {devices/lab_pin} 2105 1120 0 0 {name=l23 lab=cfg2}
N 2150 1160 2105 1160 {lab=vbias}
C {devices/lab_pin} 2105 1160 0 0 {name=l24 lab=vbias}
N 2150 1200 2105 1200 {lab=rst_b}
C {devices/lab_pin} 2105 1200 0 0 {name=l25 lab=rst_b}
N 2550 940 2595 940 {lab=fb0}
C {devices/lab_pin} 2595 940 0 1 {name=l26 lab=fb0}
N 2550 980 2595 980 {lab=cm0p}
C {devices/lab_pin} 2595 980 0 1 {name=l27 lab=cm0p}
N 2550 1020 2595 1020 {lab=cm0n}
C {devices/lab_pin} 2595 1020 0 1 {name=l28 lab=cm0n}
N 2550 1060 2595 1060 {lab=cm1p}
C {devices/lab_pin} 2595 1060 0 1 {name=l29 lab=cm1p}
N 2550 1100 2595 1100 {lab=cm1n}
C {devices/lab_pin} 2595 1100 0 1 {name=l30 lab=cm1n}
N 2550 1140 2595 1140 {lab=cm2p}
C {devices/lab_pin} 2595 1140 0 1 {name=l31 lab=cm2p}
N 2550 1180 2595 1180 {lab=cm2n}
C {devices/lab_pin} 2595 1180 0 1 {name=l32 lab=cm2n}
N 2550 1220 2595 1220 {lab=cm3p}
C {devices/lab_pin} 2595 1220 0 1 {name=l33 lab=cm3p}
N 2550 1260 2595 1260 {lab=cm3n}
C {devices/lab_pin} 2595 1260 0 1 {name=l34 lab=cm3n}
N 2300 835 2300 800 {lab=vdd}
C {devices/lab_pin} 2300 800 0 0 {name=l35 lab=vdd}
N 2400 835 2400 800 {lab=vdd_dummy}
C {devices/lab_pin} 2400 800 0 0 {name=l36 lab=vdd_dummy}
N 2350 1365 2350 1400 {lab=vss}
C {devices/lab_pin} 2350 1400 0 0 {name=l37 lab=vss}
C {serdes/C} 950 1050 0 0 {name=Cup value=20f}
N 950 1020 950 985 {lab=up}
C {devices/lab_pin} 950 985 0 0 {name=l38 lab=up}
N 950 1080 950 1115 {lab=vss}
C {devices/lab_pin} 950 1115 0 0 {name=l39 lab=vss}
C {serdes/C} 1350 1050 0 0 {name=Cdn value=20f}
N 1350 1020 1350 985 {lab=dn}
C {devices/lab_pin} 1350 985 0 0 {name=l40 lab=dn}
N 1350 1080 1350 1115 {lab=vss}
C {devices/lab_pin} 1350 1115 0 0 {name=l41 lab=vss}
C {devices/iopin} 300 410 0 1 {name=p1 lab=ref}
C {devices/iopin} 300 490 0 1 {name=p2 lab=rst_b}
C {devices/iopin} 300 650 0 1 {name=p3 lab=vbn}
C {devices/iopin} 300 705 0 1 {name=p4 lab=vbp}
C {devices/iopin} 300 760 0 1 {name=p5 lab=vbias}
C {devices/iopin} 300 850 0 1 {name=p6 lab=cfg0}
C {devices/iopin} 300 905 0 1 {name=p7 lab=cfg1}
C {devices/iopin} 300 960 0 1 {name=p8 lab=cfg2}
C {devices/iopin} 3150 430 0 0 {name=p9 lab=ctrl}
C {devices/iopin} 3150 550 0 0 {name=p10 lab=up}
C {devices/iopin} 3150 605 0 0 {name=p11 lab=dn}
C {devices/iopin} 3150 750 0 0 {name=p12 lab=fb0}
C {devices/iopin} 3150 1000 0 0 {name=p13 lab=cm0p}
C {devices/iopin} 3150 1055 0 0 {name=p14 lab=cm0n}
C {devices/iopin} 3150 1110 0 0 {name=p15 lab=cm1p}
C {devices/iopin} 3150 1165 0 0 {name=p16 lab=cm1n}
C {devices/iopin} 3150 1220 0 0 {name=p17 lab=cm2p}
C {devices/iopin} 3150 1275 0 0 {name=p18 lab=cm2n}
C {devices/iopin} 3150 1330 0 0 {name=p19 lab=cm3p}
C {devices/iopin} 3150 1385 0 0 {name=p20 lab=cm3n}
C {devices/iopin} 300 1250 0 1 {name=p21 lab=vdd}
C {devices/iopin} 300 1305 0 1 {name=p22 lab=vdd_dummy}
C {devices/iopin} 300 1360 0 1 {name=p23 lab=vss}
N 300 410 750 410 {lab=ref}
N 1150 430 1280 430 {lab=up}
N 1280 430 1280 390 {lab=up}
N 1280 390 1450 390 {lab=up}
N 1150 470 1350 470 {lab=dn}
N 1350 470 1350 430 {lab=dn}
N 1350 430 1450 430 {lab=dn}
N 1850 450 1970 450 {lab=out}
N 2030 450 2110 450 {lab=filt}
N 2110 450 2110 430 {lab=filt}
N 2110 430 2150 450 {lab=filt}
N 2550 450 2920 430 {lab=ctrl}
N 2920 430 2920 750 {lab=ctrl}
N 2920 750 1990 750 {lab=ctrl}
N 1990 750 1990 1000 {lab=ctrl}
N 1990 1000 2150 1000 {lab=ctrl}
N 2550 940 2780 940 {lab=fb0}
N 2780 940 2780 1650 {lab=fb0}
N 2780 1650 500 1650 {lab=fb0}
N 500 1650 500 450 {lab=fb0}
N 500 450 750 450 {lab=fb0}
T {250 MHz REF -> PFD -> CP -> passive LF -> VCO control} 550 210 0 0 0.35 0.35 {}
T {CLOCK FRONT END: four-stage VCO + buffers + eight-phase CMOS outputs + CML /8 + powered dummy.} 650 1780 0 0 0.28 0.28 {}
T {External bias / coarse code / reset. Test precharge and startup kick are excluded from this reusable DUT.} 650 1850 0 0 0.25 0.25 {}
T {Prototype only: mixed-view capture observed; complete transistor lock / extracted verification pending.} 650 1920 0 0 0.25 0.25 {}
T {DEFAULT PARAMETERS: cwire=0.5f per VCO leg} 650 1990 0 0 0.24 0.24 {}
