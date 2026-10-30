G {}
V {}
S {}
E {}
T {SERDES CML TO CMOS} 100 45 0 0 0.48 0.48 {}
T {Source: analog/common/cml_to_cmos/spice/cml_to_cmos.spice} 100 100 0 0 0.21 0.21 {}
T {Editable circuit view | W is total width in um | external models/bias; no layout extraction} 100 133 0 0 0.2 0.2 {}
C {devices/iopin} 90 230 0 1 {name=p1 lab=inp}
C {devices/iopin} 90 285 0 1 {name=p2 lab=inn}
C {devices/iopin} 90 340 0 1 {name=p3 lab=outp}
C {devices/iopin} 90 395 0 1 {name=p4 lab=outn}
C {devices/iopin} 90 450 0 1 {name=p5 lab=vbias}
C {devices/iopin} 90 505 0 1 {name=p6 lab=vdd}
C {devices/iopin} 90 560 0 1 {name=p7 lab=vss}
C {serdes/serdes_nfet_lvt} 500 350 0 0 {name=Xfp w="\{wsf\}"}
N 520 320 520 285 {lab=vdd}
C {devices/lab_pin} 520 285 0 0 {name=l1 lab=vdd}
N 480 350 435 350 {lab=inp}
C {devices/lab_pin} 435 350 0 0 {name=l2 lab=inp}
N 520 380 520 415 {lab=fp}
C {devices/lab_pin} 520 415 0 0 {name=l3 lab=fp}
N 520 350 585 350 {lab=vss}
C {devices/lab_pin} 585 350 0 1 {name=l4 lab=vss}
C {serdes/serdes_nfet_lvt} 1180 350 0 0 {name=Xfn w="\{wsf\}"}
N 1200 320 1200 285 {lab=vdd}
C {devices/lab_pin} 1200 285 0 0 {name=l5 lab=vdd}
N 1160 350 1115 350 {lab=inn}
C {devices/lab_pin} 1115 350 0 0 {name=l6 lab=inn}
N 1200 380 1200 415 {lab=fn}
C {devices/lab_pin} 1200 415 0 0 {name=l7 lab=fn}
N 1200 350 1265 350 {lab=vss}
C {devices/lab_pin} 1265 350 0 1 {name=l8 lab=vss}
C {serdes/serdes_nfet} 1860 350 0 0 {name=Xsp w="\{wsf_sink\}" l=0.5}
N 1880 320 1880 285 {lab=fp}
C {devices/lab_pin} 1880 285 0 0 {name=l9 lab=fp}
N 1840 350 1795 350 {lab=vbias}
C {devices/lab_pin} 1795 350 0 0 {name=l10 lab=vbias}
N 1880 380 1880 415 {lab=vss}
C {devices/lab_pin} 1880 415 0 0 {name=l11 lab=vss}
N 1880 350 1945 350 {lab=vss}
C {devices/lab_pin} 1945 350 0 1 {name=l12 lab=vss}
C {serdes/serdes_nfet} 500 780 0 0 {name=Xsn w="\{wsf_sink\}" l=0.5}
N 520 750 520 715 {lab=fn}
C {devices/lab_pin} 520 715 0 0 {name=l13 lab=fn}
N 480 780 435 780 {lab=vbias}
C {devices/lab_pin} 435 780 0 0 {name=l14 lab=vbias}
N 520 810 520 845 {lab=vss}
C {devices/lab_pin} 520 845 0 0 {name=l15 lab=vss}
N 520 780 585 780 {lab=vss}
C {devices/lab_pin} 585 780 0 1 {name=l16 lab=vss}
C {serdes/serdes_rx_diff_to_se} 1180 780 0 0 {name=Xap win="\{win\}" wload="\{wload\}" wtail="\{wtail\}"}
N 980 740 935 740 {lab=fp}
C {devices/lab_pin} 935 740 0 0 {name=l17 lab=fp}
N 980 780 935 780 {lab=fn}
C {devices/lab_pin} 935 780 0 0 {name=l18 lab=fn}
N 1380 780 1425 780 {lab=ap}
C {devices/lab_pin} 1425 780 0 1 {name=l19 lab=ap}
N 980 820 935 820 {lab=vbias}
C {devices/lab_pin} 935 820 0 0 {name=l20 lab=vbias}
N 1130 635 1130 600 {lab=vdd}
C {devices/lab_pin} 1130 600 0 0 {name=l21 lab=vdd}
N 1180 925 1180 960 {lab=vss}
C {devices/lab_pin} 1180 960 0 0 {name=l22 lab=vss}
C {serdes/serdes_rx_diff_to_se} 1860 780 0 0 {name=Xan win="\{win\}" wload="\{wload\}" wtail="\{wtail\}"}
N 1660 740 1615 740 {lab=fn}
C {devices/lab_pin} 1615 740 0 0 {name=l23 lab=fn}
N 1660 780 1615 780 {lab=fp}
C {devices/lab_pin} 1615 780 0 0 {name=l24 lab=fp}
N 2060 780 2105 780 {lab=an}
C {devices/lab_pin} 2105 780 0 1 {name=l25 lab=an}
N 1660 820 1615 820 {lab=vbias}
C {devices/lab_pin} 1615 820 0 0 {name=l26 lab=vbias}
N 1810 635 1810 600 {lab=vdd}
C {devices/lab_pin} 1810 600 0 0 {name=l27 lab=vdd}
N 1860 925 1860 960 {lab=vss}
C {devices/lab_pin} 1860 960 0 0 {name=l28 lab=vss}
C {serdes/serdes_rx_inverter} 500 1210 0 0 {name=Xbp wn="\{pre_wn\}" wp="\{pre_wp\}"}
N 300 1210 255 1210 {lab=ap}
C {devices/lab_pin} 255 1210 0 0 {name=l29 lab=ap}
N 700 1210 745 1210 {lab=bp}
C {devices/lab_pin} 745 1210 0 1 {name=l30 lab=bp}
N 450 1070 450 1035 {lab=vdd}
C {devices/lab_pin} 450 1035 0 0 {name=l31 lab=vdd}
N 500 1350 500 1385 {lab=vss}
C {devices/lab_pin} 500 1385 0 0 {name=l32 lab=vss}
C {serdes/serdes_rx_inverter} 1180 1210 0 0 {name=Xbn wn="\{pre_wn\}" wp="\{pre_wp\}"}
N 980 1210 935 1210 {lab=an}
C {devices/lab_pin} 935 1210 0 0 {name=l33 lab=an}
N 1380 1210 1425 1210 {lab=bn}
C {devices/lab_pin} 1425 1210 0 1 {name=l34 lab=bn}
N 1130 1070 1130 1035 {lab=vdd}
C {devices/lab_pin} 1130 1035 0 0 {name=l35 lab=vdd}
N 1180 1350 1180 1385 {lab=vss}
C {devices/lab_pin} 1180 1385 0 0 {name=l36 lab=vss}
C {serdes/serdes_rx_inverter} 1860 1210 0 0 {name=Xop wn=4 wp=12 nfp=4}
N 1660 1210 1615 1210 {lab=bp}
C {devices/lab_pin} 1615 1210 0 0 {name=l37 lab=bp}
N 2060 1210 2105 1210 {lab=rawp}
C {devices/lab_pin} 2105 1210 0 1 {name=l38 lab=rawp}
N 1810 1070 1810 1035 {lab=vdd}
C {devices/lab_pin} 1810 1035 0 0 {name=l39 lab=vdd}
N 1860 1350 1860 1385 {lab=vss}
C {devices/lab_pin} 1860 1385 0 0 {name=l40 lab=vss}
C {serdes/serdes_rx_inverter} 500 1640 0 0 {name=Xon wn=4 wp=12 nfp=4}
N 300 1640 255 1640 {lab=bn}
C {devices/lab_pin} 255 1640 0 0 {name=l41 lab=bn}
N 700 1640 745 1640 {lab=rawn}
C {devices/lab_pin} 745 1640 0 1 {name=l42 lab=rawn}
N 450 1500 450 1465 {lab=vdd}
C {devices/lab_pin} 450 1465 0 0 {name=l43 lab=vdd}
N 500 1780 500 1815 {lab=vss}
C {devices/lab_pin} 500 1815 0 0 {name=l44 lab=vss}
C {serdes/serdes_rx_clock_restorer} 1180 1640 0 0 {name=Xrestore out_wn="\{out_wn\}" out_wp="\{out_wp\}"}
N 980 1620 935 1620 {lab=rawp}
C {devices/lab_pin} 935 1620 0 0 {name=l45 lab=rawp}
N 980 1660 935 1660 {lab=rawn}
C {devices/lab_pin} 935 1660 0 0 {name=l46 lab=rawn}
N 1380 1620 1425 1620 {lab=outp}
C {devices/lab_pin} 1425 1620 0 1 {name=l47 lab=outp}
N 1380 1660 1425 1660 {lab=outn}
C {devices/lab_pin} 1425 1660 0 1 {name=l48 lab=outn}
N 1130 1500 1130 1465 {lab=vdd}
C {devices/lab_pin} 1130 1465 0 0 {name=l49 lab=vdd}
N 1180 1780 1180 1815 {lab=vss}
C {devices/lab_pin} 1180 1815 0 0 {name=l50 lab=vss}
T {Source-follower input isolation / CM shift -> differential gain -> edge-driven CMOS clock restorer.} 350 2650 0 0 0.27 0.27 {}
T {DEFAULT PARAMETERS: wsf=20  wsf_sink=2  win=6  wload=8  wtail=6  pre_wn=1  pre_wp=3.6  out_wn=4  out_wp=8} 100 3050 0 0 0.24 0.24 {}
