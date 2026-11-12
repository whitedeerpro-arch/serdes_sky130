# RX恢复字到宿主时钟域

**字映射→字对齐→FIFO已完成独立RTL集成，尚未接入物理混合仿真。** [rx_word_host_path](../../digital/rx/rtl/rx_word_host_path.sv)消费既有32位读出顺序，训练后输出宿主字；运行中重训或溢出使当前数据纪元报错。底层[rx_async_word_fifo](../../digital/rx/rtl/rx_async_word_fifo.sv)保持字顺序，解决异步传输与有限缓存；连续频偏下的长期吞吐、空闲补偿及系统恢复仍待完成。

[首轮SKY130 HD映射时序](rx_word_host_timing.md)发现默认映射有负裕量；加入时序目标并扁平化后，TT本域setup满足假定4ns，两个SS库角仍不满足。后续比较更适合慢角的映射与结构，数字时序及物理CDC仍未收口。

## 接口和数据纪元

| 信号 | 时钟域与含义 |
|---|---|
| `w_clk` | 恢复字时钟，名义250MHz；输入为已对齐的16位字，bit0仍最早 |
| `w_data/w_valid` | 字和到达使能；仅在`w_online`之后开始有效纪元 |
| `w_ready` | 本拍有接收信用；`w_valid && w_ready`接受一个字，不能反压实际串行接收器 |
| `w_overflow` | `w_online && w_valid && !w_ready`时置位，持续到共同复位；被拒字不会覆盖未读字 |
| `r_clk` | 独立宿主时钟，由集成方提供；频率/停顿预算待确定 |
| `r_data/r_valid/r_ready` | 宿主有效/接收握手，`r_valid && r_ready`取走一个字；停顿时有效字保持稳定 |
| `r_overflow` | 写端sticky overflow经两级同步到宿主，存在检测/同步延迟；宿主须将数据流视为有缺口并处理失效/恢复 |
| `w_online/r_online` | 本域复位已同步释放，且已同步看到对端释放；不是运行时停钟检测器 |
| `arst_n` | 两域共用的异步复位请求，各自两级同步释放；会丢弃所有在途和未读字，单侧复位不支持 |

默认`DATA_WIDTH=16`、`ADDR_BITS=4`，存16字；深度为`2**ADDR_BITS`，参数至少1。输入在`w_online=0`时不接受，也不记溢出；接入时必须在偏置/时钟、字对齐及两域复位就绪后启用有效纪元。不能仅依据CDR的瞬时`locked`门控正在运行的连续字流。

溢出后模块保留已接受字的顺序，并继续标记缺口，不自行插字、删空闲或决定帧边界。系统控制须同步处理错误并按协议恢复；不能把随后仍然有效的字解释成从未丢字。共同复位前后的字属于不同纪元。

## 实现与容量边界

本地二进制指针多一位用于回卷；只跨域传Gray指针，各位两级同步。写端将next Gray与读端同步Gray最高两位取反的值比较判满，读端将next Gray与写端同步Gray比较判空。数据为双时钟写/组合读存储器，读指针只在宿主握手时更新；同步指针提供数据建立时间，但仍需工艺映射和时序验证。

读信用返回写端也有同步/寄存延迟。因此“物理上刚释放一个位置”不等于下一拍`w_ready`立即有效；深度2/4即使读端更快，也可能无法承受连续满速到达。深度16是首版测试参数，尚非宿主流控预算的最终选择。

若写入率`fw`、持续可用读出率`fr`，长期`fw > fr`时任何有限深度都会溢出。忽略同步信用延迟、控制余量和已有存量，理想容量上界为`D/(fw-fr)`；名义250MHz、远端快100/300ppm、D=16时约640/213µs。满速写入而宿主完全停读的理想空FIFO容量仅64ns。实际保证值还须扣掉已有占用、同步信用和恢复控制余量。

可行系统接口需要足够宿主吞吐和受限停顿，或由明确协议提供可删除空闲、帧间隙等频偏补偿；不得自行删除任意payload字。后续接入点为`rx_word_align16`后的恢复字流，CDR投票器继续留在恢复字域。

## 已集成的数字字路径

`rx_word_host_path`连接原`rx_word_map`、`rx_word_align16`和FIFO，默认4次训练命中、16字缓存。`phys[31:0]`与原读出lane顺序相同；`training_enable`明确属于`word_clk`域，不能直接接异步宿主控制。物理读出必须满足字时钟捕获的建立保持；模块没有虚构模拟输出有效性检测。

FIFO的`word_online`释放map/align复位，避免一端尚未就绪就开始训练。训练期间不向宿主发送payload；数据阶段不因CDR瞬时`locked`变化而丢弃字。`aligned`/`offset`属于恢复字域调试状态，不能当作已同步宿主状态。

开始payload后重新拉高训练请求会置sticky源故障，包括首个对齐`word_valid`尚待FIFO接收时的边界。源故障或FIFO溢出后停止新写，宿主可以排空此前已接收字，但`host_error`经宿主域同步后声明整个纪元有缺口；不能据仍有`host_valid`认为流完整。重训需共同复位，复位丢弃缓存后才开始新纪元。宿主错误同步器也由本域online同步释放复位。

[集成测试](../../digital/rx/tb/tb_rx_word_host_path.sv)使用独立bitstream生成物理32位输入：16个窗口起点共检查399个观察到的payload前缀字（起点0为24字，其余各25字）；每个窗口尾部未排空，不计作完整有限包验证。另覆盖宿主停顿、满错误、未读字共同复位、运行重训及首个pending字与重训同拍。默认训练参数已由集成者重跑，Icarus、Verilator和Yosys通用检查通过；[证据](../../results/catalog/rx_word_host_path.json)固定源码与工具日志。

```bash
uv run pytest -q tests/test_rx_word_host_path.py
uv run python verification/analysis/rx_word_host_review.py
```

## 已验证与剩余工作

[测试台](../../digital/rx/tb/tb_rx_async_word_fifo.sv)以独立周期/相位的时钟检查深度2/4/16：满空、连续拒收不覆盖、多个指针回卷、宿主停顿数据稳定、快/慢宿主、带未读字的共同复位、复位释放时一端停钟、运行中任一端停钟及恢复。按实际握手排队逐字比较，计数守恒区分已读、拒收和复位丢弃；写端/宿主溢出标志均检查。

三种深度均通过Icarus功能仿真、Yosys `proc/memory/opt/check`和Verilator lint。默认深度仿真1736次接受读、569次拒收、1字因复位丢弃，总2306次有效到达；拒收是有意压力场景，不是链路质量通过率。独立Terra复核未发现指针/复位握手阻塞性问题；最终增加宿主错误同步和运行时停钟场景后重新执行上述检查。[证据索引](../../results/catalog/rx_async_word_fifo.json)固定源码、工具身份、日志与完整结果。

```bash
uv run pytest -q tests/test_rx_async_fifo_rtl.py
uv run python verification/analysis/rx_async_fifo_review.py
```

待完成：物理字输出的实际建立保持/接线，宿主时钟与容量契约，overflow后的系统控制，目标库映射优化与本域时序闭合，Gray源寄存器到首级同步器的最大延迟/跨位偏斜约束、同步器放置/MTBF、复位恢复撤除及异步读存储器实现。异步时钟分组不能无意掩盖Gray总线的物理约束；RTL独立周期与固定初始相位测试不模拟亚稳态。
