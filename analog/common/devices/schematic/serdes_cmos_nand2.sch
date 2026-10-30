G {}
V {}
S {}
E {}
T {SERDES CMOS NAND2} 100 45 0 0 0.48 0.48 {}
T {Source: analog/common/devices/spice/cmos_logic.spice} 100 100 0 0 0.21 0.21 {}
T {Editable circuit view | W is total width in um | external models/bias; no layout extraction} 100 133 0 0 0.2 0.2 {}
C {devices/iopin} 90 230 0 1 {name=p1 lab=a}
C {devices/iopin} 90 285 0 1 {name=p2 lab=b}
C {devices/iopin} 90 340 0 1 {name=p3 lab=y}
C {devices/iopin} 90 395 0 1 {name=p4 lab=vdd}
C {devices/iopin} 90 450 0 1 {name=p5 lab=vss}
C {serdes/serdes_nfet} 500 350 0 0 {name=Xna w="\{wn\}"}
N 520 320 520 285 {lab=y}
C {devices/lab_pin} 520 285 0 0 {name=l1 lab=y}
N 480 350 435 350 {lab=a}
C {devices/lab_pin} 435 350 0 0 {name=l2 lab=a}
N 520 380 520 415 {lab=mid}
C {devices/lab_pin} 520 415 0 0 {name=l3 lab=mid}
N 520 350 585 350 {lab=vss}
C {devices/lab_pin} 585 350 0 1 {name=l4 lab=vss}
C {serdes/serdes_nfet} 1180 350 0 0 {name=Xnb w="\{wn\}"}
N 1200 320 1200 285 {lab=mid}
C {devices/lab_pin} 1200 285 0 0 {name=l5 lab=mid}
N 1160 350 1115 350 {lab=b}
C {devices/lab_pin} 1115 350 0 0 {name=l6 lab=b}
N 1200 380 1200 415 {lab=vss}
C {devices/lab_pin} 1200 415 0 0 {name=l7 lab=vss}
N 1200 350 1265 350 {lab=vss}
C {devices/lab_pin} 1265 350 0 1 {name=l8 lab=vss}
C {serdes/serdes_pfet} 500 780 2 1 {name=Xpa w="\{wp\}"}
N 520 810 520 845 {lab=y}
C {devices/lab_pin} 520 845 0 0 {name=l9 lab=y}
N 480 780 435 780 {lab=a}
C {devices/lab_pin} 435 780 0 0 {name=l10 lab=a}
N 520 750 520 715 {lab=vdd}
C {devices/lab_pin} 520 715 0 0 {name=l11 lab=vdd}
N 520 780 585 780 {lab=vdd}
C {devices/lab_pin} 585 780 0 1 {name=l12 lab=vdd}
C {serdes/serdes_pfet} 1180 780 2 1 {name=Xpb w="\{wp\}"}
N 1200 810 1200 845 {lab=y}
C {devices/lab_pin} 1200 845 0 0 {name=l13 lab=y}
N 1160 780 1115 780 {lab=b}
C {devices/lab_pin} 1115 780 0 0 {name=l14 lab=b}
N 1200 750 1200 715 {lab=vdd}
C {devices/lab_pin} 1200 715 0 0 {name=l15 lab=vdd}
N 1200 780 1265 780 {lab=vdd}
C {devices/lab_pin} 1265 780 0 1 {name=l16 lab=vdd}
T {DEFAULT PARAMETERS: wn=2  wp=2} 100 1245 0 0 0.24 0.24 {}
