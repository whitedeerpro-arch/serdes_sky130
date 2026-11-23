G {}
V {}
S {}
E {}
T {PLL VCO CAP BANK} 100 45 0 0 0.48 0.48 {}
T {Source: analog/pll/vco/spice/cap_bank_3b.spice} 100 100 0 0 0.21 0.21 {}
T {Editable circuit view | W is total width in um | external models/bias; no layout extraction} 100 133 0 0 0.2 0.2 {}
C {devices/iopin} 90 230 0 1 {name=p1 lab=node}
C {devices/iopin} 90 285 0 1 {name=p2 lab=b0}
C {devices/iopin} 90 340 0 1 {name=p3 lab=b1}
C {devices/iopin} 90 395 0 1 {name=p4 lab=b2}
C {devices/iopin} 90 450 0 1 {name=p5 lab=vss}
C {serdes/pll_vco_cap_unit} 480 370 0 0 {name=X00 capw="\{capw\}" capl="\{capl\}" sw="\{sw\}"}
N 280 350 235 350 {lab=node}
C {devices/lab_pin} 235 350 0 0 {name=l1 lab=node}
N 280 390 235 390 {lab=b0}
C {devices/lab_pin} 235 390 0 0 {name=l2 lab=b0}
N 480 510 480 545 {lab=vss}
C {devices/lab_pin} 480 545 0 0 {name=l3 lab=vss}
C {serdes/pll_vco_cap_unit} 1100 370 0 0 {name=X10 capw="\{capw\}" capl="\{capl\}" sw="\{sw\}"}
N 900 350 855 350 {lab=node}
C {devices/lab_pin} 855 350 0 0 {name=l4 lab=node}
N 900 390 855 390 {lab=b1}
C {devices/lab_pin} 855 390 0 0 {name=l5 lab=b1}
N 1100 510 1100 545 {lab=vss}
C {devices/lab_pin} 1100 545 0 0 {name=l6 lab=vss}
C {serdes/pll_vco_cap_unit} 1100 820 0 0 {name=X11 capw="\{capw\}" capl="\{capl\}" sw="\{sw\}"}
N 900 800 855 800 {lab=node}
C {devices/lab_pin} 855 800 0 0 {name=l7 lab=node}
N 900 840 855 840 {lab=b1}
C {devices/lab_pin} 855 840 0 0 {name=l8 lab=b1}
N 1100 960 1100 995 {lab=vss}
C {devices/lab_pin} 1100 995 0 0 {name=l9 lab=vss}
C {serdes/pll_vco_cap_unit} 1720 370 0 0 {name=X20 capw="\{capw\}" capl="\{capl\}" sw="\{sw\}"}
N 1520 350 1475 350 {lab=node}
C {devices/lab_pin} 1475 350 0 0 {name=l10 lab=node}
N 1520 390 1475 390 {lab=b2}
C {devices/lab_pin} 1475 390 0 0 {name=l11 lab=b2}
N 1720 510 1720 545 {lab=vss}
C {devices/lab_pin} 1720 545 0 0 {name=l12 lab=vss}
C {serdes/pll_vco_cap_unit} 1720 820 0 0 {name=X21 capw="\{capw\}" capl="\{capl\}" sw="\{sw\}"}
N 1520 800 1475 800 {lab=node}
C {devices/lab_pin} 1475 800 0 0 {name=l13 lab=node}
N 1520 840 1475 840 {lab=b2}
C {devices/lab_pin} 1475 840 0 0 {name=l14 lab=b2}
N 1720 960 1720 995 {lab=vss}
C {devices/lab_pin} 1720 995 0 0 {name=l15 lab=vss}
C {serdes/pll_vco_cap_unit} 1720 1270 0 0 {name=X22 capw="\{capw\}" capl="\{capl\}" sw="\{sw\}"}
N 1520 1250 1475 1250 {lab=node}
C {devices/lab_pin} 1475 1250 0 0 {name=l16 lab=node}
N 1520 1290 1475 1290 {lab=b2}
C {devices/lab_pin} 1475 1290 0 0 {name=l17 lab=b2}
N 1720 1410 1720 1445 {lab=vss}
C {devices/lab_pin} 1720 1445 0 0 {name=l18 lab=vss}
C {serdes/pll_vco_cap_unit} 1720 1720 0 0 {name=X23 capw="\{capw\}" capl="\{capl\}" sw="\{sw\}"}
N 1520 1700 1475 1700 {lab=node}
C {devices/lab_pin} 1475 1700 0 0 {name=l19 lab=node}
N 1520 1740 1475 1740 {lab=b2}
C {devices/lab_pin} 1475 1740 0 0 {name=l20 lab=b2}
N 1720 1860 1720 1895 {lab=vss}
C {devices/lab_pin} 1720 1895 0 0 {name=l21 lab=vss}
T {Binary weights use seven identical physical MIM / NFET units: 1 + 2 + 4.} 350 2350 0 0 0.26 0.26 {}
T {DEFAULT PARAMETERS: capw=2  capl=2  sw=1} 100 2750 0 0 0.24 0.24 {}
