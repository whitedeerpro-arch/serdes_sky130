G {}
V {}
S {}
E {}
T {SERDES CML BUFFER} 100 45 0 0 0.48 0.48 {}
T {Source: analog/common/cml_buffer/spice/cml_buffer.spice} 100 100 0 0 0.21 0.21 {}
T {Editable circuit view | W is total width in um | external models/bias; no layout extraction} 100 133 0 0 0.2 0.2 {}
C {devices/iopin} 90 230 0 1 {name=p1 lab=inp}
C {devices/iopin} 90 285 0 1 {name=p2 lab=inn}
C {devices/iopin} 90 340 0 1 {name=p3 lab=outp}
C {devices/iopin} 90 395 0 1 {name=p4 lab=outn}
C {devices/iopin} 90 450 0 1 {name=p5 lab=vbias}
C {devices/iopin} 90 505 0 1 {name=p6 lab=vdd}
C {devices/iopin} 90 560 0 1 {name=p7 lab=vss}
C {serdes/serdes_cml_delay} 500 350 0 0 {name=Xgain wn="\{wn\}" nfin="\{nfin\}" wt="\{wt\}" lt=0.5 rload="\{rload\}"}
N 300 325 255 325 {lab=inp}
C {devices/lab_pin} 255 325 0 0 {name=l1 lab=inp}
N 300 375 255 375 {lab=inn}
C {devices/lab_pin} 255 375 0 0 {name=l2 lab=inn}
N 700 325 745 325 {lab=outn}
C {devices/lab_pin} 745 325 0 1 {name=l3 lab=outn}
N 700 375 745 375 {lab=outp}
C {devices/lab_pin} 745 375 0 1 {name=l4 lab=outp}
N 300 425 255 425 {lab=vbias}
C {devices/lab_pin} 255 425 0 0 {name=l5 lab=vbias}
N 450 210 450 175 {lab=vdd}
C {devices/lab_pin} 450 175 0 0 {name=l6 lab=vdd}
N 500 490 500 525 {lab=vss}
C {devices/lab_pin} 500 525 0 0 {name=l7 lab=vss}
T {Output labels intentionally exchanged: this CML buffer is noninverting.} 350 850 0 0 0.25 0.25 {}
T {DEFAULT PARAMETERS: wn=12  nfin=4  wt=12  rload=600} 100 1250 0 0 0.24 0.24 {}
