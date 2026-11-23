#include "Vmixed_cdr_top.h"
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

struct Options {
    fs::path root=fs::current_path(),out;
    double stop=48*NS,read_delay=350*PS,bundle_delay=50*PS,drive_delay=50*PS,slew=20*PS;
    double tx_phase=0,vlow=.54,vhigh=1.26;
    bool hold=false,probe=false;
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
struct Bundle {double when;uint16_t data,edge;bool prev,known;};

struct Bridge {
    Options o;
    std::unique_ptr<Vmixed_cdr_top> top{new Vmixed_cdr_top};
    VerilatedVcdC vcd;
    std::ofstream log,pairs,controls,words,phases,progress,pin_events;
    std::mutex log_mutex,error_mutex;
    std::string failure;
    std::atomic<bool> started{false},done{false},fatal{false};
    std::atomic<double> time_now{0};std::atomic<uint64_t> points{0};
    std::array<Pin,24> pins;
    std::vector<std::string> wanted{"time","xp","xn","ip","in","dp","dn","ep","en","ck","ad0","ad1","ae0","ae1","f0","f7","a0","b7"};
    std::vector<int> indices;
    std::deque<Row> ring;std::vector<Window> windows;
    Row previous_row;bool have_previous=false;
    std::deque<double> reads;std::deque<Bundle> bundles;
    uint16_t group_data=0,group_edge=0;unsigned group_pairs=0;
    bool group_previous=0,group_known=true,last_d1=0,last_d1_known=false;
    unsigned pair_count=0,bundle_count=0,invalid_bundles=0,unknown_data=0,unknown_edge=0;
    unsigned changes=0,commands_changed=0,payload_count=0,word_errors=0;
    unsigned pin_crossings=0,skipped_windows=0;
    bool payload_started=false;
    unsigned last_a=1,last_b=2,last_f=0;
    double max_read_overshoot=0,initial_phase=-1,last_phase=-1;
    double pair_fall=0,ctrl_fall=0;
    uint64_t max_ring=0;
    Bridge(const Options& options):o(options){
        fs::create_directories(o.out/"windows");fs::create_directories(o.out/"netlist");
        log.open(o.out/"ngspice.log");pairs.open(o.out/"pairs.tsv");controls.open(o.out/"controls.tsv");words.open(o.out/"words.tsv");phases.open(o.out/"clock_phase.tsv");progress.open(o.out/"progress.jsonl");
        pin_events.open(o.out/"da_pin_events.tsv");pin_events<<"time_s f0_crossing_rising rtl_code\n"<<std::setprecision(17);
        pairs<<"time_s d0 d1 e0 e1 data_known edge_known overshoot_ps\n";
        controls<<"time_s code a b fine vote transitions bundle_valid applied frequency_q debt_q launch_time_s\n";
        words<<"time_s word_hex expected_hex accepted_payload\n";phases<<"time_s phase_ps rtl_code\n";
        for(auto* f:{&pairs,&controls,&words,&phases})*f<<std::setprecision(17);
        pins[0].base=1.8;pins[8+1].base=1.8;
        top->pair_clk=0;top->ctrl_clk=0;top->enable=1;top->pair_valid=0;top->training_enable=1;
        top->bundle_valid=0;top->previous_data=0;top->data_samples=0;top->edge_samples=0;top->pair_bits=0;
        top->rst_n=1;top->eval();top->rst_n=0;top->eval();top->rst_n=1;top->eval();
        vcd.set_time_unit("1fs");vcd.set_time_resolution("1fs");top->trace(&vcd,20);vcd.open((o.out/"digital.vcd").c_str());
        windows.push_back({"startup",0,8*NS,{}});
    }
    void fail(const std::string& s){if(!fatal.exchange(true)){std::lock_guard<std::mutex> g(error_mutex);failure=s;}}
    static uint16_t payload(unsigned n){return uint16_t(0x1200u+n*0x137u);}
    int bit(long long k)const{
        uint16_t w;unsigned j=unsigned((k%16+16)%16);
        if(k<96)w=0xb5e3;else w=payload(unsigned((k-96)/16));
        return (w>>j)&1;
    }
    double serial(double t)const{
        double tt=t-o.tx_phase;long long k=static_cast<long long>(std::floor((tt+10*PS)/UI));
        double z=(tt-double(k)*UI+10*PS)/(20*PS);
        int now=bit(k),before=bit(k-1);
        if(z>=1)return 2*now-1;
        if(z<=0)return 2*before-1;
        return 2*(before+(now-before)*z)-1;
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
    void tick_pair(const Row& row,double scheduled){
        double t=row[0];bool known[4];int d[4];
        for(int i=0;i<4;++i)d[i]=decode(row[10+i],known[i]);
        if(t<4*NS){last_d1=d[1];last_d1_known=known[1];return;}
        pair_count++;unknown_data+=unsigned(!known[0])+unsigned(!known[1]);unknown_edge+=unsigned(!known[2])+unsigned(!known[3]);
        max_read_overshoot=std::max(max_read_overshoot,t-scheduled);
        pairs<<t<<' '<<d[0]<<' '<<d[1]<<' '<<d[2]<<' '<<d[3]<<' '<<(known[0]&&known[1])<<' '<<(known[2]&&known[3])<<' '<<(t-scheduled)/PS<<'\n';
        top->pair_clk=0;top->pair_valid=1;top->pair_bits=unsigned(d[0]+2*d[1]);
        if(top->aligned)top->training_enable=0;
        top->eval();top->pair_clk=1;top->eval();
        if(top->word_valid){
            unsigned w=top->word_data;bool check=payload_started||w!=0xb5e3;
            unsigned expected=payload(payload_count);
            if(check){payload_started=true;if(w!=expected)word_errors++;payload_count++;}
            words<<t<<' '<<std::hex<<w<<' '<<expected<<std::dec<<' '<<check<<'\n';
        }
        pair_fall=t+250*PS;
        if(group_pairs==0){group_previous=last_d1;group_known=last_d1_known;group_data=0;group_edge=0;}
        group_data|=uint16_t(d[0]<<unsigned(2*group_pairs));group_data|=uint16_t(d[1]<<unsigned(2*group_pairs+1));
        group_edge|=uint16_t(d[2]<<unsigned(2*group_pairs));group_edge|=uint16_t(d[3]<<unsigned(2*group_pairs+1));
        group_known=group_known&&known[0]&&known[1]&&known[2]&&known[3];
        group_pairs++;
        if(group_pairs==8){bundles.push_back({t+o.bundle_delay,group_data,group_edge,group_previous,group_known});group_pairs=0;}
        last_d1=d[1];last_d1_known=known[1];
    }
    void tick_control(double t,const Bundle& b){
        bundle_count++;if(!b.known)invalid_bundles++;
        top->ctrl_clk=0;top->bundle_valid=b.known;top->previous_data=b.prev;top->data_samples=b.data;top->edge_samples=b.edge;top->eval();
        unsigned old_code=top->phase_code;top->ctrl_clk=1;top->eval();
        unsigned a=top->select_a,bb=top->select_b,f=top->fine_b;
        if(old_code!=top->phase_code)changes++;
        if(a!=last_a||bb!=last_b||f!=last_f){
            commands_changed++;
            if(!o.hold){
                for(int i=0;i<8;++i){pins[i].set(t+o.drive_delay,o.slew,(a&(1u<<i))?1.8:0);pins[8+i].set(t+o.drive_delay,o.slew,(bb&(1u<<i))?1.8:0);pins[16+i].set(t+o.drive_delay,o.slew,(f&(1u<<i))?1.8:0);}
            }
            start_window("command_"+std::to_string(commands_changed),t+o.drive_delay);
        }
        last_a=a;last_b=bb;last_f=f;
        int vote=(top->vote_sum&32)?int(top->vote_sum)-64:int(top->vote_sum);
        controls<<t<<' '<<unsigned(top->phase_code)<<' '<<a<<' '<<bb<<' '<<f<<' '<<vote<<' '<<unsigned(top->transition_count)<<' '<<unsigned(top->bundle_valid)<<' '<<unsigned(top->step_applied)<<' '<<int32_t(top->frequency_q)<<' '<<int32_t(top->phase_debt_q)<<' '<<t+o.drive_delay<<'\n';
        ctrl_fall=t+2*NS;
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
        if(pair_fall>0&&pair_fall<=t+1e-17){top->pair_clk=0;top->eval();pair_fall=0;}
        if(ctrl_fall>0&&ctrl_fall<=t+1e-17){top->ctrl_clk=0;top->eval();ctrl_fall=0;}
        if(have_previous){
            const auto& old=previous_row;
            if(old[9]<.9&&row[9]>=.9){double edge=old[0]+(.9-old[9])*(t-old[0])/(row[9]-old[9]);reads.push_back(edge+o.read_delay);}
            if((old[14]<.9&&row[14]>=.9)||(old[14]>.9&&row[14]<=.9)){pin_crossings++;double edge=old[0]+(.9-old[14])*(t-old[0])/(row[14]-old[14]);pin_events<<edge<<' '<<(row[14]>old[14])<<' '<<unsigned(top->phase_code)<<'\n';}
            double p0=old[5]-old[6],p1=row[5]-row[6];
            if(p0<0&&p1>=0){double tt=old[0]-p0*(t-old[0])/(p1-p0);double ph=std::fmod(tt,500*PS);if(tt>4*NS&&initial_phase<0)initial_phase=ph;last_phase=ph;phases<<tt<<' '<<ph/PS<<' '<<unsigned(top->phase_code)<<'\n';}
        }
        while(!reads.empty()&&reads.front()<=t+1e-17){double s=reads.front();reads.pop_front();tick_pair(row,s);}
        while(!bundles.empty()&&bundles.front().when<=t+1e-17){auto b=bundles.front();bundles.pop_front();tick_control(t,b);}
        for(auto& pin:pins)pin.prune(t);
        vcd.dump(sim_fs);previous_row=std::move(row);have_previous=true;
    }
    double next_event(double now)const{
        double next=o.stop;
        if(pair_fall>now+1e-17)next=std::min(next,pair_fall);
        if(ctrl_fall>now+1e-17)next=std::min(next,ctrl_fall);
        if(!reads.empty()&&reads.front()>now+1e-17)next=std::min(next,reads.front());
        if(!bundles.empty()&&bundles.front().when>now+1e-17)next=std::min(next,bundles.front().when);
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
        if(n=="vip"||n=="vin"){*value=.9+(n=="vip"?1:-1)*.0875*b.serial(t);return 0;}
        if(n.size()>=3&&n[0]=='v'&&(n[1]=='a'||n[1]=='b'||n[1]=='f')){int bit=std::stoi(n.substr(2));if(bit>=0&&bit<8){int offset=n[1]=='a'?0:n[1]=='b'?8:16;*value=b.pins[offset+bit].at(t);return 0;}}
        *value=0;b.fail("unexpected external source "+n);return 1;
    }
    static int on_sync(double t,double* delta,double,int,int,int,void* u){auto& b=*static_cast<Bridge*>(u);double next=b.next_event(t);if(next>t+1e-17&&next<t+*delta)*delta=next-t;return 0;}
    fs::path deck(){
        std::string s=readfile(o.root/"verification/mixed_signal/tb/receiver.cir.in");
        replace_all(s,"@PROJECT_ROOT@",o.root.string());std::ostringstream stop;stop<<std::setprecision(17)<<o.stop;replace_all(s,"@STOP@",stop.str());
        std::istringstream in(s);std::string line,expanded;
        while(std::getline(in,line)){
            if(line.rfind(".include \"",0)==0){size_t end=line.find('"',10);fs::path source=line.substr(10,end-10);fs::path relative=fs::relative(source,o.root);fs::path dest=o.out/"netlist"/relative;fs::create_directories(dest.parent_path());fs::copy_file(source,dest,fs::copy_options::overwrite_existing);line=".include \""+dest.string()+"\"";}
            expanded+=line+"\n";
        }
        fs::path file=o.out/"netlist/tb.cir";std::ofstream(file)<<expanded;return file;
    }
    bool finish(){
        vcd.close();top->final();pairs.flush();controls.flush();words.flush();phases.flush();pin_events.flush();
        for(size_t i=0;i<windows.size();++i)flush_window(i);
        char name[]="time";auto* info=ngGet_Vec_Info(name);int retained=info?info->v_length:-1;
        double delta=last_phase-initial_phase;while(delta>250*PS)delta-=500*PS;while(delta<-250*PS)delta+=500*PS;
        bool full=std::abs(time_now-o.stop)<1e-15;
        bool good=full&&!fatal&&unknown_data==0&&word_errors==0&&retained==1;
        unsigned required_words=(o.hold&&o.stop<36*NS)?0:2;
        if(!o.probe)good=good&&changes>0&&(o.hold?(std::abs(delta)<PS&&pin_crossings==0):(std::abs(delta)>5*PS&&pin_crossings>0))&&payload_count>=required_words;
        std::ofstream f(o.out/"summary.json");f<<std::boolalpha<<std::setprecision(17)
          <<"{\n  \"passed\": "<<good<<",\n  \"scope\": \"live_Verilator_RTL_and_real_MOS_PI_CTLE_samples_CMOS; behavioral16UI_bundle_adapter; not_new_CML_word_bank_or_lock_time_signoff\",\n"
          <<"  \"kp_q\": "<<COSIM_KP<<",\n  \"control_hold_negative_test\": "<<o.hold<<",\n  \"probe_only\": "<<o.probe<<",\n  \"stop_s\": "<<o.stop<<",\n  \"actual_stop_s\": "<<time_now.load()<<",\n"
          <<"  \"accepted_points\": "<<points.load()<<",\n  \"ngspice_retained_time_points\": "<<retained<<",\n  \"ring_peak_points\": "<<max_ring<<",\n  \"pair_count\": "<<pair_count<<",\n  \"bundle_count\": "<<bundle_count<<",\n"
          <<"  \"invalid_bundles\": "<<invalid_bundles<<",\n  \"unknown_data_samples\": "<<unknown_data<<",\n  \"unknown_edge_samples\": "<<unknown_edge<<",\n  \"RTL_phase_changes\": "<<changes<<",\n"
          <<"  \"final_phase_code\": "<<unsigned(top->phase_code)<<",\n  \"analog_f0_pin_crossings\": "<<pin_crossings<<",\n  \"skipped_waveform_windows\": "<<skipped_windows<<",\n  \"required_payload_words\": "<<required_words<<",\n  \"measured_clock_phase_shift_ps\": "<<delta/PS<<",\n  \"payload_words\": "<<payload_count<<",\n  \"payload_errors\": "<<word_errors<<",\n"
          <<"  \"max_sample_deadline_overshoot_ps\": "<<max_read_overshoot/PS<<",\n  \"locked\": "<<bool(top->locked)<<",\n  \"aligned\": "<<bool(top->aligned)<<",\n"
          <<"  \"adc_low_v\": "<<o.vlow<<",\n  \"adc_high_v\": "<<o.vhigh<<",\n  \"read_delay_ps\": "<<o.read_delay/PS<<",\n  \"bundle_delay_ps\": "<<o.bundle_delay/PS<<",\n"
          <<"  \"driver_launch_ps\": "<<o.drive_delay/PS<<",\n  \"driver_input_slew_ps\": "<<o.slew/PS<<",\n  \"failure\": \""<<failure<<"\"\n}\n";
        std::cout<<"RESULT passed="<<good<<" pairs="<<pair_count<<" bundles="<<bundle_count<<" changes="<<changes<<" clock_shift_ps="<<delta/PS<<" payload="<<payload_count<<" errors="<<word_errors<<" retained="<<retained<<" failure="<<failure<<std::endl;
        return good;
    }
};

int main(int argc,char** argv){
 try{
    Options o;Verilated::commandArgs(argc,argv);Verilated::traceEverOn(true);
    for(int i=1;i<argc;++i){std::string k=argv[i];auto val=[&](){if(++i>=argc)throw std::runtime_error("missing argument");return std::string(argv[i]);};if(k=="--root")o.root=fs::absolute(val());else if(k=="--out")o.out=fs::absolute(val());else if(k=="--stop-ns")o.stop=std::stod(val())*NS;else if(k=="--tx-phase-ps")o.tx_phase=std::stod(val())*PS;else if(k=="--hold-controls")o.hold=true;else if(k=="--probe")o.probe=true;else throw std::runtime_error("unknown argument "+k);}
    if(o.out.empty())throw std::runtime_error("--out is required");
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
        if(wall-old_wall>=5){double current=(t-old_time)/(wall-old_wall);if(current>0)rate=rate?rate*.6+current*.4:current;double eta=rate?(o.stop-t)/rate:-1;
            std::ostringstream row;row<<std::setprecision(10)<<"{\"wall_s\":"<<wall<<",\"sim_time_s\":"<<t<<",\"UI\":"<<t/UI<<",\"percent\":"<<100*t/o.stop<<",\"eta_s\":"<<eta<<",\"rss_bytes\":"<<rss_bytes()<<",\"points\":"<<b.points.load()<<"}";b.progress<<row.str()<<'\n';b.progress.flush();std::cout<<row.str()<<std::endl;old_wall=wall;old_time=t;
        }
        if(b.fatal||wall>900){if(!b.fatal)b.fail("wall watchdog");command("bg_halt");break;}
    }
    for(int i=0;i<100&&ngSpice_running();++i)std::this_thread::sleep_for(std::chrono::milliseconds(10));
    bool good=b.finish();command("quit");return good?0:1;
 }catch(const std::exception& e){std::cerr<<"FATAL "<<e.what()<<std::endl;return 2;}
}
