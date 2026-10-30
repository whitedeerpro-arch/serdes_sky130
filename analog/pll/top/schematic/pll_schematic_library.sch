G {}
V {}
S {}
E {}
T {PLL SCHEMATIC LIBRARY EXPORT} 100 50 0 0 0.5 0.5 {}
T {Export root only: descend into Xcore for circuit views. External ports are named locally.
Not a simulation testbench; bias, clocks and test precharge are external.} 100 115 0 0 0.25 0.25 {}
N 390 520 450 520 {lab=ref}
N 390 560 450 560 {lab=rst_b}
N 390 600 450 600 {lab=vbn}
N 390 640 450 640 {lab=vbp}
N 390 680 450 680 {lab=vbias}
N 390 720 450 720 {lab=cfg0}
N 390 760 450 760 {lab=cfg1}
N 390 800 450 800 {lab=cfg2}
N 390 840 450 840 {lab=ctrl}
N 850 480 910 480 {lab=up}
N 850 520 910 520 {lab=dn}
N 850 560 910 560 {lab=fb0}
N 850 600 910 600 {lab=cm0p}
N 850 640 910 640 {lab=cm0n}
N 850 680 910 680 {lab=cm1p}
N 850 720 910 720 {lab=cm1n}
N 850 760 910 760 {lab=cm2p}
N 850 800 910 800 {lab=cm2n}
N 850 840 910 840 {lab=cm3p}
N 850 880 910 880 {lab=cm3n}
N 540 375 600 375 {lab=vdd}
N 700 375 760 375 {lab=vdd_dummy}
N 590 985 650 985 {lab=vss}
C {serdes/pll_balanced_core} 650 680 0 0 {name=Xcore cwire=0.5f}
C {devices/lab_pin} 390 520 0 0 {name=l0 lab=ref}
C {devices/lab_pin} 390 560 0 0 {name=l1 lab=rst_b}
C {devices/lab_pin} 390 600 0 0 {name=l2 lab=vbn}
C {devices/lab_pin} 390 640 0 0 {name=l3 lab=vbp}
C {devices/lab_pin} 390 680 0 0 {name=l4 lab=vbias}
C {devices/lab_pin} 390 720 0 0 {name=l5 lab=cfg0}
C {devices/lab_pin} 390 760 0 0 {name=l6 lab=cfg1}
C {devices/lab_pin} 390 800 0 0 {name=l7 lab=cfg2}
C {devices/lab_pin} 390 840 0 0 {name=l8 lab=ctrl}
C {devices/lab_pin} 910 480 0 1 {name=l9 lab=up}
C {devices/lab_pin} 910 520 0 1 {name=l10 lab=dn}
C {devices/lab_pin} 910 560 0 1 {name=l11 lab=fb0}
C {devices/lab_pin} 910 600 0 1 {name=l12 lab=cm0p}
C {devices/lab_pin} 910 640 0 1 {name=l13 lab=cm0n}
C {devices/lab_pin} 910 680 0 1 {name=l14 lab=cm1p}
C {devices/lab_pin} 910 720 0 1 {name=l15 lab=cm1n}
C {devices/lab_pin} 910 760 0 1 {name=l16 lab=cm2p}
C {devices/lab_pin} 910 800 0 1 {name=l17 lab=cm2n}
C {devices/lab_pin} 910 840 0 1 {name=l18 lab=cm3p}
C {devices/lab_pin} 910 880 0 1 {name=l19 lab=cm3n}
C {devices/lab_pin} 540 375 0 0 {name=l20 lab=vdd}
C {devices/lab_pin} 760 375 0 1 {name=l21 lab=vdd_dummy}
C {devices/lab_pin} 590 985 0 0 {name=l22 lab=vss}
