G {}
V {}
S {}
E {}
T {PLL CML DIV2} 100 45 0 0 0.48 0.48 {}
T {Source: analog/pll/divider/spice/cml_div2.spice} 100 100 0 0 0.21 0.21 {}
T {Editable circuit view | W is total width in um | external models/bias; no layout extraction} 100 133 0 0 0.2 0.2 {}
C {devices/iopin} 90 230 0 1 {name=p1 lab=clkp}
C {devices/iopin} 90 285 0 1 {name=p2 lab=clkn}
C {devices/iopin} 90 340 0 1 {name=p3 lab=qp}
C {devices/iopin} 90 395 0 1 {name=p4 lab=qn}
C {devices/iopin} 90 450 0 1 {name=p5 lab=mp}
C {devices/iopin} 90 505 0 1 {name=p6 lab=mn}
C {devices/iopin} 90 560 0 1 {name=p7 lab=vbias}
C {devices/iopin} 90 615 0 1 {name=p8 lab=vdd}
C {devices/iopin} 90 670 0 1 {name=p9 lab=vss}
C {serdes/serdes_nfet_lvt} 500 350 0 0 {name=Xfp w="\{wsf\}" nf=4}
N 520 320 520 285 {lab=vdd}
C {devices/lab_pin} 520 285 0 0 {name=l1 lab=vdd}
N 480 350 435 350 {lab=clkp}
C {devices/lab_pin} 435 350 0 0 {name=l2 lab=clkp}
N 520 380 520 415 {lab=ckp}
C {devices/lab_pin} 520 415 0 0 {name=l3 lab=ckp}
N 520 350 585 350 {lab=vss}
C {devices/lab_pin} 585 350 0 1 {name=l4 lab=vss}
C {serdes/serdes_nfet_lvt} 1180 350 0 0 {name=Xfn w="\{wsf\}" nf=4}
N 1200 320 1200 285 {lab=vdd}
C {devices/lab_pin} 1200 285 0 0 {name=l5 lab=vdd}
N 1160 350 1115 350 {lab=clkn}
C {devices/lab_pin} 1115 350 0 0 {name=l6 lab=clkn}
N 1200 380 1200 415 {lab=ckn}
C {devices/lab_pin} 1200 415 0 0 {name=l7 lab=ckn}
N 1200 350 1265 350 {lab=vss}
C {devices/lab_pin} 1265 350 0 1 {name=l8 lab=vss}
C {serdes/serdes_nfet} 1860 350 0 0 {name=Xsp w="\{wsf_sink\}" l=0.5}
N 1880 320 1880 285 {lab=ckp}
C {devices/lab_pin} 1880 285 0 0 {name=l9 lab=ckp}
N 1840 350 1795 350 {lab=vbias}
C {devices/lab_pin} 1795 350 0 0 {name=l10 lab=vbias}
N 1880 380 1880 415 {lab=vss}
C {devices/lab_pin} 1880 415 0 0 {name=l11 lab=vss}
N 1880 350 1945 350 {lab=vss}
C {devices/lab_pin} 1945 350 0 1 {name=l12 lab=vss}
C {serdes/serdes_nfet} 500 780 0 0 {name=Xsn w="\{wsf_sink\}" l=0.5}
N 520 750 520 715 {lab=ckn}
C {devices/lab_pin} 520 715 0 0 {name=l13 lab=ckn}
N 480 780 435 780 {lab=vbias}
C {devices/lab_pin} 435 780 0 0 {name=l14 lab=vbias}
N 520 810 520 845 {lab=vss}
C {devices/lab_pin} 520 845 0 0 {name=l15 lab=vss}
N 520 780 585 780 {lab=vss}
C {devices/lab_pin} 585 780 0 1 {name=l16 lab=vss}
C {serdes/pll_cml_latch} 1180 780 0 0 {name=Xmaster wdata="\{wdata\}" whold="\{whold\}" wclock="\{wclock\}" wtail="\{wtail\}" rload="\{rload\}"}
N 980 720 935 720 {lab=qn}
C {devices/lab_pin} 935 720 0 0 {name=l17 lab=qn}
N 1380 740 1425 740 {lab=qp}
C {devices/lab_pin} 1425 740 0 1 {name=l18 lab=qp}
N 1380 780 1425 780 {lab=mp}
C {devices/lab_pin} 1425 780 0 1 {name=l19 lab=mp}
N 1380 820 1425 820 {lab=mn}
C {devices/lab_pin} 1425 820 0 1 {name=l20 lab=mn}
N 980 760 935 760 {lab=ckp}
C {devices/lab_pin} 935 760 0 0 {name=l21 lab=ckp}
N 980 800 935 800 {lab=ckn}
C {devices/lab_pin} 935 800 0 0 {name=l22 lab=ckn}
N 980 840 935 840 {lab=vbias}
C {devices/lab_pin} 935 840 0 0 {name=l23 lab=vbias}
N 1130 635 1130 600 {lab=vdd}
C {devices/lab_pin} 1130 600 0 0 {name=l24 lab=vdd}
N 1180 925 1180 960 {lab=vss}
C {devices/lab_pin} 1180 960 0 0 {name=l25 lab=vss}
C {serdes/pll_cml_latch} 1860 780 0 0 {name=Xslave wdata="\{wdata\}" whold="\{whold\}" wclock="\{wclock\}" wtail="\{wtail\}" rload="\{rload\}"}
N 1660 720 1615 720 {lab=mp}
C {devices/lab_pin} 1615 720 0 0 {name=l26 lab=mp}
N 2060 740 2105 740 {lab=mn}
C {devices/lab_pin} 2105 740 0 1 {name=l27 lab=mn}
N 2060 780 2105 780 {lab=qp}
C {devices/lab_pin} 2105 780 0 1 {name=l28 lab=qp}
N 2060 820 2105 820 {lab=qn}
C {devices/lab_pin} 2105 820 0 1 {name=l29 lab=qn}
N 1660 760 1615 760 {lab=ckn}
C {devices/lab_pin} 1615 760 0 0 {name=l30 lab=ckn}
N 1660 800 1615 800 {lab=ckp}
C {devices/lab_pin} 1615 800 0 0 {name=l31 lab=ckp}
N 1660 840 1615 840 {lab=vbias}
C {devices/lab_pin} 1615 840 0 0 {name=l32 lab=vbias}
N 1810 635 1810 600 {lab=vdd}
C {devices/lab_pin} 1810 600 0 0 {name=l33 lab=vdd}
N 1860 925 1860 960 {lab=vss}
C {devices/lab_pin} 1860 960 0 0 {name=l34 lab=vss}
T {DEFAULT PARAMETERS: wsf=40  wsf_sink=4  wdata=20  whold=80  wclock=64  wtail=12  rload=600} 100 1360 0 0 0.24 0.24 {}
