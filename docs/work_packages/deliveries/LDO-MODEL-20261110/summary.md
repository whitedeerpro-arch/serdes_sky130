# LDO PDK 局部失配与电阻噪声核对

**结论：三种 HV MOS 的模型源码都含非零局部随机项，但 g5 NMOS／PMOS 的直接 Vth 随机系数为零；MIM 含非零局部随机项。现有 `mc.deck` 是通用重采样执行器，不会自动把当前 LDO 的 `tt` 变成 `tt_mm`，不能未经新测试台与抽样验证就直接宣称 LDO MC 覆盖完整。** 它们能否在本 LDO 具体尺寸与安装的 ngspice 版本下实际产生独立有效样本尚未通过仿真验证；不把静态阅读当作实测。

本次只读的 PDK 为 `config/pdk.toml` 记录的 sky130A，安装 ID `c6d73a35f524070e85faff4a6a9eef49553ebc2b`。路径、关键行及 SHA-256 见 [evidence.json](evidence.json)。

## 包含链及器件

`libs.tech/ngspice/sky130.lib.spice:342–353` 的 `tt_mm` 设 `mc_mm_switch=1`、`mc_pr_switch=0`，载入 `corners/tt.spice`；普通 `tt:17–27` 则两开关均为零。TT 角文件第 10–11、19–23 行分别引入三种器件的 TT corner 与 mismatch 系数；TT corner 再引入器件模型。`corners/tt.spice` → `all.spice:58,70` → MIM 和线性器件模型。常规 `tt`、`ss` 等全局角是固定模型截面，`*_mm` 是在所选固定角上加局部失配；`mc` 节 `mc_mm_switch=0, mc_pr_switch=1` 使用全局统计，不等于局部 MC，也不是两者同时开启。

| 器件 | 静态源码可证实的局部项 | 关键限制 |
|---|---|---|
| `nfet_05v0_nvt` | `vth0_slope=0.0012`、`voff=0.0035`、`nfactor=0.02`；toxe slope 亦非零。模型 `vth0` 等用开关乘 `AGAUSS(0,1,1)/sqrt(l*w*mult)`。 | 局部阈值项存在；具体 bin 与样本独立性还需实际执行确认。 |
| `nfet_g5v0d10v5` | toxe slope 非零；`voff_slope=0.13`、`nfactor_slope=0.12`；TT 模型同样乘开关、随机数和几何因子。 | `vth0_slope=0`，直接 Vth 随机项为零；不能称有直接阈值失配覆盖。 |
| `pfet_g5v0d10v5` | toxe slope 非零；`voff_slope=0.009`、`nfactor_slope=0.02`；TT 模型同样存在局部随机公式。 | `vth0_slope=0`，直接 Vth 随机项为零。 |
| `cap_mim_m3_1` | `czero` 中 `MC_MM_SWITCH*AGAUSS(0,1,1)*0.01*2.8*(carea+cperim)/sqrt(wc*lc*mf)`。 | `mf` 仅进入随机项分母，并不乘名义电容；多个实际电容应显式实例化。LDO 当前补偿电容是否采用此器件由实际 deck 决定。 |

MOS 子电路第 30–33 行声明 `w,l,nf,mult`，把 `w,l,nf` 传给内部 MOS；随机公式用 `sqrt(l*w*mult)`，没有独立 `nf` 因子。LDO 使用的总宽 W 和 `nf` 应按该 wrapper 解释；源码不支持把同一实例当成 `nf` 个独立随机抽样。不同实例／参数的随机独立性、实际 bin 与相关性需针对 `mc_source` 做小样本验证。`dvt0/dvt1` 是 BSIM 模型参数，名称本身不证明有随机失配。

`src/serdes_flow/mc.py:4–16,45–73` 用 `setseed`、先丢弃一次初始 draw 的 `mc_source` 和逐样本再 `mc_source`。使用前须构造正确 `*_mm` 模型 deck、冻结输入身份并确认多个实例的样本变化与 seed 重现；若考虑全局与局部联合统计，须另设计并验证，不能把单独角扫描或 `mc` 直接当联合 MC。

## 高阻 poly 热噪声：已由实测修正

此前仅按源码静态推断 `res_high_po` 不产生热噪声是不正确的。源模型的 `rhead_model` 与 `rbody_model` 确实标有 `isnoisy=0`，寄生子电路也仅含两只电容；但 ngspice 47 实测 (`results/analog/common/ldo/resistor_noise_check/20261110T111240.488278Z/summary.json`)日志显示 `isnoisy` 参数不识别并被忽略，普通 `high_po` 的电阻噪声实际存在。此前发送的“不可视为包含电阻热噪声”结论已由此修正。

TT、27 °C 的独立测试：理想 1 kΩ 的等效热噪声电阻为 999.9997 Ω；`high_po` 的 1 kΩ 附近器件为 1012.68 Ω；行为电阻主体的 `xhigh_po` 名义约 1 MΩ，但等效仅 159.75 Ω；r4 中 32 个约 31.25 kΩ `high_po` 串联的实例等效 1.00069 MΩ。测试台、raw、日志、模型与快照哈希记录在 evidence 中；该结果是当前安装 PDK 和 ngspice 47 的特定测试，不能外推为完整 LDO 噪声或其他模拟器的验证。

本审计未自行运行仿真；电阻噪声引用上述既有实测，没有判断完整 LDO 的失配、噪声或良率。
