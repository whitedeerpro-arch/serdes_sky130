G {}
V {}
S {}
E {}
T {PLL LOOP FILTER | ideal passive prototype} 120 50 0 0 0.5 0.5 {}
T {Source: analog/pll/loop_filter/spice/passive_rc.spice
External test precharge is omitted from this DUT sheet.} 120 110 0 0 0.24 0.24 {}
N 160 240 270 240 {lab=cp_in}
N 330 240 750 240 {lab=vctrl}
N 430 240 430 380 {lab=vctrl}
N 610 240 610 300 {lab=vctrl}
N 610 360 610 450 {lab=z}
N 430 440 430 580 {lab=vss}
N 610 510 610 580 {lab=vss}
N 160 580 610 580 {lab=vss}
C {devices/iopin} 160 240 0 1 {name=p1 lab=cp_in}
C {devices/iopin} 750 240 0 0 {name=p2 lab=vctrl}
C {devices/iopin} 160 580 0 1 {name=p3 lab=vss}
C {devices/vsource} 300 240 3 0 {name=Vlink value=0}
C {devices/capa} 430 410 0 0 {name=Cf value=\{cfast\} m=1}
C {devices/res} 610 330 0 0 {name=Rz value=\{rz\} m=1}
C {devices/capa} 610 480 0 0 {name=Ci value=\{cint\} m=1}
C {devices/lab_pin} 610 400 0 1 {name=l1 lab=z}
T {DEFAULT PARAMETERS: rz=6.5k  cint=40p  cfast=2p} 100 980 0 0 0.24 0.24 {}
