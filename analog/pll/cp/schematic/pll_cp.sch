G {}
V {}
S {}
E {}
T {PLL CP} 100 45 0 0 0.48 0.48 {}
T {Source: analog/pll/cp/spice/charge_pump.spice} 100 100 0 0 0.21 0.21 {}
T {Editable circuit view | W is total width in um | external models/bias; no layout extraction} 100 133 0 0 0.2 0.2 {}
C {devices/iopin} 90 230 0 1 {name=p1 lab=up}
C {devices/iopin} 90 285 0 1 {name=p2 lab=dn}
C {devices/iopin} 90 340 0 1 {name=p3 lab=out}
C {devices/iopin} 90 395 0 1 {name=p4 lab=vbn}
C {devices/iopin} 90 450 0 1 {name=p5 lab=vbp}
C {devices/iopin} 90 505 0 1 {name=p6 lab=vdd}
C {devices/iopin} 90 560 0 1 {name=p7 lab=vss}
C {serdes/serdes_nfet} 450 550 0 0 {name=Xupn w="\{up_wn\}" l="\{up_ln\}"}
N 470 520 470 485 {lab=up_b}
C {devices/lab_pin} 470 485 0 0 {name=l1 lab=up_b}
N 430 550 385 550 {lab=up}
C {devices/lab_pin} 385 550 0 0 {name=l2 lab=up}
N 470 580 470 615 {lab=vss}
C {devices/lab_pin} 470 615 0 0 {name=l3 lab=vss}
N 470 550 535 550 {lab=vss}
C {devices/lab_pin} 535 550 0 1 {name=l4 lab=vss}
C {serdes/serdes_pfet} 450 350 2 1 {name=Xupp w="\{up_wp\}"}
N 470 380 470 415 {lab=up_b}
C {devices/lab_pin} 470 415 0 0 {name=l5 lab=up_b}
N 430 350 385 350 {lab=up}
C {devices/lab_pin} 385 350 0 0 {name=l6 lab=up}
N 470 320 470 285 {lab=vdd}
C {devices/lab_pin} 470 285 0 0 {name=l7 lab=vdd}
N 470 350 535 350 {lab=vdd}
C {devices/lab_pin} 535 350 0 1 {name=l8 lab=vdd}
C {serdes/serdes_cmos_inv} 460 930 0 0 {name=Xdn1 wn=1 wp=2}
N 260 930 215 930 {lab=dn}
C {devices/lab_pin} 215 930 0 0 {name=l9 lab=dn}
N 660 930 705 930 {lab=dn_b}
C {devices/lab_pin} 705 930 0 1 {name=l10 lab=dn_b}
N 410 790 410 755 {lab=vdd}
C {devices/lab_pin} 410 755 0 0 {name=l11 lab=vdd}
N 460 1070 460 1105 {lab=vss}
C {devices/lab_pin} 460 1105 0 0 {name=l12 lab=vss}
C {serdes/serdes_cmos_inv} 460 1330 0 0 {name=Xdn2 wn=1 wp=2}
N 260 1330 215 1330 {lab=dn_b}
C {devices/lab_pin} 215 1330 0 0 {name=l13 lab=dn_b}
N 660 1330 705 1330 {lab=dn_on}
C {devices/lab_pin} 705 1330 0 1 {name=l14 lab=dn_on}
N 410 1190 410 1155 {lab=vdd}
C {devices/lab_pin} 410 1155 0 0 {name=l15 lab=vdd}
N 460 1470 460 1505 {lab=vss}
C {devices/lab_pin} 460 1505 0 0 {name=l16 lab=vss}
C {serdes/serdes_pfet} 1120 350 2 1 {name=Xp w="\{wp\}" l="\{lmirror\}" nf=4}
N 1140 380 1140 415 {lab=ps}
C {devices/lab_pin} 1140 415 0 0 {name=l17 lab=ps}
N 1100 350 1055 350 {lab=vbp}
C {devices/lab_pin} 1055 350 0 0 {name=l18 lab=vbp}
N 1140 320 1140 285 {lab=vdd}
C {devices/lab_pin} 1140 285 0 0 {name=l19 lab=vdd}
N 1140 350 1205 350 {lab=vdd}
C {devices/lab_pin} 1205 350 0 1 {name=l20 lab=vdd}
C {serdes/serdes_pfet} 1120 650 2 1 {name=Xps w="\{wsp\}"}
N 1140 680 1140 715 {lab=out}
C {devices/lab_pin} 1140 715 0 0 {name=l21 lab=out}
N 1100 650 1055 650 {lab=up_b}
C {devices/lab_pin} 1055 650 0 0 {name=l22 lab=up_b}
N 1140 620 1140 585 {lab=ps}
C {devices/lab_pin} 1140 585 0 0 {name=l23 lab=ps}
N 1140 650 1205 650 {lab=vdd}
C {devices/lab_pin} 1205 650 0 1 {name=l24 lab=vdd}
C {serdes/serdes_nfet} 1120 950 0 0 {name=Xns w="\{wsn\}"}
N 1140 920 1140 885 {lab=out}
C {devices/lab_pin} 1140 885 0 0 {name=l25 lab=out}
N 1100 950 1055 950 {lab=dn_on}
C {devices/lab_pin} 1055 950 0 0 {name=l26 lab=dn_on}
N 1140 980 1140 1015 {lab=ns}
C {devices/lab_pin} 1140 1015 0 0 {name=l27 lab=ns}
N 1140 950 1205 950 {lab=vss}
C {devices/lab_pin} 1205 950 0 1 {name=l28 lab=vss}
C {serdes/serdes_nfet} 1120 1250 0 0 {name=Xn w="\{wn\}" l="\{lmirror\}"}
N 1140 1220 1140 1185 {lab=ns}
C {devices/lab_pin} 1140 1185 0 0 {name=l29 lab=ns}
N 1100 1250 1055 1250 {lab=vbn}
C {devices/lab_pin} 1055 1250 0 0 {name=l30 lab=vbn}
N 1140 1280 1140 1315 {lab=vss}
C {devices/lab_pin} 1140 1315 0 0 {name=l31 lab=vss}
N 1140 1250 1205 1250 {lab=vss}
C {devices/lab_pin} 1205 1250 0 1 {name=l32 lab=vss}
N 1140 380 1140 620 {lab=ps}
N 1140 680 1140 920 {lab=out}
N 1140 980 1140 1220 {lab=ns}
N 470 380 470 520 {lab=up_b}
T {UP path: PMOS mirror / series switch} 1370 420 0 0 0.24 0.24 {}
T {DN path: series switch / NMOS mirror} 1370 1100 0 0 0.24 0.24 {}
T {Bias references are external; positive output current charges LF.} 390 1600 0 0 0.26 0.26 {}
T {DEFAULT PARAMETERS: wn=5  wp=20  lmirror=1  wsn=2  wsp=4  up_wn=0.5  up_wp=2  up_ln=0.88} 100 2000 0 0 0.24 0.24 {}
