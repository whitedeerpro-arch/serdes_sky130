"""WP-002: extract current TX ingress facts without importing/running a bench.

Only evidence.json is generated. The summary and handoff are maintained by hand.
SPICE continuation lines are joined before ports and instances are parsed.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import itertools
import json
import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SER = "analog/tx/serializer/spice/serializer16_retimed_lowov.spice"
LOW = "analog/common/cml_mux/spice/cml_lowov_cells.spice"
MUX = "analog/common/cml_mux/spice/cml_mux2.spice"
CONV = "analog/common/cmos_to_cml/spice/cmos_to_cml_data.spice"
DFF = "analog/common/devices/spice/cmos_dff_reset.spice"
LOGIC = "analog/common/devices/spice/cmos_logic.spice"
NATIVE = "analog/tx/serializer/tb/native_clock/run.py"
R5 = "analog/tx/serializer/tb/native_clock/r5_v3.py"
COUNTER_PROBE = "analog/tx/serializer/tb/clock_replay/counter.py"
COUNTER = "analog/tx/clock_distribution/spice/tx_clock_counter.spice"
REVISION = "config/tx_working_revision.toml"
DOC_SER = "docs/design/tx_serializer.md"
DOC_CLOCK = "docs/design/tx_clock_distribution.md"
BENCH = "analog/tx/serializer/tb/native_clock/tb_native_tx_ngspice.cir.in"
PRIMITIVES = "analog/common/devices/spice/sky130_primitives.spice"
EXPECTED = "analog/tx/serializer/tb/clock_states/serializer_expected.json"
DIST_V3 = "analog/tx/serializer/tb/clock_replay/variants/dist_v3.py"
FIXED = [SER, LOW, MUX, CONV, DFF, LOGIC, NATIVE, R5, COUNTER_PROBE,
         COUNTER, REVISION, DOC_SER, DOC_CLOCK]
SUPPLEMENTAL = [BENCH, PRIMITIVES, EXPECTED, DIST_V3]


class MissingInput(Exception):
    pass


class Sources:
    def __init__(self):
        self.data: dict[str, str] = {}
        self.inputs = []
        for path in FIXED + SUPPLEMENTAL + [str(Path(__file__).relative_to(ROOT))]:
            p = ROOT / path
            if p.is_file():
                raw = p.read_bytes()
                self.data[path] = raw.decode()
                digest = hashlib.sha256(raw).hexdigest()
            else:
                digest = None
            self.inputs.append(dict(path=path, sha256=digest))

    def text(self, path):
        if path not in self.data:
            raise MissingInput(path)
        return self.data[path]

    def cite(self, path, needle):
        matches = [(i, line) for i, line in enumerate(self.text(path).splitlines(), 1)
                   if needle in line]
        if len(matches) != 1:
            raise ValueError(f"{path}: expected one occurrence of {needle!r}, got {len(matches)}")
        line, excerpt = matches[0]
        return dict(path=path, line=line, excerpt=excerpt.strip())

    def logical(self, path):
        rows = []
        for line, text in enumerate(self.text(path).splitlines(), 1):
            text = text.strip()
            if not text or text.startswith("*"):
                continue
            if text.startswith("+"):
                if not rows:
                    raise ValueError(f"{path}:{line}: orphan continuation")
                rows[-1]["text"] += " " + text[1:].strip()
                rows[-1]["source"]["end_line"] = line
            else:
                rows.append(dict(text=text, source=dict(path=path, line=line, end_line=line)))
        return rows

    def subckt(self, path, name):
        rows = self.logical(path)
        begin = next(i for i, row in enumerate(rows)
                     if row["text"].lower().startswith(f".subckt {name.lower()} "))
        end = next(i for i in range(begin + 1, len(rows))
                   if rows[i]["text"].lower().startswith(".ends"))
        tokens = rows[begin]["text"].split()[2:]
        cut = next((i for i, t in enumerate(tokens) if t.lower() == "params:" or "=" in t), len(tokens))
        defaults = dict(t.split("=", 1) for t in tokens[cut:] if "=" in t)
        return dict(name=name, ports=tokens[:cut], defaults=defaults,
                    source=rows[begin]["source"], body=rows[begin + 1:end])

    def instances(self, rows):
        out = []
        for row in rows:
            t = row["text"].split()
            if not t[0].lower().startswith("x"):
                continue
            cut = next((i for i, word in enumerate(t) if "=" in word or word.lower() == "params:"), len(t))
            out.append(dict(instance=t[0], nodes=t[1:cut - 1], cell=t[cut - 1],
                            params=dict(word.split("=", 1) for word in t[cut:] if "=" in word),
                            source=row["source"], statement=row["text"]))
        return out

    def py(self, path):
        return ast.parse(self.text(path), filename=path)

    def literal(self, path, name):
        node = next(n for n in self.py(path).body if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == name for t in n.targets))
        return dict(value=ast.literal_eval(node.value), source=dict(path=path, line=node.lineno,
                    end_line=node.end_lineno), expression=ast.get_source_segment(self.text(path), node))


def public_subckt(s):
    return {k: v for k, v in s.items() if k != "body"}


def bind(inst, definition):
    if len(inst["nodes"]) != len(definition["ports"]):
        raise ValueError(f"{inst['instance']}: {len(inst['nodes'])} nodes for {len(definition['ports'])} ports")
    return dict(zip(definition["ports"], inst["nodes"]))


def require(condition, detail):
    if not condition:
        raise ValueError(detail)


def serializer(s):
    root = s.subckt(SER, "serdes16_cml_tree_retimed_lowov")
    defs = {n: s.subckt(LOW, n) for n in
            ("serdes_cml_mux2_lowov", "serdes_cml_latched_mux2_lowov")}
    connections = []
    for inst in s.instances(root["body"]):
        match = re.fullmatch(r"Xr([1-4])_(\d+)", inst["instance"], re.I)
        if match:
            p = bind(inst, defs[inst["cell"]])
            connections.append(dict(instance=inst["instance"], rank=int(match[1]),
                                    A=[p["ap"], p["an"]], B=[p["bp"], p["bn"]],
                                    select=[p["sp"], p["sn"]], output=[p["qp"], p["qn"]],
                                    cell=inst["cell"], source=inst["source"], params=inst["params"]))
    counts = {str(k): sum(c["rank"] == k for c in connections) for k in range(1, 5)}
    require(counts == {"1": 8, "2": 4, "3": 2, "4": 1}, f"unexpected rank counts: {counts}")
    for k, count in ((1, 8), (2, 4), (3, 2), (4, 1)):
        require({c["instance"].lower() for c in connections if c["rank"] == k}
                == {f"xr{k}_{i}" for i in range(count)}, f"unexpected rank {k} instance identities")
    require(root["ports"][:32] == [f"d{i}{pol}" for i in range(16) for pol in "pn"],
            "root data ports do not match d0..d15 pairs")
    by_output = {tuple(c["output"]): c for c in connections}
    require(len(by_output) == 15, "duplicate driven output pairs")
    select_names = {("c250p", "c250n"): "s250", ("c500p", "c500n"): "s500",
                    ("c1gp", "c1gn"): "s1g", ("c2gp", "c2gn"): "s2g"}

    def leaf(pair, state, visited=()):
        if pair in by_output:
            c = by_output[pair]
            require(c["instance"] not in visited, "cycle in serializer graph")
            choice = "B" if state[select_names[tuple(c["select"])]] else "A"
            return leaf(tuple(c[choice]), state, visited + (c["instance"],))
        match = re.fullmatch(r"d(\d+)p", pair[0])
        require(match is not None and pair[1] == f"d{match[1]}n", f"unexpected leaf pair: {pair}")
        require(0 <= int(match[1]) < 16, f"leaf out of range: {pair}")
        return dict(leaf=f"d{match[1]}", data_pair=list(pair), path=list(visited))

    table = []
    for values in itertools.product((0, 1), repeat=4):
        state = dict(zip(("s250", "s500", "s1g", "s2g"), values))
        table.append(dict(**state, **leaf(("qp", "qn"), state)))
    require(sorted(int(r["leaf"][1:]) for r in table) == list(range(16)), "static leaf table is not bijective")
    return dict(kind="direct_observation_and_static_calculation", root=public_subckt(root),
                rank_counts=counts, connections=connections, ideal_static_table=table,
                convention="1 means sp>sn selects B; 0 means sp<sn selects A; equal inputs are undefined",
                convention_sources=[s.cite(LOW, "* sp>sn selects B"), s.cite(MUX, "* sp>sn selects B")],
                scope="Only this static table replaces the final latched cell by an ideal noninverting MUX. "
                      "It contains no latch history, clk-to-q, propagation delay, setup/hold, analog dynamics, "
                      "temporal state sequence, or dynamic word-boundary proof.")


def final_latches(s):
    final = s.subckt(LOW, "serdes_cml_latched_mux2_lowov")
    latch = s.subckt(LOW, "serdes_cml_data_latch_lowov")
    insts = {i["instance"]: i for i in s.instances(final["body"])}
    devices = {i["instance"]: i for i in s.instances(latch["body"])}
    require(devices["Xct"]["nodes"][0:2] == ["track", "clk_track"]
            and devices["Xch"]["nodes"][0:2] == ["hold", "clk_hold"], "latch clock steering changed")
    rows = []
    for name, track, hold, follower_track, follower_hold in (
            ("Xla", "sap", "san", "Xfpa", "Xfna"),
            ("Xlb", "sbn", "sbp", "Xfnb", "Xfpb")):
        pins = bind(insts[name], latch)
        require(pins["clk_track"] == track and pins["clk_hold"] == hold, f"{name}: unexpected clock wiring")
        tf, hf = insts[follower_track], insts[follower_hold]
        require(tf["nodes"][2] == track and hf["nodes"][2] == hold, "follower outputs changed")
        rows.append(dict(instance=name, pins=pins, source=insts[name]["source"],
                         track_clock=track, hold_clock=hold,
                         external_track_source=tf["nodes"][1], external_hold_source=hf["nodes"][1],
                         clock_followers=[tf, hf]))
    return dict(kind="direct_wiring_and_polarity_inference", final_cell=public_subckt(final),
                latch_cell=public_subckt(latch), latches=rows, steering=[devices["Xct"], devices["Xch"]],
                polarity_source=s.cite(LOW, "* clk_track > clk_hold"),
                selected_mux=insts["Xm"],
                inference="A is wired to track when sap>san (followers driven by sp/sn), while B is selected; "
                          "B is wired to track when sbn>sbp (followers driven by sn/sp), while A is selected. "
                          "The selected branch is wired for hold. Follower lag and transient behavior are unmeasured.",
                numerical_setup_s=None, numerical_hold_s=None,
                difference_from_static_table="Actual Xm selects held ahp/ahn or bhp/bhn; the ideal table traces "
                                             "the original A/B inputs without those latch state variables.")


def ingress(s):
    conv = s.subckt(CONV, "serdes_cmos_to_cml_data")
    inv = s.subckt(LOGIC, "serdes_cmos_inv")
    root = s.subckt(SER, "serdes16_cml_tree_retimed_lowov")
    top = s.instances(s.logical(BENCH))
    tree = next(i for i in top if i["instance"] == "Xtree")
    ports = bind(tree, root)
    paths = []
    for n in range(16):
        inst = next(i for i in top if i["instance"] == f"Xconv{n}")
        pins = bind(inst, conv)
        require(pins["din"] == f"d{n}" and pins["outp"] == ports[f"d{n}p"]
                and pins["outn"] == ports[f"d{n}n"], f"lane {n}: disconnected converter")
        require(inst["cell"] == conv["name"] and not inst["params"], "unexpected converter override")
        paths.append(dict(lane=n, source=f"Vd{n}: d{n} to ground PWL", converter=inst,
                          pins=pins, serializer_ports=[f"d{n}p", f"d{n}n"]))
    root_devices = s.instances(root["body"])
    require(all(i["cell"] in {"serdes_tx_logic_bias", "serdes_cml_mux2_lowov",
                              "serdes_cml_latched_mux2_lowov"} for i in root_devices), "unexpected serializer device")
    external_d_users = [i for i in top if any(re.fullmatch(r"d\d+", p) for p in i["nodes"])]
    require({i["instance"] for i in external_d_users} == {f"Xconv{i}" for i in range(16)},
            "unexpected direct d-lane users")
    conv_devices = {i["instance"]: i for i in s.instances(conv["body"])}
    require(conv_devices["Xp"]["nodes"][1] == "din" and conv_devices["Xinv"]["nodes"][0] == "din",
            "converter input loading changed")
    return dict(kind="direct_wiring_and_bounded_absence_inference", bench=BENCH, paths=paths,
                serializer_instance=tree, source_generator=s.cite(NATIVE, 'lines.append(f"Vd{m[j]}'),
                ingress_word_register_present=False,
                absence_scope="This bench's d0..d15 -> Xconv0..15 -> Xtree path and this serializer subckt. "
                              "DFFs in clock/detector hierarchies do not register these data lanes.",
                converter_cell=public_subckt(conv), converter_input_devices=[conv_devices["Xinv"], conv_devices["Xp"]],
                converter_other_data_device=conv_devices["Xn"], inverter_cell=public_subckt(inv),
                inverter_devices=s.instances(inv["body"]),
                effective_input_gate_geometry=[
                    dict(device="XconvN.Xp", type="serdes_nfet_lvt", width_um=float(conv["defaults"]["wdata"]),
                         length_um=0.15, fingers=4, source=conv_devices["Xp"]["source"]),
                    dict(device="XconvN.Xinv.Xn", type="serdes_nfet", width_um=float(conv_devices["Xinv"]["params"]["wn"]),
                         length_um=0.15, fingers=1, source=s.cite(LOGIC, "Xn y a vss vss serdes_nfet")),
                    dict(device="XconvN.Xinv.Xp", type="serdes_pfet", width_um=float(conv_devices["Xinv"]["params"]["wp"]),
                         length_um=0.15, fingers=1, source=s.cite(LOGIC, "Xp y a vdd vdd serdes_pfet"))],
                geometry_sources=[public_subckt(s.subckt(PRIMITIVES, n)) for n in
                                  ("serdes_nfet", "serdes_nfet_lvt", "serdes_pfet")],
                width_convention=s.cite(PRIMITIVES, "w is TOTAL width"),
                input_capacitance_f=None,
                input_capacitance_reason="Gate dimensions identify load devices; no charge/AC extraction or simulation was performed.")


def reusable_dff(s):
    dff = s.subckt(DFF, "serdes_cmos_dff_reset")
    latch = s.subckt(DFF, "serdes_cmos_latch_reset")
    return dict(kind="source_description_and_wiring", dff=public_subckt(dff), latch=public_subckt(latch),
                dff_instances=s.instances(dff["body"]), latch_instances=s.instances(latch["body"]),
                documented_behavior=s.cite(DFF, "* Fully static positive-edge DFF"),
                polarity="positive-edge clk; asynchronous active-low rst_b clears master and slave; noninverting q",
                interpretation="Master enable is NOR(clk,slave_en); slave enable is NOR(clk_b,master_en). "
                               "Reset drives each internal x low while disabling pass/hold; two inverters produce q=0.",
                cell_usage="Available CMOS cell only; absent from the audited data-lane path.",
                clk_to_q_s=None, setup_s=None, hold_s=None,
                missing_characterization="No timing characterization for these cells driving this CMOS-to-CML input is provided by this package.")


def stimuli(s):
    delay, words, settle = (s.literal(NATIVE, n) for n in ("WORD_DELAY", "WORDS", "SETTLE"))
    tree = s.py(NATIVE)
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "stimuli")
    offsets = []
    for n in ast.walk(function):
        if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Add, ast.Sub)) and isinstance(n.left, ast.Subscript):
            if isinstance(n.left.value, ast.Name) and n.left.value.id == "edges":
                offsets.append(float(ast.literal_eval(n.right)))
    require(len(offsets) == 2 and offsets[0] == offsets[1], f"unrecognized PWL transition: {offsets}")
    require(delay["value"] == 78.3e-12 and words["value"] == 13, "native scheduling constants changed; review interpretation")
    bits = json.loads(s.text(EXPECTED))["bits"]
    require(len(bits) >= words["value"] * 16 and set(bits) <= {0, 1}, "expected bit source too short or nonbinary")
    r5_tree = s.py(R5)
    ap_steps = [n for n in ast.walk(r5_tree) if isinstance(n, ast.Call)
                and any(k.arg == "choices" for k in n.keywords)]
    choices = [ast.literal_eval(k.value) for n in ap_steps for k in n.keywords if k.arg == "choices"]
    require(choices == [("probe",)], f"r5 command set changed: {choices}")
    return dict(kind="source_extraction_and_calculation", shared_generator=dict(
                    function_source=dict(path=NATIVE, line=function.lineno, end_line=function.end_lineno),
                    bit_index=s.cite(NATIVE, "vals = [bits[16 * k + j]"),
                    initial_value=s.cite(NATIVE, 'pts = [f"0 '),
                    loop=s.cite(NATIVE, "for k in range(1, len(edges))"),
                    transition=s.cite(NATIVE, "edges[k] - 10e-12"),
                    offset_each_side_s=offsets[0], transition_width_s=sum(offsets),
                    output_source=s.cite(NATIVE, 'lines.append(f"Vd{m[j]}'),
                    remap_contract=s.cite(NATIVE, "remap: permutation m"),
                    epoch_behavior="Word 0 exists at t=0. edges[0] generates no PWL event; only changed lanes for k>=1 transition.",
                    voltage_levels="0 V and {supply} V (bench supply in volts)",
                    bit_source=dict(path=EXPECTED, json_pointer="/bits", bit_count=len(bits),
                                    first_word_bits=bits[:16])),
                old_native_data=dict(
                    revision_scope="native_clock/run.py data(): PLL r4 open-loop frontend and TX r2 distribution by default",
                    word_delay=delay, words=words, settle_overrides=settle, default_settle_s=30e-9,
                    default_settle_source=s.cite(NATIVE, 'first = [x for x in p["src250_falls_s"]'),
                    source_250_expression=s.cite(BENCH, "let src250="),
                    serializer_250_expression=s.cite(BENCH, "let d250="),
                    measured_source_falls=s.cite(NATIVE, 'falls = clock.edges(w.t, w["src250"]'),
                    first_reference_fall=s.cite(NATIVE, 'first = [x for x in p["src250_falls_s"]'),
                    ui_source=s.cite(NATIVE, "ui = 0.5 / f"),
                    frequency_source=s.cite(NATIVE, 'f = clock.period_stats(w.t, w["pb0"]'),
                    word_period=s.cite(NATIVE, 'period = 16 * p["ui_s"]'),
                    schedule=s.cite(NATIVE, "edges = [first + WORD_DELAY"),
                    generator_call=s.cite(NATIVE, '(d / "stimuli.inc").write_text(stimuli(edges'),
                    interpretation="Epoch center = first source-250 falling edge after settle +78.3 ps; later centers extrapolate at 16 measured UI. "
                                   "Not a trigger on every serializer c250 falling edge. A changed lane's 20 ps ramp spans center +/-10 ps. "
                                   "The first center has no update event because word 0 was set at t=0.",
                    optional_remap_sources=[s.cite(NATIVE, "if remap_state is not None:"),
                                            s.cite(NATIVE, 'remap = [int(x, 16)')],
                    legacy_lookup=s.cite(NATIVE, "probes = _latest_probes()"),
                    lookup_scope="Historical data() code uses a latest-probe lookup. This extractor does not invoke it or read any results/latest pointer."),
                r5_v3_static=dict(
                    mode_choices_source=s.cite(R5, 'choices=("probe",)'),
                    generator_call=s.cite(R5, "static = native.stimuli([0.0], bits)"),
                    bit_source=s.cite(R5, 'bits = json.loads(native.EXPECTED.read_text())'),
                    write_call=s.cite(R5, '(d / "stimuli.inc").write_text(static)'),
                    frontend_replacement=s.cite(R5, 'clock_frontend_r4.spice\"\''),
                    distribution_replacement=s.cite(R5, 'dist_v3.netlist(dist_cfg)'),
                    real_bias_pdk=s.cite(R5, "return bias.section(rcorner.to_pdk"),
                    interpretation="One word (the first 16 bits) held for the whole run; no changed-lane PWL ramps and no dynamic word scheduling/remap call.",
                    dynamic_word_delay_s=None, dynamic_reference_edge=None, dynamic_transition_width_s=None,
                    dynamic_word_latency_cycles=None,
                    unknown_reason="Only a static [0.0] edge list is passed; old WORD_DELAY/WORDS and dynamic ramp code are not exercised.",
                    doc_scope=s.cite(DOC_CLOCK, "当前并行输入是静态电平")))


def clocks(s):
    counter = s.subckt(COUNTER, "serdes_tx_sync_counter8")
    return dict(kind="direct_wiring_and_source_description", counter=public_subckt(counter),
                instances=s.instances(counter["body"]),
                update_polarity_source=s.cite(COUNTER, "Next state (slave updates on the falling crossing"),
                select_sources=s.cite(DIST_V3, 'src = {"250": "q2"'),
                counter_instance=s.cite(DIST_V3, 'L.append("Xcnt '),
                replica_instance=s.cite(DIST_V3, 'L.append("Xrep '),
                bench_initialization=s.cite(DIST_V3, 'L.append(".ic "'),
                initialization_scope="Generated .ic values assist a simulator initial state; counter has no hardware reset port. "
                                     "This is not real-power-up or deterministic-reset proof.",
                probe_window=s.literal(COUNTER_PROBE, "WINDOW"), nominal_probe_ui=s.literal(COUNTER_PROBE, "UI"),
                probe_clk_to_q=s.cite(COUNTER_PROBE, 'cq[f"q{i}"] = float(np.median(delays))'),
                measurement_scope="counter.py measures counter-output crossing delay relative to its own internal clock falls; "
                                  "this is not the unmeasured ingress CMOS-DFF clk-to-q.",
                actual_ingress_update_window_s=None)


def metadata(s):
    cfg = tomllib.loads(s.text(REVISION))
    return dict(kind="configuration_and_document_statements", revision=cfg["revision"],
                revision_source=s.cite(REVISION, 'revision = '), serializer=cfg["serializer"],
                candidate_scope=cfg["v3_candidate_native_static_scope"],
                candidate_scope_source=s.cite(REVISION, 'v3_candidate_native_static_scope = '),
                missing_ingress_doc=s.cite(DOC_SER, "没有并行字捕获寄存器"),
                ideal_data_boundary_doc=s.cite(DOC_CLOCK, "数据输入接口："),
                qualifier="Historical pass counts were not remeasured and are not transferred to r5 dynamic ingress.")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    s = Sources()
    evidence = dict(package_id="WP-002", execution_status="complete", inputs=s.inputs,
                    observations={}, checks=[], unresolved=[])
    missing = [i["path"] for i in s.inputs if i["sha256"] is None]
    evidence["checks"].append(dict(id="input_identity", status="missing" if missing else "pass",
                                   detail=dict(missing=missing, input_count=len(s.inputs),
                                               source="current workspace bytes, not git HEAD")))
    tasks = [("serializer", serializer), ("final_latches", final_latches), ("ingress", ingress),
             ("reusable_cmos_dff", reusable_dff), ("stimuli", stimuli), ("clocks", clocks), ("metadata", metadata)]
    for name, function in tasks:
        try:
            evidence["observations"][name] = function(s)
            evidence["checks"].append(dict(id=name + "_extraction", status="pass", detail="Source extraction completed; see observations."))
        except (MissingInput, ValueError, KeyError, StopIteration, IndexError, SyntaxError) as err:
            status = "missing" if isinstance(err, MissingInput) else "fail"
            evidence["observations"][name] = None
            evidence["checks"].append(dict(id=name + "_extraction", status=status, detail=f"{type(err).__name__}: {err}"))
            evidence["unresolved"].append(dict(id=name + "_extraction", value=None, reason=str(err) or type(err).__name__))
    for ident, reason in (
            ("r5_dynamic_ingress_contract", "Static r5 stimulus defines no word launch edge, delay, allowed window or latency contract."),
            ("ingress_cmos_dff_timing", "Loaded clk-to-q, setup/hold, clock input shape and PVT/mismatch ranges need characterization."),
            ("converter_input_capacitance", "Device widths are known; effective input capacitance/charge versus data, bias and PVT is unmeasured."),
            ("allowed_dynamic_update_window", "Actual retimed tree update windows, old/new word mixing and bit mapping need a timed model and circuit measurements."),
            ("integration_decisions", "Integrator must set clock/edge domain, word latency, data-valid/startup/reset contract, clock/data delay and jitter budgets and acceptance scope.")):
        evidence["unresolved"].append(dict(id=ident, value=None, reason=reason))
        evidence["checks"].append(dict(id=ident, status="ungraded", detail=reason))
    evidence["checks"].append(dict(id="scope", status="pass",
                                   detail="Read-only source extraction and static enumeration. No simulator, network, result discovery, circuit edit or design signoff."))
    if any(c["status"] in ("fail", "missing") for c in evidence["checks"]):
        evidence["execution_status"] = "partial"
    args.output.mkdir(parents=True, exist_ok=True)
    out = args.output / "evidence.json"
    out.write_text(json.dumps(evidence, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    print(json.dumps(dict(package_id="WP-002", execution_status=evidence["execution_status"],
                          output=str(out), checks={status: sum(c["status"] == status for c in evidence["checks"])
                                                   for status in ("pass", "fail", "ungraded", "missing")}), ensure_ascii=False))
    return 0 if evidence["execution_status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
