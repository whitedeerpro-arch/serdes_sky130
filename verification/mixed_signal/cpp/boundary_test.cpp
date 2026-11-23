// Exercise the actual bridge classes without loading a SPICE circuit.
#define main mixed_application_main
#include "cosim.cpp"
#undef main
int main(int argc,char** argv){
    if(argc!=2)return 2;
    Verilated::commandArgs(argc,argv);Verilated::traceEverOn(true);
    Options o;o.out=fs::absolute(argv[1]);Bridge b(o);
    struct Test {double voltage;bool known;int bit;};
    Test tests[]={{0,true,0},{.53,true,0},{.54,true,0},{.55,false,0},
                  {.9,false,0},{1.25,false,0},{1.26,true,1},{1.8,true,1}};
    for(auto t:tests){bool known;int bit=b.decode(t.voltage,known);if(known!=t.known||(known&&bit!=t.bit))return 1;}
    Pin p;p.base=0;p.set(100*PS,20*PS,1.8);p.set(200*PS,20*PS,0);
    auto near=[](double a,double c){return std::abs(a-c)<1e-10;};
    // Bit 1 -> bit 2 of b5e3 is a falling edge centered at 2 UI.
    // Both halves of the 20 ps transition must exist and be continuous.
    for(int i=0;i<=4;++i){double t=2*UI+(i*5-10)*PS;if(!near(b.serial(t),1-i*.5))return 1;}
    if(!near(p.at(99*PS),0)||!near(p.at(100*PS),0)||!near(p.at(110*PS),.9)||!near(p.at(120*PS),1.8)||!near(p.at(210*PS),.9)||!near(p.at(220*PS),0))return 1;
    // Out-of-order trial queries must not consume future source events.
    double a=p.at(105*PS);p.at(250*PS);if(!near(a,p.at(105*PS)))return 1;
    p.prune(5*NS);if(!p.ramps.empty()||!near(p.at(5*NS),0))return 1;
    b.top->final();b.vcd.close();
    std::cout<<"PASS A/D thresholds/unknown-zone, finite NRZ edges and D/A latency/slew/pure rollback queries/history pruning"<<std::endl;
    return 0;
}
