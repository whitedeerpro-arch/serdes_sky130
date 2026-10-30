G {}
V {}
S {}
E {}
T {SERDES CMOS DFF RESET} 100 45 0 0 0.48 0.48 {}
T {Source: analog/common/devices/spice/cmos_dff_reset.spice} 100 100 0 0 0.21 0.21 {}
T {Editable circuit view | W is total width in um | external models/bias; no layout extraction} 100 133 0 0 0.2 0.2 {}
C {devices/iopin} 90 230 0 1 {name=p1 lab=d}
C {devices/iopin} 90 285 0 1 {name=p2 lab=clk}
C {devices/iopin} 90 340 0 1 {name=p3 lab=rst_b}
C {devices/iopin} 90 395 0 1 {name=p4 lab=q}
C {devices/iopin} 90 450 0 1 {name=p5 lab=vdd}
C {devices/iopin} 90 505 0 1 {name=p6 lab=vss}
C {serdes/serdes_cmos_inv} 500 350 0 0 {name=Xcb}
N 300 350 255 350 {lab=clk}
C {devices/lab_pin} 255 350 0 0 {name=l1 lab=clk}
N 700 350 745 350 {lab=clk_b}
C {devices/lab_pin} 745 350 0 1 {name=l2 lab=clk_b}
N 450 210 450 175 {lab=vdd}
C {devices/lab_pin} 450 175 0 0 {name=l3 lab=vdd}
N 500 490 500 525 {lab=vss}
C {devices/lab_pin} 500 525 0 0 {name=l4 lab=vss}
C {serdes/serdes_cmos_nor2} 1180 350 0 0 {name=Xme}
N 980 330 935 330 {lab=clk}
C {devices/lab_pin} 935 330 0 0 {name=l5 lab=clk}
N 980 370 935 370 {lab=slave_en}
C {devices/lab_pin} 935 370 0 0 {name=l6 lab=slave_en}
N 1380 350 1425 350 {lab=master_en}
C {devices/lab_pin} 1425 350 0 1 {name=l7 lab=master_en}
N 1130 210 1130 175 {lab=vdd}
C {devices/lab_pin} 1130 175 0 0 {name=l8 lab=vdd}
N 1180 490 1180 525 {lab=vss}
C {devices/lab_pin} 1180 525 0 0 {name=l9 lab=vss}
C {serdes/serdes_cmos_nor2} 500 780 0 0 {name=Xse}
N 300 760 255 760 {lab=clk_b}
C {devices/lab_pin} 255 760 0 0 {name=l10 lab=clk_b}
N 300 800 255 800 {lab=master_en}
C {devices/lab_pin} 255 800 0 0 {name=l11 lab=master_en}
N 700 780 745 780 {lab=slave_en}
C {devices/lab_pin} 745 780 0 1 {name=l12 lab=slave_en}
N 450 640 450 605 {lab=vdd}
C {devices/lab_pin} 450 605 0 0 {name=l13 lab=vdd}
N 500 920 500 955 {lab=vss}
C {devices/lab_pin} 500 955 0 0 {name=l14 lab=vss}
C {serdes/serdes_cmos_latch_reset} 1180 780 0 0 {name=Xm}
N 980 740 935 740 {lab=d}
C {devices/lab_pin} 935 740 0 0 {name=l15 lab=d}
N 980 780 935 780 {lab=master_en}
C {devices/lab_pin} 935 780 0 0 {name=l16 lab=master_en}
N 980 820 935 820 {lab=rst_b}
C {devices/lab_pin} 935 820 0 0 {name=l17 lab=rst_b}
N 1380 780 1425 780 {lab=m}
C {devices/lab_pin} 1425 780 0 1 {name=l18 lab=m}
N 1130 635 1130 600 {lab=vdd}
C {devices/lab_pin} 1130 600 0 0 {name=l19 lab=vdd}
N 1180 925 1180 960 {lab=vss}
C {devices/lab_pin} 1180 960 0 0 {name=l20 lab=vss}
C {serdes/serdes_cmos_latch_reset} 500 1210 0 0 {name=Xs}
N 300 1170 255 1170 {lab=m}
C {devices/lab_pin} 255 1170 0 0 {name=l21 lab=m}
N 300 1210 255 1210 {lab=slave_en}
C {devices/lab_pin} 255 1210 0 0 {name=l22 lab=slave_en}
N 300 1250 255 1250 {lab=rst_b}
C {devices/lab_pin} 255 1250 0 0 {name=l23 lab=rst_b}
N 700 1210 745 1210 {lab=q}
C {devices/lab_pin} 745 1210 0 1 {name=l24 lab=q}
N 450 1065 450 1030 {lab=vdd}
C {devices/lab_pin} 450 1030 0 0 {name=l25 lab=vdd}
N 500 1355 500 1390 {lab=vss}
C {devices/lab_pin} 500 1390 0 0 {name=l26 lab=vss}
