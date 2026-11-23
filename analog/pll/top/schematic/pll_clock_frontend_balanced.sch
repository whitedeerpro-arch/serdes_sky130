G {}
V {}
S {}
E {}
T {PLL CLOCK FRONTEND BALANCED} 100 45 0 0 0.48 0.48 {}
T {Source: analog/pll/top/spice/clock_frontend_balanced.spice} 100 100 0 0 0.21 0.21 {}
T {Editable circuit view | W is total width in um | external models/bias; no layout extraction} 100 133 0 0 0.2 0.2 {}
C {devices/iopin} 90 230 0 1 {name=p1 lab=ctrl}
C {devices/iopin} 90 285 0 1 {name=p2 lab=cfg0}
C {devices/iopin} 90 340 0 1 {name=p3 lab=cfg1}
C {devices/iopin} 90 395 0 1 {name=p4 lab=cfg2}
C {devices/iopin} 90 450 0 1 {name=p5 lab=vbias}
C {devices/iopin} 90 505 0 1 {name=p6 lab=rst_b}
C {devices/iopin} 90 560 0 1 {name=p7 lab=fb0}
C {devices/iopin} 90 615 0 1 {name=p8 lab=cm0p}
C {devices/iopin} 90 670 0 1 {name=p9 lab=cm0n}
C {devices/iopin} 90 725 0 1 {name=p10 lab=cm1p}
C {devices/iopin} 90 780 0 1 {name=p11 lab=cm1n}
C {devices/iopin} 90 835 0 1 {name=p12 lab=cm2p}
C {devices/iopin} 90 890 0 1 {name=p13 lab=cm2n}
C {devices/iopin} 90 945 0 1 {name=p14 lab=cm3p}
C {devices/iopin} 90 1000 0 1 {name=p15 lab=cm3n}
C {devices/iopin} 90 1055 0 1 {name=p16 lab=vdd}
C {devices/iopin} 90 1110 0 1 {name=p17 lab=vdd_dummy}
C {devices/iopin} 90 1165 0 1 {name=p18 lab=vss}
C {serdes/pll_vco_ring4} 600 720 0 0 {name=Xvco}
N 800 560 845 560 {lab=v0p}
C {devices/lab_pin} 845 560 0 1 {name=l1 lab=v0p}
N 800 600 845 600 {lab=v0n}
C {devices/lab_pin} 845 600 0 1 {name=l2 lab=v0n}
N 800 640 845 640 {lab=v1p}
C {devices/lab_pin} 845 640 0 1 {name=l3 lab=v1p}
N 800 680 845 680 {lab=v1n}
C {devices/lab_pin} 845 680 0 1 {name=l4 lab=v1n}
N 800 720 845 720 {lab=v2p}
C {devices/lab_pin} 845 720 0 1 {name=l5 lab=v2p}
N 800 760 845 760 {lab=v2n}
C {devices/lab_pin} 845 760 0 1 {name=l6 lab=v2n}
N 800 800 845 800 {lab=v3p}
C {devices/lab_pin} 845 800 0 1 {name=l7 lab=v3p}
N 800 840 845 840 {lab=v3n}
C {devices/lab_pin} 845 840 0 1 {name=l8 lab=v3n}
N 800 880 845 880 {lab=ctrl}
C {devices/lab_pin} 845 880 0 1 {name=l9 lab=ctrl}
N 400 660 355 660 {lab=cfg0}
C {devices/lab_pin} 355 660 0 0 {name=l10 lab=cfg0}
N 400 700 355 700 {lab=cfg1}
C {devices/lab_pin} 355 700 0 0 {name=l11 lab=cfg1}
N 400 740 355 740 {lab=cfg2}
C {devices/lab_pin} 355 740 0 0 {name=l12 lab=cfg2}
N 400 780 355 780 {lab=vbias}
C {devices/lab_pin} 355 780 0 0 {name=l13 lab=vbias}
N 550 455 550 420 {lab=vdd}
C {devices/lab_pin} 550 420 0 0 {name=l14 lab=vdd}
N 600 985 600 1020 {lab=vss}
C {devices/lab_pin} 600 1020 0 0 {name=l15 lab=vss}
C {serdes/serdes_cml_buffer} 1200 320 0 0 {name=Xbuf0}
N 1000 280 955 280 {lab=v0p}
C {devices/lab_pin} 955 280 0 0 {name=l16 lab=v0p}
N 1000 320 955 320 {lab=v0n}
C {devices/lab_pin} 955 320 0 0 {name=l17 lab=v0n}
N 1400 300 1445 300 {lab=b0p}
C {devices/lab_pin} 1445 300 0 1 {name=l18 lab=b0p}
N 1400 340 1445 340 {lab=b0n}
C {devices/lab_pin} 1445 340 0 1 {name=l19 lab=b0n}
N 1000 360 955 360 {lab=vbias}
C {devices/lab_pin} 955 360 0 0 {name=l20 lab=vbias}
N 1150 175 1150 140 {lab=vdd}
C {devices/lab_pin} 1150 140 0 0 {name=l21 lab=vdd}
N 1200 465 1200 500 {lab=vss}
C {devices/lab_pin} 1200 500 0 0 {name=l22 lab=vss}
C {serdes/serdes_cml_to_cmos} 1840 320 0 0 {name=Xrx0}
N 1640 280 1595 280 {lab=b0p}
C {devices/lab_pin} 1595 280 0 0 {name=l23 lab=b0p}
N 1640 320 1595 320 {lab=b0n}
C {devices/lab_pin} 1595 320 0 0 {name=l24 lab=b0n}
N 2040 300 2085 300 {lab=cm0p}
C {devices/lab_pin} 2085 300 0 1 {name=l25 lab=cm0p}
N 2040 340 2085 340 {lab=cm0n}
C {devices/lab_pin} 2085 340 0 1 {name=l26 lab=cm0n}
N 1640 360 1595 360 {lab=vbias}
C {devices/lab_pin} 1595 360 0 0 {name=l27 lab=vbias}
N 1790 175 1790 140 {lab=vdd}
C {devices/lab_pin} 1790 140 0 0 {name=l28 lab=vdd}
N 1840 465 1840 500 {lab=vss}
C {devices/lab_pin} 1840 500 0 0 {name=l29 lab=vss}
C {serdes/pll_cml_prescaler8} 2500 320 0 0 {name=Xpre0}
N 2300 280 2255 280 {lab=b0p}
C {devices/lab_pin} 2255 280 0 0 {name=l30 lab=b0p}
N 2300 320 2255 320 {lab=b0n}
C {devices/lab_pin} 2255 320 0 0 {name=l31 lab=b0n}
N 2700 220 2745 220 {lab=d02p}
C {devices/lab_pin} 2745 220 0 1 {name=l32 lab=d02p}
N 2700 260 2745 260 {lab=d02n}
C {devices/lab_pin} 2745 260 0 1 {name=l33 lab=d02n}
N 2700 300 2745 300 {lab=d04p}
C {devices/lab_pin} 2745 300 0 1 {name=l34 lab=d04p}
N 2700 340 2745 340 {lab=d04n}
C {devices/lab_pin} 2745 340 0 1 {name=l35 lab=d04n}
N 2700 380 2745 380 {lab=d08p}
C {devices/lab_pin} 2745 380 0 1 {name=l36 lab=d08p}
N 2700 420 2745 420 {lab=d08n}
C {devices/lab_pin} 2745 420 0 1 {name=l37 lab=d08n}
N 2300 360 2255 360 {lab=vbias}
C {devices/lab_pin} 2255 360 0 0 {name=l38 lab=vbias}
N 2450 135 2450 100 {lab=vdd}
C {devices/lab_pin} 2450 100 0 0 {name=l39 lab=vdd}
N 2500 505 2500 540 {lab=vss}
C {devices/lab_pin} 2500 540 0 0 {name=l40 lab=vss}
C {serdes/serdes_cml_to_cmos} 3150 320 0 0 {name=Xfb0}
N 2950 280 2905 280 {lab=d08p}
C {devices/lab_pin} 2905 280 0 0 {name=l41 lab=d08p}
N 2950 320 2905 320 {lab=d08n}
C {devices/lab_pin} 2905 320 0 0 {name=l42 lab=d08n}
N 3350 300 3395 300 {lab=fb0}
C {devices/lab_pin} 3395 300 0 1 {name=l43 lab=fb0}
N 3350 340 3395 340 {lab=fb0n}
C {devices/lab_pin} 3395 340 0 1 {name=l44 lab=fb0n}
N 2950 360 2905 360 {lab=vbias}
C {devices/lab_pin} 2905 360 0 0 {name=l45 lab=vbias}
N 3100 175 3100 140 {lab=vdd}
C {devices/lab_pin} 3100 140 0 0 {name=l46 lab=vdd}
N 3150 465 3150 500 {lab=vss}
C {devices/lab_pin} 3150 500 0 0 {name=l47 lab=vss}
T {REAL FEEDBACK} 2330 60 0 0 0.3 0.3 {}
C {serdes/serdes_cml_buffer} 1200 1020 0 0 {name=Xbuf1}
N 1000 980 955 980 {lab=v1p}
C {devices/lab_pin} 955 980 0 0 {name=l48 lab=v1p}
N 1000 1020 955 1020 {lab=v1n}
C {devices/lab_pin} 955 1020 0 0 {name=l49 lab=v1n}
N 1400 1000 1445 1000 {lab=b1p}
C {devices/lab_pin} 1445 1000 0 1 {name=l50 lab=b1p}
N 1400 1040 1445 1040 {lab=b1n}
C {devices/lab_pin} 1445 1040 0 1 {name=l51 lab=b1n}
N 1000 1060 955 1060 {lab=vbias}
C {devices/lab_pin} 955 1060 0 0 {name=l52 lab=vbias}
N 1150 875 1150 840 {lab=vdd}
C {devices/lab_pin} 1150 840 0 0 {name=l53 lab=vdd}
N 1200 1165 1200 1200 {lab=vss}
C {devices/lab_pin} 1200 1200 0 0 {name=l54 lab=vss}
C {serdes/serdes_cml_to_cmos} 1840 1020 0 0 {name=Xrx1}
N 1640 980 1595 980 {lab=b1p}
C {devices/lab_pin} 1595 980 0 0 {name=l55 lab=b1p}
N 1640 1020 1595 1020 {lab=b1n}
C {devices/lab_pin} 1595 1020 0 0 {name=l56 lab=b1n}
N 2040 1000 2085 1000 {lab=cm1p}
C {devices/lab_pin} 2085 1000 0 1 {name=l57 lab=cm1p}
N 2040 1040 2085 1040 {lab=cm1n}
C {devices/lab_pin} 2085 1040 0 1 {name=l58 lab=cm1n}
N 1640 1060 1595 1060 {lab=vbias}
C {devices/lab_pin} 1595 1060 0 0 {name=l59 lab=vbias}
N 1790 875 1790 840 {lab=vdd}
C {devices/lab_pin} 1790 840 0 0 {name=l60 lab=vdd}
N 1840 1165 1840 1200 {lab=vss}
C {devices/lab_pin} 1840 1200 0 0 {name=l61 lab=vss}
C {serdes/pll_cml_prescaler8} 2500 1020 0 0 {name=Xpre1}
N 2300 980 2255 980 {lab=b1p}
C {devices/lab_pin} 2255 980 0 0 {name=l62 lab=b1p}
N 2300 1020 2255 1020 {lab=b1n}
C {devices/lab_pin} 2255 1020 0 0 {name=l63 lab=b1n}
N 2700 920 2745 920 {lab=d12p}
C {devices/lab_pin} 2745 920 0 1 {name=l64 lab=d12p}
N 2700 960 2745 960 {lab=d12n}
C {devices/lab_pin} 2745 960 0 1 {name=l65 lab=d12n}
N 2700 1000 2745 1000 {lab=d14p}
C {devices/lab_pin} 2745 1000 0 1 {name=l66 lab=d14p}
N 2700 1040 2745 1040 {lab=d14n}
C {devices/lab_pin} 2745 1040 0 1 {name=l67 lab=d14n}
N 2700 1080 2745 1080 {lab=d18p}
C {devices/lab_pin} 2745 1080 0 1 {name=l68 lab=d18p}
N 2700 1120 2745 1120 {lab=d18n}
C {devices/lab_pin} 2745 1120 0 1 {name=l69 lab=d18n}
N 2300 1060 2255 1060 {lab=vbias}
C {devices/lab_pin} 2255 1060 0 0 {name=l70 lab=vbias}
N 2450 835 2450 800 {lab=vdd_dummy}
C {devices/lab_pin} 2450 800 0 0 {name=l71 lab=vdd_dummy}
N 2500 1205 2500 1240 {lab=vss}
C {devices/lab_pin} 2500 1240 0 0 {name=l72 lab=vss}
C {serdes/serdes_cml_to_cmos} 3150 1020 0 0 {name=Xfb1}
N 2950 980 2905 980 {lab=d18p}
C {devices/lab_pin} 2905 980 0 0 {name=l73 lab=d18p}
N 2950 1020 2905 1020 {lab=d18n}
C {devices/lab_pin} 2905 1020 0 0 {name=l74 lab=d18n}
N 3350 1000 3395 1000 {lab=fb1}
C {devices/lab_pin} 3395 1000 0 1 {name=l75 lab=fb1}
N 3350 1040 3395 1040 {lab=fb1n}
C {devices/lab_pin} 3395 1040 0 1 {name=l76 lab=fb1n}
N 2950 1060 2905 1060 {lab=vbias}
C {devices/lab_pin} 2905 1060 0 0 {name=l77 lab=vbias}
N 3100 875 3100 840 {lab=vdd_dummy}
C {devices/lab_pin} 3100 840 0 0 {name=l78 lab=vdd_dummy}
N 3150 1165 3150 1200 {lab=vss}
C {devices/lab_pin} 3150 1200 0 0 {name=l79 lab=vss}
C {serdes/serdes_cmos_dff_reset} 3780 1020 0 0 {name=Xload1}
N 3580 980 3535 980 {lab=vdd_dummy}
C {devices/lab_pin} 3535 980 0 0 {name=l80 lab=vdd_dummy}
N 3580 1020 3535 1020 {lab=fb1}
C {devices/lab_pin} 3535 1020 0 0 {name=l81 lab=fb1}
N 3580 1060 3535 1060 {lab=rst_b}
C {devices/lab_pin} 3535 1060 0 0 {name=l82 lab=rst_b}
N 3980 1020 4025 1020 {lab=dq1}
C {devices/lab_pin} 4025 1020 0 1 {name=l83 lab=dq1}
N 3730 875 3730 840 {lab=vdd_dummy}
C {devices/lab_pin} 3730 840 0 0 {name=l84 lab=vdd_dummy}
N 3780 1165 3780 1200 {lab=vss}
C {devices/lab_pin} 3780 1200 0 0 {name=l85 lab=vss}
T {POWERED DUMMY 1} 2330 760 0 0 0.3 0.3 {}
C {serdes/serdes_cml_buffer} 1200 1720 0 0 {name=Xbuf2}
N 1000 1680 955 1680 {lab=v2p}
C {devices/lab_pin} 955 1680 0 0 {name=l86 lab=v2p}
N 1000 1720 955 1720 {lab=v2n}
C {devices/lab_pin} 955 1720 0 0 {name=l87 lab=v2n}
N 1400 1700 1445 1700 {lab=b2p}
C {devices/lab_pin} 1445 1700 0 1 {name=l88 lab=b2p}
N 1400 1740 1445 1740 {lab=b2n}
C {devices/lab_pin} 1445 1740 0 1 {name=l89 lab=b2n}
N 1000 1760 955 1760 {lab=vbias}
C {devices/lab_pin} 955 1760 0 0 {name=l90 lab=vbias}
N 1150 1575 1150 1540 {lab=vdd}
C {devices/lab_pin} 1150 1540 0 0 {name=l91 lab=vdd}
N 1200 1865 1200 1900 {lab=vss}
C {devices/lab_pin} 1200 1900 0 0 {name=l92 lab=vss}
C {serdes/serdes_cml_to_cmos} 1840 1720 0 0 {name=Xrx2}
N 1640 1680 1595 1680 {lab=b2p}
C {devices/lab_pin} 1595 1680 0 0 {name=l93 lab=b2p}
N 1640 1720 1595 1720 {lab=b2n}
C {devices/lab_pin} 1595 1720 0 0 {name=l94 lab=b2n}
N 2040 1700 2085 1700 {lab=cm2p}
C {devices/lab_pin} 2085 1700 0 1 {name=l95 lab=cm2p}
N 2040 1740 2085 1740 {lab=cm2n}
C {devices/lab_pin} 2085 1740 0 1 {name=l96 lab=cm2n}
N 1640 1760 1595 1760 {lab=vbias}
C {devices/lab_pin} 1595 1760 0 0 {name=l97 lab=vbias}
N 1790 1575 1790 1540 {lab=vdd}
C {devices/lab_pin} 1790 1540 0 0 {name=l98 lab=vdd}
N 1840 1865 1840 1900 {lab=vss}
C {devices/lab_pin} 1840 1900 0 0 {name=l99 lab=vss}
C {serdes/pll_cml_prescaler8} 2500 1720 0 0 {name=Xpre2}
N 2300 1680 2255 1680 {lab=b2p}
C {devices/lab_pin} 2255 1680 0 0 {name=l100 lab=b2p}
N 2300 1720 2255 1720 {lab=b2n}
C {devices/lab_pin} 2255 1720 0 0 {name=l101 lab=b2n}
N 2700 1620 2745 1620 {lab=d22p}
C {devices/lab_pin} 2745 1620 0 1 {name=l102 lab=d22p}
N 2700 1660 2745 1660 {lab=d22n}
C {devices/lab_pin} 2745 1660 0 1 {name=l103 lab=d22n}
N 2700 1700 2745 1700 {lab=d24p}
C {devices/lab_pin} 2745 1700 0 1 {name=l104 lab=d24p}
N 2700 1740 2745 1740 {lab=d24n}
C {devices/lab_pin} 2745 1740 0 1 {name=l105 lab=d24n}
N 2700 1780 2745 1780 {lab=d28p}
C {devices/lab_pin} 2745 1780 0 1 {name=l106 lab=d28p}
N 2700 1820 2745 1820 {lab=d28n}
C {devices/lab_pin} 2745 1820 0 1 {name=l107 lab=d28n}
N 2300 1760 2255 1760 {lab=vbias}
C {devices/lab_pin} 2255 1760 0 0 {name=l108 lab=vbias}
N 2450 1535 2450 1500 {lab=vdd_dummy}
C {devices/lab_pin} 2450 1500 0 0 {name=l109 lab=vdd_dummy}
N 2500 1905 2500 1940 {lab=vss}
C {devices/lab_pin} 2500 1940 0 0 {name=l110 lab=vss}
C {serdes/serdes_cml_to_cmos} 3150 1720 0 0 {name=Xfb2}
N 2950 1680 2905 1680 {lab=d28p}
C {devices/lab_pin} 2905 1680 0 0 {name=l111 lab=d28p}
N 2950 1720 2905 1720 {lab=d28n}
C {devices/lab_pin} 2905 1720 0 0 {name=l112 lab=d28n}
N 3350 1700 3395 1700 {lab=fb2}
C {devices/lab_pin} 3395 1700 0 1 {name=l113 lab=fb2}
N 3350 1740 3395 1740 {lab=fb2n}
C {devices/lab_pin} 3395 1740 0 1 {name=l114 lab=fb2n}
N 2950 1760 2905 1760 {lab=vbias}
C {devices/lab_pin} 2905 1760 0 0 {name=l115 lab=vbias}
N 3100 1575 3100 1540 {lab=vdd_dummy}
C {devices/lab_pin} 3100 1540 0 0 {name=l116 lab=vdd_dummy}
N 3150 1865 3150 1900 {lab=vss}
C {devices/lab_pin} 3150 1900 0 0 {name=l117 lab=vss}
C {serdes/serdes_cmos_dff_reset} 3780 1720 0 0 {name=Xload2}
N 3580 1680 3535 1680 {lab=vdd_dummy}
C {devices/lab_pin} 3535 1680 0 0 {name=l118 lab=vdd_dummy}
N 3580 1720 3535 1720 {lab=fb2}
C {devices/lab_pin} 3535 1720 0 0 {name=l119 lab=fb2}
N 3580 1760 3535 1760 {lab=rst_b}
C {devices/lab_pin} 3535 1760 0 0 {name=l120 lab=rst_b}
N 3980 1720 4025 1720 {lab=dq2}
C {devices/lab_pin} 4025 1720 0 1 {name=l121 lab=dq2}
N 3730 1575 3730 1540 {lab=vdd_dummy}
C {devices/lab_pin} 3730 1540 0 0 {name=l122 lab=vdd_dummy}
N 3780 1865 3780 1900 {lab=vss}
C {devices/lab_pin} 3780 1900 0 0 {name=l123 lab=vss}
T {POWERED DUMMY 2} 2330 1460 0 0 0.3 0.3 {}
C {serdes/serdes_cml_buffer} 1200 2420 0 0 {name=Xbuf3}
N 1000 2380 955 2380 {lab=v3p}
C {devices/lab_pin} 955 2380 0 0 {name=l124 lab=v3p}
N 1000 2420 955 2420 {lab=v3n}
C {devices/lab_pin} 955 2420 0 0 {name=l125 lab=v3n}
N 1400 2400 1445 2400 {lab=b3p}
C {devices/lab_pin} 1445 2400 0 1 {name=l126 lab=b3p}
N 1400 2440 1445 2440 {lab=b3n}
C {devices/lab_pin} 1445 2440 0 1 {name=l127 lab=b3n}
N 1000 2460 955 2460 {lab=vbias}
C {devices/lab_pin} 955 2460 0 0 {name=l128 lab=vbias}
N 1150 2275 1150 2240 {lab=vdd}
C {devices/lab_pin} 1150 2240 0 0 {name=l129 lab=vdd}
N 1200 2565 1200 2600 {lab=vss}
C {devices/lab_pin} 1200 2600 0 0 {name=l130 lab=vss}
C {serdes/serdes_cml_to_cmos} 1840 2420 0 0 {name=Xrx3}
N 1640 2380 1595 2380 {lab=b3p}
C {devices/lab_pin} 1595 2380 0 0 {name=l131 lab=b3p}
N 1640 2420 1595 2420 {lab=b3n}
C {devices/lab_pin} 1595 2420 0 0 {name=l132 lab=b3n}
N 2040 2400 2085 2400 {lab=cm3p}
C {devices/lab_pin} 2085 2400 0 1 {name=l133 lab=cm3p}
N 2040 2440 2085 2440 {lab=cm3n}
C {devices/lab_pin} 2085 2440 0 1 {name=l134 lab=cm3n}
N 1640 2460 1595 2460 {lab=vbias}
C {devices/lab_pin} 1595 2460 0 0 {name=l135 lab=vbias}
N 1790 2275 1790 2240 {lab=vdd}
C {devices/lab_pin} 1790 2240 0 0 {name=l136 lab=vdd}
N 1840 2565 1840 2600 {lab=vss}
C {devices/lab_pin} 1840 2600 0 0 {name=l137 lab=vss}
C {serdes/pll_cml_prescaler8} 2500 2420 0 0 {name=Xpre3}
N 2300 2380 2255 2380 {lab=b3p}
C {devices/lab_pin} 2255 2380 0 0 {name=l138 lab=b3p}
N 2300 2420 2255 2420 {lab=b3n}
C {devices/lab_pin} 2255 2420 0 0 {name=l139 lab=b3n}
N 2700 2320 2745 2320 {lab=d32p}
C {devices/lab_pin} 2745 2320 0 1 {name=l140 lab=d32p}
N 2700 2360 2745 2360 {lab=d32n}
C {devices/lab_pin} 2745 2360 0 1 {name=l141 lab=d32n}
N 2700 2400 2745 2400 {lab=d34p}
C {devices/lab_pin} 2745 2400 0 1 {name=l142 lab=d34p}
N 2700 2440 2745 2440 {lab=d34n}
C {devices/lab_pin} 2745 2440 0 1 {name=l143 lab=d34n}
N 2700 2480 2745 2480 {lab=d38p}
C {devices/lab_pin} 2745 2480 0 1 {name=l144 lab=d38p}
N 2700 2520 2745 2520 {lab=d38n}
C {devices/lab_pin} 2745 2520 0 1 {name=l145 lab=d38n}
N 2300 2460 2255 2460 {lab=vbias}
C {devices/lab_pin} 2255 2460 0 0 {name=l146 lab=vbias}
N 2450 2235 2450 2200 {lab=vdd_dummy}
C {devices/lab_pin} 2450 2200 0 0 {name=l147 lab=vdd_dummy}
N 2500 2605 2500 2640 {lab=vss}
C {devices/lab_pin} 2500 2640 0 0 {name=l148 lab=vss}
C {serdes/serdes_cml_to_cmos} 3150 2420 0 0 {name=Xfb3}
N 2950 2380 2905 2380 {lab=d38p}
C {devices/lab_pin} 2905 2380 0 0 {name=l149 lab=d38p}
N 2950 2420 2905 2420 {lab=d38n}
C {devices/lab_pin} 2905 2420 0 0 {name=l150 lab=d38n}
N 3350 2400 3395 2400 {lab=fb3}
C {devices/lab_pin} 3395 2400 0 1 {name=l151 lab=fb3}
N 3350 2440 3395 2440 {lab=fb3n}
C {devices/lab_pin} 3395 2440 0 1 {name=l152 lab=fb3n}
N 2950 2460 2905 2460 {lab=vbias}
C {devices/lab_pin} 2905 2460 0 0 {name=l153 lab=vbias}
N 3100 2275 3100 2240 {lab=vdd_dummy}
C {devices/lab_pin} 3100 2240 0 0 {name=l154 lab=vdd_dummy}
N 3150 2565 3150 2600 {lab=vss}
C {devices/lab_pin} 3150 2600 0 0 {name=l155 lab=vss}
C {serdes/serdes_cmos_dff_reset} 3780 2420 0 0 {name=Xload3}
N 3580 2380 3535 2380 {lab=vdd_dummy}
C {devices/lab_pin} 3535 2380 0 0 {name=l156 lab=vdd_dummy}
N 3580 2420 3535 2420 {lab=fb3}
C {devices/lab_pin} 3535 2420 0 0 {name=l157 lab=fb3}
N 3580 2460 3535 2460 {lab=rst_b}
C {devices/lab_pin} 3535 2460 0 0 {name=l158 lab=rst_b}
N 3980 2420 4025 2420 {lab=dq3}
C {devices/lab_pin} 4025 2420 0 1 {name=l159 lab=dq3}
N 3730 2275 3730 2240 {lab=vdd_dummy}
C {devices/lab_pin} 3730 2240 0 0 {name=l160 lab=vdd_dummy}
N 3780 2565 3780 2600 {lab=vss}
C {devices/lab_pin} 3780 2600 0 0 {name=l161 lab=vss}
T {POWERED DUMMY 3} 2330 2160 0 0 0.3 0.3 {}
C {serdes/C} 530 3450 0 0 {name=Cw0p value="\{cwire\}"}
N 530 3420 530 3385 {lab=v0p}
C {devices/lab_pin} 530 3385 0 0 {name=l162 lab=v0p}
N 530 3480 530 3515 {lab=vss}
C {devices/lab_pin} 530 3515 0 0 {name=l163 lab=vss}
C {serdes/C} 870 3450 0 0 {name=Cw0n value="\{cwire\}"}
N 870 3420 870 3385 {lab=v0n}
C {devices/lab_pin} 870 3385 0 0 {name=l164 lab=v0n}
N 870 3480 870 3515 {lab=vss}
C {devices/lab_pin} 870 3515 0 0 {name=l165 lab=vss}
C {serdes/C} 1210 3450 0 0 {name=Ccm0p value=20f}
N 1210 3420 1210 3385 {lab=cm0p}
C {devices/lab_pin} 1210 3385 0 0 {name=l166 lab=cm0p}
N 1210 3480 1210 3515 {lab=vss}
C {devices/lab_pin} 1210 3515 0 0 {name=l167 lab=vss}
C {serdes/C} 1550 3450 0 0 {name=Ccm0n value=20f}
N 1550 3420 1550 3385 {lab=cm0n}
C {devices/lab_pin} 1550 3385 0 0 {name=l168 lab=cm0n}
N 1550 3480 1550 3515 {lab=vss}
C {devices/lab_pin} 1550 3515 0 0 {name=l169 lab=vss}
C {serdes/C} 1890 3450 0 0 {name=Cfb0 value=20f}
N 1890 3420 1890 3385 {lab=fb0}
C {devices/lab_pin} 1890 3385 0 0 {name=l170 lab=fb0}
N 1890 3480 1890 3515 {lab=vss}
C {devices/lab_pin} 1890 3515 0 0 {name=l171 lab=vss}
C {serdes/C} 2230 3450 0 0 {name=Cfb0n value=20f}
N 2230 3420 2230 3385 {lab=fb0n}
C {devices/lab_pin} 2230 3385 0 0 {name=l172 lab=fb0n}
N 2230 3480 2230 3515 {lab=vss}
C {devices/lab_pin} 2230 3515 0 0 {name=l173 lab=vss}
C {serdes/C} 2570 3450 0 0 {name=Cdiv02p value=5f}
N 2570 3420 2570 3385 {lab=d02p}
C {devices/lab_pin} 2570 3385 0 0 {name=l174 lab=d02p}
N 2570 3480 2570 3515 {lab=vss}
C {devices/lab_pin} 2570 3515 0 0 {name=l175 lab=vss}
C {serdes/C} 2910 3450 0 0 {name=Cdiv02n value=5f}
N 2910 3420 2910 3385 {lab=d02n}
C {devices/lab_pin} 2910 3385 0 0 {name=l176 lab=d02n}
N 2910 3480 2910 3515 {lab=vss}
C {devices/lab_pin} 2910 3515 0 0 {name=l177 lab=vss}
C {serdes/C} 3250 3450 0 0 {name=Cdiv04p value=5f}
N 3250 3420 3250 3385 {lab=d04p}
C {devices/lab_pin} 3250 3385 0 0 {name=l178 lab=d04p}
N 3250 3480 3250 3515 {lab=vss}
C {devices/lab_pin} 3250 3515 0 0 {name=l179 lab=vss}
C {serdes/C} 3590 3450 0 0 {name=Cdiv04n value=5f}
N 3590 3420 3590 3385 {lab=d04n}
C {devices/lab_pin} 3590 3385 0 0 {name=l180 lab=d04n}
N 3590 3480 3590 3515 {lab=vss}
C {devices/lab_pin} 3590 3515 0 0 {name=l181 lab=vss}
C {serdes/C} 3930 3450 0 0 {name=Cdiv08p value=5f}
N 3930 3420 3930 3385 {lab=d08p}
C {devices/lab_pin} 3930 3385 0 0 {name=l182 lab=d08p}
N 3930 3480 3930 3515 {lab=vss}
C {devices/lab_pin} 3930 3515 0 0 {name=l183 lab=vss}
C {serdes/C} 4270 3450 0 0 {name=Cdiv08n value=5f}
N 4270 3420 4270 3385 {lab=d08n}
C {devices/lab_pin} 4270 3385 0 0 {name=l184 lab=d08n}
N 4270 3480 4270 3515 {lab=vss}
C {devices/lab_pin} 4270 3515 0 0 {name=l185 lab=vss}
C {serdes/C} 530 3750 0 0 {name=Cw1p value="\{cwire\}"}
N 530 3720 530 3685 {lab=v1p}
C {devices/lab_pin} 530 3685 0 0 {name=l186 lab=v1p}
N 530 3780 530 3815 {lab=vss}
C {devices/lab_pin} 530 3815 0 0 {name=l187 lab=vss}
C {serdes/C} 870 3750 0 0 {name=Cw1n value="\{cwire\}"}
N 870 3720 870 3685 {lab=v1n}
C {devices/lab_pin} 870 3685 0 0 {name=l188 lab=v1n}
N 870 3780 870 3815 {lab=vss}
C {devices/lab_pin} 870 3815 0 0 {name=l189 lab=vss}
C {serdes/C} 1210 3750 0 0 {name=Ccm1p value=20f}
N 1210 3720 1210 3685 {lab=cm1p}
C {devices/lab_pin} 1210 3685 0 0 {name=l190 lab=cm1p}
N 1210 3780 1210 3815 {lab=vss}
C {devices/lab_pin} 1210 3815 0 0 {name=l191 lab=vss}
C {serdes/C} 1550 3750 0 0 {name=Ccm1n value=20f}
N 1550 3720 1550 3685 {lab=cm1n}
C {devices/lab_pin} 1550 3685 0 0 {name=l192 lab=cm1n}
N 1550 3780 1550 3815 {lab=vss}
C {devices/lab_pin} 1550 3815 0 0 {name=l193 lab=vss}
C {serdes/C} 1890 3750 0 0 {name=Cfb1 value=20f}
N 1890 3720 1890 3685 {lab=fb1}
C {devices/lab_pin} 1890 3685 0 0 {name=l194 lab=fb1}
N 1890 3780 1890 3815 {lab=vss}
C {devices/lab_pin} 1890 3815 0 0 {name=l195 lab=vss}
C {serdes/C} 2230 3750 0 0 {name=Cfb1n value=20f}
N 2230 3720 2230 3685 {lab=fb1n}
C {devices/lab_pin} 2230 3685 0 0 {name=l196 lab=fb1n}
N 2230 3780 2230 3815 {lab=vss}
C {devices/lab_pin} 2230 3815 0 0 {name=l197 lab=vss}
C {serdes/C} 2570 3750 0 0 {name=Cdiv12p value=5f}
N 2570 3720 2570 3685 {lab=d12p}
C {devices/lab_pin} 2570 3685 0 0 {name=l198 lab=d12p}
N 2570 3780 2570 3815 {lab=vss}
C {devices/lab_pin} 2570 3815 0 0 {name=l199 lab=vss}
C {serdes/C} 2910 3750 0 0 {name=Cdiv12n value=5f}
N 2910 3720 2910 3685 {lab=d12n}
C {devices/lab_pin} 2910 3685 0 0 {name=l200 lab=d12n}
N 2910 3780 2910 3815 {lab=vss}
C {devices/lab_pin} 2910 3815 0 0 {name=l201 lab=vss}
C {serdes/C} 3250 3750 0 0 {name=Cdiv14p value=5f}
N 3250 3720 3250 3685 {lab=d14p}
C {devices/lab_pin} 3250 3685 0 0 {name=l202 lab=d14p}
N 3250 3780 3250 3815 {lab=vss}
C {devices/lab_pin} 3250 3815 0 0 {name=l203 lab=vss}
C {serdes/C} 3590 3750 0 0 {name=Cdiv14n value=5f}
N 3590 3720 3590 3685 {lab=d14n}
C {devices/lab_pin} 3590 3685 0 0 {name=l204 lab=d14n}
N 3590 3780 3590 3815 {lab=vss}
C {devices/lab_pin} 3590 3815 0 0 {name=l205 lab=vss}
C {serdes/C} 3930 3750 0 0 {name=Cdiv18p value=5f}
N 3930 3720 3930 3685 {lab=d18p}
C {devices/lab_pin} 3930 3685 0 0 {name=l206 lab=d18p}
N 3930 3780 3930 3815 {lab=vss}
C {devices/lab_pin} 3930 3815 0 0 {name=l207 lab=vss}
C {serdes/C} 4270 3750 0 0 {name=Cdiv18n value=5f}
N 4270 3720 4270 3685 {lab=d18n}
C {devices/lab_pin} 4270 3685 0 0 {name=l208 lab=d18n}
N 4270 3780 4270 3815 {lab=vss}
C {devices/lab_pin} 4270 3815 0 0 {name=l209 lab=vss}
C {serdes/C} 530 4050 0 0 {name=Cdq1 value=20f}
N 530 4020 530 3985 {lab=dq1}
C {devices/lab_pin} 530 3985 0 0 {name=l210 lab=dq1}
N 530 4080 530 4115 {lab=vss}
C {devices/lab_pin} 530 4115 0 0 {name=l211 lab=vss}
C {serdes/C} 870 4050 0 0 {name=Cw2p value="\{cwire\}"}
N 870 4020 870 3985 {lab=v2p}
C {devices/lab_pin} 870 3985 0 0 {name=l212 lab=v2p}
N 870 4080 870 4115 {lab=vss}
C {devices/lab_pin} 870 4115 0 0 {name=l213 lab=vss}
C {serdes/C} 1210 4050 0 0 {name=Cw2n value="\{cwire\}"}
N 1210 4020 1210 3985 {lab=v2n}
C {devices/lab_pin} 1210 3985 0 0 {name=l214 lab=v2n}
N 1210 4080 1210 4115 {lab=vss}
C {devices/lab_pin} 1210 4115 0 0 {name=l215 lab=vss}
C {serdes/C} 1550 4050 0 0 {name=Ccm2p value=20f}
N 1550 4020 1550 3985 {lab=cm2p}
C {devices/lab_pin} 1550 3985 0 0 {name=l216 lab=cm2p}
N 1550 4080 1550 4115 {lab=vss}
C {devices/lab_pin} 1550 4115 0 0 {name=l217 lab=vss}
C {serdes/C} 1890 4050 0 0 {name=Ccm2n value=20f}
N 1890 4020 1890 3985 {lab=cm2n}
C {devices/lab_pin} 1890 3985 0 0 {name=l218 lab=cm2n}
N 1890 4080 1890 4115 {lab=vss}
C {devices/lab_pin} 1890 4115 0 0 {name=l219 lab=vss}
C {serdes/C} 2230 4050 0 0 {name=Cfb2 value=20f}
N 2230 4020 2230 3985 {lab=fb2}
C {devices/lab_pin} 2230 3985 0 0 {name=l220 lab=fb2}
N 2230 4080 2230 4115 {lab=vss}
C {devices/lab_pin} 2230 4115 0 0 {name=l221 lab=vss}
C {serdes/C} 2570 4050 0 0 {name=Cfb2n value=20f}
N 2570 4020 2570 3985 {lab=fb2n}
C {devices/lab_pin} 2570 3985 0 0 {name=l222 lab=fb2n}
N 2570 4080 2570 4115 {lab=vss}
C {devices/lab_pin} 2570 4115 0 0 {name=l223 lab=vss}
C {serdes/C} 2910 4050 0 0 {name=Cdiv22p value=5f}
N 2910 4020 2910 3985 {lab=d22p}
C {devices/lab_pin} 2910 3985 0 0 {name=l224 lab=d22p}
N 2910 4080 2910 4115 {lab=vss}
C {devices/lab_pin} 2910 4115 0 0 {name=l225 lab=vss}
C {serdes/C} 3250 4050 0 0 {name=Cdiv22n value=5f}
N 3250 4020 3250 3985 {lab=d22n}
C {devices/lab_pin} 3250 3985 0 0 {name=l226 lab=d22n}
N 3250 4080 3250 4115 {lab=vss}
C {devices/lab_pin} 3250 4115 0 0 {name=l227 lab=vss}
C {serdes/C} 3590 4050 0 0 {name=Cdiv24p value=5f}
N 3590 4020 3590 3985 {lab=d24p}
C {devices/lab_pin} 3590 3985 0 0 {name=l228 lab=d24p}
N 3590 4080 3590 4115 {lab=vss}
C {devices/lab_pin} 3590 4115 0 0 {name=l229 lab=vss}
C {serdes/C} 3930 4050 0 0 {name=Cdiv24n value=5f}
N 3930 4020 3930 3985 {lab=d24n}
C {devices/lab_pin} 3930 3985 0 0 {name=l230 lab=d24n}
N 3930 4080 3930 4115 {lab=vss}
C {devices/lab_pin} 3930 4115 0 0 {name=l231 lab=vss}
C {serdes/C} 4270 4050 0 0 {name=Cdiv28p value=5f}
N 4270 4020 4270 3985 {lab=d28p}
C {devices/lab_pin} 4270 3985 0 0 {name=l232 lab=d28p}
N 4270 4080 4270 4115 {lab=vss}
C {devices/lab_pin} 4270 4115 0 0 {name=l233 lab=vss}
C {serdes/C} 530 4350 0 0 {name=Cdiv28n value=5f}
N 530 4320 530 4285 {lab=d28n}
C {devices/lab_pin} 530 4285 0 0 {name=l234 lab=d28n}
N 530 4380 530 4415 {lab=vss}
C {devices/lab_pin} 530 4415 0 0 {name=l235 lab=vss}
C {serdes/C} 870 4350 0 0 {name=Cdq2 value=20f}
N 870 4320 870 4285 {lab=dq2}
C {devices/lab_pin} 870 4285 0 0 {name=l236 lab=dq2}
N 870 4380 870 4415 {lab=vss}
C {devices/lab_pin} 870 4415 0 0 {name=l237 lab=vss}
C {serdes/C} 1210 4350 0 0 {name=Cw3p value="\{cwire\}"}
N 1210 4320 1210 4285 {lab=v3p}
C {devices/lab_pin} 1210 4285 0 0 {name=l238 lab=v3p}
N 1210 4380 1210 4415 {lab=vss}
C {devices/lab_pin} 1210 4415 0 0 {name=l239 lab=vss}
C {serdes/C} 1550 4350 0 0 {name=Cw3n value="\{cwire\}"}
N 1550 4320 1550 4285 {lab=v3n}
C {devices/lab_pin} 1550 4285 0 0 {name=l240 lab=v3n}
N 1550 4380 1550 4415 {lab=vss}
C {devices/lab_pin} 1550 4415 0 0 {name=l241 lab=vss}
C {serdes/C} 1890 4350 0 0 {name=Ccm3p value=20f}
N 1890 4320 1890 4285 {lab=cm3p}
C {devices/lab_pin} 1890 4285 0 0 {name=l242 lab=cm3p}
N 1890 4380 1890 4415 {lab=vss}
C {devices/lab_pin} 1890 4415 0 0 {name=l243 lab=vss}
C {serdes/C} 2230 4350 0 0 {name=Ccm3n value=20f}
N 2230 4320 2230 4285 {lab=cm3n}
C {devices/lab_pin} 2230 4285 0 0 {name=l244 lab=cm3n}
N 2230 4380 2230 4415 {lab=vss}
C {devices/lab_pin} 2230 4415 0 0 {name=l245 lab=vss}
C {serdes/C} 2570 4350 0 0 {name=Cfb3 value=20f}
N 2570 4320 2570 4285 {lab=fb3}
C {devices/lab_pin} 2570 4285 0 0 {name=l246 lab=fb3}
N 2570 4380 2570 4415 {lab=vss}
C {devices/lab_pin} 2570 4415 0 0 {name=l247 lab=vss}
C {serdes/C} 2910 4350 0 0 {name=Cfb3n value=20f}
N 2910 4320 2910 4285 {lab=fb3n}
C {devices/lab_pin} 2910 4285 0 0 {name=l248 lab=fb3n}
N 2910 4380 2910 4415 {lab=vss}
C {devices/lab_pin} 2910 4415 0 0 {name=l249 lab=vss}
C {serdes/C} 3250 4350 0 0 {name=Cdiv32p value=5f}
N 3250 4320 3250 4285 {lab=d32p}
C {devices/lab_pin} 3250 4285 0 0 {name=l250 lab=d32p}
N 3250 4380 3250 4415 {lab=vss}
C {devices/lab_pin} 3250 4415 0 0 {name=l251 lab=vss}
C {serdes/C} 3590 4350 0 0 {name=Cdiv32n value=5f}
N 3590 4320 3590 4285 {lab=d32n}
C {devices/lab_pin} 3590 4285 0 0 {name=l252 lab=d32n}
N 3590 4380 3590 4415 {lab=vss}
C {devices/lab_pin} 3590 4415 0 0 {name=l253 lab=vss}
C {serdes/C} 3930 4350 0 0 {name=Cdiv34p value=5f}
N 3930 4320 3930 4285 {lab=d34p}
C {devices/lab_pin} 3930 4285 0 0 {name=l254 lab=d34p}
N 3930 4380 3930 4415 {lab=vss}
C {devices/lab_pin} 3930 4415 0 0 {name=l255 lab=vss}
C {serdes/C} 4270 4350 0 0 {name=Cdiv34n value=5f}
N 4270 4320 4270 4285 {lab=d34n}
C {devices/lab_pin} 4270 4285 0 0 {name=l256 lab=d34n}
N 4270 4380 4270 4415 {lab=vss}
C {devices/lab_pin} 4270 4415 0 0 {name=l257 lab=vss}
C {serdes/C} 530 4650 0 0 {name=Cdiv38p value=5f}
N 530 4620 530 4585 {lab=d38p}
C {devices/lab_pin} 530 4585 0 0 {name=l258 lab=d38p}
N 530 4680 530 4715 {lab=vss}
C {devices/lab_pin} 530 4715 0 0 {name=l259 lab=vss}
C {serdes/C} 870 4650 0 0 {name=Cdiv38n value=5f}
N 870 4620 870 4585 {lab=d38n}
C {devices/lab_pin} 870 4585 0 0 {name=l260 lab=d38n}
N 870 4680 870 4715 {lab=vss}
C {devices/lab_pin} 870 4715 0 0 {name=l261 lab=vss}
C {serdes/C} 1210 4650 0 0 {name=Cdq3 value=20f}
N 1210 4620 1210 4585 {lab=dq3}
C {devices/lab_pin} 1210 4585 0 0 {name=l262 lab=dq3}
N 1210 4680 1210 4715 {lab=vss}
C {devices/lab_pin} 1210 4715 0 0 {name=l263 lab=vss}
T {VCO taps all see identical buffers. Three full dummy prescalers/RX/DFFs form a conservative load reference.} 340 3000 0 0 0.32 0.32 {}
T {vdd_dummy remains biased; dummy reset is external rst_b, while PFD reset is internal. Not a final low-power tree.} 340 3070 0 0 0.28 0.28 {}
T {Each CMOS output: 20 fF; VCO wire: cwire per leg; intermediate divider taps: 5 fF.} 340 3140 0 0 0.26 0.26 {}
T {DEFAULT PARAMETERS: cwire=0.5f} 100 5115 0 0 0.24 0.24 {}
