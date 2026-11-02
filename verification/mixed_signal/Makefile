ROOT := $(abspath ../..)
NGSPICE_PREFIX ?= $(HOME)/.local/opt/ngspice47-shared
BUILD ?= $(ROOT)/results/verification/mixed_signal/build
KP ?= 65536
VERILATOR_ROOT ?= /usr/share/verilator
RTL := $(ROOT)/digital/rx/rtl/bbpd_window_vote.sv \
       $(ROOT)/digital/rx/rtl/cdr_phase_frequency.sv \
       $(ROOT)/digital/rx/rtl/pi_step_commutator.sv \
       $(ROOT)/digital/rx/rtl/rx_deserializer16.sv \
       $(ROOT)/verification/mixed_signal/rtl/mixed_cdr_top.sv
.PHONY: build run boundary-test clean build-words run-words
BUILD_WORDS ?= $(ROOT)/results/verification/mixed_signal/build_words
RTL_WORDS := $(ROOT)/digital/rx/rtl/bbpd_window_vote.sv \
       $(ROOT)/digital/rx/rtl/cdr_phase_frequency.sv \
       $(ROOT)/digital/rx/rtl/pi_step_commutator.sv \
       $(ROOT)/digital/rx/rtl/rx_word_map.sv \
       $(ROOT)/digital/rx/rtl/rx_word_align16.sv \
       $(ROOT)/verification/mixed_signal/rtl/mixed_cdr_words_top.sv
build:
	mkdir -p $(BUILD)
	verilator --cc --trace -Wall --top-module mixed_cdr_top -GKP=$(KP) \
	  --Mdir $(BUILD) --exe $(ROOT)/verification/mixed_signal/cpp/cosim.cpp \
	  -CFLAGS '-std=c++17 -O2 -pthread -I$(NGSPICE_PREFIX)/include -DCOSIM_KP=$(KP)' \
	  -LDFLAGS '-L$(NGSPICE_PREFIX)/lib -Wl,-rpath,$(NGSPICE_PREFIX)/lib -lngspice -pthread' $(RTL)
	$(MAKE) -C $(BUILD) -f Vmixed_cdr_top.mk -j4
run: build
	@test -n "$(OUT)" || (echo 'Set OUT to an absolute run directory'; exit 2)
	cd $(ROOT) && $(BUILD)/Vmixed_cdr_top --root $(ROOT) --out $(OUT)
boundary-test: build
	$(CXX) -std=c++17 -O2 -pthread -DCOSIM_KP=$(KP) \
	  -I$(BUILD) -I$(VERILATOR_ROOT)/include -I$(VERILATOR_ROOT)/include/vltstd \
	  -I$(NGSPICE_PREFIX)/include $(ROOT)/verification/mixed_signal/cpp/boundary_test.cpp \
	  $(BUILD)/Vmixed_cdr_top__ALL.a $(BUILD)/verilated.o $(BUILD)/verilated_vcd_c.o \
	  -L$(NGSPICE_PREFIX)/lib -Wl,-rpath,$(NGSPICE_PREFIX)/lib -lngspice \
	  -o $(BUILD)/boundary_test
	$(BUILD)/boundary_test $(BUILD)/boundary_unit
clean:
	$(MAKE) -C $(BUILD) -f Vmixed_cdr_top.mk clean
# Physical readout (rx_readout_deser16) variant: cosim_words.cpp, receiver_words.cir.in, mixed_cdr_words_top.sv
build-words:
	mkdir -p $(BUILD_WORDS)
	verilator --cc --trace -Wall --top-module mixed_cdr_words_top -GKP=$(KP) \
	  --Mdir $(BUILD_WORDS) --exe $(ROOT)/verification/mixed_signal/cpp/cosim_words.cpp \
	  -CFLAGS '-std=c++17 -O2 -pthread -I$(NGSPICE_PREFIX)/include -DCOSIM_KP=$(KP)' \
	  -LDFLAGS '-L$(NGSPICE_PREFIX)/lib -Wl,-rpath,$(NGSPICE_PREFIX)/lib -lngspice -pthread' $(RTL_WORDS)
	$(MAKE) -C $(BUILD_WORDS) -f Vmixed_cdr_words_top.mk -j2
run-words: build-words
	@test -n "$(OUT)" || (echo 'Set OUT to an absolute run directory'; exit 2)
	cd $(ROOT) && $(BUILD_WORDS)/Vmixed_cdr_words_top --root $(ROOT) --out $(OUT) $(ARGS)
