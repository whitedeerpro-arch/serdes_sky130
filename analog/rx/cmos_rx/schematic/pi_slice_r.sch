G {}
V {}
S {}
E {}
C {devices/iopin} 145 278 0 1 {name=p1 lab=ca}
C {devices/iopin} 145 426 0 1 {name=p2 lab=cb}
C {devices/iopin} 765 102 0 0 {name=p3 lab=f}
C {devices/iopin} 852 102 0 0 {name=p4 lab=fb}
C {devices/iopin} 1088 352 0 0 {name=p5 lab=mix}
C {devices/iopin} 955 102 0 0 {name=p6 lab=vdd}
C {devices/iopin} 1079 102 0 0 {name=p7 lab=vss}
T {RX phase interpolator} 100 31 0 0 0.54 0.54 {}
T {One constant-load resistive mixer slice} 100 85 0 0 0.28 0.28 {}
T {Signal path} 100 182 0 0 0.33 0.33 {}
T {Dummy load path} 100 542 0 0 0.33 0.33 {}
T {Complementary selects send the unselected clock to matched MOS gate loads.} 100 579 0 0 0.2 0.2 {}
T {Slice defaults   Wn 0.42 um   Wp 1.70 um   Lpoly 11.0 um} 100 944 0 0 0.2 0.2 {}
T {Mixer instance   Lpoly 10.8 um   |   MOS widths are total; L = 0.15 um for gain and dummy devices.} 100 976 0 0 0.2 0.2 {}
N 145 278 282 278 {lab=ca}
N 358 278 500 278 {lab=sel}
N 320 225 320 248 {lab=fb}
N 320 308 320 331 {lab=f}
N 345 258 371 258 {lab=vdd}
N 345 298 371 298 {lab=vss}
N 145 426 282 426 {lab=cb}
N 358 426 500 426 {lab=sel}
N 320 373 320 396 {lab=f}
N 320 456 320 479 {lab=fb}
N 345 406 371 406 {lab=vdd}
N 345 446 371 446 {lab=vss}
N 500 278 500 352 {lab=sel}
N 500 352 500 426 {lab=sel}
N 500 352 611 352 {lab=sel}
N 611 286 611 352 {lab=sel}
N 611 286 680 286 {lab=sel}
N 611 352 611 418 {lab=sel}
N 611 418 680 418 {lab=sel}
N 720 237 720 256 {lab=vdd}
N 720 219 720 237 {lab=vdd}
N 734 286 749 286 {lab=vdd}
N 749 237 749 286 {lab=vdd}
N 720 237 749 237 {lab=vdd}
N 720 448 720 467 {lab=vss}
N 720 467 720 485 {lab=vss}
N 734 418 749 418 {lab=vss}
N 749 418 749 467 {lab=vss}
N 720 467 749 467 {lab=vss}
N 720 316 720 352 {lab=drv}
N 720 352 720 388 {lab=drv}
N 720 352 835 352 {lab=drv}
N 835 352 888 352 {lab=drv}
N 835 329 835 352 {lab=drv}
C {devices/lab_pin} 835 329 0 0 {name=l27_m lab=drv}
N 930 377 930 404 {lab=vss}
N 972 352 1088 352 {lab=mix}
N 145 690 282 690 {lab=ca}
N 358 690 500 690 {lab=dum}
N 320 637 320 660 {lab=f}
N 320 720 320 743 {lab=fb}
N 345 670 371 670 {lab=vdd}
N 345 710 371 710 {lab=vss}
N 145 838 282 838 {lab=cb}
N 358 838 500 838 {lab=dum}
N 320 785 320 808 {lab=fb}
N 320 868 320 891 {lab=f}
N 345 818 371 818 {lab=vdd}
N 345 858 371 858 {lab=vss}
N 500 690 500 764 {lab=dum}
N 500 764 500 838 {lab=dum}
N 500 764 611 764 {lab=dum}
N 611 695 611 764 {lab=dum}
N 611 695 680 695 {lab=dum}
N 611 764 611 833 {lab=dum}
N 611 833 680 833 {lab=dum}
N 720 648 720 665 {lab=vdd}
N 720 648 814 648 {lab=vdd}
N 814 648 814 695 {lab=vdd}
N 814 695 814 742 {lab=vdd}
N 720 742 814 742 {lab=vdd}
N 720 725 720 742 {lab=vdd}
N 734 695 814 695 {lab=vdd}
N 720 786 720 803 {lab=vss}
N 720 786 814 786 {lab=vss}
N 814 786 814 833 {lab=vss}
N 814 833 814 880 {lab=vss}
N 720 880 814 880 {lab=vss}
N 720 863 720 880 {lab=vss}
N 734 833 814 833 {lab=vss}
C {rx_cmos/pi_tgate_symbol} 320 278 0 0 {name=Xsa}
C {devices/lab_pin} 320 225 0 0 {name=l1 lab=fb}
C {devices/lab_pin} 320 331 0 0 {name=l2 lab=f}
C {devices/lab_pin} 371 258 0 1 {name=l3 lab=vdd}
C {devices/lab_pin} 371 298 0 1 {name=l4 lab=vss}
C {rx_cmos/pi_tgate_symbol} 320 426 0 0 {name=Xsb}
C {devices/lab_pin} 320 373 0 0 {name=l5 lab=f}
C {devices/lab_pin} 320 479 0 0 {name=l6 lab=fb}
C {devices/lab_pin} 371 406 0 1 {name=l7 lab=vdd}
C {devices/lab_pin} 371 446 0 1 {name=l8 lab=vss}
C {devices/lab_pin} 500 352 0 0 {name=l9 lab=sel}
C {rx_cmos/pi_pfet} 700 286 0 0 {name=Xinv_p w="\{wp\}" l=0.15 nf=1}
C {rx_cmos/pi_nfet_lvt} 700 418 0 0 {name=Xinv_n w="\{wn\}" l=0.15 nf=1}
C {devices/lab_pin} 720 219 0 0 {name=l10 lab=vdd}
C {devices/lab_pin} 720 485 0 0 {name=l11 lab=vss}
C {rx_cmos/pi_poly_res} 930 352 0 0 {name=Xres l="\{lres\}"}
C {devices/lab_pin} 930 404 0 1 {name=l12 lab=vss}
C {rx_cmos/pi_tgate_symbol} 320 690 0 0 {name=Xda}
C {devices/lab_pin} 145 690 0 0 {name=l13 lab=ca}
C {devices/lab_pin} 320 637 0 0 {name=l14 lab=f}
C {devices/lab_pin} 320 743 0 0 {name=l15 lab=fb}
C {devices/lab_pin} 371 670 0 1 {name=l16 lab=vdd}
C {devices/lab_pin} 371 710 0 1 {name=l17 lab=vss}
C {rx_cmos/pi_tgate_symbol} 320 838 0 0 {name=Xdb}
C {devices/lab_pin} 145 838 0 0 {name=l18 lab=cb}
C {devices/lab_pin} 320 785 0 0 {name=l19 lab=fb}
C {devices/lab_pin} 320 891 0 0 {name=l20 lab=f}
C {devices/lab_pin} 371 818 0 1 {name=l21 lab=vdd}
C {devices/lab_pin} 371 858 0 1 {name=l22 lab=vss}
C {devices/lab_pin} 500 764 0 0 {name=l23 lab=dum}
C {rx_cmos/pi_pfet} 700 695 0 0 {name=Xdp w="\{wp\}" l=0.15 nf=1}
C {rx_cmos/pi_nfet_lvt} 700 833 0 0 {name=Xdn w="\{wn\}" l=0.15 nf=1}
C {devices/lab_pin} 814 648 0 1 {name=l24 lab=vdd}
C {devices/lab_pin} 814 880 0 1 {name=l25 lab=vss}
