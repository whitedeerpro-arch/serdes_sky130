G {}
V {}
S {}
E {}
T {PLL VCO RING4} 100 45 0 0 0.48 0.48 {}
T {Source: analog/pll/vco/spice/vco_ring4.spice} 100 100 0 0 0.21 0.21 {}
T {Editable circuit view | W is total width in um | external models/bias; no layout extraction} 100 133 0 0 0.2 0.2 {}
C {devices/iopin} 90 230 0 1 {name=p1 lab=q0p}
C {devices/iopin} 90 285 0 1 {name=p2 lab=q0n}
C {devices/iopin} 90 340 0 1 {name=p3 lab=q1p}
C {devices/iopin} 90 395 0 1 {name=p4 lab=q1n}
C {devices/iopin} 90 450 0 1 {name=p5 lab=q2p}
C {devices/iopin} 90 505 0 1 {name=p6 lab=q2n}
C {devices/iopin} 90 560 0 1 {name=p7 lab=q3p}
C {devices/iopin} 90 615 0 1 {name=p8 lab=q3n}
C {devices/iopin} 90 670 0 1 {name=p9 lab=vctrl}
C {devices/iopin} 90 725 0 1 {name=p10 lab=b0}
C {devices/iopin} 90 780 0 1 {name=p11 lab=b1}
C {devices/iopin} 90 835 0 1 {name=p12 lab=b2}
C {devices/iopin} 90 890 0 1 {name=p13 lab=vbias}
C {devices/iopin} 90 945 0 1 {name=p14 lab=vdd}
C {devices/iopin} 90 1000 0 1 {name=p15 lab=vss}
C {serdes/serdes_cml_delay} 550 420 0 0 {name=X0 wn="\{wn\}" nfin="\{nfin\}" wt="\{wt\}" lt="\{lt\}" rload="\{rload\}"}
N 350 395 305 395 {lab=q3n}
C {devices/lab_pin} 305 395 0 0 {name=l1 lab=q3n}
N 350 445 305 445 {lab=q3p}
C {devices/lab_pin} 305 445 0 0 {name=l2 lab=q3p}
N 750 395 795 395 {lab=q0p}
C {devices/lab_pin} 795 395 0 1 {name=l3 lab=q0p}
N 750 445 795 445 {lab=q0n}
C {devices/lab_pin} 795 445 0 1 {name=l4 lab=q0n}
N 350 495 305 495 {lab=vbias}
C {devices/lab_pin} 305 495 0 0 {name=l5 lab=vbias}
N 500 280 500 245 {lab=vdd}
C {devices/lab_pin} 500 245 0 0 {name=l6 lab=vdd}
N 550 560 550 595 {lab=vss}
C {devices/lab_pin} 550 595 0 0 {name=l7 lab=vss}
C {serdes/serdes_cml_delay} 1160 420 0 0 {name=X1 wn="\{wn\}" nfin="\{nfin\}" wt="\{wt\}" lt="\{lt\}" rload="\{rload\}"}
N 960 395 915 395 {lab=q0p}
C {devices/lab_pin} 915 395 0 0 {name=l8 lab=q0p}
N 960 445 915 445 {lab=q0n}
C {devices/lab_pin} 915 445 0 0 {name=l9 lab=q0n}
N 1360 395 1405 395 {lab=q1p}
C {devices/lab_pin} 1405 395 0 1 {name=l10 lab=q1p}
N 1360 445 1405 445 {lab=q1n}
C {devices/lab_pin} 1405 445 0 1 {name=l11 lab=q1n}
N 960 495 915 495 {lab=vbias}
C {devices/lab_pin} 915 495 0 0 {name=l12 lab=vbias}
N 1110 280 1110 245 {lab=vdd}
C {devices/lab_pin} 1110 245 0 0 {name=l13 lab=vdd}
N 1160 560 1160 595 {lab=vss}
C {devices/lab_pin} 1160 595 0 0 {name=l14 lab=vss}
C {serdes/serdes_cml_delay} 1770 420 0 0 {name=X2 wn="\{wn\}" nfin="\{nfin\}" wt="\{wt\}" lt="\{lt\}" rload="\{rload\}"}
N 1570 395 1525 395 {lab=q1p}
C {devices/lab_pin} 1525 395 0 0 {name=l15 lab=q1p}
N 1570 445 1525 445 {lab=q1n}
C {devices/lab_pin} 1525 445 0 0 {name=l16 lab=q1n}
N 1970 395 2015 395 {lab=q2p}
C {devices/lab_pin} 2015 395 0 1 {name=l17 lab=q2p}
N 1970 445 2015 445 {lab=q2n}
C {devices/lab_pin} 2015 445 0 1 {name=l18 lab=q2n}
N 1570 495 1525 495 {lab=vbias}
C {devices/lab_pin} 1525 495 0 0 {name=l19 lab=vbias}
N 1720 280 1720 245 {lab=vdd}
C {devices/lab_pin} 1720 245 0 0 {name=l20 lab=vdd}
N 1770 560 1770 595 {lab=vss}
C {devices/lab_pin} 1770 595 0 0 {name=l21 lab=vss}
C {serdes/serdes_cml_delay} 2380 420 0 0 {name=X3 wn="\{wn\}" nfin="\{nfin\}" wt="\{wt\}" lt="\{lt\}" rload="\{rload\}"}
N 2180 395 2135 395 {lab=q2p}
C {devices/lab_pin} 2135 395 0 0 {name=l22 lab=q2p}
N 2180 445 2135 445 {lab=q2n}
C {devices/lab_pin} 2135 445 0 0 {name=l23 lab=q2n}
N 2580 395 2625 395 {lab=q3p}
C {devices/lab_pin} 2625 395 0 1 {name=l24 lab=q3p}
N 2580 445 2625 445 {lab=q3n}
C {devices/lab_pin} 2625 445 0 1 {name=l25 lab=q3n}
N 2180 495 2135 495 {lab=vbias}
C {devices/lab_pin} 2135 495 0 0 {name=l26 lab=vbias}
N 2330 280 2330 245 {lab=vdd}
C {devices/lab_pin} 2330 245 0 0 {name=l27 lab=vdd}
N 2380 560 2380 595 {lab=vss}
C {devices/lab_pin} 2380 595 0 0 {name=l28 lab=vss}
C {serdes/sky130_fd_pr__cap_var_lvt} 550 830 0 0 {name=Xv0p w="\{varw\}" l="\{varl\}"}
N 550 800 550 765 {lab=q0p}
C {devices/lab_pin} 550 765 0 0 {name=l29 lab=q0p}
N 550 860 550 895 {lab=vctrl}
C {devices/lab_pin} 550 895 0 0 {name=l30 lab=vctrl}
N 500 845 500 880 {lab=vss}
C {devices/lab_pin} 500 880 0 0 {name=l31 lab=vss}
C {serdes/sky130_fd_pr__cap_var_lvt} 550 1120 0 0 {name=Xv0n w="\{varw\}" l="\{varl\}"}
N 550 1090 550 1055 {lab=q0n}
C {devices/lab_pin} 550 1055 0 0 {name=l32 lab=q0n}
N 550 1150 550 1185 {lab=vctrl}
C {devices/lab_pin} 550 1185 0 0 {name=l33 lab=vctrl}
N 500 1135 500 1170 {lab=vss}
C {devices/lab_pin} 500 1170 0 0 {name=l34 lab=vss}
C {serdes/sky130_fd_pr__cap_var_lvt} 1160 830 0 0 {name=Xv1p w="\{varw\}" l="\{varl\}"}
N 1160 800 1160 765 {lab=q1p}
C {devices/lab_pin} 1160 765 0 0 {name=l35 lab=q1p}
N 1160 860 1160 895 {lab=vctrl}
C {devices/lab_pin} 1160 895 0 0 {name=l36 lab=vctrl}
N 1110 845 1110 880 {lab=vss}
C {devices/lab_pin} 1110 880 0 0 {name=l37 lab=vss}
C {serdes/sky130_fd_pr__cap_var_lvt} 1160 1120 0 0 {name=Xv1n w="\{varw\}" l="\{varl\}"}
N 1160 1090 1160 1055 {lab=q1n}
C {devices/lab_pin} 1160 1055 0 0 {name=l38 lab=q1n}
N 1160 1150 1160 1185 {lab=vctrl}
C {devices/lab_pin} 1160 1185 0 0 {name=l39 lab=vctrl}
N 1110 1135 1110 1170 {lab=vss}
C {devices/lab_pin} 1110 1170 0 0 {name=l40 lab=vss}
C {serdes/sky130_fd_pr__cap_var_lvt} 1770 830 0 0 {name=Xv2p w="\{varw\}" l="\{varl\}"}
N 1770 800 1770 765 {lab=q2p}
C {devices/lab_pin} 1770 765 0 0 {name=l41 lab=q2p}
N 1770 860 1770 895 {lab=vctrl}
C {devices/lab_pin} 1770 895 0 0 {name=l42 lab=vctrl}
N 1720 845 1720 880 {lab=vss}
C {devices/lab_pin} 1720 880 0 0 {name=l43 lab=vss}
C {serdes/sky130_fd_pr__cap_var_lvt} 1770 1120 0 0 {name=Xv2n w="\{varw\}" l="\{varl\}"}
N 1770 1090 1770 1055 {lab=q2n}
C {devices/lab_pin} 1770 1055 0 0 {name=l44 lab=q2n}
N 1770 1150 1770 1185 {lab=vctrl}
C {devices/lab_pin} 1770 1185 0 0 {name=l45 lab=vctrl}
N 1720 1135 1720 1170 {lab=vss}
C {devices/lab_pin} 1720 1170 0 0 {name=l46 lab=vss}
C {serdes/sky130_fd_pr__cap_var_lvt} 2380 830 0 0 {name=Xv3p w="\{varw\}" l="\{varl\}"}
N 2380 800 2380 765 {lab=q3p}
C {devices/lab_pin} 2380 765 0 0 {name=l47 lab=q3p}
N 2380 860 2380 895 {lab=vctrl}
C {devices/lab_pin} 2380 895 0 0 {name=l48 lab=vctrl}
N 2330 845 2330 880 {lab=vss}
C {devices/lab_pin} 2330 880 0 0 {name=l49 lab=vss}
C {serdes/sky130_fd_pr__cap_var_lvt} 2380 1120 0 0 {name=Xv3n w="\{varw\}" l="\{varl\}"}
N 2380 1090 2380 1055 {lab=q3n}
C {devices/lab_pin} 2380 1055 0 0 {name=l50 lab=q3n}
N 2380 1150 2380 1185 {lab=vctrl}
C {devices/lab_pin} 2380 1185 0 0 {name=l51 lab=vctrl}
N 2330 1135 2330 1170 {lab=vss}
C {devices/lab_pin} 2330 1170 0 0 {name=l52 lab=vss}
C {serdes/pll_vco_cap_bank} 550 1550 0 0 {name=Xc0p capw="\{capw\}" capl="\{capl\}" sw="\{sw\}"}
N 350 1490 305 1490 {lab=q0p}
C {devices/lab_pin} 305 1490 0 0 {name=l53 lab=q0p}
N 350 1530 305 1530 {lab=b0}
C {devices/lab_pin} 305 1530 0 0 {name=l54 lab=b0}
N 350 1570 305 1570 {lab=b1}
C {devices/lab_pin} 305 1570 0 0 {name=l55 lab=b1}
N 350 1610 305 1610 {lab=b2}
C {devices/lab_pin} 305 1610 0 0 {name=l56 lab=b2}
N 550 1695 550 1730 {lab=vss}
C {devices/lab_pin} 550 1730 0 0 {name=l57 lab=vss}
C {serdes/pll_vco_cap_bank} 550 1990 0 0 {name=Xc0n capw="\{capw\}" capl="\{capl\}" sw="\{sw\}"}
N 350 1930 305 1930 {lab=q0n}
C {devices/lab_pin} 305 1930 0 0 {name=l58 lab=q0n}
N 350 1970 305 1970 {lab=b0}
C {devices/lab_pin} 305 1970 0 0 {name=l59 lab=b0}
N 350 2010 305 2010 {lab=b1}
C {devices/lab_pin} 305 2010 0 0 {name=l60 lab=b1}
N 350 2050 305 2050 {lab=b2}
C {devices/lab_pin} 305 2050 0 0 {name=l61 lab=b2}
N 550 2135 550 2170 {lab=vss}
C {devices/lab_pin} 550 2170 0 0 {name=l62 lab=vss}
C {serdes/pll_vco_cap_bank} 1160 1550 0 0 {name=Xc1p capw="\{capw\}" capl="\{capl\}" sw="\{sw\}"}
N 960 1490 915 1490 {lab=q1p}
C {devices/lab_pin} 915 1490 0 0 {name=l63 lab=q1p}
N 960 1530 915 1530 {lab=b0}
C {devices/lab_pin} 915 1530 0 0 {name=l64 lab=b0}
N 960 1570 915 1570 {lab=b1}
C {devices/lab_pin} 915 1570 0 0 {name=l65 lab=b1}
N 960 1610 915 1610 {lab=b2}
C {devices/lab_pin} 915 1610 0 0 {name=l66 lab=b2}
N 1160 1695 1160 1730 {lab=vss}
C {devices/lab_pin} 1160 1730 0 0 {name=l67 lab=vss}
C {serdes/pll_vco_cap_bank} 1160 1990 0 0 {name=Xc1n capw="\{capw\}" capl="\{capl\}" sw="\{sw\}"}
N 960 1930 915 1930 {lab=q1n}
C {devices/lab_pin} 915 1930 0 0 {name=l68 lab=q1n}
N 960 1970 915 1970 {lab=b0}
C {devices/lab_pin} 915 1970 0 0 {name=l69 lab=b0}
N 960 2010 915 2010 {lab=b1}
C {devices/lab_pin} 915 2010 0 0 {name=l70 lab=b1}
N 960 2050 915 2050 {lab=b2}
C {devices/lab_pin} 915 2050 0 0 {name=l71 lab=b2}
N 1160 2135 1160 2170 {lab=vss}
C {devices/lab_pin} 1160 2170 0 0 {name=l72 lab=vss}
C {serdes/pll_vco_cap_bank} 1770 1550 0 0 {name=Xc2p capw="\{capw\}" capl="\{capl\}" sw="\{sw\}"}
N 1570 1490 1525 1490 {lab=q2p}
C {devices/lab_pin} 1525 1490 0 0 {name=l73 lab=q2p}
N 1570 1530 1525 1530 {lab=b0}
C {devices/lab_pin} 1525 1530 0 0 {name=l74 lab=b0}
N 1570 1570 1525 1570 {lab=b1}
C {devices/lab_pin} 1525 1570 0 0 {name=l75 lab=b1}
N 1570 1610 1525 1610 {lab=b2}
C {devices/lab_pin} 1525 1610 0 0 {name=l76 lab=b2}
N 1770 1695 1770 1730 {lab=vss}
C {devices/lab_pin} 1770 1730 0 0 {name=l77 lab=vss}
C {serdes/pll_vco_cap_bank} 1770 1990 0 0 {name=Xc2n capw="\{capw\}" capl="\{capl\}" sw="\{sw\}"}
N 1570 1930 1525 1930 {lab=q2n}
C {devices/lab_pin} 1525 1930 0 0 {name=l78 lab=q2n}
N 1570 1970 1525 1970 {lab=b0}
C {devices/lab_pin} 1525 1970 0 0 {name=l79 lab=b0}
N 1570 2010 1525 2010 {lab=b1}
C {devices/lab_pin} 1525 2010 0 0 {name=l80 lab=b1}
N 1570 2050 1525 2050 {lab=b2}
C {devices/lab_pin} 1525 2050 0 0 {name=l81 lab=b2}
N 1770 2135 1770 2170 {lab=vss}
C {devices/lab_pin} 1770 2170 0 0 {name=l82 lab=vss}
C {serdes/pll_vco_cap_bank} 2380 1550 0 0 {name=Xc3p capw="\{capw\}" capl="\{capl\}" sw="\{sw\}"}
N 2180 1490 2135 1490 {lab=q3p}
C {devices/lab_pin} 2135 1490 0 0 {name=l83 lab=q3p}
N 2180 1530 2135 1530 {lab=b0}
C {devices/lab_pin} 2135 1530 0 0 {name=l84 lab=b0}
N 2180 1570 2135 1570 {lab=b1}
C {devices/lab_pin} 2135 1570 0 0 {name=l85 lab=b1}
N 2180 1610 2135 1610 {lab=b2}
C {devices/lab_pin} 2135 1610 0 0 {name=l86 lab=b2}
N 2380 1695 2380 1730 {lab=vss}
C {devices/lab_pin} 2380 1730 0 0 {name=l87 lab=vss}
C {serdes/pll_vco_cap_bank} 2380 1990 0 0 {name=Xc3n capw="\{capw\}" capl="\{capl\}" sw="\{sw\}"}
N 2180 1930 2135 1930 {lab=q3n}
C {devices/lab_pin} 2135 1930 0 0 {name=l88 lab=q3n}
N 2180 1970 2135 1970 {lab=b0}
C {devices/lab_pin} 2135 1970 0 0 {name=l89 lab=b0}
N 2180 2010 2135 2010 {lab=b1}
C {devices/lab_pin} 2135 2010 0 0 {name=l90 lab=b1}
N 2180 2050 2135 2050 {lab=b2}
C {devices/lab_pin} 2135 2050 0 0 {name=l91 lab=b2}
N 2380 2135 2380 2170 {lab=vss}
C {devices/lab_pin} 2380 2170 0 0 {name=l92 lab=vss}
N 750 395 960 395 {lab=q0p}
N 750 445 960 445 {lab=q0n}
N 1360 395 1570 395 {lab=q1p}
N 1360 445 1570 445 {lab=q1n}
N 1970 395 2180 395 {lab=q2p}
N 1970 445 2180 445 {lab=q2n}
T {Feedback has exactly one differential cross-connection: stage 0 inputs = q3n, q3p.} 380 220 0 0 0.28 0.28 {}
T {Every stage: identical p/n varactors and 1:2:4 cap banks; code frozen during fine lock.} 380 2350 0 0 0.28 0.28 {}
T {DEFAULT PARAMETERS: wn=40  nfin=8  wt=20  lt=0.5  rload=400  varw=15  varl=0.5  capw=2  capl=5  sw=1} 100 2750 0 0 0.24 0.24 {}
