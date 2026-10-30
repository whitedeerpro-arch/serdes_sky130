G {}
V {}
S {}
E {}
T {PLL CML PRESCALER8} 100 45 0 0 0.48 0.48 {}
T {Source: analog/pll/divider/spice/cml_prescaler8.spice} 100 100 0 0 0.21 0.21 {}
T {Editable circuit view | W is total width in um | external models/bias; no layout extraction} 100 133 0 0 0.2 0.2 {}
C {devices/iopin} 90 230 0 1 {name=p1 lab=clkp}
C {devices/iopin} 90 285 0 1 {name=p2 lab=clkn}
C {devices/iopin} 90 340 0 1 {name=p3 lab=q2p}
C {devices/iopin} 90 395 0 1 {name=p4 lab=q2n}
C {devices/iopin} 90 450 0 1 {name=p5 lab=q4p}
C {devices/iopin} 90 505 0 1 {name=p6 lab=q4n}
C {devices/iopin} 90 560 0 1 {name=p7 lab=q8p}
C {devices/iopin} 90 615 0 1 {name=p8 lab=q8n}
C {devices/iopin} 90 670 0 1 {name=p9 lab=vbias}
C {devices/iopin} 90 725 0 1 {name=p10 lab=vdd}
C {devices/iopin} 90 780 0 1 {name=p11 lab=vss}
C {serdes/pll_cml_div2} 500 530 0 0 {name=X2}
N 300 490 255 490 {lab=clkp}
C {devices/lab_pin} 255 490 0 0 {name=l1 lab=clkp}
N 300 530 255 530 {lab=clkn}
C {devices/lab_pin} 255 530 0 0 {name=l2 lab=clkn}
N 700 470 745 470 {lab=q2p}
C {devices/lab_pin} 745 470 0 1 {name=l3 lab=q2p}
N 700 510 745 510 {lab=q2n}
C {devices/lab_pin} 745 510 0 1 {name=l4 lab=q2n}
N 700 550 745 550 {lab=m2p}
C {devices/lab_pin} 745 550 0 1 {name=l5 lab=m2p}
N 700 590 745 590 {lab=m2n}
C {devices/lab_pin} 745 590 0 1 {name=l6 lab=m2n}
N 300 570 255 570 {lab=vbias}
C {devices/lab_pin} 255 570 0 0 {name=l7 lab=vbias}
N 450 385 450 350 {lab=vdd}
C {devices/lab_pin} 450 350 0 0 {name=l8 lab=vdd}
N 500 675 500 710 {lab=vss}
C {devices/lab_pin} 500 710 0 0 {name=l9 lab=vss}
C {serdes/pll_cml_div2} 1150 530 0 0 {name=X4}
N 950 490 905 490 {lab=q2p}
C {devices/lab_pin} 905 490 0 0 {name=l10 lab=q2p}
N 950 530 905 530 {lab=q2n}
C {devices/lab_pin} 905 530 0 0 {name=l11 lab=q2n}
N 1350 470 1395 470 {lab=q4p}
C {devices/lab_pin} 1395 470 0 1 {name=l12 lab=q4p}
N 1350 510 1395 510 {lab=q4n}
C {devices/lab_pin} 1395 510 0 1 {name=l13 lab=q4n}
N 1350 550 1395 550 {lab=m4p}
C {devices/lab_pin} 1395 550 0 1 {name=l14 lab=m4p}
N 1350 590 1395 590 {lab=m4n}
C {devices/lab_pin} 1395 590 0 1 {name=l15 lab=m4n}
N 950 570 905 570 {lab=vbias}
C {devices/lab_pin} 905 570 0 0 {name=l16 lab=vbias}
N 1100 385 1100 350 {lab=vdd}
C {devices/lab_pin} 1100 350 0 0 {name=l17 lab=vdd}
N 1150 675 1150 710 {lab=vss}
C {devices/lab_pin} 1150 710 0 0 {name=l18 lab=vss}
C {serdes/pll_cml_div2} 1800 530 0 0 {name=X8}
N 1600 490 1555 490 {lab=q4p}
C {devices/lab_pin} 1555 490 0 0 {name=l19 lab=q4p}
N 1600 530 1555 530 {lab=q4n}
C {devices/lab_pin} 1555 530 0 0 {name=l20 lab=q4n}
N 2000 470 2045 470 {lab=q8p}
C {devices/lab_pin} 2045 470 0 1 {name=l21 lab=q8p}
N 2000 510 2045 510 {lab=q8n}
C {devices/lab_pin} 2045 510 0 1 {name=l22 lab=q8n}
N 2000 550 2045 550 {lab=m8p}
C {devices/lab_pin} 2045 550 0 1 {name=l23 lab=m8p}
N 2000 590 2045 590 {lab=m8n}
C {devices/lab_pin} 2045 590 0 1 {name=l24 lab=m8n}
N 1600 570 1555 570 {lab=vbias}
C {devices/lab_pin} 1555 570 0 0 {name=l25 lab=vbias}
N 1750 385 1750 350 {lab=vdd}
C {devices/lab_pin} 1750 350 0 0 {name=l26 lab=vdd}
N 1800 675 1800 710 {lab=vss}
C {devices/lab_pin} 1800 710 0 0 {name=l27 lab=vss}
T {Fixed /2 -> /4 -> /8. Common mode is rebuilt at each CML stage.} 350 980 0 0 0.27 0.27 {}
