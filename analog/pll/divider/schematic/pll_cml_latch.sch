G {}
V {}
S {}
E {}
T {PLL CML LATCH} 100 45 0 0 0.48 0.48 {}
T {Source: analog/pll/divider/spice/cml_latch.spice} 100 100 0 0 0.21 0.21 {}
T {Editable circuit view | W is total width in um | external models/bias; no layout extraction} 100 133 0 0 0.2 0.2 {}
C {devices/iopin} 90 230 0 1 {name=p1 lab=dp}
C {devices/iopin} 90 285 0 1 {name=p2 lab=dn}
C {devices/iopin} 90 340 0 1 {name=p3 lab=qp}
C {devices/iopin} 90 395 0 1 {name=p4 lab=qn}
C {devices/iopin} 90 450 0 1 {name=p5 lab=clk_track}
C {devices/iopin} 90 505 0 1 {name=p6 lab=clk_hold}
C {devices/iopin} 90 560 0 1 {name=p7 lab=vbias}
C {devices/iopin} 90 615 0 1 {name=p8 lab=vdd}
C {devices/iopin} 90 670 0 1 {name=p9 lab=vss}
C {serdes/R} 500 350 0 0 {name=Rp value="\{rload\}"}
N 500 320 500 285 {lab=vdd}
C {devices/lab_pin} 500 285 0 0 {name=l1 lab=vdd}
N 500 380 500 415 {lab=qp}
C {devices/lab_pin} 500 415 0 0 {name=l2 lab=qp}
C {serdes/R} 1180 350 0 0 {name=Rn value="\{rload\}"}
N 1180 320 1180 285 {lab=vdd}
C {devices/lab_pin} 1180 285 0 0 {name=l3 lab=vdd}
N 1180 380 1180 415 {lab=qn}
C {devices/lab_pin} 1180 415 0 0 {name=l4 lab=qn}
C {serdes/serdes_nfet_lvt} 1860 350 0 0 {name=Xdp w="\{wdata\}" nf=4}
N 1880 320 1880 285 {lab=qn}
C {devices/lab_pin} 1880 285 0 0 {name=l5 lab=qn}
N 1840 350 1795 350 {lab=dp}
C {devices/lab_pin} 1795 350 0 0 {name=l6 lab=dp}
N 1880 380 1880 415 {lab=track}
C {devices/lab_pin} 1880 415 0 0 {name=l7 lab=track}
N 1880 350 1945 350 {lab=vss}
C {devices/lab_pin} 1945 350 0 1 {name=l8 lab=vss}
C {serdes/serdes_nfet_lvt} 500 780 0 0 {name=Xdn w="\{wdata\}" nf=4}
N 520 750 520 715 {lab=qp}
C {devices/lab_pin} 520 715 0 0 {name=l9 lab=qp}
N 480 780 435 780 {lab=dn}
C {devices/lab_pin} 435 780 0 0 {name=l10 lab=dn}
N 520 810 520 845 {lab=track}
C {devices/lab_pin} 520 845 0 0 {name=l11 lab=track}
N 520 780 585 780 {lab=vss}
C {devices/lab_pin} 585 780 0 1 {name=l12 lab=vss}
C {serdes/serdes_nfet_lvt} 1180 780 0 0 {name=Xhp w="\{whold\}" nf=4}
N 1200 750 1200 715 {lab=qn}
C {devices/lab_pin} 1200 715 0 0 {name=l13 lab=qn}
N 1160 780 1115 780 {lab=qp}
C {devices/lab_pin} 1115 780 0 0 {name=l14 lab=qp}
N 1200 810 1200 845 {lab=hold}
C {devices/lab_pin} 1200 845 0 0 {name=l15 lab=hold}
N 1200 780 1265 780 {lab=vss}
C {devices/lab_pin} 1265 780 0 1 {name=l16 lab=vss}
C {serdes/serdes_nfet_lvt} 1860 780 0 0 {name=Xhn w="\{whold\}" nf=4}
N 1880 750 1880 715 {lab=qp}
C {devices/lab_pin} 1880 715 0 0 {name=l17 lab=qp}
N 1840 780 1795 780 {lab=qn}
C {devices/lab_pin} 1795 780 0 0 {name=l18 lab=qn}
N 1880 810 1880 845 {lab=hold}
C {devices/lab_pin} 1880 845 0 0 {name=l19 lab=hold}
N 1880 780 1945 780 {lab=vss}
C {devices/lab_pin} 1945 780 0 1 {name=l20 lab=vss}
C {serdes/serdes_nfet_lvt} 500 1210 0 0 {name=Xct w="\{wclock\}" nf=4}
N 520 1180 520 1145 {lab=track}
C {devices/lab_pin} 520 1145 0 0 {name=l21 lab=track}
N 480 1210 435 1210 {lab=clk_track}
C {devices/lab_pin} 435 1210 0 0 {name=l22 lab=clk_track}
N 520 1240 520 1275 {lab=tail}
C {devices/lab_pin} 520 1275 0 0 {name=l23 lab=tail}
N 520 1210 585 1210 {lab=vss}
C {devices/lab_pin} 585 1210 0 1 {name=l24 lab=vss}
C {serdes/serdes_nfet_lvt} 1180 1210 0 0 {name=Xch w="\{wclock\}" nf=4}
N 1200 1180 1200 1145 {lab=hold}
C {devices/lab_pin} 1200 1145 0 0 {name=l25 lab=hold}
N 1160 1210 1115 1210 {lab=clk_hold}
C {devices/lab_pin} 1115 1210 0 0 {name=l26 lab=clk_hold}
N 1200 1240 1200 1275 {lab=tail}
C {devices/lab_pin} 1200 1275 0 0 {name=l27 lab=tail}
N 1200 1210 1265 1210 {lab=vss}
C {devices/lab_pin} 1265 1210 0 1 {name=l28 lab=vss}
C {serdes/serdes_nfet} 1860 1210 0 0 {name=Xtail w="\{wtail\}" l=0.5 nf=4}
N 1880 1180 1880 1145 {lab=tail}
C {devices/lab_pin} 1880 1145 0 0 {name=l29 lab=tail}
N 1840 1210 1795 1210 {lab=vbias}
C {devices/lab_pin} 1795 1210 0 0 {name=l30 lab=vbias}
N 1880 1240 1880 1275 {lab=vss}
C {devices/lab_pin} 1880 1275 0 0 {name=l31 lab=vss}
N 1880 1210 1945 1210 {lab=vss}
C {devices/lab_pin} 1945 1210 0 1 {name=l32 lab=vss}
T {DEFAULT PARAMETERS: wdata=20  whold=20  wclock=24  wtail=12  rload=600} 100 1675 0 0 0.24 0.24 {}
