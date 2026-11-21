module tx_ingress_control (a_valid,
    b_valid,
    capture_valid,
    clock_good,
    enable,
    in_valid,
    rst_n,
    word_clk,
    word_ready,
    capture_data,
    in_data,
    VPWR,
    VGND);
 output a_valid;
 output b_valid;
 output capture_valid;
 input clock_good;
 input enable;
 input in_valid;
 input rst_n;
 input word_clk;
 output word_ready;
 output [15:0] capture_data;
 input [15:0] in_data;
 input VPWR;
 input VGND;

 wire _00_;
 wire net1;
 wire net2;
 wire clknet_0_word_clk;
 wire clknet_1_0__leaf_word_clk;
 wire clknet_1_1__leaf_word_clk;

 sky130_fd_sc_hd__and2_2 _01_ (.A(net2),
    .B(word_ready),
    .X(capture_valid));
 sky130_fd_sc_hd__and3_2 _02_ (.A(in_valid),
    .B(word_ready),
    .C(in_data[0]),
    .X(capture_data[0]));
 sky130_fd_sc_hd__and3_2 _03_ (.A(net2),
    .B(word_ready),
    .C(in_data[1]),
    .X(capture_data[1]));
 sky130_fd_sc_hd__and3_4 _04_ (.A(net2),
    .B(word_ready),
    .C(in_data[2]),
    .X(capture_data[2]));
 sky130_fd_sc_hd__and3_2 _05_ (.A(net2),
    .B(word_ready),
    .C(in_data[3]),
    .X(capture_data[3]));
 sky130_fd_sc_hd__and3_2 _06_ (.A(in_valid),
    .B(word_ready),
    .C(in_data[4]),
    .X(capture_data[4]));
 sky130_fd_sc_hd__and3_4 _07_ (.A(net2),
    .B(word_ready),
    .C(in_data[5]),
    .X(capture_data[5]));
 sky130_fd_sc_hd__and3_2 _08_ (.A(net2),
    .B(net1),
    .C(in_data[6]),
    .X(capture_data[6]));
 sky130_fd_sc_hd__and3_2 _09_ (.A(net2),
    .B(net1),
    .C(in_data[7]),
    .X(capture_data[7]));
 sky130_fd_sc_hd__and3_2 _10_ (.A(net2),
    .B(net1),
    .C(in_data[8]),
    .X(capture_data[8]));
 sky130_fd_sc_hd__and3_2 _11_ (.A(net2),
    .B(net1),
    .C(in_data[9]),
    .X(capture_data[9]));
 sky130_fd_sc_hd__and3_2 _12_ (.A(net2),
    .B(word_ready),
    .C(in_data[10]),
    .X(capture_data[10]));
 sky130_fd_sc_hd__and3_2 _13_ (.A(in_valid),
    .B(word_ready),
    .C(in_data[11]),
    .X(capture_data[11]));
 sky130_fd_sc_hd__and3_2 _14_ (.A(in_valid),
    .B(word_ready),
    .C(in_data[12]),
    .X(capture_data[12]));
 sky130_fd_sc_hd__and3_4 _15_ (.A(in_valid),
    .B(word_ready),
    .C(in_data[13]),
    .X(capture_data[13]));
 sky130_fd_sc_hd__and3_2 _16_ (.A(net2),
    .B(net1),
    .C(in_data[14]),
    .X(capture_data[14]));
 sky130_fd_sc_hd__and3_2 _17_ (.A(in_valid),
    .B(word_ready),
    .C(in_data[15]),
    .X(capture_data[15]));
 sky130_fd_sc_hd__and2_1 _18_ (.A(clock_good),
    .B(enable),
    .X(_00_));
 sky130_fd_sc_hd__dfrtp_2 _19_ (.CLK(clknet_1_0__leaf_word_clk),
    .D(capture_valid),
    .RESET_B(rst_n),
    .Q(a_valid));
 sky130_fd_sc_hd__dfrtn_1 _20_ (.CLK_N(clknet_1_0__leaf_word_clk),
    .D(_00_),
    .RESET_B(rst_n),
    .Q(net1));
 sky130_fd_sc_hd__dfrtn_1 _21_ (.CLK_N(clknet_1_1__leaf_word_clk),
    .D(a_valid),
    .RESET_B(rst_n),
    .Q(b_valid));
 sky130_fd_sc_hd__decap_3 PHY_0 ();
 sky130_fd_sc_hd__decap_3 PHY_1 ();
 sky130_fd_sc_hd__decap_3 PHY_2 ();
 sky130_fd_sc_hd__decap_3 PHY_3 ();
 sky130_fd_sc_hd__decap_3 PHY_4 ();
 sky130_fd_sc_hd__decap_3 PHY_5 ();
 sky130_fd_sc_hd__decap_3 PHY_6 ();
 sky130_fd_sc_hd__decap_3 PHY_7 ();
 sky130_fd_sc_hd__decap_3 PHY_8 ();
 sky130_fd_sc_hd__decap_3 PHY_9 ();
 sky130_fd_sc_hd__decap_3 PHY_10 ();
 sky130_fd_sc_hd__decap_3 PHY_11 ();
 sky130_fd_sc_hd__decap_3 PHY_12 ();
 sky130_fd_sc_hd__decap_3 PHY_13 ();
 sky130_fd_sc_hd__decap_3 PHY_14 ();
 sky130_fd_sc_hd__decap_3 PHY_15 ();
 sky130_fd_sc_hd__tapvpwrvgnd_1 TAP_16 ();
 sky130_fd_sc_hd__tapvpwrvgnd_1 TAP_17 ();
 sky130_fd_sc_hd__tapvpwrvgnd_1 TAP_18 ();
 sky130_fd_sc_hd__tapvpwrvgnd_1 TAP_19 ();
 sky130_fd_sc_hd__tapvpwrvgnd_1 TAP_20 ();
 sky130_fd_sc_hd__tapvpwrvgnd_1 TAP_21 ();
 sky130_fd_sc_hd__tapvpwrvgnd_1 TAP_22 ();
 sky130_fd_sc_hd__tapvpwrvgnd_1 TAP_23 ();
 sky130_fd_sc_hd__tapvpwrvgnd_1 TAP_24 ();
 sky130_fd_sc_hd__tapvpwrvgnd_1 TAP_25 ();
 sky130_fd_sc_hd__buf_6 repeater1 (.A(net1),
    .X(word_ready));
 sky130_fd_sc_hd__buf_2 repeater2 (.A(in_valid),
    .X(net2));
 sky130_fd_sc_hd__clkbuf_16 clkbuf_0_word_clk (.A(word_clk),
    .X(clknet_0_word_clk));
 sky130_fd_sc_hd__clkbuf_16 clkbuf_1_0__f_word_clk (.A(clknet_0_word_clk),
    .X(clknet_1_0__leaf_word_clk));
 sky130_fd_sc_hd__clkbuf_16 clkbuf_1_1__f_word_clk (.A(clknet_0_word_clk),
    .X(clknet_1_1__leaf_word_clk));
 sky130_fd_sc_hd__decap_6 FILLER_0_31 ();
 sky130_fd_sc_hd__decap_4 FILLER_0_26 ();
 sky130_fd_sc_hd__fill_2 FILLER_0_15 ();
 sky130_fd_sc_hd__decap_12 FILLER_0_3 ();
 sky130_fd_sc_hd__decap_12 FILLER_0_41 ();
 sky130_fd_sc_hd__decap_6 FILLER_0_53 ();
 sky130_fd_sc_hd__fill_1 FILLER_0_59 ();
 sky130_fd_sc_hd__decap_6 FILLER_0_61 ();
 sky130_fd_sc_hd__decap_4 FILLER_0_73 ();
 sky130_fd_sc_hd__decap_8 FILLER_1_3 ();
 sky130_fd_sc_hd__fill_1 FILLER_1_17 ();
 sky130_fd_sc_hd__decap_3 FILLER_1_39 ();
 sky130_fd_sc_hd__decap_6 FILLER_1_54 ();
 sky130_fd_sc_hd__fill_1 FILLER_1_76 ();
 sky130_fd_sc_hd__decap_12 FILLER_2_3 ();
 sky130_fd_sc_hd__decap_3 FILLER_2_15 ();
 sky130_fd_sc_hd__decap_6 FILLER_2_24 ();
 sky130_fd_sc_hd__decap_12 FILLER_2_31 ();
 sky130_fd_sc_hd__decap_12 FILLER_2_43 ();
 sky130_fd_sc_hd__decap_12 FILLER_2_55 ();
 sky130_fd_sc_hd__decap_8 FILLER_2_67 ();
 sky130_fd_sc_hd__fill_2 FILLER_2_75 ();
 sky130_fd_sc_hd__decap_12 FILLER_3_43 ();
 sky130_fd_sc_hd__decap_4 FILLER_3_55 ();
 sky130_fd_sc_hd__fill_1 FILLER_3_59 ();
 sky130_fd_sc_hd__decap_12 FILLER_3_61 ();
 sky130_fd_sc_hd__decap_4 FILLER_3_73 ();
 sky130_fd_sc_hd__decap_12 FILLER_4_3 ();
 sky130_fd_sc_hd__decap_12 FILLER_4_15 ();
 sky130_fd_sc_hd__decap_3 FILLER_4_27 ();
 sky130_fd_sc_hd__decap_12 FILLER_4_46 ();
 sky130_fd_sc_hd__decap_12 FILLER_4_58 ();
 sky130_fd_sc_hd__decap_6 FILLER_4_70 ();
 sky130_fd_sc_hd__fill_1 FILLER_4_76 ();
 sky130_fd_sc_hd__decap_8 FILLER_5_3 ();
 sky130_fd_sc_hd__decap_8 FILLER_5_16 ();
 sky130_fd_sc_hd__fill_1 FILLER_5_24 ();
 sky130_fd_sc_hd__decap_12 FILLER_5_46 ();
 sky130_fd_sc_hd__fill_2 FILLER_5_58 ();
 sky130_fd_sc_hd__decap_12 FILLER_5_61 ();
 sky130_fd_sc_hd__decap_4 FILLER_5_73 ();
 sky130_fd_sc_hd__decap_6 FILLER_6_3 ();
 sky130_fd_sc_hd__fill_1 FILLER_6_9 ();
 sky130_fd_sc_hd__fill_1 FILLER_6_31 ();
 sky130_fd_sc_hd__decap_4 FILLER_6_58 ();
 sky130_fd_sc_hd__fill_1 FILLER_6_62 ();
 sky130_fd_sc_hd__decap_8 FILLER_6_69 ();
 sky130_fd_sc_hd__decap_12 FILLER_7_3 ();
 sky130_fd_sc_hd__decap_3 FILLER_7_15 ();
 sky130_fd_sc_hd__decap_3 FILLER_7_57 ();
 sky130_fd_sc_hd__decap_12 FILLER_7_61 ();
 sky130_fd_sc_hd__decap_4 FILLER_7_73 ();
endmodule
