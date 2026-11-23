# LDO电容尺寸与物理候选

本测试台独立比较r4及减容候选，原r4电路与历史运行不改写。结论入口：[减容设计](../../../../docs/design/ldo_smallcap.md)，项目采用状态见[current.md](../../../../docs/status/current.md)。

`b32_h2`的LDO本体为70pF：放大器供电2kΩ/32pF、隔离栅31.25kΩ/16pF、输出4pF、参考16pF、补偿2pF/2kΩ；独立尾偏置16pF不计入70pF，也未缩减。所有电容由实际1pF MIM叶单元明确并联，不用mf缩放。候选改变的源码逐个冻结到campaign/variants下。

```bash
uv run python analog/ldo/tb/cap_sizing/run.py --prepare screen --variants r4 b32_h2 --reduced
uv run python analog/ldo/tb/cap_sizing/run.py --resume <campaign> --workers 2
uv run python analog/ldo/tb/cap_sizing/run.py --prepare pvt --variants b32_h2 --reduced
uv run python analog/ldo/tb/cap_sizing/transient.py --prepare <screen-campaign> --variants b32_h2 --profiles tt fs ss
uv run python analog/ldo/tb/cap_sizing/transient.py --resume <dynamic-campaign> --workers 2
```

每次prepare创建新目录；resume只补身份/完整性不通过的deck。DC检查完整电流轴，AC检查完整频率轴与双注入交越，瞬态检查实际终点，noise使用纯DC源并逐谱核对两条调整管电流和输出偏置。分析追加新子目录。执行失败、缺测和门槛失败分开保存。

`--reduced`显式使用器件族精简库：保持原文件顺序和参数，生成模型清单/哈希，原PDK不改。初次使用先将r4与完整库逐点对照；本轮TT、FS/ll共5条件的四组交流表逐值相同。该方法不用于MC。启动/noise默认使用完整PDK。

DC网格为MOS5×RC3×HV3×host3×温度3×负载3=1215；AC只做每模型16个边界和一个名义点，共255。复用r4每MOS/RC一次校准所得码，跨网格保持固定，不逐工况调码。规划门槛：输出±2%、20MHz抑制≥34dB；另用单向交越且PM≥60°作为局部稳定性保护带。没有新分配的噪声/阶跃门槛均为ungraded，需与实际PLL预算衔接。

动态边界是单LDO＋真实BG/拷贝：180µs电源斜坡/使能、2/10mA等效电阻启动；6mA静态上叠加0.1/1/4mA、1ns沿的人工负载阶跃；独立1kHz–199.5MHz噪声。它不含原r4启动bench额外n85支路/12pF分布/尾滤波，不把新噪声与旧不同加载谱直接比较。实际PLL数据/负载、全上电监督、MC、完整宏PEX和系统抖动分别保留。

核心PEX使用`--pex-core`绑定提取文件SHA、固定端口顺序与实际内部探针映射；原理图其他模块及输出/参考边界保持明确。只证明所测核心电容提取回灌，不等于全LDO金属RC、pad/package或PEX全角。

## 70pF局部失配

`mismatch.py`使用完整PDK的`tt_mm`/`fs_ll_mm`，不使用精简模型。每颗样本在HV3.3V/host1.8V/27°C/6mA扫全部64码，选输出最接近1.8V的码后保持，检查本工况2/6/10mA的DC及10mA的HV PSRR/双注入PM。FS检查边界为HV3.0V/host1.95V/85°C；没有跨MOS角声称相同seed就是同一颗芯片。每工况另起进程复现首样本，标量和完整AC谱均比对。

```bash
uv run python analog/ldo/tb/cap_sizing/mismatch.py --prepare --samples 16 --chunk 4 --seed 70 --profiles fs tt
uv run python analog/ldo/tb/cap_sizing/mismatch.py --resume <campaign> --workers 2
uv run python analog/ldo/tb/cap_sizing/mismatch.py --analyse <campaign>
```

campaign冻结电路、deck、源脚本和PDK身份；`mc.run_many`只续跑缺失的完整块，不改变原seed/chunk/样本数。输出先检查完整样本、有限标量及完整频率轴，再判门槛。首轮小样本用于识别偏差和余量，不作为量产良率结论；PNP无随机模型、g5直接Vth随机系数为零等盲点见[模型审计](../../../../docs/work_packages/deliveries/LDO-MODEL-20261110/summary.md)。未覆盖启动、宏PEX和实际PLL负载的随机行为。

## 第二轮：12pF和同值叠层

设计、面积与边界见[电容面积迭代](../../../../docs/design/ldo_cap_area.md)。`peripheral`为4模型/10条件短筛，包含实际FS热最差PSRR点；12pF是2×6实际单元，并非8pF量化。`stack_core70`只把核心32/16pF各一半换成MIM2，其余容量和MOS/R保持。精简库必须从实际候选/PEX取器件族的并集；本轮新MIM2已与完整库的40张AC表逐值复核。MC始终使用完整PDK。

```bash
uv run python analog/ldo/tb/cap_sizing/run.py --prepare peripheral --variants b32_h2 cas12_only stack_core70 --reduced
uv run python analog/ldo/tb/cap_sizing/run.py --prepare pvt --variants stack_core70 --reduced
uv run python analog/ldo/tb/cap_sizing/mismatch_candidate.py --prepare --variant stack_core70 --samples 8 --chunk 4 --seed 71
uv run python analog/ldo/tb/cap_sizing/mismatch_candidate.py --resume <campaign> --workers 2
uv run python verification/analysis/ldo_cap_area.py --manifest config/ldo_cap_area_evidence.json
```

新MC执行器复用已验证的校准/双注入/复现分析，但单独选择候选、冻结原始失配runner和实际源，不改变旧70pF样本身份。`peripheral_card.py`比较原/叠层1MΩ/16pF提取网表，在TT、FS/ll热、SS/hh冷加载1/5pF代理；纯DC源的AC与自身热噪声均检查完整轴，noise前后DC输出按10µV数值容差复核。它不是原生VCO门负载或PLL噪声资格；已有记录用`--analyse <campaign>`复读，不必重跑模型。
