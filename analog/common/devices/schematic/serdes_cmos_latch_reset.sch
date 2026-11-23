G {}
V {}
S {}
E {}
T {SERDES CMOS LATCH RESET} 100 45 0 0 0.48 0.48 {}
T {Source: analog/common/devices/spice/cmos_dff_reset.spice} 100 100 0 0 0.21 0.21 {}
T {Editable circuit view | W is total width in um | external models/bias; no layout extraction} 100 133 0 0 0.2 0.2 {}
C {devices/iopin} 90 230 0 1 {name=p1 lab=d}
C {devices/iopin} 90 285 0 1 {name=p2 lab=en}
C {devices/iopin} 90 340 0 1 {name=p3 lab=rst_b}
C {devices/iopin} 90 395 0 1 {name=p4 lab=q}
C {devices/iopin} 90 450 0 1 {name=p5 lab=vdd}
C {devices/iopin} 90 505 0 1 {name=p6 lab=vss}
C {serdes/serdes_cmos_inv} 500 350 0 0 {name=Xeb}
N 300 350 255 350 {lab=en}
C {devices/lab_pin} 255 350 0 0 {name=l1 lab=en}
N 700 350 745 350 {lab=en_b}
C {devices/lab_pin} 745 350 0 1 {name=l2 lab=en_b}
N 450 210 450 175 {lab=vdd}
C {devices/lab_pin} 450 175 0 0 {name=l3 lab=vdd}
N 500 490 500 525 {lab=vss}
C {devices/lab_pin} 500 525 0 0 {name=l4 lab=vss}
C {serdes/serdes_cmos_nand2} 1180 350 0 0 {name=Xpn}
N 980 330 935 330 {lab=en}
C {devices/lab_pin} 935 330 0 0 {name=l5 lab=en}
N 980 370 935 370 {lab=rst_b}
C {devices/lab_pin} 935 370 0 0 {name=l6 lab=rst_b}
N 1380 350 1425 350 {lab=pass_b}
C {devices/lab_pin} 1425 350 0 1 {name=l7 lab=pass_b}
N 1130 210 1130 175 {lab=vdd}
C {devices/lab_pin} 1130 175 0 0 {name=l8 lab=vdd}
N 1180 490 1180 525 {lab=vss}
C {devices/lab_pin} 1180 525 0 0 {name=l9 lab=vss}
C {serdes/serdes_cmos_inv} 1860 350 0 0 {name=Xpi}
N 1660 350 1615 350 {lab=pass_b}
C {devices/lab_pin} 1615 350 0 0 {name=l10 lab=pass_b}
N 2060 350 2105 350 {lab=pass}
C {devices/lab_pin} 2105 350 0 1 {name=l11 lab=pass}
N 1810 210 1810 175 {lab=vdd}
C {devices/lab_pin} 1810 175 0 0 {name=l12 lab=vdd}
N 1860 490 1860 525 {lab=vss}
C {devices/lab_pin} 1860 525 0 0 {name=l13 lab=vss}
C {serdes/serdes_cmos_nand2} 500 780 0 0 {name=Xhn}
N 300 760 255 760 {lab=en_b}
C {devices/lab_pin} 255 760 0 0 {name=l14 lab=en_b}
N 300 800 255 800 {lab=rst_b}
C {devices/lab_pin} 255 800 0 0 {name=l15 lab=rst_b}
N 700 780 745 780 {lab=hold_b}
C {devices/lab_pin} 745 780 0 1 {name=l16 lab=hold_b}
N 450 640 450 605 {lab=vdd}
C {devices/lab_pin} 450 605 0 0 {name=l17 lab=vdd}
N 500 920 500 955 {lab=vss}
C {devices/lab_pin} 500 955 0 0 {name=l18 lab=vss}
C {serdes/serdes_cmos_inv} 1180 780 0 0 {name=Xhi}
N 980 780 935 780 {lab=hold_b}
C {devices/lab_pin} 935 780 0 0 {name=l19 lab=hold_b}
N 1380 780 1425 780 {lab=hold}
C {devices/lab_pin} 1425 780 0 1 {name=l20 lab=hold}
N 1130 640 1130 605 {lab=vdd}
C {devices/lab_pin} 1130 605 0 0 {name=l21 lab=vdd}
N 1180 920 1180 955 {lab=vss}
C {devices/lab_pin} 1180 955 0 0 {name=l22 lab=vss}
C {serdes/serdes_cmos_inv} 1860 780 0 0 {name=Xr}
N 1660 780 1615 780 {lab=rst_b}
C {devices/lab_pin} 1615 780 0 0 {name=l23 lab=rst_b}
N 2060 780 2105 780 {lab=rst}
C {devices/lab_pin} 2105 780 0 1 {name=l24 lab=rst}
N 1810 640 1810 605 {lab=vdd}
C {devices/lab_pin} 1810 605 0 0 {name=l25 lab=vdd}
N 1860 920 1860 955 {lab=vss}
C {devices/lab_pin} 1860 955 0 0 {name=l26 lab=vss}
C {serdes/serdes_cmos_tgate} 500 1210 0 0 {name=Xpass}
N 300 1150 255 1150 {lab=d}
C {devices/lab_pin} 255 1150 0 0 {name=l27 lab=d}
N 300 1190 255 1190 {lab=x}
C {devices/lab_pin} 255 1190 0 0 {name=l28 lab=x}
N 300 1230 255 1230 {lab=pass}
C {devices/lab_pin} 255 1230 0 0 {name=l29 lab=pass}
N 300 1270 255 1270 {lab=pass_b}
C {devices/lab_pin} 255 1270 0 0 {name=l30 lab=pass_b}
N 450 1065 450 1030 {lab=vdd}
C {devices/lab_pin} 450 1030 0 0 {name=l31 lab=vdd}
N 500 1355 500 1390 {lab=vss}
C {devices/lab_pin} 500 1390 0 0 {name=l32 lab=vss}
C {serdes/serdes_cmos_tgate} 1180 1210 0 0 {name=Xhold}
N 980 1150 935 1150 {lab=q}
C {devices/lab_pin} 935 1150 0 0 {name=l33 lab=q}
N 980 1190 935 1190 {lab=x}
C {devices/lab_pin} 935 1190 0 0 {name=l34 lab=x}
N 980 1230 935 1230 {lab=hold}
C {devices/lab_pin} 935 1230 0 0 {name=l35 lab=hold}
N 980 1270 935 1270 {lab=hold_b}
C {devices/lab_pin} 935 1270 0 0 {name=l36 lab=hold_b}
N 1130 1065 1130 1030 {lab=vdd}
C {devices/lab_pin} 1130 1030 0 0 {name=l37 lab=vdd}
N 1180 1355 1180 1390 {lab=vss}
C {devices/lab_pin} 1180 1390 0 0 {name=l38 lab=vss}
C {serdes/serdes_nfet} 1860 1210 0 0 {name=Xreset w=4}
N 1880 1180 1880 1145 {lab=x}
C {devices/lab_pin} 1880 1145 0 0 {name=l39 lab=x}
N 1840 1210 1795 1210 {lab=rst}
C {devices/lab_pin} 1795 1210 0 0 {name=l40 lab=rst}
N 1880 1240 1880 1275 {lab=vss}
C {devices/lab_pin} 1880 1275 0 0 {name=l41 lab=vss}
N 1880 1210 1945 1210 {lab=vss}
C {devices/lab_pin} 1945 1210 0 1 {name=l42 lab=vss}
C {serdes/serdes_cmos_inv} 500 1640 0 0 {name=Xi}
N 300 1640 255 1640 {lab=x}
C {devices/lab_pin} 255 1640 0 0 {name=l43 lab=x}
N 700 1640 745 1640 {lab=q_b}
C {devices/lab_pin} 745 1640 0 1 {name=l44 lab=q_b}
N 450 1500 450 1465 {lab=vdd}
C {devices/lab_pin} 450 1465 0 0 {name=l45 lab=vdd}
N 500 1780 500 1815 {lab=vss}
C {devices/lab_pin} 500 1815 0 0 {name=l46 lab=vss}
C {serdes/serdes_cmos_inv} 1180 1640 0 0 {name=Xo}
N 980 1640 935 1640 {lab=q_b}
C {devices/lab_pin} 935 1640 0 0 {name=l47 lab=q_b}
N 1380 1640 1425 1640 {lab=q}
C {devices/lab_pin} 1425 1640 0 1 {name=l48 lab=q}
N 1130 1500 1130 1465 {lab=vdd}
C {devices/lab_pin} 1130 1465 0 0 {name=l49 lab=vdd}
N 1180 1780 1180 1815 {lab=vss}
C {devices/lab_pin} 1180 1815 0 0 {name=l50 lab=vss}
