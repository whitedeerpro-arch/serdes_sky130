G {}
V {}
S {}
E {}
T {SERDES NFET LVT} 100 45 0 0 0.48 0.48 {}
T {Source: analog/common/devices/spice/sky130_primitives.spice} 100 100 0 0 0.21 0.21 {}
T {Editable circuit view | W is total width in um | external models/bias; no layout extraction} 100 133 0 0 0.2 0.2 {}
C {devices/iopin} 90 230 0 1 {name=p1 lab=d}
C {devices/iopin} 90 285 0 1 {name=p2 lab=g}
C {devices/iopin} 90 340 0 1 {name=p3 lab=s}
C {devices/iopin} 90 395 0 1 {name=p4 lab=b}
C {serdes/sky130_fd_pr__nfet_01v8_lvt} 500 350 0 0 {name=Xmos w="\{w\}" l="\{l\}" nf="\{nf\}" ad="\{floor((nf+1)/2)*(w/nf)*0.29\}" as="\{floor((nf+2)/2)*(w/nf)*0.29\}" pd="\{2*floor((nf+1)/2)*(w/nf+0.29)\}" ps="\{2*floor((nf+2)/2)*(w/nf+0.29)\}"}
N 520 320 520 285 {lab=d}
C {devices/lab_pin} 520 285 0 0 {name=l1 lab=d}
N 480 350 435 350 {lab=g}
C {devices/lab_pin} 435 350 0 0 {name=l2 lab=g}
N 520 380 520 415 {lab=s}
C {devices/lab_pin} 520 415 0 0 {name=l3 lab=s}
N 520 350 585 350 {lab=b}
C {devices/lab_pin} 585 350 0 1 {name=l4 lab=b}
T {DEFAULT PARAMETERS: w=1  l=0.15  nf=1} 100 815 0 0 0.24 0.24 {}
