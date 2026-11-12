# 完整参考环中的电阻串候选

**测试台和离线拓扑检查已完成，电气运行尚未启动。** [宽电阻卡](wide_load_planning.md)的受控电压电阻串只能比较R比值；本卡保留带隙、V→I环、真实trim MOS和镜像，核对改参考串后实际电流及各段压降。它是独立局部对照，未改变生产DUT或采用修订。

## 实验边界

三种实现共用理想1.8V电源，彼此没有信号/偏置连接：原通用参考串、固定1p41主电阻单段、固定1p41主电阻八段。每种覆盖trim 0/14/15/16/31，均保留五只原实际旁路MOS；固定分支只替换112kΩ主电阻和780/1560/3120/6240/12480Ω五段，其他带隙电阻维持原通用卡，放大器Rz仍为原理想元件。

每组使用完整当前bandgap及2pF V→I补偿、5pF Vbg电容；四个输出分别钳位0.7V，另接实际n85 PMOS拷贝和5/0.5µm NMOS二极管/5pF去耦。保存Vbg、s、rt1…rt5、vg/vgi、vbias、四输出电流和n85支路电流。该负载不是完整TX，也不等于其尾电流或摆幅。

15份独立电路合并一个deck，在TT模型下只改变−40/27/85°C，预计45个模式/码/温度组合；**不是MOS45点资格**。每份有独立名字、trim常数和nodeset。nodeset用于选择既有工作分支；OP不证明上电可达性、稳定性或噪声。

## 几何和证据身份

先用独立短deck校准原六个通用参考电阻，严格使用原`w=1, l=(R−378)/317`；780Ω原段不能套用通用负载转换器的w=2近似。固定1p41尺寸由宽卡实测的有符号曲线求解，只在0.5–512µm校准域内取0.01µm网格。八段主电阻各自匹配原主电阻实际值的1/8，所有串段都是独立实例。

引用宽卡明确验证的模型副本，原PDK不改。准备目录固定脚本、原电路、模型身份、宽卡数据、工具/配置及ngspice初始化文件；候选另存副本，三个模式的子电路名字隔离。按deck续跑，只接受完整有限标量、正确执行身份与deck哈希；运行输出和分析只追加。

集成者review后补存vg与初始化配置身份，当前准备目录为`results/analog/common/bias/physical_reference_card/20261112T054945.997244Z_a179ce18`。更早`20261112T054802.675317Z_ce4d74de`仅准备、未运行，不继续使用其旧输入身份。

## 执行与下一步

[运行器](../../analog/common/bias/tb/physical_reference_card/run.py)与[离线测试](../../tests/test_physical_reference_card.py)已交付：5项检查覆盖实际w1校准、六段/五开关连接、八段主串、跨case名字与节点隔离、三次OP及45个独立输出；集成者已重跑。单worker，每次开NG前检查全局小于4；尚待名额。

```bash
uv run pytest -q tests/test_physical_reference_card.py
uv run python analog/common/bias/tb/physical_reference_card/run.py --resume results/analog/common/bias/physical_reference_card/20261112T054945.997244Z_a179ce18
```

运行后先检查实际工作分支、镜像电流、V→I误差、trim单调性及各段/开关压降，再与受控R-only代理比较。随后才按差异扩压力角、供电/RC、启动及必要失配/噪声；最终需接实际负载，不能据本卡先宣布新参考或TX通过。
