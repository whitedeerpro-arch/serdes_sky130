G {}
V {}
S {}
E {}
T {PLL VCO CAP UNIT} 100 45 0 0 0.48 0.48 {}
T {Source: analog/pll/vco/spice/cap_bank_3b.spice} 100 100 0 0 0.21 0.21 {}
T {Editable circuit view | W is total width in um | external models/bias; no layout extraction} 100 133 0 0 0.2 0.2 {}
C {devices/iopin} 90 230 0 1 {name=p1 lab=node}
C {devices/iopin} 90 285 0 1 {name=p2 lab=en}
C {devices/iopin} 90 340 0 1 {name=p3 lab=vss}
C {serdes/sky130_fd_pr__cap_mim_m3_1} 650 350 0 0 {name=Xcap w="\{capw\}" l="\{capl\}"}
N 650 320 650 285 {lab=node}
C {devices/lab_pin} 650 285 0 0 {name=l1 lab=node}
N 650 380 650 415 {lab=plate}
C {devices/lab_pin} 650 415 0 0 {name=l2 lab=plate}
C {serdes/sky130_fd_pr__nfet_01v8} 650 650 0 0 {name=Xsw w="\{sw\}" l=0.15 ad="\{sw*0.29\}" as="\{sw*0.29\}" pd="\{2*(sw+0.29)\}" ps="\{2*(sw+0.29)\}"}
N 670 620 670 585 {lab=plate}
C {devices/lab_pin} 670 585 0 0 {name=l3 lab=plate}
N 630 650 585 650 {lab=en}
C {devices/lab_pin} 585 650 0 0 {name=l4 lab=en}
N 670 680 670 715 {lab=vss}
C {devices/lab_pin} 670 715 0 0 {name=l5 lab=vss}
N 670 650 735 650 {lab=vss}
C {devices/lab_pin} 735 650 0 1 {name=l6 lab=vss}
C {serdes/R} 1050 600 0 0 {name=Rdc value=1T}
N 1050 570 1050 535 {lab=plate}
C {devices/lab_pin} 1050 535 0 0 {name=l7 lab=plate}
N 1050 630 1050 665 {lab=vss}
C {devices/lab_pin} 1050 665 0 0 {name=l8 lab=vss}
N 650 380 670 620 {lab=plate}
T {MIM bottom plate switch retains off-state parasitics; Rdc = 1 Tohm DC reference.} 350 950 0 0 0.23 0.23 {}
T {DEFAULT PARAMETERS: capw=2  capl=2  sw=1} 100 1350 0 0 0.24 0.24 {}
