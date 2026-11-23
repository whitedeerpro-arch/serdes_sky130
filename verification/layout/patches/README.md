# Magic 电容节点修复

本机 GUI 仍是原 AppImage；批量工作使用 `config/tools.toml` 的 `layout.magic_batch`，安装在 `~/.local/opt/magic-8.3.685-capfix/`，不覆盖旧工具。

基底为上游 tag `8.3.685`，commit `bed8d4ff84333767aa923d469d339cd05c56a00a`。补丁只将两处 `spcdevResPi` 限定为 `DEV_RSUBCKT`：层级输出的 `ext2hier.c` 以及平铺输出的 `ext2spice.c`。原代码对MIM顶板或MOS栅也执行电阻体的π分配，误将对地电容移到源漏；仅修其中一路不够。

重建：取得该tag、`git apply magic-8.3.685-capacitance-net.patch`，按上游INSTALL配置Tcl批量版本并安装到独立prefix。通常需Tcl/Tk/X11开发头。此机使用AppImage附带的Tcl头/库，临时下载解包X11头到`/tmp/serdes_magic_capfix_sdk`；configure为`--without-x --without-tk --without-opengl --disable-readline --disable-threads`，仍需给magicexec链接Tk。私有launcher只设置`TCL_LIBRARY`到AppImage的`lib/tcl8.6`，然后执行该prefix的magic。

安装验证：

```bash
uv run pytest -q tests/test_flat_cap_export.py
```

两种hierarchy设置都必须保留注入的顶板0.2 fF、栅0.9 fF、底板1 fF及原耦合。真实半单元/31颗bank还与独立EXT矩阵导出逐项对比；Magic会把小于约0.0002 fF的部分耦合打印为0，矩阵导出保留原数值。因此本轮bank仿真使用`_cap.spice`，不依赖其打印精度。

原先由旧工具产生的`_pex.spice`不可因新工具安装完成就视为有效。须重新导出或明确替换为经过校验的矩阵文件。
