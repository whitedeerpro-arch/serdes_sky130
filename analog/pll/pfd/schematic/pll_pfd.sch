G {}
V {}
S {}
E {}
T {PLL PFD} 100 45 0 0 0.48 0.48 {}
T {Source: analog/pll/pfd/spice/pfd_cmos.spice} 100 100 0 0 0.21 0.21 {}
T {Editable circuit view | W is total width in um | external models/bias; no layout extraction} 100 133 0 0 0.2 0.2 {}
C {devices/iopin} 90 230 0 1 {name=p1 lab=ref}
C {devices/iopin} 90 285 0 1 {name=p2 lab=fb}
C {devices/iopin} 90 340 0 1 {name=p3 lab=rst_b}
C {devices/iopin} 90 395 0 1 {name=p4 lab=up}
C {devices/iopin} 90 450 0 1 {name=p5 lab=dn}
C {devices/iopin} 90 505 0 1 {name=p6 lab=vdd}
C {devices/iopin} 90 560 0 1 {name=p7 lab=vss}
C {serdes/pll_cmos_dff_reset} 500 350 0 0 {name=Xup}
N 300 310 255 310 {lab=vdd}
C {devices/lab_pin} 255 310 0 0 {name=l1 lab=vdd}
N 300 350 255 350 {lab=ref}
C {devices/lab_pin} 255 350 0 0 {name=l2 lab=ref}
N 300 390 255 390 {lab=clear_b}
C {devices/lab_pin} 255 390 0 0 {name=l3 lab=clear_b}
N 700 350 745 350 {lab=qu}
C {devices/lab_pin} 745 350 0 1 {name=l4 lab=qu}
N 450 205 450 170 {lab=vdd}
C {devices/lab_pin} 450 170 0 0 {name=l5 lab=vdd}
N 500 495 500 530 {lab=vss}
C {devices/lab_pin} 500 530 0 0 {name=l6 lab=vss}
C {serdes/pll_cmos_dff_reset} 1180 350 0 0 {name=Xdn}
N 980 310 935 310 {lab=vdd}
C {devices/lab_pin} 935 310 0 0 {name=l7 lab=vdd}
N 980 350 935 350 {lab=fb}
C {devices/lab_pin} 935 350 0 0 {name=l8 lab=fb}
N 980 390 935 390 {lab=clear_b}
C {devices/lab_pin} 935 390 0 0 {name=l9 lab=clear_b}
N 1380 350 1425 350 {lab=qd}
C {devices/lab_pin} 1425 350 0 1 {name=l10 lab=qd}
N 1130 205 1130 170 {lab=vdd}
C {devices/lab_pin} 1130 170 0 0 {name=l11 lab=vdd}
N 1180 495 1180 530 {lab=vss}
C {devices/lab_pin} 1180 530 0 0 {name=l12 lab=vss}
C {serdes/serdes_cmos_nand2} 1860 350 0 0 {name=Xdetect}
N 1660 330 1615 330 {lab=qu}
C {devices/lab_pin} 1615 330 0 0 {name=l13 lab=qu}
N 1660 370 1615 370 {lab=qd}
C {devices/lab_pin} 1615 370 0 0 {name=l14 lab=qd}
N 2060 350 2105 350 {lab=request_b}
C {devices/lab_pin} 2105 350 0 1 {name=l15 lab=request_b}
N 1810 210 1810 175 {lab=vdd}
C {devices/lab_pin} 1810 175 0 0 {name=l16 lab=vdd}
N 1860 490 1860 525 {lab=vss}
C {devices/lab_pin} 1860 525 0 0 {name=l17 lab=vss}
C {serdes/serdes_cmos_inv} 500 780 0 0 {name=Xdelay1}
N 300 780 255 780 {lab=request_b}
C {devices/lab_pin} 255 780 0 0 {name=l18 lab=request_b}
N 700 780 745 780 {lab=rd1}
C {devices/lab_pin} 745 780 0 1 {name=l19 lab=rd1}
N 450 640 450 605 {lab=vdd}
C {devices/lab_pin} 450 605 0 0 {name=l20 lab=vdd}
N 500 920 500 955 {lab=vss}
C {devices/lab_pin} 500 955 0 0 {name=l21 lab=vss}
C {serdes/serdes_cmos_inv} 1180 780 0 0 {name=Xdelay2}
N 980 780 935 780 {lab=rd1}
C {devices/lab_pin} 935 780 0 0 {name=l22 lab=rd1}
N 1380 780 1425 780 {lab=rd2}
C {devices/lab_pin} 1425 780 0 1 {name=l23 lab=rd2}
N 1130 640 1130 605 {lab=vdd}
C {devices/lab_pin} 1130 605 0 0 {name=l24 lab=vdd}
N 1180 920 1180 955 {lab=vss}
C {devices/lab_pin} 1180 955 0 0 {name=l25 lab=vss}
C {serdes/C} 1860 780 0 0 {name=Cd1 value="\{reset_cap\}"}
N 1860 750 1860 715 {lab=rd1}
C {devices/lab_pin} 1860 715 0 0 {name=l26 lab=rd1}
N 1860 810 1860 845 {lab=vss}
C {devices/lab_pin} 1860 845 0 0 {name=l27 lab=vss}
C {serdes/C} 500 1210 0 0 {name=Cd2 value="\{reset_cap\}"}
N 500 1180 500 1145 {lab=rd2}
C {devices/lab_pin} 500 1145 0 0 {name=l28 lab=rd2}
N 500 1240 500 1275 {lab=vss}
C {devices/lab_pin} 500 1275 0 0 {name=l29 lab=vss}
C {serdes/serdes_cmos_and2} 1180 1210 0 0 {name=Xclear}
N 980 1190 935 1190 {lab=rst_b}
C {devices/lab_pin} 935 1190 0 0 {name=l30 lab=rst_b}
N 980 1230 935 1230 {lab=rd2}
C {devices/lab_pin} 935 1230 0 0 {name=l31 lab=rd2}
N 1380 1210 1425 1210 {lab=clear_b}
C {devices/lab_pin} 1425 1210 0 1 {name=l32 lab=clear_b}
N 1130 1070 1130 1035 {lab=vdd}
C {devices/lab_pin} 1130 1035 0 0 {name=l33 lab=vdd}
N 1180 1350 1180 1385 {lab=vss}
C {devices/lab_pin} 1180 1385 0 0 {name=l34 lab=vss}
C {serdes/serdes_cmos_inv} 1860 1210 0 0 {name=Xub1 wn=2 wp=4}
N 1660 1210 1615 1210 {lab=qu}
C {devices/lab_pin} 1615 1210 0 0 {name=l35 lab=qu}
N 2060 1210 2105 1210 {lab=ub}
C {devices/lab_pin} 2105 1210 0 1 {name=l36 lab=ub}
N 1810 1070 1810 1035 {lab=vdd}
C {devices/lab_pin} 1810 1035 0 0 {name=l37 lab=vdd}
N 1860 1350 1860 1385 {lab=vss}
C {devices/lab_pin} 1860 1385 0 0 {name=l38 lab=vss}
C {serdes/serdes_cmos_inv} 500 1640 0 0 {name=Xub2 wn="\{out_wn\}" wp="\{out_wp\}"}
N 300 1640 255 1640 {lab=ub}
C {devices/lab_pin} 255 1640 0 0 {name=l39 lab=ub}
N 700 1640 745 1640 {lab=up}
C {devices/lab_pin} 745 1640 0 1 {name=l40 lab=up}
N 450 1500 450 1465 {lab=vdd}
C {devices/lab_pin} 450 1465 0 0 {name=l41 lab=vdd}
N 500 1780 500 1815 {lab=vss}
C {devices/lab_pin} 500 1815 0 0 {name=l42 lab=vss}
C {serdes/serdes_cmos_inv} 1180 1640 0 0 {name=Xdb1 wn=2 wp=4}
N 980 1640 935 1640 {lab=qd}
C {devices/lab_pin} 935 1640 0 0 {name=l43 lab=qd}
N 1380 1640 1425 1640 {lab=db}
C {devices/lab_pin} 1425 1640 0 1 {name=l44 lab=db}
N 1130 1500 1130 1465 {lab=vdd}
C {devices/lab_pin} 1130 1465 0 0 {name=l45 lab=vdd}
N 1180 1780 1180 1815 {lab=vss}
C {devices/lab_pin} 1180 1815 0 0 {name=l46 lab=vss}
C {serdes/serdes_cmos_inv} 1860 1640 0 0 {name=Xdb2 wn="\{out_wn\}" wp="\{out_wp\}"}
N 1660 1640 1615 1640 {lab=db}
C {devices/lab_pin} 1615 1640 0 0 {name=l47 lab=db}
N 2060 1640 2105 1640 {lab=dn}
C {devices/lab_pin} 2105 1640 0 1 {name=l48 lab=dn}
N 1810 1500 1810 1465 {lab=vdd}
C {devices/lab_pin} 1810 1465 0 0 {name=l49 lab=vdd}
N 1860 1780 1860 1815 {lab=vss}
C {devices/lab_pin} 1860 1815 0 0 {name=l50 lab=vss}
T {DEFAULT PARAMETERS: reset_cap=5f  out_wn=4  out_wp=8} 100 2215 0 0 0.24 0.24 {}
