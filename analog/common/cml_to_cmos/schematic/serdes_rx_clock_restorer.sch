G {}
V {}
S {}
E {}
T {SERDES RX CLOCK RESTORER} 100 45 0 0 0.48 0.48 {}
T {Source: analog/common/cml_to_cmos/spice/cml_to_cmos.spice} 100 100 0 0 0.21 0.21 {}
T {Editable circuit view | W is total width in um | external models/bias; no layout extraction} 100 133 0 0 0.2 0.2 {}
C {devices/iopin} 90 230 0 1 {name=p1 lab=rawp}
C {devices/iopin} 90 285 0 1 {name=p2 lab=rawn}
C {devices/iopin} 90 340 0 1 {name=p3 lab=outp}
C {devices/iopin} 90 395 0 1 {name=p4 lab=outn}
C {devices/iopin} 90 450 0 1 {name=p5 lab=vdd}
C {devices/iopin} 90 505 0 1 {name=p6 lab=vss}
C {serdes/serdes_rx_inverter} 500 350 0 0 {name=Xdp1 wn=0.5 wp=1.5}
N 300 350 255 350 {lab=rawp}
C {devices/lab_pin} 255 350 0 0 {name=l1 lab=rawp}
N 700 350 745 350 {lab=dp1}
C {devices/lab_pin} 745 350 0 1 {name=l2 lab=dp1}
N 450 210 450 175 {lab=vdd}
C {devices/lab_pin} 450 175 0 0 {name=l3 lab=vdd}
N 500 490 500 525 {lab=vss}
C {devices/lab_pin} 500 525 0 0 {name=l4 lab=vss}
C {serdes/serdes_rx_inverter} 1180 350 0 0 {name=Xdp2 wn=0.5 wp=1.5}
N 980 350 935 350 {lab=dp1}
C {devices/lab_pin} 935 350 0 0 {name=l5 lab=dp1}
N 1380 350 1425 350 {lab=dp2}
C {devices/lab_pin} 1425 350 0 1 {name=l6 lab=dp2}
N 1130 210 1130 175 {lab=vdd}
C {devices/lab_pin} 1130 175 0 0 {name=l7 lab=vdd}
N 1180 490 1180 525 {lab=vss}
C {devices/lab_pin} 1180 525 0 0 {name=l8 lab=vss}
C {serdes/serdes_rx_inverter} 1860 350 0 0 {name=Xdp3 wn=0.5 wp=1.5}
N 1660 350 1615 350 {lab=dp2}
C {devices/lab_pin} 1615 350 0 0 {name=l9 lab=dp2}
N 2060 350 2105 350 {lab=dp3}
C {devices/lab_pin} 2105 350 0 1 {name=l10 lab=dp3}
N 1810 210 1810 175 {lab=vdd}
C {devices/lab_pin} 1810 175 0 0 {name=l11 lab=vdd}
N 1860 490 1860 525 {lab=vss}
C {devices/lab_pin} 1860 525 0 0 {name=l12 lab=vss}
C {serdes/serdes_rx_inverter} 500 780 0 0 {name=Xdn1 wn=0.5 wp=1.5}
N 300 780 255 780 {lab=rawn}
C {devices/lab_pin} 255 780 0 0 {name=l13 lab=rawn}
N 700 780 745 780 {lab=dn1}
C {devices/lab_pin} 745 780 0 1 {name=l14 lab=dn1}
N 450 640 450 605 {lab=vdd}
C {devices/lab_pin} 450 605 0 0 {name=l15 lab=vdd}
N 500 920 500 955 {lab=vss}
C {devices/lab_pin} 500 955 0 0 {name=l16 lab=vss}
C {serdes/serdes_rx_inverter} 1180 780 0 0 {name=Xdn2 wn=0.5 wp=1.5}
N 980 780 935 780 {lab=dn1}
C {devices/lab_pin} 935 780 0 0 {name=l17 lab=dn1}
N 1380 780 1425 780 {lab=dn2}
C {devices/lab_pin} 1425 780 0 1 {name=l18 lab=dn2}
N 1130 640 1130 605 {lab=vdd}
C {devices/lab_pin} 1130 605 0 0 {name=l19 lab=vdd}
N 1180 920 1180 955 {lab=vss}
C {devices/lab_pin} 1180 955 0 0 {name=l20 lab=vss}
C {serdes/serdes_rx_inverter} 1860 780 0 0 {name=Xdn3 wn=0.5 wp=1.5}
N 1660 780 1615 780 {lab=dn2}
C {devices/lab_pin} 1615 780 0 0 {name=l21 lab=dn2}
N 2060 780 2105 780 {lab=dn3}
C {devices/lab_pin} 2105 780 0 1 {name=l22 lab=dn3}
N 1810 640 1810 605 {lab=vdd}
C {devices/lab_pin} 1810 605 0 0 {name=l23 lab=vdd}
N 1860 920 1860 955 {lab=vss}
C {devices/lab_pin} 1860 955 0 0 {name=l24 lab=vss}
C {serdes/serdes_rx_nand2} 500 1210 0 0 {name=Xset}
N 300 1190 255 1190 {lab=rawp}
C {devices/lab_pin} 255 1190 0 0 {name=l25 lab=rawp}
N 300 1230 255 1230 {lab=dp3}
C {devices/lab_pin} 255 1230 0 0 {name=l26 lab=dp3}
N 700 1210 745 1210 {lab=set_b}
C {devices/lab_pin} 745 1210 0 1 {name=l27 lab=set_b}
N 450 1070 450 1035 {lab=vdd}
C {devices/lab_pin} 450 1035 0 0 {name=l28 lab=vdd}
N 500 1350 500 1385 {lab=vss}
C {devices/lab_pin} 500 1385 0 0 {name=l29 lab=vss}
C {serdes/serdes_rx_nand2} 1180 1210 0 0 {name=Xreset}
N 980 1190 935 1190 {lab=rawn}
C {devices/lab_pin} 935 1190 0 0 {name=l30 lab=rawn}
N 980 1230 935 1230 {lab=dn3}
C {devices/lab_pin} 935 1230 0 0 {name=l31 lab=dn3}
N 1380 1210 1425 1210 {lab=reset_b}
C {devices/lab_pin} 1425 1210 0 1 {name=l32 lab=reset_b}
N 1130 1070 1130 1035 {lab=vdd}
C {devices/lab_pin} 1130 1035 0 0 {name=l33 lab=vdd}
N 1180 1350 1180 1385 {lab=vss}
C {devices/lab_pin} 1180 1385 0 0 {name=l34 lab=vss}
C {serdes/serdes_rx_nand2} 1860 1210 0 0 {name=Xqp wn=4 wp=6}
N 1660 1190 1615 1190 {lab=set_b}
C {devices/lab_pin} 1615 1190 0 0 {name=l35 lab=set_b}
N 1660 1230 1615 1230 {lab=qn}
C {devices/lab_pin} 1615 1230 0 0 {name=l36 lab=qn}
N 2060 1210 2105 1210 {lab=qp}
C {devices/lab_pin} 2105 1210 0 1 {name=l37 lab=qp}
N 1810 1070 1810 1035 {lab=vdd}
C {devices/lab_pin} 1810 1035 0 0 {name=l38 lab=vdd}
N 1860 1350 1860 1385 {lab=vss}
C {devices/lab_pin} 1860 1385 0 0 {name=l39 lab=vss}
C {serdes/serdes_rx_nand2} 500 1640 0 0 {name=Xqn wn=4 wp=6}
N 300 1620 255 1620 {lab=reset_b}
C {devices/lab_pin} 255 1620 0 0 {name=l40 lab=reset_b}
N 300 1660 255 1660 {lab=qp}
C {devices/lab_pin} 255 1660 0 0 {name=l41 lab=qp}
N 700 1640 745 1640 {lab=qn}
C {devices/lab_pin} 745 1640 0 1 {name=l42 lab=qn}
N 450 1500 450 1465 {lab=vdd}
C {devices/lab_pin} 450 1465 0 0 {name=l43 lab=vdd}
N 500 1780 500 1815 {lab=vss}
C {devices/lab_pin} 500 1815 0 0 {name=l44 lab=vss}
C {serdes/serdes_rx_inverter} 1180 1640 0 0 {name=Xrp1 wn=2 wp=6}
N 980 1640 935 1640 {lab=qp}
C {devices/lab_pin} 935 1640 0 0 {name=l45 lab=qp}
N 1380 1640 1425 1640 {lab=rp1}
C {devices/lab_pin} 1425 1640 0 1 {name=l46 lab=rp1}
N 1130 1500 1130 1465 {lab=vdd}
C {devices/lab_pin} 1130 1465 0 0 {name=l47 lab=vdd}
N 1180 1780 1180 1815 {lab=vss}
C {devices/lab_pin} 1180 1815 0 0 {name=l48 lab=vss}
C {serdes/serdes_rx_inverter} 1860 1640 0 0 {name=Xrp2 wn=1 wp=3}
N 1660 1640 1615 1640 {lab=rp1}
C {devices/lab_pin} 1615 1640 0 0 {name=l49 lab=rp1}
N 2060 1640 2105 1640 {lab=rp2}
C {devices/lab_pin} 2105 1640 0 1 {name=l50 lab=rp2}
N 1810 1500 1810 1465 {lab=vdd}
C {devices/lab_pin} 1810 1465 0 0 {name=l51 lab=vdd}
N 1860 1780 1860 1815 {lab=vss}
C {devices/lab_pin} 1860 1815 0 0 {name=l52 lab=vss}
C {serdes/serdes_rx_inverter} 500 2070 0 0 {name=Xrn1 wn=2 wp=6}
N 300 2070 255 2070 {lab=qn}
C {devices/lab_pin} 255 2070 0 0 {name=l53 lab=qn}
N 700 2070 745 2070 {lab=rn1}
C {devices/lab_pin} 745 2070 0 1 {name=l54 lab=rn1}
N 450 1930 450 1895 {lab=vdd}
C {devices/lab_pin} 450 1895 0 0 {name=l55 lab=vdd}
N 500 2210 500 2245 {lab=vss}
C {devices/lab_pin} 500 2245 0 0 {name=l56 lab=vss}
C {serdes/serdes_rx_inverter} 1180 2070 0 0 {name=Xrn2 wn=1 wp=3}
N 980 2070 935 2070 {lab=rn1}
C {devices/lab_pin} 935 2070 0 0 {name=l57 lab=rn1}
N 1380 2070 1425 2070 {lab=rn2}
C {devices/lab_pin} 1425 2070 0 1 {name=l58 lab=rn2}
N 1130 1930 1130 1895 {lab=vdd}
C {devices/lab_pin} 1130 1895 0 0 {name=l59 lab=vdd}
N 1180 2210 1180 2245 {lab=vss}
C {devices/lab_pin} 1180 2245 0 0 {name=l60 lab=vss}
C {serdes/serdes_rx_nand2} 1860 2070 0 0 {name=Xbp}
N 1660 2050 1615 2050 {lab=qp}
C {devices/lab_pin} 1615 2050 0 0 {name=l61 lab=qp}
N 1660 2090 1615 2090 {lab=rp2}
C {devices/lab_pin} 1615 2090 0 0 {name=l62 lab=rp2}
N 2060 2070 2105 2070 {lab=bp}
C {devices/lab_pin} 2105 2070 0 1 {name=l63 lab=bp}
N 1810 1930 1810 1895 {lab=vdd}
C {devices/lab_pin} 1810 1895 0 0 {name=l64 lab=vdd}
N 1860 2210 1860 2245 {lab=vss}
C {devices/lab_pin} 1860 2245 0 0 {name=l65 lab=vss}
C {serdes/serdes_rx_nand2} 500 2500 0 0 {name=Xbn}
N 300 2480 255 2480 {lab=qn}
C {devices/lab_pin} 255 2480 0 0 {name=l66 lab=qn}
N 300 2520 255 2520 {lab=rn2}
C {devices/lab_pin} 255 2520 0 0 {name=l67 lab=rn2}
N 700 2500 745 2500 {lab=bn}
C {devices/lab_pin} 745 2500 0 1 {name=l68 lab=bn}
N 450 2360 450 2325 {lab=vdd}
C {devices/lab_pin} 450 2325 0 0 {name=l69 lab=vdd}
N 500 2640 500 2675 {lab=vss}
C {devices/lab_pin} 500 2675 0 0 {name=l70 lab=vss}
C {serdes/serdes_rx_inverter} 1180 2500 0 0 {name=Xop wn="\{out_wn\}" wp="\{out_wp\}" nfp=4}
N 980 2500 935 2500 {lab=bp}
C {devices/lab_pin} 935 2500 0 0 {name=l71 lab=bp}
N 1380 2500 1425 2500 {lab=outp}
C {devices/lab_pin} 1425 2500 0 1 {name=l72 lab=outp}
N 1130 2360 1130 2325 {lab=vdd}
C {devices/lab_pin} 1130 2325 0 0 {name=l73 lab=vdd}
N 1180 2640 1180 2675 {lab=vss}
C {devices/lab_pin} 1180 2675 0 0 {name=l74 lab=vss}
C {serdes/serdes_rx_inverter} 1860 2500 0 0 {name=Xon wn="\{out_wn\}" wp="\{out_wp\}" nfp=4}
N 1660 2500 1615 2500 {lab=bn}
C {devices/lab_pin} 1615 2500 0 0 {name=l75 lab=bn}
N 2060 2500 2105 2500 {lab=outn}
C {devices/lab_pin} 2105 2500 0 1 {name=l76 lab=outn}
N 1810 2360 1810 2325 {lab=vdd}
C {devices/lab_pin} 1810 2325 0 0 {name=l77 lab=vdd}
N 1860 2640 1860 2675 {lab=vss}
C {devices/lab_pin} 1860 2675 0 0 {name=l78 lab=vss}
T {Clock-only stateful receiver: edge pulses drive an SR latch. Not a static data receiver; no reset.} 350 3450 0 0 0.26 0.26 {}
T {DEFAULT PARAMETERS: out_wn=4  out_wp=8} 100 3850 0 0 0.24 0.24 {}
