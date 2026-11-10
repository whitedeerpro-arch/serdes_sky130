# 交接

先用 `summary.md` 和 `evidence.json` 的电源边界审阅数值。LDO 后续应在原生 r5/k4 拆开 VCO、四一级 buffer、CP/LF 的电源，记录每个电源和预充源的电流并作功率守恒；所有下游保留 host 供电，建立实际偏置与跨电源域接口，覆盖启动/预充、锁定、码切换、负载瞬态及45 PVT，再确定最大负载和余量。历史 native raw 没有电流向量，无法补算。

TX 的 45 点为离线时间加权，RX 新旧数字在不同窗口、偏置和 averaging 规则下，不能简单横比；旧45点绝非当前 W40 完整回归。不可将 TX/RX 台架功耗直接作为全 SerDes 功耗。`collect.py` 仅由显式 catalog 指定的 raw/deck 重建计算，无 ngspice 调用；原始记录和工作区已有文件未修改。
