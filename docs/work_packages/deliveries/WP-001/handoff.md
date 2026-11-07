# WP-001 交接

交付已有原始raw复核脚本、数据和上述结论。提取脚本由先前局部执行产生，集成者恢复交付、独立复跑并审查；未重新运行ngspice，也未修改历史结果。

复现：

```sh
uv run python verification/work_packages/wp001_pll_waveforms.py --output /tmp/serdes-review-wp001
uv run python -m serdes_flow.work_packages check WP-001
```

Reviewer检查点：实际tran/`.ic/uic`、raw终点与deck哈希、统一8–24ns窗口，以及没有屏蔽窗内坏点的3级逐沿诊断。脚本以相邻分频边沿在VCO参考周期中的距离诊断漏沿/多沿，不能用此宽松检查替代抖动预算。

剩余：自动DC、真实上电、PLL闭环、实际TX/RX接口与噪声/失配。当前工作态边界只绑定本地前端，挂接其他模块需复核新消费者身份。
