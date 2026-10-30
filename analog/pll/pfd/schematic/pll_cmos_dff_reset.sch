G {}
V {}
S {}
E {}
T {PLL CMOS DFF RESET} 100 45 0 0 0.48 0.48 {}
T {Source: analog/pll/pfd/spice/cmos_dff_reset.spice} 100 100 0 0 0.21 0.21 {}
T {Editable circuit view | W is total width in um | external models/bias; no layout extraction} 100 133 0 0 0.2 0.2 {}
C {devices/iopin} 90 230 0 1 {name=p1 lab=d}
C {devices/iopin} 90 285 0 1 {name=p2 lab=clk}
C {devices/iopin} 90 340 0 1 {name=p3 lab=rst_b}
C {devices/iopin} 90 395 0 1 {name=p4 lab=q}
C {devices/iopin} 90 450 0 1 {name=p5 lab=vdd}
C {devices/iopin} 90 505 0 1 {name=p6 lab=vss}
C {serdes/serdes_cmos_dff_reset} 500 350 0 0 {name=Xcore}
N 300 310 255 310 {lab=d}
C {devices/lab_pin} 255 310 0 0 {name=l1 lab=d}
N 300 350 255 350 {lab=clk}
C {devices/lab_pin} 255 350 0 0 {name=l2 lab=clk}
N 300 390 255 390 {lab=rst_b}
C {devices/lab_pin} 255 390 0 0 {name=l3 lab=rst_b}
N 700 350 745 350 {lab=q}
C {devices/lab_pin} 745 350 0 1 {name=l4 lab=q}
N 450 205 450 170 {lab=vdd}
C {devices/lab_pin} 450 170 0 0 {name=l5 lab=vdd}
N 500 495 500 530 {lab=vss}
C {devices/lab_pin} 500 530 0 0 {name=l6 lab=vss}
