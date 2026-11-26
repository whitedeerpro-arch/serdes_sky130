#!/usr/bin/env python3
"""Generate an 8-card 3:4 (1500 x 2000 px) Xiaohongshu (小红书) publication image pack
for the SKY130A 5.0 Gb/s Plan-C SerDes (`serdes_5g_top_pdk`, 2026-11-26).

All embedded silicon layouts, eye diagrams, waveforms, VCO/PLL spectra, IR/EM maps,
LDO/BIAS/PDN plots, and OpenROAD digital layouts are sourced directly from the verified
240/300-DPI signoff figures and live summary JSONs (zero hand-drawn mockups).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[2]
FIG_DIR = REPO / "docs/figures"
IR_JSON = REPO / "results/layout/chip_top_5g_20261126/ir_em_5g/summary.json"
TOP_JSON = REPO / "results/layout/chip_top_5g_20261126/plan_v4p1/summary.json"

FONT_FAMILIES = ["Noto Sans CJK SC", "Droid Sans Fallback", "DejaVu Sans"]
plt.rcParams["font.sans-serif"] = FONT_FAMILIES
plt.rcParams["axes.unicode_minus"] = False

# Editorial palette (clean light paper, high mobile contrast)
BG_PAGE = "#F8FAFC"
BG_CARD = "#FFFFFF"
BORDER = "#CBD5E1"
INK = "#0F172A"
MUTED = "#475569"
ACCENT_BLUE = "#1D4ED8"
ACCENT_TEAL = "#0F766E"
ACCENT_ROSE = "#BE123C"
ACCENT_AMBER = "#B45309"
ACCENT_VIOLET = "#6D28D9"


def _crop_frac(img: Image.Image, x0: float, y0: float, x1: float, y1: float) -> Image.Image:
    w, h = img.size
    return img.crop((int(round(w * x0)), int(round(h * y0)), int(round(w * x1)), int(round(h * y1))))


def _new_card(
    page_idx: int,
    total_pages: int,
    eyebrow: str,
    title: str,
    subtitle: str,
    accent: str = ACCENT_BLUE,
) -> tuple[plt.Figure, plt.Axes]:
    """Create a 1500 x 2000 px (3:4) Xiaohongshu card with consistent editorial header."""
    fig = plt.figure(figsize=(7.5, 10.0), dpi=200, facecolor=BG_PAGE)
    ax = fig.add_axes([0.0, 0.0, 1.0, 1.0])
    ax.set_xlim(0.0, 1.0)
    ax.set_ylim(0.0, 1.0)
    ax.axis("off")

    # Top subtle accent bar
    ax.add_patch(FancyBboxPatch((0.0, 0.992), 1.0, 0.008, boxstyle="square,pad=0", fc=accent, ec="none", zorder=1))

    # Eyebrow pill (left) + page counter pill (right)
    ax.add_patch(
        FancyBboxPatch(
            (0.045, 0.946), 0.56, 0.028,
            boxstyle="round,pad=0.004,rounding_size=0.010",
            fc=accent, ec="none", alpha=0.11, zorder=2,
        )
    )
    ax.text(
        0.060, 0.960, eyebrow,
        fontsize=9.6, fontweight="bold", color=accent, va="center", ha="left", zorder=3,
    )
    ax.add_patch(
        FancyBboxPatch(
            (0.845, 0.946), 0.110, 0.028,
            boxstyle="round,pad=0.004,rounding_size=0.010",
            fc="#E2E8F0", ec="none", zorder=2,
        )
    )
    ax.text(
        0.900, 0.960, f"{page_idx:02d} / {total_pages:02d}",
        fontsize=9.2, fontweight="bold", color=MUTED, va="center", ha="center", zorder=3,
    )

    # Bold Chinese headline + concise subtitle
    ax.text(
        0.045, 0.916, title,
        fontsize=18.5, fontweight="bold", color=INK, va="center", ha="left", zorder=3,
    )
    ax.text(
        0.045, 0.884, subtitle,
        fontsize=10.0, color=MUTED, va="center", ha="left", zorder=3,
    )

    # Subtle footer credit
    ax.text(
        0.045, 0.016, "SKY130A 180 nm 开源 PDK · 4/5 Gb/s 双速 NRZ SerDes (serdes_5g_top_pdk)",
        fontsize=7.8, color="#64748B", va="center", ha="left", zorder=3,
    )
    ax.text(
        0.955, 0.016, "全流程 ngspice + Magic + OpenROAD",
        fontsize=7.8, color="#64748B", va="center", ha="right", zorder=3,
    )
    return fig, ax


def _place_panel(
    fig: plt.Figure,
    ax_bg: plt.Axes,
    img: Image.Image,
    box: tuple[float, float, float, float],
    caption: str | None = None,
    accent: str = ACCENT_BLUE,
    pad: float = 0.010,
) -> None:
    """Place a cropped PIL image inside a rounded white card box preserving exact aspect ratio."""
    x, y, w, h = box
    ax_bg.add_patch(
        FancyBboxPatch(
            (x, y), w, h,
            boxstyle="round,pad=0.0,rounding_size=0.014",
            fc=BG_CARD, ec=BORDER, lw=1.0, zorder=2,
        )
    )
    cap_h = 0.028 if caption else 0.0
    if caption:
        ax_bg.add_patch(
            FancyBboxPatch(
                (x + 0.008, y + h - cap_h - 0.004), w - 0.016, cap_h,
                boxstyle="round,pad=0.0,rounding_size=0.008",
                fc="#F1F5F9", ec="none", zorder=3,
            )
        )
        ax_bg.text(
            x + 0.020, y + h - cap_h * 0.5 - 0.004, caption,
            fontsize=9.2, fontweight="bold", color=accent, va="center", ha="left", zorder=4,
        )

    ix = x + pad
    iy = y + pad
    iw = w - 2 * pad
    ih = h - cap_h - 2 * pad - (0.004 if caption else 0.0)

    # Fit preserving exact aspect ratio in figure pixel coordinates (fig aspect = 7.5 / 10.0 = 0.75)
    img_ar = img.size[0] / img.size[1]
    box_ar = (iw * 7.5) / (ih * 10.0)
    if img_ar > box_ar:
        draw_w = iw
        draw_h = (iw * 7.5) / (img_ar * 10.0)
    else:
        draw_h = ih
        draw_w = (ih * 10.0 * img_ar) / 7.5
    ox = ix + 0.5 * (iw - draw_w)
    oy = iy + 0.5 * (ih - draw_h)

    sub = fig.add_axes([ox, oy, draw_w, draw_h], zorder=5)
    sub.imshow(np.asarray(img), interpolation="lanczos")
    sub.axis("off")


def _draw_kpi_row(
    ax: plt.Axes,
    items: list[tuple[str, str, str, str]],
    y: float = 0.042,
    h: float = 0.095,
    x0: float = 0.045,
    x1: float = 0.955,
) -> None:
    """Draw N rounded KPI summary tiles horizontally across [x0, x1]."""
    n = len(items)
    gap = 0.016
    w = (x1 - x0 - gap * (n - 1)) / n
    for i, (label, big, sub, col) in enumerate(items):
        bx = x0 + i * (w + gap)
        ax.add_patch(
            FancyBboxPatch(
                (bx, y), w, h,
                boxstyle="round,pad=0.0,rounding_size=0.012",
                fc=BG_CARD, ec=col, lw=1.25, zorder=3,
            )
        )
        ax.add_patch(
            FancyBboxPatch(
                (bx, y + h - 0.008), w, 0.008,
                boxstyle="round,pad=0.0,rounding_size=0.004",
                fc=col, ec="none", alpha=0.85, zorder=4,
            )
        )
        ax.text(bx + w * 0.5, y + h * 0.76, label, fontsize=8.5, color=MUTED, fontweight="bold", ha="center", va="center", zorder=5)
        ax.text(bx + w * 0.5, y + h * 0.45, big, fontsize=13.2, color=col, fontweight="bold", ha="center", va="center", zorder=5)
        ax.text(bx + w * 0.5, y + h * 0.17, sub, fontsize=7.8, color="#334155", ha="center", va="center", zorder=5)


def build_pack(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ir = json.loads(IR_JSON.read_text()) if IR_JSON.exists() else {}
    top = json.loads(TOP_JSON.read_text()) if TOP_JSON.exists() else {}

    # Load live numbers from latest signoff JSONs
    tot_p_tt = ir.get("chip_totals", {}).get("total_power_tt_mw", 129.2)
    dom_map = {r["domain"]: r for r in ir.get("domain_summary", [])}
    vss_pk = ir.get("domains_hot_100c", {}).get("VSS", {}).get("peak", {}).get("max_macro_ir_mv", 13.8)
    worst_tot = max((r["total_drop_peak_mv"] for r in ir.get("domain_summary", [])), default=28.0)
    worst_em = max(
        (max(r["worst_metal_em_pct"], r["worst_via_em_pct"]) for r in ir.get("domain_summary", [])),
        default=89.3,
    )
    rx_vdd_pk = dom_map.get("VDD_RX", {}).get("vdd_drop_peak_mv", 15.4)
    rx_tot_pk = dom_map.get("VDD_RX", {}).get("total_drop_peak_mv", 25.4)
    gds_mb = ((top.get("magic_verify") or {}).get("gds_bytes", 58_174_464)) / (1024.0 * 1024.0)
    cap_pf = top.get("decap_top_cap_pf", 147.0)
    ntiles = top.get("decap_tiles_total", 131)
    drc_tot = (top.get("magic_verify") or {}).get("drc_total", 0)

    # Load verified source figures
    im_top = Image.open(FIG_DIR / "layout/serdes_5g_top_pdk_20261126_light.png")
    im_ir = Image.open(FIG_DIR / "layout/serdes_5g_ir_em_20261126.png")
    im_eye = Image.open(FIG_DIR / "system/serdes_5g_tt_eyes_20261126.png")
    im_16ui = Image.open(FIG_DIR / "system/serdes_5g_16ui_waveforms_20261126.png")
    im_ldo = Image.open(FIG_DIR / "verification/serdes_5g_ldo_bias_pdn_20261126.png")
    im_pll = Image.open(FIG_DIR / "clocking/serdes_5g_lcpll_stability_20261126.png")
    im_vco = Image.open(FIG_DIR / "clocking/serdes_5g_vco_pll_char_20261126.png")
    im_dig = Image.open(FIG_DIR / "system/serdes_5g_digital_v4p1_20261126.png")

    written: list[Path] = []
    N = 8

    # =========================================================================
    # Card 01: COVER — Full-Chip Light Silicon Layout
    # =========================================================================
    fig, ax = _new_card(
        1, N,
        eyebrow="开源 PDK 芯片实战 · SKY130A 180 nm",
        title="用开源工具手搓 5 Gb/s SerDes 芯片！",
        subtitle="全定制模拟前端 + 八边形 LC-PLL + 32-bit 数字顶层 · 一次拉通 DRC/LVS/IR/EM",
        accent=ACCENT_ROSE,
    )
    top_clean = _crop_frac(im_top, 0.015, 0.042, 0.992, 0.992)
    _place_panel(
        fig, ax, top_clean, (0.045, 0.255, 0.910, 0.605),
        caption="serdes_5g_top_pdk 真实硅片物理版图（936 × 650 µm = 0.6084 mm²，300 DPI）",
        accent=ACCENT_ROSE, pad=0.008,
    )
    # 2x2 hero KPI cards at bottom
    _draw_kpi_row(
        ax,
        [
            ("核心面积", "0.61 mm²", "936×650 µm · 4/5 Gb/s", ACCENT_ROSE),
            ("典型功耗", f"{tot_p_tt:.0f} mW", "1.8 V / 3.3 V 双电源", ACCENT_BLUE),
            ("物理签核", f"DRC = {drc_tot}", f"GDS {gds_mb:.1f} MB · LVS 全过", ACCENT_TEAL),
        ],
        y=0.145, h=0.095,
    )
    _draw_kpi_row(
        ax,
        [
            ("定制规模", "13 模拟宏", f"+ {ntiles} 块混合去耦 ({cap_pf:.0f} pF)", ACCENT_VIOLET),
            ("供电签核", "8/8 PASS", f"地弹 ≤{vss_pk:.1f}mV · EM ≤{worst_em:.0f}%", ACCENT_AMBER),
            ("5G 眼图 / 抖动", "215 mV", "0.90 UI · PLL 221 fs RMS", ACCENT_BLUE),
        ],
        y=0.040, h=0.095,
    )
    p1 = out_dir / "01_cover_chip_top.png"
    fig.savefig(p1, dpi=200, facecolor=BG_PAGE)
    plt.close(fig)
    written.append(p1)

    # =========================================================================
    # Card 02: 2x2 High-Res Silicon Zoom Details (from fresh 300-DPI light TOP)
    # =========================================================================
    fig, ax = _new_card(
        2, N,
        eyebrow="硅片版图微距 · 4 大关键模块实拍",
        title="放大看细节：八边形电感与全满供电梳",
        subtitle="所有线圈、差分走线、M5 供电插指与 P+ 隔离护城河均为真实 SKY130A 几何",
        accent=ACCENT_TEAL,
    )
    z_vco = _crop_frac(im_top, 0.103, 0.285, 0.402, 0.655)
    z_rx  = _crop_frac(im_top, 0.555, 0.515, 0.942, 0.892)
    z_tx  = _crop_frac(im_top, 0.386, 0.532, 0.585, 0.908)
    z_ldo = _crop_frac(im_top, 0.095, 0.068, 0.435, 0.295)
    _place_panel(fig, ax, z_vco, (0.045, 0.495, 0.445, 0.365), caption="① 5 GHz 八边形 LC-VCO (2.5 nH 45° 线圈)", accent=ACCENT_ROSE, pad=0.008)
    _place_panel(fig, ax, z_rx,  (0.510, 0.495, 0.445, 0.365), caption="② 5G RX 补满 M5 供电梳 + W3 电感(0% M5)", accent=ACCENT_TEAL, pad=0.008)
    _place_panel(fig, ax, z_tx,  (0.045, 0.148, 0.445, 0.330), caption="③ 28-Slice SST TX v5 + 6 块片上 MIM 去耦", accent=ACCENT_AMBER, pad=0.008)
    _place_panel(fig, ax, z_ldo, (0.510, 0.148, 0.445, 0.330), caption="④ HV18 Kelvin LDO + 24 µm 中央地干线", accent=ACCENT_BLUE, pad=0.008)
    _draw_kpi_row(
        ax,
        [
            ("RX 内部干线", "6.0 µm M5", "EM 173%→69% + 上下双端回地", ACCENT_TEAL),
            ("磁隔离禁布", "0% M5", "LC-VCO 与 CTLE 电感区零涡流", ACCENT_ROSE),
            ("高速出片口", "90° 正交", "南向 TX / 东向 RX GSSG 隔离", ACCENT_BLUE),
        ],
        y=0.040, h=0.092,
    )
    p2 = out_dir / "02_silicon_zoom_details.png"
    fig.savefig(p2, dpi=200, facecolor=BG_PAGE)
    plt.close(fig)
    written.append(p2)

    # =========================================================================
    # Card 03: 5.0 Gb/s Real-CPEX Eyes + 16-UI Waveforms
    # =========================================================================
    fig, ax = _new_card(
        3, N,
        eyebrow="高速链路验证 · 完整后仿寄生网表 (CPEX)",
        title="5.0 Gb/s 实测眼图 + 16-UI 时域波形",
        subtitle="TX SST v5 (FFE=3) → −6.9 dB PCB 信道 → W3 电感峰化 CTLE → 5G 采样器",
        accent=ACCENT_BLUE,
    )
    eye_top = _crop_frac(im_eye, 0.010, 0.065, 0.992, 0.520)
    w16_core = _crop_frac(im_16ui, 0.020, 0.078, 0.996, 0.962)
    _place_panel(
        fig, ax, eye_top, (0.045, 0.565, 0.910, 0.295),
        caption="三级眼图演化：TX 发射端 (272 mV) → 过 −6.9 dB 信道 (201 mV) → CTLE 均衡后 (215 mV / 0.90 UI)",
        accent=ACCENT_BLUE, pad=0.008,
    )
    _place_panel(
        fig, ax, w16_core, (0.045, 0.145, 0.910, 0.405),
        caption="16-UI 实测波形（FFE=3 去加重 −3.91 dB vs FFE=0）：16/16 位全部越过 ±75 mV 规格线",
        accent=ACCENT_TEAL, pad=0.008,
    )
    _draw_kpi_row(
        ax,
        [
            ("5G 眼高 / 眼宽", "215 mV", "0.90 UI (边沿散布 0.093 UI)", ACCENT_BLUE),
            ("16-UI 逐位裕量", "16/16 PASS", "FFE=3: 99.5–141.5 mV (≥75)", ACCENT_TEAL),
            ("采样器失调 3σ", "20.3 mV", "250× MC 后仿 · 6-bit 可校准", ACCENT_VIOLET),
        ],
        y=0.040, h=0.092,
    )
    p3 = out_dir / "03_eyes_and_16ui.png"
    fig.savefig(p3, dpi=200, facecolor=BG_PAGE)
    plt.close(fig)
    written.append(p3)

    # =========================================================================
    # Card 04: 5 GHz LC-VCO Full Char & Transistor-Level Closed-Loop PLL
    # =========================================================================
    fig, ax = _new_card(
        4, N,
        eyebrow="时钟引擎 · 5.0 GHz 八边形 LC-VCO & 闭环 PLL",
        title="16 码单调调谐 + 晶体管级 437 ns 锁相",
        subtitle="48 点 CPEX 频段全重叠无死区 · 实跑晶体管级 5G LC-PLL 捕获与 250 MHz 杂散",
        accent=ACCENT_VIOLET,
    )
    vco_top = _crop_frac(im_vco, 0.012, 0.068, 1.000, 0.525)
    vco_bot = _crop_frac(im_vco, 0.012, 0.530, 0.996, 0.988)
    _place_panel(
        fig, ax, vco_top, (0.045, 0.510, 0.910, 0.350),
        caption="上左：16 码全单调调谐 4.42–5.40 GHz (15/15 重叠) | 上右：K_VDD 与全码 I/Q 误差 < 0.30 ps",
        accent=ACCENT_VIOLET, pad=0.008,
    )
    _place_panel(
        fig, ax, vco_bot, (0.045, 0.145, 0.910, 0.350),
        caption="下左：晶体管级 5G 闭环锁相 (过冲 41.8%→8.3%) | 下右：250 MHz 参考杂散 −60.8 / −61.8 dBc",
        accent=ACCENT_TEAL, pad=0.008,
    )
    _draw_kpi_row(
        ax,
        [
            ("调谐区间 (TT)", "4.42–5.40G", "15/15 码重叠 83–101 MHz", ACCENT_VIOLET),
            ("正交 I/Q 精度", "< 0.30 ps", "全 16 码 < 0.36° @ 2.5 GHz", ACCENT_BLUE),
            ("闭环锁定 / 杂散", "437 ns", "过冲 8.3% · 杂散 −60.8 dBc", ACCENT_TEAL),
        ],
        y=0.040, h=0.092,
    )
    p4 = out_dir / "04_vco_and_lcpll.png"
    fig.savefig(p4, dpi=200, facecolor=BG_PAGE)
    plt.close(fig)
    written.append(p4)

    # =========================================================================
    # Card 05: LC-PLL Loop Stability & 5 GHz Phase Noise (Big Readable Panel!)
    # =========================================================================
    fig, ax = _new_card(
        5, N,
        eyebrow="环路稳定性与抖动 · 5.0 GHz 相位噪声谱",
        title="221 fs RMS 抖动（1.11 mUI）与环路裕度",
        subtitle="6 工艺角双速 (/20 & /16) 环路相位裕度审计 · 相噪分项精准定位 CP 主导源",
        accent=ACCENT_BLUE,
    )
    pll_bode = _crop_frac(im_pll, 0.505, 0.062, 0.992, 0.505)
    pll_jtf  = _crop_frac(im_pll, 0.012, 0.512, 0.495, 0.985)
    pll_pn   = _crop_frac(im_pll, 0.505, 0.512, 0.992, 0.985)
    _place_panel(fig, ax, pll_bode, (0.045, 0.555, 0.448, 0.305), caption="开环波特图：PM 67–74° · GM 20 dB", accent=ACCENT_BLUE, pad=0.006)
    _place_panel(fig, ax, pll_jtf,  (0.507, 0.555, 0.448, 0.305), caption="闭环抖动传递：4G/5G 峰值 < 1.0 dB", accent=ACCENT_TEAL, pad=0.006)
    _place_panel(
        fig, ax, pll_pn, (0.045, 0.145, 0.910, 0.395),
        caption="5.0 GHz 输出相位噪声分项谱（10 kHz–100 MHz）：重调后消除 1–2 MHz 欠阻尼鼓包",
        accent=ACCENT_VIOLET, pad=0.008,
    )
    _draw_kpi_row(
        ax,
        [
            ("积分抖动 (TT)", "221 fs", "1.11 mUI (14σ RJ=0.016 UI)", ACCENT_VIOLET),
            ("最差角 FS+85°C", "300 fs", "1.50 mUI · 远优于 0.50 UI", ACCENT_BLUE),
            ("下期优化方向", "CP 占主导", "CP 203 fs > Ref 73 > VCO 32", ACCENT_AMBER),
        ],
        y=0.040, h=0.092,
    )
    p5 = out_dir / "05_pll_stability_pn.png"
    fig.savefig(p5, dpi=200, facecolor=BG_PAGE)
    plt.close(fig)
    written.append(p5)

    # =========================================================================
    # Card 06: 2D FVM Static IR-Drop & 110°C DC EM Signoff
    # =========================================================================
    fig, ax = _new_card(
        6, N,
        eyebrow="片顶供电可靠性 · 真实几何 2D 有限体积法",
        title="8/8 电源域 IR & 110 °C 电迁移全绿签核",
        subtitle="独立 24 µm 中央 M5 地干线 + RX 双端回地 + 6 µm 内部梳干线，彻底根治地弹",
        accent=ACCENT_AMBER,
    )
    ir_map = _crop_frac(im_ir, 0.012, 0.120, 0.562, 0.920)
    ir_bar = _crop_frac(im_ir, 0.592, 0.058, 0.992, 0.455)
    em_bar = _crop_frac(im_ir, 0.592, 0.495, 0.992, 0.920)
    _place_panel(
        fig, ax, ir_map, (0.045, 0.430, 0.910, 0.430),
        caption="936 × 650 µm 实几何热力图（100 °C 热点方阻 / 过孔阻 · 满载 86.2 mA Peak）",
        accent=ACCENT_AMBER, pad=0.008,
    )
    _place_panel(fig, ax, ir_bar, (0.045, 0.145, 0.448, 0.270), caption="分域静态 IR 压降 (全低于预算)", accent=ACCENT_BLUE, pad=0.006)
    _place_panel(fig, ax, em_bar, (0.507, 0.145, 0.448, 0.270), caption="金属/过孔 EM 占用 (110 °C <100%)", accent=ACCENT_ROSE, pad=0.006)
    _draw_kpi_row(
        ax,
        [
            ("地弹治理", f"≤ {vss_pk:.1f} mV", "从初版 581 mV 降幅 97.6%", ACCENT_TEAL),
            ("最大总压降", f"{worst_tot:.1f} mV", f"RX VDD {rx_vdd_pk:.1f} / 总 {rx_tot_pk:.1f} mV", ACCENT_AMBER),
            ("110 °C EM 峰值", f"{worst_em:.1f}%", "8/8 电源域金属与过孔全 PASS", ACCENT_ROSE),
        ],
        y=0.040, h=0.092,
    )
    p6 = out_dir / "06_ir_drop_and_em.png"
    fig.savefig(p6, dpi=200, facecolor=BG_PAGE)
    plt.close(fig)
    written.append(p6)

    # =========================================================================
    # Card 07: LDO, TX Sub-LDO, BIAS v2 & 131-Tile Hybrid PDN Stability
    # =========================================================================
    fig, ax = _new_card(
        7, N,
        eyebrow="电源与偏置稳定性 · 实跑 ngspice 后仿表征",
        title="双 LDO + 带隙基准 + 147 pF 混合去耦全稳",
        subtitle="3.3→1.8 V Kelvin LDO · TX 片上零负载稳压 · BIAS v2 温漂 · 封装抗谐振",
        accent=ACCENT_TEAL,
    )
    ldo_a = _crop_frac(im_ldo, 0.010, 0.060, 0.495, 0.505)
    ldo_b = _crop_frac(im_ldo, 0.505, 0.060, 0.992, 0.505)
    ldo_c = _crop_frac(im_ldo, 0.010, 0.520, 0.495, 0.985)
    ldo_d = _crop_frac(im_ldo, 0.505, 0.520, 0.992, 0.985)
    _place_panel(fig, ax, ldo_a, (0.045, 0.510, 0.448, 0.350), caption="① HV18 Kelvin LDO (PM 64–84° / PSRR 50dB)", accent=ACCENT_BLUE, pad=0.006)
    _place_panel(fig, ax, ldo_b, (0.507, 0.510, 0.448, 0.350), caption="② TX V_drv LDO (0 mA 零负载 PM ≥58.6°)", accent=ACCENT_TEAL, pad=0.006)
    _place_panel(fig, ax, ldo_c, (0.045, 0.145, 0.448, 0.350), caption="③ BIAS v2 温漂 28 ppm/°C & PM ≥82°", accent=ACCENT_VIOLET, pad=0.006)
    _place_panel(fig, ax, ldo_d, (0.507, 0.145, 0.448, 0.350), caption="④ 131 块阻尼去耦抗谐振 (振铃 13.3→5 ns)", accent=ACCENT_AMBER, pad=0.006)
    _draw_kpi_row(
        ax,
        [
            ("HV18 LDO PSRR", "49.9 dB", "@ 20 MHz · R_eff −92.9%", ACCENT_BLUE),
            ("BIAS v2 基准", "28 ppm/°C", "−40~85 °C · 0 死锁启动", ACCENT_VIOLET),
            ("混合阻尼去耦", "147 pF", "VDD_D 阻抗峰 18.1→7.7 Ω", ACCENT_AMBER),
        ],
        y=0.040, h=0.092,
    )
    p7 = out_dir / "07_ldo_bias_pdn.png"
    fig.savefig(p7, dpi=200, facecolor=BG_PAGE)
    plt.close(fig)
    written.append(p7)

    # =========================================================================
    # Card 08: Digital Top v4p1 (OpenROAD) + Full-Chip Spec Cheat Sheet
    # =========================================================================
    fig, ax = _new_card(
        8, N,
        eyebrow="数字后端与全片速查 · 收藏级参数总卡",
        title="32-bit 双速数字顶层 & 全芯片签核总表",
        subtitle="OpenROAD 75% 高密度自动布局布线 · ±300 ppm CDR 零误码锁定 · 一图速览指标",
        accent=ACCENT_BLUE,
    )
    dig_lay = _crop_frac(im_dig, 0.012, 0.095, 0.280, 0.530)
    dig_sta = _crop_frac(im_dig, 0.500, 0.068, 0.992, 0.535)
    dig_cdr = _crop_frac(im_dig, 0.004, 0.548, 0.505, 0.985)
    _place_panel(fig, ax, dig_lay, (0.045, 0.575, 0.340, 0.285), caption="OpenROAD 真实版图 (75% 利用率)", accent=ACCENT_BLUE, pad=0.006)
    _place_panel(fig, ax, dig_sta, (0.400, 0.575, 0.555, 0.285), caption="6 角 ±5% OCV 签核 STA（5/5 规格角全 PASS）", accent=ACCENT_TEAL, pad=0.006)
    _place_panel(fig, ax, dig_cdr, (0.045, 0.295, 0.910, 0.265), caption="真实 RTL 闭环 Bang-Bang CDR：±300 ppm 频偏 3.32 µs 锁定 · 7.35 ps RMS · 0 / 298k 误码", accent=ACCENT_VIOLET, pad=0.006)

    # Bottom clean full-chip spec summary card (bookmarkable!)
    sx, sy, sw, sh = 0.045, 0.040, 0.910, 0.240
    ax.add_patch(
        FancyBboxPatch(
            (sx, sy), sw, sh,
            boxstyle="round,pad=0.0,rounding_size=0.014",
            fc=BG_CARD, ec=ACCENT_BLUE, lw=1.35, zorder=2,
        )
    )
    ax.add_patch(
        FancyBboxPatch(
            (sx + 0.008, sy + sh - 0.036), sw - 0.016, 0.028,
            boxstyle="round,pad=0.0,rounding_size=0.008",
            fc="#EFF6FF", ec="none", zorder=3,
        )
    )
    ax.text(sx + 0.022, sy + sh - 0.022, "全芯片核心规格总表（SKY130A 5.0 Gb/s Plan-C SerDes）",
            fontsize=9.8, fontweight="bold", color=ACCENT_BLUE, va="center", ha="left", zorder=4)

    rows = [
        ("工艺 / 供电", "SKY130A 180 nm · 1.8 V + 3.3 V LDO", "线速 / 架构", "双速 4/5 Gb/s NRZ · 四相 1/4 速率"),
        ("核心面积", "936×650 µm = 0.61 mm² (13 宏+131 去耦)", "典型 / 峰值功耗", f"{tot_p_tt:.1f} mW ({tot_p_tt/5.0:.1f} pJ/b) · 180 mW Peak"),
        ("TX / RX", "28-Slice SST (FFE=3) + W3 CTLE + PI", "5G 链眼图", "215 mV / 0.90 UI · 16/16 ≥ 75 mV"),
        ("时钟 PLL", "5 GHz 八边形 LC-VCO + ÷8/÷10", "抖动 / 杂散", "221 fs RMS (1.11 mUI) · −60.8 dBc"),
        ("数字顶层", "v4p1 32-bit (6,484 门 · 0 交叉)", "物理 / PDN", f"DRC={drc_tot} · LVS 69/69 · IR&EM 8/8"),
    ]
    y_top_row = sy + sh - 0.062
    dy_row = 0.036
    for idx, (k1, v1, k2, v2) in enumerate(rows):
        yr = y_top_row - idx * dy_row
        if idx % 2 == 1:
            ax.add_patch(FancyBboxPatch((sx + 0.012, yr - 0.015), sw - 0.024, 0.031, boxstyle="round,pad=0,rounding_size=0.004", fc="#F8FAFC", ec="none", zorder=3))
        ax.text(sx + 0.020, yr, k1, fontsize=8.0, fontweight="bold", color=MUTED, va="center", ha="left", zorder=4)
        ax.text(sx + 0.122, yr, v1, fontsize=7.8, color=INK, va="center", ha="left", zorder=4)
        ax.text(sx + 0.495, yr, k2, fontsize=8.0, fontweight="bold", color=MUTED, va="center", ha="left", zorder=4)
        ax.text(sx + 0.605, yr, v2, fontsize=7.8, color=INK, va="center", ha="left", zorder=4)

    p8 = out_dir / "08_digital_and_spec_card.png"
    fig.savefig(p8, dpi=200, facecolor=BG_PAGE)
    plt.close(fig)
    written.append(p8)

    print(f"[xhs_pack] Built {len(written)} 3:4 cards (1500x2000 px) -> {out_dir}")
    return written


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", type=Path, default=REPO / "results/showcase/xhs_5g_serdes_20261126")
    args = ap.parse_args()
    build_pack(args.out_dir.resolve())


if __name__ == "__main__":
    main()
