# 当前r6原生闭环

主入口为 `campaign.py`，复用 `run.py` 的原电路构造。设计侧PLL、LDO和BG采用源码均不改；`ext`用理想quiet电源和真实共享BG/偏置，支持在版图完成前做原理图级闭环检查。参考为直接进入PFD的理想250 MHz，带预充、初值与分频kick，不代表焊盘参考路径或从零启动。

本轮修复旧入口工况目录的 `Path + str` 错误，并增加固定输入续跑。准备时保存四/五bit版本依赖的具体身份、映射表、项目源、改写电阻副本、deck、PDK/标准单元库哈希；运行只读取准备好的deck，恢复不重新选码或生成DUT。改变终点/工况/预充值使用新campaign。

```bash
uv run python analog/pll/top/tb/native_r6/campaign.py --prepare \
  --map results/analog/pll/vco/r6/map_20261112T062237Z/table.json \
  --points tt_v1800_t27:tt --variants ext --stop 1e-7

uv run python analog/pll/top/tb/native_r6/campaign.py --check results/analog/pll/top/native_r6/<run_id>
uv run python analog/pll/top/tb/native_r6/campaign.py --resume results/analog/pll/top/native_r6/<run_id> --workers 1 --timeout 1200
uv run python analog/pll/top/tb/native_r6/campaign.py --analyse results/analog/pll/top/native_r6/<run_id>
```

每个工况先做独立1 ns冒烟，保留冒烟deck/日志/波形；之后跑到声明终点。`--smoke-only`只做冒烟。先登记、查全机进程，本任务≤2worker，全机≤4。完成判定要求执行无错、原deck一致、全部探针、有限数据及实际瞬态终点；缺测或超时另存，不拿截断波形补作完成。自动分析每次追加新目录。

100 ns仅为预充释放后短窗。项目锁定工程判据在[合同](../../../../../verification/contracts/pll_lock_screen.toml)：32参考周期窗口、步进8周期、频差≤100ppm、展开相位变化≤20ps、记录末尾持续≥320ns。旧16周期均频/末60沿读数保留为诊断；项目评分由公共 `pll_lock.screen` 给出。短窗不能因“最后几沿静止”而通过。新评分与旧r5完整波形的离线对照见[主线复核](../../../../../docs/design/r6_mainline_review.md)。

`campaign.py` 的 `metrics.locked_at_end` 仍是16周期诊断字段；释放M2对应工作点前运行 `verification/analysis/r6_lock_confirmation.py --native-summary <explicit_summary>` 导出，以其中的 `engineering_lock` 为项目评分。两种读数不互相覆盖，保留实际测量身份。

下一层验证须保存较长终点，先TT，再补FS低压热hh、SS低压冷hh、SF低压冷ll；按实测成本设置逐工况timeout。不要将本轮100 ns短窗原目录改成1.2 µs。M1对应点成立后接当前完整TX，M4需当前r6控制导纳、噪声器件与工作点校准；详见主线复核中的依赖与边界。


## 持续锁定记录

当前续做评分及实际输入见[持续锁定报告](../../../../../docs/design/r6_lock_confirmation.md)，导出器为 `verification/analysis/r6_lock_confirmation.py`。600ns记录末频率已接近2GHz，但持续合格288ns不足320ns，不能释放M1。800ns使用独立campaign、相同DUT/4ps步长重算，现已通过TT/ext点（持续480ns）；小时级任务显式使用`--timeout 9000`，不沿用上方100ns例子的1200s。

长任务可用`setsid nohup uv run python … --resume <explicit_campaign> --workers 1 --timeout 9000 > <campaign>/driver.log 2>&1 < /dev/null &`与交互会话分离，并保留启动命令、PID与持久日志。中断后仍查实际NG进程，再按同一campaign续跑缺失工况；不把没有execution/raw的中断attempt写成电路失败，也不覆盖旧attempt。健康检查用`serdes_flow.watch`，是否通过仍由实际终点和工程评分决定。
