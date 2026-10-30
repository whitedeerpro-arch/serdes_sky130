G {}
V {}
S {}
E {}
T {SERDES CML DELAY} 100 45 0 0 0.48 0.48 {}
T {Source: analog/common/cml_buffer/spice/cml_delay_resistive.spice} 100 100 0 0 0.21 0.21 {}
T {Editable circuit view | W is total width in um | external models/bias; no layout extraction} 100 133 0 0 0.2 0.2 {}
C {devices/iopin} 90 230 0 1 {name=p1 lab=inp}
C {devices/iopin} 90 285 0 1 {name=p2 lab=inn}
C {devices/iopin} 90 340 0 1 {name=p3 lab=outp}
C {devices/iopin} 90 395 0 1 {name=p4 lab=outn}
C {devices/iopin} 90 450 0 1 {name=p5 lab=vbias}
C {devices/iopin} 90 505 0 1 {name=p6 lab=vdd}
C {devices/iopin} 90 560 0 1 {name=p7 lab=vss}
C {serdes/R} 620 300 0 0 {name=Rp value="\{rload\}"}
N 620 270 620 235 {lab=vdd}
C {devices/lab_pin} 620 235 0 0 {name=l1 lab=vdd}
N 620 330 620 365 {lab=outp}
C {devices/lab_pin} 620 365 0 0 {name=l2 lab=outp}
C {serdes/R} 1020 300 0 0 {name=Rn value="\{rload\}"}
N 1020 270 1020 235 {lab=vdd}
C {devices/lab_pin} 1020 235 0 0 {name=l3 lab=vdd}
N 1020 330 1020 365 {lab=outn}
C {devices/lab_pin} 1020 365 0 0 {name=l4 lab=outn}
C {serdes/sky130_fd_pr__nfet_01v8_lvt} 600 500 0 0 {name=Xmp w="\{wn\}" l="\{lin\}" nf="\{nfin\}" ad="\{floor((nfin+1)/2)*(wn/nfin)*0.29\}" as="\{floor((nfin+2)/2)*(wn/nfin)*0.29\}" pd="\{2*floor((nfin+1)/2)*(wn/nfin+0.29)\}" ps="\{2*floor((nfin+2)/2)*(wn/nfin+0.29)\}"}
N 620 470 620 435 {lab=outp}
C {devices/lab_pin} 620 435 0 0 {name=l5 lab=outp}
N 580 500 535 500 {lab=inp}
C {devices/lab_pin} 535 500 0 0 {name=l6 lab=inp}
N 620 530 620 565 {lab=tail}
C {devices/lab_pin} 620 565 0 0 {name=l7 lab=tail}
N 620 500 685 500 {lab=vss}
C {devices/lab_pin} 685 500 0 1 {name=l8 lab=vss}
C {serdes/sky130_fd_pr__nfet_01v8_lvt} 1000 500 0 0 {name=Xmn w="\{wn\}" l="\{lin\}" nf="\{nfin\}" ad="\{floor((nfin+1)/2)*(wn/nfin)*0.29\}" as="\{floor((nfin+2)/2)*(wn/nfin)*0.29\}" pd="\{2*floor((nfin+1)/2)*(wn/nfin+0.29)\}" ps="\{2*floor((nfin+2)/2)*(wn/nfin+0.29)\}"}
N 1020 470 1020 435 {lab=outn}
C {devices/lab_pin} 1020 435 0 0 {name=l9 lab=outn}
N 980 500 935 500 {lab=inn}
C {devices/lab_pin} 935 500 0 0 {name=l10 lab=inn}
N 1020 530 1020 565 {lab=tail}
C {devices/lab_pin} 1020 565 0 0 {name=l11 lab=tail}
N 1020 500 1085 500 {lab=vss}
C {devices/lab_pin} 1085 500 0 1 {name=l12 lab=vss}
C {serdes/sky130_fd_pr__nfet_01v8} 800 820 0 0 {name=Xtail w="\{wt\}" l="\{lt\}" nf="\{nftail\}" ad="\{floor((nftail+1)/2)*(wt/nftail)*0.29\}" as="\{floor((nftail+2)/2)*(wt/nftail)*0.29\}" pd="\{2*floor((nftail+1)/2)*(wt/nftail+0.29)\}" ps="\{2*floor((nftail+2)/2)*(wt/nftail+0.29)\}"}
N 820 790 820 755 {lab=tail}
C {devices/lab_pin} 820 755 0 0 {name=l13 lab=tail}
N 780 820 735 820 {lab=vbias}
C {devices/lab_pin} 735 820 0 0 {name=l14 lab=vbias}
N 820 850 820 885 {lab=vss}
C {devices/lab_pin} 820 885 0 0 {name=l15 lab=vss}
N 820 820 885 820 {lab=vss}
C {devices/lab_pin} 885 820 0 1 {name=l16 lab=vss}
N 620 330 620 470 {lab=outp}
N 1020 330 1020 470 {lab=outn}
N 620 530 620 680 {lab=tail}
N 620 680 1020 680 {lab=tail}
N 1020 530 1020 680 {lab=tail}
N 820 680 820 790 {lab=tail}
T {Resistive CML delay cell: differential LVT pair + standard-Vt tail} 400 1020 0 0 0.3 0.3 {}
T {DEFAULT PARAMETERS: wn=40  lin=0.15  nfin=8  wt=20  lt=0.5  nftail=4  rload=400} 100 1420 0 0 0.24 0.24 {}
