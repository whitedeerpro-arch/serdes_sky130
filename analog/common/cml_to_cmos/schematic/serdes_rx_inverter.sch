G {}
V {}
S {}
E {}
T {SERDES RX INVERTER} 100 45 0 0 0.48 0.48 {}
T {Source: analog/common/cml_to_cmos/spice/cml_to_cmos.spice} 100 100 0 0 0.21 0.21 {}
T {Editable circuit view | W is total width in um | external models/bias; no layout extraction} 100 133 0 0 0.2 0.2 {}
C {devices/iopin} 90 230 0 1 {name=p1 lab=in}
C {devices/iopin} 90 285 0 1 {name=p2 lab=out}
C {devices/iopin} 90 340 0 1 {name=p3 lab=vdd}
C {devices/iopin} 90 395 0 1 {name=p4 lab=vss}
C {serdes/serdes_nfet} 500 350 0 0 {name=Xn w="\{wn\}" nf="\{nfn\}"}
N 520 320 520 285 {lab=out}
C {devices/lab_pin} 520 285 0 0 {name=l1 lab=out}
N 480 350 435 350 {lab=in}
C {devices/lab_pin} 435 350 0 0 {name=l2 lab=in}
N 520 380 520 415 {lab=vss}
C {devices/lab_pin} 520 415 0 0 {name=l3 lab=vss}
N 520 350 585 350 {lab=vss}
C {devices/lab_pin} 585 350 0 1 {name=l4 lab=vss}
C {serdes/serdes_pfet} 1180 350 2 1 {name=Xp w="\{wp\}" nf="\{nfp\}"}
N 1200 380 1200 415 {lab=out}
C {devices/lab_pin} 1200 415 0 0 {name=l5 lab=out}
N 1160 350 1115 350 {lab=in}
C {devices/lab_pin} 1115 350 0 0 {name=l6 lab=in}
N 1200 320 1200 285 {lab=vdd}
C {devices/lab_pin} 1200 285 0 0 {name=l7 lab=vdd}
N 1200 350 1265 350 {lab=vdd}
C {devices/lab_pin} 1265 350 0 1 {name=l8 lab=vdd}
T {DEFAULT PARAMETERS: wn=1  wp=3  nfn=1  nfp=1} 100 815 0 0 0.24 0.24 {}
