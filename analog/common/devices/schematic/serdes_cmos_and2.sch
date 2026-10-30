G {}
V {}
S {}
E {}
T {SERDES CMOS AND2} 100 45 0 0 0.48 0.48 {}
T {Source: analog/common/devices/spice/cmos_logic.spice} 100 100 0 0 0.21 0.21 {}
T {Editable circuit view | W is total width in um | external models/bias; no layout extraction} 100 133 0 0 0.2 0.2 {}
C {devices/iopin} 90 230 0 1 {name=p1 lab=a}
C {devices/iopin} 90 285 0 1 {name=p2 lab=b}
C {devices/iopin} 90 340 0 1 {name=p3 lab=y}
C {devices/iopin} 90 395 0 1 {name=p4 lab=vdd}
C {devices/iopin} 90 450 0 1 {name=p5 lab=vss}
C {serdes/serdes_cmos_nand2} 500 350 0 0 {name=Xn}
N 300 330 255 330 {lab=a}
C {devices/lab_pin} 255 330 0 0 {name=l1 lab=a}
N 300 370 255 370 {lab=b}
C {devices/lab_pin} 255 370 0 0 {name=l2 lab=b}
N 700 350 745 350 {lab=yn}
C {devices/lab_pin} 745 350 0 1 {name=l3 lab=yn}
N 450 210 450 175 {lab=vdd}
C {devices/lab_pin} 450 175 0 0 {name=l4 lab=vdd}
N 500 490 500 525 {lab=vss}
C {devices/lab_pin} 500 525 0 0 {name=l5 lab=vss}
C {serdes/serdes_cmos_inv} 1180 350 0 0 {name=Xi}
N 980 350 935 350 {lab=yn}
C {devices/lab_pin} 935 350 0 0 {name=l6 lab=yn}
N 1380 350 1425 350 {lab=y}
C {devices/lab_pin} 1425 350 0 1 {name=l7 lab=y}
N 1130 210 1130 175 {lab=vdd}
C {devices/lab_pin} 1130 175 0 0 {name=l8 lab=vdd}
N 1180 490 1180 525 {lab=vss}
C {devices/lab_pin} 1180 525 0 0 {name=l9 lab=vss}
