* Launch the simulator from the project root.
.include "verification/stimuli/spice/clock_cmos.spice"
.include "verification/stimuli/spice/cml_diff_clock.spice"
.include "verification/stimuli/spice/pfd_clock_pair.spice"
.include "verification/stimuli/spice/cp_pulse_pair.spice"
.include "verification/stimuli/spice/vctrl_ramp.spice"

Xclk clk 0 stim_clock_cmos
Xdiff inp inn 0 stim_cml_diff_clock
Xpair ref fb 0 stim_pfd_clock_pair
Xcp up dn 0 stim_cp_pulse_pair
Xctrl vctrl 0 stim_vctrl_ramp
Bdiff diff 0 V={V(inp)-V(inn)}
Bcm cm 0 V={(V(inp)+V(inn))/2}

* Test-only bleed loads for isolated source outputs, not DUT termination values.
Rclk clk 0 1G
Rinp inp 0 1G
Rinn inn 0 1G
Rref ref 0 1G
Rfb fb 0 1G
Rup up 0 1G
Rdn dn 0 1G
Rctrl vctrl 0 1G
Rdiff diff 0 1G
Rcm cm 0 1G
