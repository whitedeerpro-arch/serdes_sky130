G {}
V {}
S {}
E {}
T {SERDES RX DIFF TO SE} 100 45 0 0 0.48 0.48 {}
T {Source: analog/common/cml_to_cmos/spice/cml_to_cmos.spice} 100 100 0 0 0.21 0.21 {}
T {Editable circuit view | W is total width in um | external models/bias; no layout extraction} 100 133 0 0 0.2 0.2 {}
C {devices/iopin} 90 230 0 1 {name=p1 lab=inp}
C {devices/iopin} 90 285 0 1 {name=p2 lab=inn}
C {devices/iopin} 90 340 0 1 {name=p3 lab=out}
C {devices/iopin} 90 395 0 1 {name=p4 lab=vbias}
C {devices/iopin} 90 450 0 1 {name=p5 lab=vdd}
C {devices/iopin} 90 505 0 1 {name=p6 lab=vss}
C {serdes/serdes_nfet_lvt} 500 350 0 0 {name=Xip w="\{win\}" nf="\{nfin\}"}
N 520 320 520 285 {lab=mirror}
C {devices/lab_pin} 520 285 0 0 {name=l1 lab=mirror}
N 480 350 435 350 {lab=inp}
C {devices/lab_pin} 435 350 0 0 {name=l2 lab=inp}
N 520 380 520 415 {lab=tail}
C {devices/lab_pin} 520 415 0 0 {name=l3 lab=tail}
N 520 350 585 350 {lab=vss}
C {devices/lab_pin} 585 350 0 1 {name=l4 lab=vss}
C {serdes/serdes_nfet_lvt} 1180 350 0 0 {name=Xin w="\{win\}" nf="\{nfin\}"}
N 1200 320 1200 285 {lab=out}
C {devices/lab_pin} 1200 285 0 0 {name=l5 lab=out}
N 1160 350 1115 350 {lab=inn}
C {devices/lab_pin} 1115 350 0 0 {name=l6 lab=inn}
N 1200 380 1200 415 {lab=tail}
C {devices/lab_pin} 1200 415 0 0 {name=l7 lab=tail}
N 1200 350 1265 350 {lab=vss}
C {devices/lab_pin} 1265 350 0 1 {name=l8 lab=vss}
C {serdes/serdes_pfet} 500 780 2 1 {name=Xlp w="\{wload\}" nf="\{nfload\}"}
N 520 810 520 845 {lab=mirror}
C {devices/lab_pin} 520 845 0 0 {name=l9 lab=mirror}
N 480 780 435 780 {lab=mirror}
C {devices/lab_pin} 435 780 0 0 {name=l10 lab=mirror}
N 520 750 520 715 {lab=vdd}
C {devices/lab_pin} 520 715 0 0 {name=l11 lab=vdd}
N 520 780 585 780 {lab=vdd}
C {devices/lab_pin} 585 780 0 1 {name=l12 lab=vdd}
C {serdes/serdes_pfet} 1180 780 2 1 {name=Xln w="\{wload\}" nf="\{nfload\}"}
N 1200 810 1200 845 {lab=out}
C {devices/lab_pin} 1200 845 0 0 {name=l13 lab=out}
N 1160 780 1115 780 {lab=mirror}
C {devices/lab_pin} 1115 780 0 0 {name=l14 lab=mirror}
N 1200 750 1200 715 {lab=vdd}
C {devices/lab_pin} 1200 715 0 0 {name=l15 lab=vdd}
N 1200 780 1265 780 {lab=vdd}
C {devices/lab_pin} 1265 780 0 1 {name=l16 lab=vdd}
C {serdes/serdes_nfet} 500 1210 0 0 {name=Xtail w="\{wtail\}" l=0.5}
N 520 1180 520 1145 {lab=tail}
C {devices/lab_pin} 520 1145 0 0 {name=l17 lab=tail}
N 480 1210 435 1210 {lab=vbias}
C {devices/lab_pin} 435 1210 0 0 {name=l18 lab=vbias}
N 520 1240 520 1275 {lab=vss}
C {devices/lab_pin} 520 1275 0 0 {name=l19 lab=vss}
N 520 1210 585 1210 {lab=vss}
C {devices/lab_pin} 585 1210 0 1 {name=l20 lab=vss}
T {DEFAULT PARAMETERS: win=6  nfin=1  wload=8  nfload=2  wtail=6} 100 1675 0 0 0.24 0.24 {}
