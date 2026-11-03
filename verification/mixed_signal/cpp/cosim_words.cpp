// Live Verilator RTL <-> shared ngspice RX loop on the physical readout (rx_readout_deser16).
// Same bridge as cosim.cpp (one continuous transient, RTL advanced on accepted points, PI control
// pins driven back with a launch delay and slew), but the analog->digital boundary is the readout's
// 32 word outputs read `read_delay` after each rising edge of the word clock w; all RTL runs on w
// (mixed_cdr_words_top: rx_word_map -> vote -> loop -> commutator, rx_word_align16).
// Stimulus: ideal NRZ, training word b5e3 for --train-ui, then payload words; training_enable is
// released once the aligner is aligned after --release-ns.
// COSIM_CAL build (make build-cal): top mixed_cdr_cal_top, netlist receiver_cal.cir.in (sampler with the
// offset trim).  The input stays in electrical idle (differential 0) until --cal-end-ns; the first
// counted word starts rx_offset_cal; its 24 code bits drive the trim code pins like the PI controls
// (launch delay + slew); the CDR loop runs after cal_done; training starts at --cal-end-ns and
// --release-ns counts from there.  --inject-ua sets the per-lane sink currents on the trim nodes
// (a sink of k unit currents on tp acts like code + k/2, on tn like code - k/2 to first order; the
// injection compresses the step, so 31.5 -+ k/2 is reported as `estimate` only).  Pass criterion per
// lane: |code - expected| <= --cal-tol (default 1) with --cal-expect d0=..,d1=..,e0=..,e1=.. (balance
// codes measured on the ramp bench, analog/rx/sampler/tb/offset_dac/cal_check.py), otherwise the code
// must not be saturated (1..62).  --corner/--supply/--temp select the condition.
#ifdef COSIM_CAL
#include "Vmixed_cdr_cal_top.h"
using Top=Vmixed_cdr_cal_top;
static const char* TEMPLATE="verification/mixed_signal/tb/receiver_cal.cir.in";
#else
#include "Vmixed_cdr_words_top.h"
using Top=Vmixed_cdr_words_top;
static const char* TEMPLATE="verification/mixed_signal/tb/receiver_words.cir.in";
#endif
#include "verilated.h"
#include "verilated_vcd_c.h"
#include <ngspice/sharedspice.h>
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <deque>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <memory>
#include <mutex>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace fs=std::filesystem;
using Clock=std::chrono::steady_clock;
static uint64_t sim_fs=0;
double sc_time_stamp(){ return double(sim_fs); }
static constexpr double PS=1e-12,NS=1e-9,UI=250*PS;
static std::string readfile(const fs::path& p){std::ifstream f(p);if(!f)throw std::runtime_error("open "+p.string());return {std::istreambuf_iterator<char>(f),{}};}
static void replace_all(std::string& s,const std::string& a,const std::string& b){size_t i=0;while((i=s.find(a,i))!=std::string::npos){s.replace(i,a.size(),b);i+=b.size();}}
static std::string lower(std::string s){for(char& c:s)c=char(std::tolower(static_cast<unsigned char>(c)));return s;}
static int command(const std::string& s){std::vector<char> b(s.begin(),s.end());b.push_back(0);return ngSpice_Command(b.data());}
static uint64_t rss_bytes(){std::ifstream f("/proc/self/status");std::string s;while(std::getline(f,s))if(s.rfind("VmRSS:",0)==0){std::istringstream q(s.substr(6));uint64_t k;q>>k;return k*1024;}return 0;}

static const char* LANES[8]={"a0","b0","ae1","be1","a1","b1","ae0","be0"};
static bool edge_lane(int l){return l==2||l==3||l==6||l==7;}

struct Options {
    fs::path root=fs::current_path(),out;
    double stop=80*NS,read_delay=100*PS,drive_delay=50*PS,slew=20*PS,release=50*NS,wall=7200;
    double tx_phase=0,vcm=1.05,vlow=.54,vhigh=1.26;
    long long train_ui=160;
    bool hold=false;
    double supply=1.8,temp=27,cal_end=0,iu_ua=0.996;
    std::string corner="tt";
    std::map<std::string,double> inject_ua;   // d0p d0n d1p ... -> uA
    std::map<std::string,double> cal_expect;  // d0 d1 e0 e1 -> balance code
    double cal_tol=1.0;
};
struct Ramp {double start,end,from,to;};
struct Pin {
    double base=0; std::deque<Ramp> ramps;
    double at(double t)const {
        double v=base;
        for(const auto& r:ramps){if(t<r.start)return v;if(t<r.end)return r.from+(r.to-r.from)*(t-r.start)/(r.end-r.start);v=r.to;}
        return v;
    }
    void set(double start,double slew,double to){double from=at(start);if(std::abs(from-to)>1e-9)ramps.push_back({start,start+slew,from,to});}
    void prune(double t){while(!ramps.empty()&&ramps.front().end<t-2*NS){base=ramps.front().to;ramps.pop_front();}}
};
using Row=std::vector<double>;
struct Window {std::string name;double lo,hi;std::vector<Row> rows;bool written=false;};

struct Bridge {
    Options o;
    std::unique_ptr<Top> top{new Top};
    VerilatedVcdC vcd;
    std::ofstream log,reads_log,controls,words,phases,progress,pin_events;
    std::mutex log_mutex,error_mutex;
    std::string failure;
    std::atomic<bool> started{false},done{false},fatal{false};
    std::atomic<double> time_now{0};std::atomic<uint64_t> points{0};
    std::array<Pin,48> pins;                         // 0..23 PI controls a/b/f, 24..47 trim codes (lane*6+bit)
    unsigned last_cal=0xffffffff,cal_changes=0;double cal_done_t=-1,cal_start_t=-1;bool cal_started=false;
    std::ofstream cal_log;
    std::vector<std::string> wanted;
    int I_W=0,I_OUT=0,I_F0=0,I_DP=5,I_DN=6;
    std::vector<int> indices;
    std::deque<Row> ring;std::vector<Window> windows;
    Row previous_row;bool have_previous=false;
    std::deque<double> reads;
    unsigned word_reads=0,votes=0,invalid_bundles=0,unknown_data=0,unknown_edge=0;
    unsigned changes=0,commands_changed=0,payload_count=0,word_errors=0,training_words=0;
    unsigned pin_crossings=0,skipped_windows=0,sector_crossings=0,realigns=0;
    bool payload_started=false,training=true,aligned_at_release=false;
    double release_time=-1;
    unsigned last_a=1,last_b=2,last_f=0,last_code=0,min_code=0,max_code=0;
    int net_steps=0;
    std::set<unsigned> codes_seen{0};
    double max_read_overshoot=0,initial_phase=-1,last_phase=-1;
    double clk_fall=0;
    uint64_t max_ring=0;
    Bridge(const Options& options):o(options){
        wanted={"time","xp","xn","ip","in","dp","dn","ep","en","w"};
        I_W=9;I_OUT=int(wanted.size());
        for(int l=0;l<8;++l)for(int k=0;k<4;++k)wanted.push_back(std::string(LANES[l])+"_"+std::to_string(k));
        I_F0=int(wanted.size());for(const char* n:{"f0","f7","a0","b7"})wanted.push_back(n);
        fs::create_directories(o.out/"windows");fs::create_directories(o.out/"netlist");
        log.open(o.out/"ngspice.log");reads_log.open(o.out/"word_reads.tsv");controls.open(o.out/"controls.tsv");words.open(o.out/"words.tsv");phases.open(o.out/"clock_phase.tsv");progress.open(o.out/"progress.jsonl");
        pin_events.open(o.out/"da_pin_events.tsv");pin_events<<"time_s f0_crossing_rising rtl_code\n"<<std::setprecision(17);
        reads_log<<"time_s phys_hex data_known edge_known overshoot_ps training\n";
        controls<<"time_s code a b fine vote transitions bundle_valid applied frequency_q debt_q launch_time_s\n";
        words<<"time_s word_hex expected_hex accepted_payload offset\n";phases<<"time_s phase_ps rtl_code\n";
        for(auto* f:{&reads_log,&controls,&words,&phases})*f<<std::setprecision(17);
        o.vlow=.3*o.supply;o.vhigh=.7*o.supply;
        pins[0].base=o.supply;pins[8+1].base=o.supply;
        for(int l=0;l<4;++l)pins[24+6*l+5].base=o.supply;          // reset code 32 = bit 5
        cal_log.open(o.out/"cal.tsv");cal_log<<"time_s busy done d0 d1 e0 e1\n"<<std::setprecision(17);
        top->clk=0;top->enable=1;top->training_enable=1;top->sample_known=0;top->phys=0;
#ifdef COSIM_CAL
        top->cal_start=0;
#endif
        top->rst_n=1;top->eval();top->rst_n=0;top->eval();top->rst_n=1;top->eval();
        vcd.set_time_unit("1fs");vcd.set_time_resolution("1fs");top->trace(&vcd,20);vcd.open((o.out/"digital.vcd").c_str());
        windows.push_back({"startup",0,8*NS,{}});
    }
    void fail(const std::string& s){if(!fatal.exchange(true)){std::lock_guard<std::mutex> g(error_mutex);failure=s;}}
    static uint16_t payload(unsigned n){return uint16_t(0x1200u+n*0x137u);}
    int bit(long long k)const{
        uint16_t w;unsigned j=unsigned((k%16+16)%16);
        if(k<0)return 0;
        if(k<o.train_ui)w=0xb5e3;else w=payload(unsigned((k-o.train_ui)/16));
        return (w>>j)&1;
    }
    double level(long long k)const{return (o.cal_end>0&&k<0)?0.0:double(2*bit(k)-1);}   // electrical idle before the data
    double serial(double t)const{
        double tt=t-o.cal_end-o.tx_phase;long long k=static_cast<long long>(std::floor((tt+10*PS)/UI));
        double z=(tt-double(k)*UI+10*PS)/(20*PS);
        double now=level(k),before=level(k-1);
        if(z>=1)return now;
        if(z<=0)return before;
        return before+(now-before)*z;
    }
    int decode(double v,bool& known)const{known=v<=o.vlow||v>=o.vhigh;return v>=o.vhigh;}
    void start_window(const std::string& name,double center){
        if(windows.size()>=16){skipped_windows++;return;}
        Window w{name,center-2*NS,center+2*NS,{}};
        for(const auto& r:ring)if(r[0]>=w.lo&&r[0]<=w.hi)w.rows.push_back(r);
        windows.push_back(std::move(w));
    }
    void flush_window(size_t i){
        auto& w=windows[i];if(w.written)return;
        std::ofstream f(o.out/"windows"/(std::to_string(i)+"_"+w.name+".tsv"));
        for(const auto& n:wanted)f<<n<<'\t';f<<'\n'<<std::setprecision(17);
        for(const auto& row:w.rows){for(double x:row)f<<x<<'\t';f<<'\n';}
        w.rows.clear();w.rows.shrink_to_fit();w.written=true;
    }
    void tick_word(const Row& row,double scheduled){
        double t=row[0];uint32_t phys=0;bool dknown=true,eknown=true;
        for(int l=0;l<8;++l)for(int k=0;k<4;++k){bool kn;int d=decode(row[I_OUT+4*l+k],kn);phys|=uint32_t(d)<<unsigned(4*l+k);if(edge_lane(l))eknown=eknown&&kn;else dknown=dknown&&kn;}
        bool counted=t>=4*NS;                                   // reads before 4 ns: readout still settling
        if(counted){word_reads++;if(!dknown)unknown_data++;if(!eknown)unknown_edge++;max_read_overshoot=std::max(max_read_overshoot,t-scheduled);}
        if(training&&release_time<0&&t>=o.cal_end+o.release&&top->aligned){training=false;release_time=t;aligned_at_release=true;}
        reads_log<<t<<' '<<std::hex<<phys<<std::dec<<' '<<dknown<<' '<<eknown<<' '<<(t-scheduled)/PS<<' '<<training<<'\n';
        bool was_aligned=top->aligned;
        top->clk=0;top->phys=phys;top->sample_known=counted&&eknown;top->training_enable=training;
#ifdef COSIM_CAL
        bool start_now=counted&&!cal_started;top->cal_start=start_now;if(start_now){cal_started=true;cal_start_t=t;}
#endif
        top->eval();
        unsigned old_code=top->phase_code;top->clk=1;top->eval();
#ifdef COSIM_CAL
        top->cal_start=0;
        unsigned cc=top->cal_codes;
        if(cc!=last_cal){
            if(last_cal!=0xffffffff)cal_changes++;
            for(int i=0;i<24;++i)pins[24+i].set(t+o.drive_delay,o.slew,((cc>>i)&1u)?o.supply:0);
            last_cal=cc;
        }
        if(top->cal_done&&cal_done_t<0)cal_done_t=t;
        cal_log<<t<<' '<<unsigned(top->cal_busy)<<' '<<unsigned(top->cal_done);for(int l=0;l<4;++l)cal_log<<' '<<((cc>>(6*l))&63u);cal_log<<'\n';
#endif
        if(was_aligned&&!top->aligned)realigns++;
        unsigned code=top->phase_code;
        if(old_code!=code){
            changes++;int step=((int(code)-int(old_code)+96)%64)-32;net_steps+=step;
            if(code/8!=old_code/8)sector_crossings++;codes_seen.insert(code);
        }
        if(top->vote_valid){votes++;}
        if(counted&&!top->bundle_valid)invalid_bundles++;
        unsigned a=top->select_a,bb=top->select_b,f=top->fine_b;
        if(a!=last_a||bb!=last_b||f!=last_f){
            commands_changed++;
            if(!o.hold){
                for(int i=0;i<8;++i){pins[i].set(t+o.drive_delay,o.slew,(a&(1u<<i))?o.supply:0);pins[8+i].set(t+o.drive_delay,o.slew,(bb&(1u<<i))?o.supply:0);pins[16+i].set(t+o.drive_delay,o.slew,(f&(1u<<i))?o.supply:0);}
            }
            start_window("command_"+std::to_string(commands_changed),t+o.drive_delay);
        }
        last_a=a;last_b=bb;last_f=f;
        int vote=(top->vote_sum&32)?int(top->vote_sum)-64:int(top->vote_sum);
        controls<<t<<' '<<code<<' '<<a<<' '<<bb<<' '<<f<<' '<<vote<<' '<<unsigned(top->transition_count)<<' '<<unsigned(top->bundle_valid)<<' '<<unsigned(top->step_applied)<<' '<<int32_t(top->frequency_q)<<' '<<int32_t(top->phase_debt_q)<<' '<<t+o.drive_delay<<'\n';
        if(top->word_valid){
            unsigned w=top->word_data;bool check=payload_started||w!=0xb5e3;
            unsigned expected=payload(payload_count);
            if(check){payload_started=true;if(w!=expected)word_errors++;payload_count++;}else training_words++;
            words<<t<<' '<<std::hex<<w<<' '<<expected<<std::dec<<' '<<check<<' '<<unsigned(top->offset)<<'\n';
        }
        clk_fall=t+2*NS;
    }
    void data(pvecvaluesall v){
        if(indices.empty())return;
        Row row;row.reserve(indices.size());for(int idx:indices)row.push_back(v->vecsa[idx]->creal);
        double t=row[0];if(have_previous&&t<=previous_row[0])return;
        if(!std::isfinite(t)||t<0){fail("invalid analog time");return;}
        time_now=t;points++;sim_fs=uint64_t(std::llround(t*1e15));
        ring.push_back(row);while(ring.size()>1&&ring[1][0]<t-2*NS)ring.pop_front();max_ring=std::max<uint64_t>(max_ring,ring.size());
        if(ring.size()>32768){fail("pretrigger capacity exceeded");ring.pop_front();}
        for(size_t i=0;i<windows.size();++i){auto& w=windows[i];if(!w.written&&w.lo<=t&&t<=w.hi){if(w.rows.size()>=65536)fail("waveform window capacity exceeded");else w.rows.push_back(row);}if(!w.written&&t>w.hi)flush_window(i);}
        if(clk_fall>0&&clk_fall<=t+1e-17){top->clk=0;top->eval();clk_fall=0;}
        if(have_previous){
            const auto& old=previous_row;
            const double mid=.5*o.supply;
            if(old[I_W]<mid&&row[I_W]>=mid){double edge=old[0]+(mid-old[I_W])*(t-old[0])/(row[I_W]-old[I_W]);reads.push_back(edge+o.read_delay);}
            if((old[I_F0]<mid&&row[I_F0]>=mid)||(old[I_F0]>mid&&row[I_F0]<=mid)){pin_crossings++;double edge=old[0]+(mid-old[I_F0])*(t-old[0])/(row[I_F0]-old[I_F0]);pin_events<<edge<<' '<<(row[I_F0]>old[I_F0])<<' '<<unsigned(top->phase_code)<<'\n';}
            double p0=old[I_DP]-old[I_DN],p1=row[I_DP]-row[I_DN];
            if(p0<0&&p1>=0){double tt=old[0]-p0*(t-old[0])/(p1-p0);double ph=std::fmod(tt,500*PS);if(tt>4*NS&&initial_phase<0)initial_phase=ph;last_phase=ph;phases<<tt<<' '<<ph/PS<<' '<<unsigned(top->phase_code)<<'\n';}
        }
        while(!reads.empty()&&reads.front()<=t+1e-17){double s=reads.front();reads.pop_front();tick_word(row,s);}
        for(auto& pin:pins)pin.prune(t);
        vcd.dump(sim_fs);previous_row=std::move(row);have_previous=true;
    }
    double next_event(double now)const{
        double next=o.stop;
        if(clk_fall>now+1e-17)next=std::min(next,clk_fall);
        if(!reads.empty()&&reads.front()>now+1e-17)next=std::min(next,reads.front());
        for(const auto& p:pins)for(const auto& r:p.ramps){if(r.start>now+1e-17)next=std::min(next,r.start);if(r.end>now+1e-17)next=std::min(next,r.end);}
        return next;
    }
    static int on_char(char* text,int,void* u){auto& b=*static_cast<Bridge*>(u);std::lock_guard<std::mutex> g(b.log_mutex);b.log<<text<<'\n';if(std::string(text).find("Error:")!=std::string::npos)b.fail(std::string("ngspice: ")+text);return 0;}
    static int on_stat(char*,int,void*){return 0;}
    static int on_exit(int code,NG_BOOL,NG_BOOL,int,void* u){if(code)static_cast<Bridge*>(u)->fail("ngspice controlled exit "+std::to_string(code));return 0;}
    static int on_thread(NG_BOOL exited,int,void* u){auto& b=*static_cast<Bridge*>(u);if(!exited)b.started=true;else b.done=true;return 0;}
    static int on_init(pvecinfoall info,int,void* u){auto& b=*static_cast<Bridge*>(u);b.indices.clear();
        std::map<std::string,int> map;
        for(int i=0;i<info->veccount;++i){std::string n=lower(info->vecs[i]->vecname);if(n.rfind("v(",0)==0&&n.back()==')')n=n.substr(2,n.size()-3);map[n]=i;}
        for(const auto& n:b.wanted){auto j=map.find(n);if(j==map.end()){b.fail("missing analog vector "+n);return 1;}b.indices.push_back(j->second);}return 0;
    }
    static int on_data(pvecvaluesall data,int,int,void* u){auto& b=*static_cast<Bridge*>(u);try{b.data(data);}catch(const std::exception& e){b.fail(e.what());}return 0;}
    static int on_source(double* value,double t,char* source,int,void* u){auto& b=*static_cast<Bridge*>(u);std::string n=lower(source);
        if(n=="vip"||n=="vin"){*value=b.o.vcm+(n=="vip"?1:-1)*.0875*b.serial(t);return 0;}
        if(n.rfind("vcal_",0)==0&&n.size()==9){int lane=(n[5]=='d'?0:2)+(n[6]-'0');int bit=n[8]-'0';if(lane>=0&&lane<4&&bit>=0&&bit<6){*value=b.pins[24+6*lane+bit].at(t);return 0;}}
        if(n.size()>=3&&n[0]=='v'&&(n[1]=='a'||n[1]=='b'||n[1]=='f')){int bit=std::stoi(n.substr(2));if(bit>=0&&bit<8){int offset=n[1]=='a'?0:n[1]=='b'?8:16;*value=b.pins[offset+bit].at(t);return 0;}}
        *value=0;b.fail("unexpected external source "+n);return 1;
    }
    static int on_sync(double t,double* delta,double,int,int,int,void* u){auto& b=*static_cast<Bridge*>(u);double next=b.next_event(t);if(next>t+1e-17&&next<t+*delta)*delta=next-t;return 0;}
    fs::path deck(){
        std::string s=readfile(o.root/TEMPLATE);
        replace_all(s,"@PROJECT_ROOT@",o.root.string());
        {std::ostringstream v;v<<std::setprecision(6)<<o.supply;replace_all(s,"@SUPPLY@",v.str());}
        {std::ostringstream v;v<<o.temp;replace_all(s,"@TEMP@",v.str());}
        replace_all(s,"@SECTION@",o.corner);
        for(const char* l:{"D0","D1","E0","E1"})for(const char* side:{"P","N"}){std::string key=lower(std::string(l)+side);double ua=o.inject_ua.count(key)?o.inject_ua.at(key):0;std::ostringstream v;v<<std::setprecision(9)<<ua<<"u";replace_all(s,std::string("@INJ_")+l+side+"@",v.str());}std::ostringstream stop;stop<<std::setprecision(17)<<o.stop;replace_all(s,"@STOP@",stop.str());
        std::istringstream in(s);std::string line,expanded;
        while(std::getline(in,line)){
            if(line.rfind(".include \"",0)==0){size_t end=line.find('"',10);fs::path source=line.substr(10,end-10);fs::path relative=fs::relative(source,o.root);fs::path dest=o.out/"netlist"/relative;fs::create_directories(dest.parent_path());fs::copy_file(source,dest,fs::copy_options::overwrite_existing);line=".include \""+dest.string()+"\"";}
            expanded+=line+"\n";
        }
        fs::path file=o.out/"netlist/tb.cir";std::ofstream(file)<<expanded;return file;
    }
    bool finish(){
        vcd.close();top->final();reads_log.flush();controls.flush();words.flush();phases.flush();pin_events.flush();
        for(size_t i=0;i<windows.size();++i)flush_window(i);
        char name[]="time";auto* info=ngGet_Vec_Info(name);int retained=info?info->v_length:-1;
        double delta=last_phase-initial_phase;while(delta>250*PS)delta-=500*PS;while(delta<-250*PS)delta+=500*PS;
        bool full=std::abs(time_now-o.stop)<1e-15;
        bool good=full&&!fatal&&unknown_data==0&&word_errors==0&&retained==1&&changes>0&&aligned_at_release&&payload_count>=4;
        if(!o.hold)good=good&&pin_crossings>0;
        std::ostringstream calj;bool cal_ok=true;
#ifdef COSIM_CAL
        {static const char* L[4]={"d0","d1","e0","e1"};unsigned cc=top->cal_codes;
         cal_ok=cal_done_t>0&&cal_done_t<o.cal_end;
         calj<<"  \"cal_start_s\": "<<cal_start_t<<",\n  \"cal_done_s\": "<<cal_done_t<<",\n  \"cal_end_s\": "<<o.cal_end<<",\n  \"cal_code_changes\": "<<cal_changes<<",\n  \"cal_lanes\": {";
         for(int l=0;l<4;++l){std::string lp=std::string(L[l])+"p",ln=std::string(L[l])+"n";
            double kp=(o.inject_ua.count(lp)?o.inject_ua.at(lp):0)/o.iu_ua,kn=(o.inject_ua.count(ln)?o.inject_ua.at(ln):0)/o.iu_ua;
            double estimate=31.5-kp/2+kn/2;unsigned code=(cc>>(6*l))&63u;bool has=o.cal_expect.count(L[l]);
            bool ok=has?std::abs(double(code)-o.cal_expect.at(L[l]))<=o.cal_tol:(code>=1&&code<=62);cal_ok=cal_ok&&ok;
            calj<<(l?", ":"")<<"\""<<L[l]<<"\": {\"code\": "<<code<<", \"estimate\": "<<estimate<<", \"expected\": ";
            if(has)calj<<o.cal_expect.at(L[l]);else calj<<"null";
            calj<<", \"ok\": "<<(ok?"true":"false")<<"}";}
         calj<<"},\n  \"cal_passed\": "<<(cal_ok?"true":"false")<<",\n  \"corner\": \""<<o.corner<<"\",\n  \"supply_v\": "<<o.supply<<",\n  \"temp_c\": "<<o.temp<<",\n  \"iu_ua\": "<<o.iu_ua<<",\n  \"cal_tol\": "<<o.cal_tol<<",\n";}
        good=good&&cal_ok;
#endif
        std::ostringstream codes;bool first=true;for(unsigned c:codes_seen){codes<<(first?"":",")<<c;first=false;}
        std::ofstream f(o.out/"summary.json");f<<std::boolalpha<<std::setprecision(17)
          <<"{\n  \"passed\": "<<good<<",\n  \"scope\": \"live_Verilator_RTL_and_real_MOS_PI_CTLE_sampler_"
#ifdef COSIM_CAL
          <<"ac_trim_rk_with_offset_calibration"
#else
          <<"ac_rk"
#endif
          <<"_readout_deser16; physical_16UI_words; ideal_NRZ_source; not_lock_time_signoff\",\n"<<calj.str()
          <<"  \"kp_q\": "<<COSIM_KP<<",\n  \"control_hold_negative_test\": "<<o.hold<<",\n  \"stop_s\": "<<o.stop<<",\n  \"actual_stop_s\": "<<time_now.load()<<",\n"
          <<"  \"tx_phase_ps\": "<<o.tx_phase/PS<<",\n  \"train_ui\": "<<o.train_ui<<",\n  \"release_time_s\": "<<release_time<<",\n  \"aligned_at_release\": "<<aligned_at_release<<",\n  \"realigns\": "<<realigns<<",\n"
          <<"  \"accepted_points\": "<<points.load()<<",\n  \"ngspice_retained_time_points\": "<<retained<<",\n  \"ring_peak_points\": "<<max_ring<<",\n  \"word_reads\": "<<word_reads<<",\n  \"votes\": "<<votes<<",\n"
          <<"  \"invalid_bundles\": "<<invalid_bundles<<",\n  \"unknown_data_reads\": "<<unknown_data<<",\n  \"unknown_edge_reads\": "<<unknown_edge<<",\n  \"RTL_phase_changes\": "<<changes<<",\n  \"net_steps\": "<<net_steps<<",\n"
          <<"  \"sector_crossings\": "<<sector_crossings<<",\n  \"codes_visited\": ["<<codes.str()<<"],\n"
          <<"  \"final_phase_code\": "<<unsigned(top->phase_code)<<",\n  \"analog_f0_pin_crossings\": "<<pin_crossings<<",\n  \"skipped_waveform_windows\": "<<skipped_windows<<",\n  \"measured_clock_phase_shift_ps\": "<<delta/PS<<",\n"
          <<"  \"training_words_out\": "<<training_words<<",\n  \"payload_words\": "<<payload_count<<",\n  \"payload_errors\": "<<word_errors<<",\n"
          <<"  \"max_read_deadline_overshoot_ps\": "<<max_read_overshoot/PS<<",\n  \"locked\": "<<bool(top->locked)<<",\n  \"aligned\": "<<bool(top->aligned)<<",\n  \"offset\": "<<unsigned(top->offset)<<",\n"
          <<"  \"adc_low_v\": "<<o.vlow<<",\n  \"adc_high_v\": "<<o.vhigh<<",\n  \"read_delay_ps\": "<<o.read_delay/PS<<",\n  \"input_cm_v\": "<<o.vcm<<",\n"
          <<"  \"driver_launch_ps\": "<<o.drive_delay/PS<<",\n  \"driver_input_slew_ps\": "<<o.slew/PS<<",\n  \"failure\": \""<<failure<<"\"\n}\n";
        std::cout<<"RESULT passed="<<good<<" cal_ok="<<cal_ok<<" reads="<<word_reads<<" changes="<<changes<<" net_steps="<<net_steps<<" sectors="<<sector_crossings<<" clock_shift_ps="<<delta/PS<<" payload="<<payload_count<<" errors="<<word_errors<<" aligned_at_release="<<aligned_at_release<<" failure="<<failure<<std::endl;
        return good;
    }
};

int main(int argc,char** argv){
 try{
    Options o;Verilated::commandArgs(argc,argv);Verilated::traceEverOn(true);
    for(int i=1;i<argc;++i){std::string k=argv[i];auto val=[&](){if(++i>=argc)throw std::runtime_error("missing argument");return std::string(argv[i]);};
        if(k=="--root")o.root=fs::absolute(val());else if(k=="--out")o.out=fs::absolute(val());else if(k=="--stop-ns")o.stop=std::stod(val())*NS;
        else if(k=="--tx-phase-ps")o.tx_phase=std::stod(val())*PS;else if(k=="--train-ui")o.train_ui=std::stoll(val());else if(k=="--release-ns")o.release=std::stod(val())*NS;
        else if(k=="--wall-s")o.wall=std::stod(val());else if(k=="--hold-controls")o.hold=true;
        else if(k=="--corner")o.corner=val();else if(k=="--supply")o.supply=std::stod(val());else if(k=="--temp")o.temp=std::stod(val());
        else if(k=="--cal-end-ns")o.cal_end=std::stod(val())*NS;else if(k=="--iu-ua")o.iu_ua=std::stod(val());
        else if(k=="--cal-tol")o.cal_tol=std::stod(val());
        else if(k=="--cal-expect"){std::istringstream in(val());std::string item;while(std::getline(in,item,',')){auto e=item.find('=');if(e==std::string::npos)throw std::runtime_error("--cal-expect lane=code,...");o.cal_expect[lower(item.substr(0,e))]=std::stod(item.substr(e+1));}}
        else if(k=="--inject-ua"){std::istringstream in(val());std::string item;while(std::getline(in,item,',')){auto e=item.find('=');if(e==std::string::npos)throw std::runtime_error("--inject-ua lane=uA,...");o.inject_ua[lower(item.substr(0,e))]=std::stod(item.substr(e+1));}}
        else throw std::runtime_error("unknown argument "+k);}
#ifdef COSIM_CAL
    if(o.cal_end<=0)throw std::runtime_error("--cal-end-ns is required for the calibration build");
#endif
    if(o.out.empty())throw std::runtime_error("--out is required");
    if(o.train_ui%16)throw std::runtime_error("--train-ui must be a multiple of 16");
    Bridge b(o);auto deck=b.deck();int ident=0;
    ngSpice_Init(Bridge::on_char,Bridge::on_stat,Bridge::on_exit,Bridge::on_data,Bridge::on_init,Bridge::on_thread,&b);
    ngSpice_Init_Sync(Bridge::on_source,nullptr,Bridge::on_sync,&ident,&b);
    command("set ngbehavior=hsa");command("set num_threads=1");command("set noaskquit");command("version");
    std::cout<<"{\"stage\":\"load_models_and_parse_netlist\"}"<<std::endl;
    if(command("source "+deck.string()))throw std::runtime_error("cannot source circuit");
    std::cout<<"{\"stage\":\"analog_transient_and_live_RTL\",\"kp_q\":"<<COSIM_KP<<"}"<<std::endl;
    auto begin=Clock::now();command("bg_run");double old_wall=0,old_time=0,rate=0;
    while(!b.done){
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
        double wall=std::chrono::duration<double>(Clock::now()-begin).count(),t=b.time_now.load();
        if(wall-old_wall>=30){double current=(t-old_time)/(wall-old_wall);if(current>0)rate=rate?rate*.6+current*.4:current;double eta=rate?(o.stop-t)/rate:-1;
            std::ostringstream row;row<<std::setprecision(10)<<"{\"wall_s\":"<<wall<<",\"sim_time_s\":"<<t<<",\"UI\":"<<t/UI<<",\"percent\":"<<100*t/o.stop<<",\"eta_s\":"<<eta<<",\"rss_bytes\":"<<rss_bytes()<<",\"points\":"<<b.points.load()<<",\"code\":"<<unsigned(b.top->phase_code)<<",\"aligned\":"<<int(b.top->aligned)<<"}";b.progress<<row.str()<<'\n';b.progress.flush();std::cout<<row.str()<<std::endl;old_wall=wall;old_time=t;
        }
        if(b.fatal||wall>o.wall){if(!b.fatal)b.fail("wall watchdog");command("bg_halt");break;}
    }
    for(int i=0;i<100&&ngSpice_running();++i)std::this_thread::sleep_for(std::chrono::milliseconds(10));
    bool good=b.finish();command("quit");return good?0:1;
 }catch(const std::exception& e){std::cerr<<"FATAL "<<e.what()<<std::endl;return 2;}
}
