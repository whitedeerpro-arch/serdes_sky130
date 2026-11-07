"""WP-003: read-only inventory of ten fixed RX readout campaigns.

Run from any directory with ``uv run python .../wp003_rx_lineage.py --output DIR``.
Only evidence.json is generated; summary.md and handoff.md are hand-maintained.
No simulation or PRBS analysis is performed. Raw files are opened one at a time.
"""
from __future__ import annotations

import argparse
import gc
import gzip
import hashlib
import json
import re
import shlex
import tomllib
from collections import Counter
from pathlib import Path

from serdes_flow import bias, spice

ROOT = Path(__file__).resolve().parents[2]
BASE = Path("results/analog/rx/sampler/readout_deser")
RUNS = (
    "20261103T124408Z_ac_trim32",
    "20261105T195752Z_ac_trim32_realbias_rhh",
    "20261105T195755Z_ac_trim32_realbias_rhh",
    "20261105T195758Z_ac_trim32_realbias_rhh",
    "20261105T195801Z_ac_trim32_realbias_rhh",
    "20261105T211802Z_ac_trim32_realbias_rhh",
    "20261105T211805Z_ac_trim32_realbias_rll",
    "20261105T211808Z_ac_trim32_realbias_rll",
    "20261105T211811Z_ac_trim32_realbias_rll",
    "20261105T213614Z_ac_trim32_realbias_rhh",
)
INTENT = (
    "config/rx_working_revision.toml",
    "analog/rx/sampler/spice/rx_readout_deser16.spice",
    "analog/rx/sampler/spice/rx_readout_demux2.spice",
    "analog/pll/divider/spice/cml_div2.spice",
    "analog/rx/sampler/tb/readout_deser/run.py",
)
STRESS = ("tt_v1800_t27", "ss_v1650_t-40", "ss_v1650_t85", "fs_v1650_t-40", "fs_v1650_t85", "ff_v1950_t-40")
PARAM_RE = re.compile(r"([a-zA-Z_][\w]*)\s*=\s*(\{[^}]*\}|[^\s]+)")
CASE_RE = re.compile(r"([a-z]{2}_v\d+_t-?\d+)(?:_c(\d+))?", re.I)
INPUTS: dict[str, dict] = {}
CHECKS: list[dict] = []
UNRESOLVED: list[dict] = []


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def register(path: Path) -> dict:
    key = rel(path)
    if key not in INPUTS:
        if not path.is_file():
            INPUTS[key] = dict(path=key, sha256=None, reason="file missing")
        else:
            sha = hashlib.sha256()
            with path.open("rb") as f:
                for block in iter(lambda: f.read(1024 * 1024), b""):
                    sha.update(block)
            INPUTS[key] = dict(path=key, sha256=sha.hexdigest(), bytes=path.stat().st_size)
    return INPUTS[key]


def read_text(path: Path) -> str:
    register(path)
    return path.read_text(errors="replace")


def read_json(path: Path):
    register(path)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (ValueError, OSError) as e:
        UNRESOLVED.append(dict(path=rel(path), reason=f"JSON not readable: {e}"))
        return None


def check(id_: str, status: str, detail):
    CHECKS.append(dict(id=id_, status=status, detail=detail))


def logical_lines(path: Path, text: str) -> list[dict]:
    """Join SPICE continuations and retain exact physical source text and line numbers."""
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("+") and out:
            out[-1]["text"] += " " + line.lstrip()[1:].strip()
            out[-1]["original"] += "\n" + line
            out[-1]["end_line"] = n
        else:
            out.append(dict(path=rel(path), line=n, end_line=n, text=line.strip(), original=line))
    return out


def params(text: str) -> dict[str, str]:
    return {m[1].lower(): m[2] for m in PARAM_RE.finditer(text)}


def number(text: str | None) -> float | None:
    if text is None:
        return None
    m = re.fullmatch(r"([+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?)([a-z]*)", text, re.I)
    if not m:
        return None
    scales = {"": 1, "t": 1e12, "g": 1e9, "meg": 1e6, "k": 1e3, "m": 1e-3, "u": 1e-6, "n": 1e-9, "p": 1e-12, "f": 1e-15}
    suffix = m[2].lower()
    return float(m[1]) * scales[suffix] if suffix in scales else None


def eval_param(value: str, env: dict) -> float | None:
    numeric = number(value)
    if numeric is not None:
        return numeric
    # Only literal values or a single forwarded parameter are accepted. No eval.
    m = re.fullmatch(r"\{(\w+)\}", value)
    return env.get(m[1].lower()) if m else None


def instance(line: dict) -> dict | None:
    if not re.match(r"^[xX]\w", line["text"]):
        return None
    m = PARAM_RE.search(line["text"])
    prefix = line["text"][:m.start()] if m else line["text"]
    tokens = prefix.split()
    if len(tokens) < 3:
        return None
    return dict(name=tokens[0], cell=tokens[-1].lower(), parameters=params(line["text"]), source=line)


def definitions(sources: dict[str, list[dict]]) -> dict:
    out = {}
    for lines in sources.values():
        active = None
        for line in lines:
            if line["text"].lower().startswith(".subckt "):
                name = line["text"].split()[1].lower()
                active = dict(name=name, parameters=params(line["text"]), source=line, instances=[])
                out[name] = active
            elif line["text"].lower().startswith(".ends"):
                active = None
            elif active is not None and (ins := instance(line)):
                active["instances"].append(ins)
    return out


def bind(ins: dict, defs: dict, parent: dict) -> tuple[dict, dict | None]:
    definition = defs.get(ins["cell"])
    env = {}
    if definition:
        for k, v in definition["parameters"].items():
            env[k] = eval_param(v, {**parent, **env})
    for k, v in ins["parameters"].items():
        env[k] = eval_param(v, parent)
    return env, definition


def trace_readout(ro: dict | None, defs: dict) -> dict:
    """Resolve Xro -> Xf -> Xdiv -> Xmaster/Xslave; do not borrow PLL prescaler sizes."""
    steps = []
    if ro is None:
        return dict(whold_um=None, reason="Xro instance missing", chain=steps)
    ins, parent = ro, {}
    for child in ("xf", "xdiv", None):
        env, definition = bind(ins, defs, parent)
        steps.append(dict(instance=ins, defaults_source=definition["source"] if definition else None, effective_parameters=env))
        if definition is None:
            return dict(whold_um=None, reason=f"Historical subckt {ins['cell']} has no in-campaign snapshot; mutable include is not historical evidence", chain=steps)
        if child is None:
            forwarded = [x for x in definition["instances"] if x["name"].lower() in ("xmaster", "xslave")]
            return dict(whold_um=env.get("whold"), reason=None if env.get("whold") is not None else "whold could not be resolved", chain=steps,
                        latch_forwarding=[dict(instance=x, whold_um=eval_param(x["parameters"].get("whold", ""), env)) for x in forwarded])
        found = [x for x in definition["instances"] if x["name"].lower() == child]
        if len(found) != 1:
            return dict(whold_um=None, reason=f"Expected one {child}, found {len(found)}", chain=steps)
        ins, parent = found[0], env
    raise AssertionError("unreachable")


def include_sources(deck: Path, root: Path, lines: list[dict]) -> tuple[dict, list[dict]]:
    """Open only actual deck includes inside this fixed root; never current analog paths."""
    sources = {rel(deck): lines}
    entries = []
    queue = [(deck, lines)]
    while queue:
        source_path, current = queue.pop(0)
        for line in current:
            if not re.match(r"^\.inc(?:lude)?\s", line["text"], re.I):
                continue
            tokens = shlex.split(line["text"])
            path = Path(tokens[1])
            path = path if path.is_absolute() else source_path.parent / path
            path = path.resolve()
            inside = path.is_relative_to(root.resolve())
            entry = dict(source=line, declared=tokens[1], resolved=rel(path), available=path.is_file(),
                         provenance="in_campaign_file" if inside else "mutable_external_reference_not_used_for_history")
            entries.append(entry)
            if inside and rel(path) not in sources:
                register(path)
                if path.is_file():
                    # The PWL file is identified by hash, not embedded as two enormous lines.
                    new_lines = [] if path.suffix == ".inc" else logical_lines(path, read_text(path))
                    sources[rel(path)] = new_lines
                    queue.append((path, new_lines))
                else:
                    UNRESOLVED.append(dict(path=rel(path), reason="deck include missing"))
    return sources, entries


def control_outputs(lines: list[dict]) -> list[dict]:
    library = next((x for x in lines if x["text"].lower().startswith(".lib ")), None)
    section = shlex.split(library["text"])[-1].lower() if library else None
    supply = next((number(x["text"].split()[-1]) for x in lines if re.match(r"^Vdd\s", x["text"], re.I)), None)
    temp = next((number(x["text"].split()[-1]) for x in lines if x["text"].lower().startswith(".temp ")), None)
    code = None
    case = None
    tran = None
    in_control = False
    outputs = []
    for line in lines:
        text = line["text"]
        if text.lower() == ".control":
            in_control = True
        elif text.lower() == ".endc":
            in_control = False
        if not in_control:
            continue
        if text.lower().startswith("* case "):
            case = text.split(maxsplit=2)[-1]
            m = CASE_RE.fullmatch(case)
            code = int(m[2]) if m and m[2] else None
        if m := re.match(r"option\s+temp=(\S+)", text, re.I):
            temp = number(m[1])
        if m := re.match(r"alter\s+Vdd\s+dc=(\S+)", text, re.I):
            supply = number(m[1])
        if re.match(r"tran\s", text, re.I):
            ts = text.split()[1:]
            tran = dict(step_s=number(ts[0]), target_end_s=number(ts[1]), save_from_s=number(ts[2]) if len(ts) > 2 else 0.0,
                        max_step_s=number(ts[3]) if len(ts) > 3 else None, source=line)
        if re.match(r"write\s", text, re.I):
            tokens = text.split()
            tag_match = CASE_RE.match(case or tokens[1])
            outputs.append(dict(case_label=case, condition=tag_match[1].lower() if tag_match else None,
                                pi_code_from_case_label=code, mos=section.split("_")[0] if section else None,
                                library_section=section, supply_v=supply, temperature_c=temp,
                                tran=tran.copy() if tran else None, filename=tokens[1], write_source=line,
                                vectors=tokens[2:]))
    return outputs


def raw_header(path: Path) -> dict:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as f:
        header = {}
        while True:
            line = f.readline()
            if not line:
                raise ValueError("no Binary:/Values: section")
            text = line.decode("latin-1").strip()
            if text in ("Binary:", "Values:"):
                offset = f.tell()
                break
            if ":" in text:
                k, v = text.split(":", 1)
                header[k] = v.strip()
        header["format"] = text[:-1]
        header["payload_offset"] = offset
        if text == "Binary:" and path.suffix != ".gz":
            n = int(header.get("No. Points", 0))
            cols = int(header.get("No. Variables", 0))
            header["payload_bytes"] = path.stat().st_size - offset
            header["expected_payload_bytes"] = n * cols * 8 if n and cols else None
            header["payload_matches_header"] = header["payload_bytes"] == n * cols * 8 if n and cols else None
        return header


def inspect_raw(path: Path, output: dict) -> dict:
    target = output["tran"]["target_end_s"] if output["tran"] else None
    found = next((p for p in (path, Path(str(path) + ".gz")) if p.is_file()), None)
    if found is None:
        register(path)
        result = dict(path=rel(path), status="missing", finite=None, time_strictly_increasing=None,
                      start_s=None, end_s=None, target_end_s=target, complete_to_target=None, reason="write output absent")
    else:
        register(found)
        try:
            header = raw_header(found)
            w = spice.Waves(found)
            # Waves verifies all columns for finite values and strictly increasing time.
            n, cols = w.data.shape
            start = float(w.t[0]) if n else None
            stop = float(w.t[-1]) if n else None
            complete = bool(n and stop >= target * (1 - 1e-6)) if target is not None else None
            payload_ok = header.get("payload_matches_header")
            expected = [v.lower() for v in output["vectors"]]
            missing_vectors = [v for v in expected if v not in w]
            status = "pass" if complete and payload_ok is not False and not missing_vectors else "fail" if complete is False or payload_ok is False or missing_vectors else "ungraded"
            result = dict(path=rel(found), status=status, header=header, points=n, variables=cols, finite=True,
                          time_strictly_increasing=True, start_s=start, end_s=stop, target_end_s=target,
                          complete_to_target=complete, missing_written_vectors=missing_vectors,
                          reason="truncated before deck target" if complete is False else None)
            del w
        except (ValueError, OSError, IndexError) as e:
            result = dict(path=rel(found), status="fail", finite=None, time_strictly_increasing=None, start_s=None, end_s=None,
                          target_end_s=target, complete_to_target=None, reason=f"raw unreadable: {e}")
        finally:
            gc.collect()
    check(f"raw:{result['path']}", result["status"], result)
    return result


def deck_facts(lines: list[dict], sources: dict, includes: list[dict]) -> dict:
    top = {x["name"].lower(): x for line in lines if (x := instance(line))}
    defs = definitions(sources)
    dut, ro = top.get("xdut"), top.get("xro")
    env, definition = bind(dut, defs, {}) if dut else ({}, None)
    library = [line for line in lines if line["text"].lower().startswith(".lib ")]
    bias = "real" if "xbias_ref" in top and "xiref" in top else "ideal_current_reference" if any(re.match(r"^Iref\s", x["text"], re.I) for x in lines) else None
    ref_sources = [x for x in lines if re.match(r"^(?:Xbias_ref|XIref|XIctle|Xref|Iref|Ictle|\.nodeset|Ikick)\s", x["text"], re.I)]
    anchors = [x for x in lines if re.match(r"^Bc[0-3][pn]\s", x["text"], re.I)]
    trim_sources = [x for x in lines if re.match(r"^Vcal", x["text"], re.I)]
    codes = {}
    for lane in ("d0", "d1", "e0", "e1"):
        bits = {}
        for x in trim_sources:
            tokens = x["text"].split()
            if m := re.fullmatch(rf"Vcal{lane}b([0-5])", tokens[0], re.I):
                bits[int(m[1])] = 1 if tokens[2].lower() == "vdd" and tokens[-1] == "0" else 0 if tokens[2] == "0" and tokens[-1] == "0" else None
        codes[lane] = sum(v << k for k, v in bits.items()) if len(bits) == 6 and None not in bits.values() else None
    resistor_sources = [line for ls in sources.values() for line in ls if "sky130_fd_pr__res_high_po" in line["text"] and not line["text"].startswith("*")]
    width = trace_readout(ro, defs)
    return dict(library=library, includes=includes, bias_kind=bias, reference_sources=ref_sources,
                phase_anchors=dict(kind="ideal_behavioral_voltage" if len(anchors) == 8 else None, sources=anchors),
                sampler=dict(instance=dut, uses_rk_cell=bool(dut and dut["cell"].endswith("_rk")), explicit_parameters=dut["parameters"] if dut else None,
                             defaults_source=definition["source"] if definition else None, effective_parameters=env or None,
                             trim_codes_from_deck=codes, trim_source_lines=trim_sources),
                readout=dict(instance=ro, divider=width),
                passive=dict(pdk_high_po_instances=len(resistor_sources), sources=resistor_sources,
                             historical_implementation="PDK high_po instances observed in snapshots" if resistor_sources else None,
                             reason=None if resistor_sources else "no in-campaign passive snapshot; do not infer historical ideal/PDK implementation from current sources"),
                loads=[x for x in lines if re.match(r"^C(?:[dDeE][01][pn]|[ab][e01_]|w\s)", x["text"], re.I)],
                numerical_sources=[x for x in lines if re.match(r"^(?:\.options|option\s+(?:reltol|temp))", x["text"], re.I)])


def attempt(directory: Path, root: Path) -> dict:
    deck = directory / "tb.cir"
    lines = logical_lines(deck, read_text(deck))
    sources, includes = include_sources(deck, root, lines)
    ex_path = directory / "execution.json"
    execution = read_json(ex_path)
    log = directory / "simulator.log"
    if log.is_file():
        log_lines = read_text(log).splitlines()
        excerpts = [dict(path=rel(log), line=n, text=s) for n, s in enumerate(log_lines, 1)
                    if re.search(r"Error:|doAnalyses:|simulation\(s\) aborted|No\. of Data Rows|Doing analysis at TEMP|binary raw file", s, re.I)]
    else:
        register(log)
        excerpts = None
    deck_match = register(deck)["sha256"] == execution.get("deck_sha256") if execution and execution.get("deck_sha256") else None
    check(f"deck_execution_identity:{rel(directory)}", "pass" if deck_match else "fail" if deck_match is False else "missing", dict(deck=rel(deck), matches_execution_sha256=deck_match))
    stimuli = directory / "stimuli.inc"
    register(stimuli)
    stim_match = register(stimuli)["sha256"] == execution.get("inputs_sha256", {}).get("stimuli.inc") if execution else None
    check(f"stimuli_execution_identity:{rel(directory)}", "pass" if stim_match else "fail" if stim_match is False else "missing", dict(path=rel(stimuli), matches_execution_sha256=stim_match))
    outputs = control_outputs(lines)
    for output in outputs:
        output["waveform"] = inspect_raw(directory / output["filename"], output)
    smoke = directory.name.endswith(".smoke")
    facts = deck_facts(lines, sources, includes)
    return dict(path=rel(directory), is_smoke=smoke, deck_path=rel(deck), execution_path=rel(ex_path),
                execution=execution, deck_matches_execution_sha256=deck_match, stimuli_matches_execution_sha256=stim_match,
                log_excerpts=excerpts, facts=facts, outputs=outputs)


def campaign(path: Path) -> dict:
    print(f"Inspecting {rel(path)}", flush=True)
    if not path.is_dir():
        UNRESOLVED.append(dict(path=rel(path), reason="fixed campaign directory missing"))
        return dict(path=rel(path), exists=False, conditions=[], attempts=[])
    plan_path, summary_path = path / "plan.json", path / "summary.json"
    plan, summary = read_json(plan_path), read_json(summary_path)
    plan_decks = plan.get("decks", {}) if isinstance(plan, dict) else {}
    summary_rows = summary.get("rows", []) if isinstance(summary, dict) else []
    if (path / "stimuli.inc").is_file():
        register(path / "stimuli.inc")
    # Only descend to direct run directories containing an actual tb.cir, including retries/smoke.
    attempts = [attempt(child, path) for child in sorted(path.iterdir()) if child.is_dir() and (child / "tb.cir").is_file()]
    tags = list(plan_decks)
    for row in summary_rows:
        if row.get("condition") and row["condition"] not in tags:
            tags.append(row["condition"])
    for a in attempts:
        for o in a["outputs"]:
            if o["condition"] and o["condition"] not in tags:
                tags.append(o["condition"])
    conditions = []
    for tag in tags:
        rows = [row for row in summary_rows if row.get("condition") == tag]
        matching = [a for a in attempts if any(o["condition"] == tag for o in a["outputs"]) or (a["execution"] or {}).get("condition") == tag]
        normal = [a for a in matching if not a["is_smoke"]]
        complete = [dict(attempt=a["path"], raw=o["waveform"]["path"], whold_um=a["facts"]["readout"]["divider"]["whold_um"],
                         bias=a["facts"]["bias_kind"], library_section=o["library_section"])
                    for a in normal for o in a["outputs"] if o["condition"] == tag and o["waveform"]["status"] == "pass"]
        conditions.append(dict(condition=tag, planned_decks=plan_decks.get(tag), present_in_plan=tag in plan_decks,
                               historical_summary=dict(source=rel(summary_path), rows=rows, recomputed=False),
                               attempt_paths=[a["path"] for a in matching], formal_attempt_count=len(normal),
                               smoke_attempt_count=len(matching) - len(normal), execution_present=any(a["execution"] is not None for a in normal),
                               complete_formal_outputs=complete,
                               scope="historical boundary only; no current-design signoff"))
        check(f"condition_complete_output:{rel(path)}:{tag}", "pass" if complete else "missing", dict(condition=tag, complete_formal_outputs=complete))
    return dict(path=rel(path), exists=True, plan_source=rel(plan_path), plan_decks=plan_decks,
                summary_source=rel(summary_path), summary_metadata={k: v for k, v in (summary or {}).items() if k != "rows"},
                summary_present=summary is not None, conditions=conditions, attempts=attempts)


def coverage(campaigns: list[dict]) -> list[dict]:
    matrix = []
    for tag in STRESS:
        for rc in ("hh", "ll"):
            expected_section = bias.section(f'.lib "unused" {tag[:2]}', tag[:2], rc).split()[-1]
            explicit, incomplete, mismatch = [], [], []
            for camp in campaigns:
                cond = next((x for x in camp["conditions"] if x["condition"] == tag), None)
                if cond is None:
                    continue
                matching_attempts = [a for a in camp["attempts"] if a["path"] in cond["attempt_paths"]]
                for a in matching_attempts:
                    for output in a["outputs"]:
                        if output["condition"] != tag:
                            continue
                        width = a["facts"]["readout"]["divider"]["whold_um"]
                        item = dict(campaign=camp["path"], attempt=a["path"], smoke=a["is_smoke"], whold_um=width,
                                    bias=a["facts"]["bias_kind"], library_section=output["library_section"], waveform=output["waveform"],
                                    historical_summary=cond["historical_summary"], boundary_source=a["deck_path"])
                        boundary_ok = width == 40 and item["bias"] == "real" and output["library_section"] == expected_section and a["facts"]["passive"]["pdk_high_po_instances"] > 0
                        identity_ok = a["deck_matches_execution_sha256"] is True and a["stimuli_matches_execution_sha256"] is True
                        if boundary_ok and identity_ok and not a["is_smoke"] and output["waveform"]["status"] == "pass":
                            explicit.append(item)
                        elif boundary_ok:
                            incomplete.append(item)
                        else:
                            item["mismatch_reasons"] = [r for ok, r in ((width == 40, "historical RX divider W40 not established"),
                                                                       (item["bias"] == "real", "reference is not real-bias boundary"),
                                                                       (output["library_section"] == expected_section, f"library section is not {expected_section}"),
                                                                       (a["facts"]["passive"]["pdk_high_po_instances"] > 0, "historical passive snapshot absent")) if not ok]
                            mismatch.append(item)
            status = "pass" if explicit else "missing"
            matrix.append(dict(condition=tag, resistor_corner=rc, status=status, explicit_complete_evidence=explicit,
                               correct_boundary_incomplete_attempts=incomplete, other_boundary_or_unknown_evidence=mismatch,
                               reason=None if explicit else "No complete formal W40 / real reference / requested PDK resistor section waveform among fixed roots"))
            check(f"current_scope_evidence:{tag}:{rc}", status, dict(complete_count=len(explicit), incomplete_count=len(incomplete), boundary_mismatch_or_unknown_count=len(mismatch)))
    return matrix


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    output = args.output.resolve()
    # Prevent accidentally selecting an immutable historical input as the output.
    if output.is_relative_to((ROOT / "results").resolve()):
        ap.error("--output must not be in results/")
    texts = {p: read_text(ROOT / p) for p in INTENT}
    intent_config = tomllib.loads(texts[INTENT[0]])
    intent_sources = {p: logical_lines(ROOT / p, texts[p]) for p in INTENT[1:4]}
    current_ro = dict(name="Xro", cell="serdes_rx_readout_deser16", parameters={}, source=None)
    current = dict(scope="present working-tree intent, independent of all historical observations", config=intent_config,
                   readout_width_trace=trace_readout(current_ro, definitions(intent_sources)),
                   old_W80_claim=dict(value=intent_config.get("readout", {}).get("old_full45_scope"),
                                      source=INTENT[0], kind="current_configuration_reported_claim; not a historical snapshot"),
                   runner_excerpts=[x for x in logical_lines(ROOT / INTENT[4], texts[INTENT[4]])
                                    if any(s in x["text"] for s in ('"--param"', '"--dut"', '"--cal-code"', '"--bc"', '"--bias"', '"--rpdk"', "case_output(", '"deser"', "sp.link.STOP", "word_check(words"))])
    # Hash the actual shared reader implementation and task requirements used by this extraction.
    for p in ("src/serdes_flow/spice.py", "src/serdes_flow/bias.py", "AGENTS.md", "docs/work_packages/README.md", "docs/work_packages/WP-003-rx-readout-lineage.md", rel(Path(__file__))):
        register(ROOT / p)
    roots = [ROOT / BASE / run for run in RUNS]
    raw_paths = [p for root in roots if root.is_dir() for p in root.rglob("*") if p.is_file() and (p.name.endswith(".raw") or p.name.endswith(".raw.gz"))]
    scale = dict(raw_files=len(raw_paths), raw_bytes=sum(p.stat().st_size for p in raw_paths),
                 max_single_raw_bytes=max((p.stat().st_size for p in raw_paths), default=0),
                 reading_method="spice.Waves, sequential single raw, release and collect before next; SHA256 streamed in 1 MiB blocks")
    print(json.dumps(scale), flush=True)
    campaigns = [campaign(root) for root in roots]
    matrix = coverage(campaigns)
    all_attempts = [a for c in campaigns for a in c["attempts"]]
    all_waves = [o["waveform"] for a in all_attempts for o in a["outputs"]]
    for c in campaigns:
        for row in c["conditions"]:
            if not row["complete_formal_outputs"]:
                UNRESOLVED.append(dict(path=c["path"], condition=row["condition"], reason="no complete formal output; historical absence retained"))
        unknown = [a["path"] for a in c["attempts"] if a["facts"]["readout"]["divider"]["whold_um"] is None]
        if unknown:
            UNRESOLVED.append(dict(path=c["path"], reason="mutable project includes have no historical snapshot; divider width and unrecorded defaults/passive implementation unknown", attempts=unknown))
    inventory = dict(fixed_root_count=len(RUNS), existing_root_count=sum(c["exists"] for c in campaigns),
                     planned_condition_rows=sum(len(c.get("plan_decks", {})) for c in campaigns),
                     condition_rows=sum(len(c["conditions"]) for c in campaigns),
                     historical_summary_rows=sum(len(x["historical_summary"]["rows"]) for c in campaigns for x in c["conditions"]),
                     formal_attempts=sum(not a["is_smoke"] for a in all_attempts), smoke_attempts=sum(a["is_smoke"] for a in all_attempts),
                     output_integrity_status_counts=dict(Counter(w["status"] for w in all_waves)),
                     scope_evidence_complete_cells=sum(bool(x["explicit_complete_evidence"]) for x in matrix), scope_evidence_total_cells=len(matrix))
    check("fixed_roots", "pass" if inventory["existing_root_count"] == 10 else "missing", inventory)
    check("historical_prbs_reanalysis", "ungraded", "No PRBS stream, mapping, errors, words or capture slack recomputed. Summary fields are historical_summary only.")
    check("native_pll_or_true_powerup", "ungraded", "All observed PI anchors are ideal behavioral voltage sources. Real-reference decks contain nodeset/initial-state aids; these are not native PLL or real power-up evidence.")
    evidence = dict(package_id="WP-003", execution_status="complete", inputs=[INPUTS[k] for k in sorted(INPUTS)],
                    observations=dict(current_intent=current, input_scale=scale, inventory=inventory,
                                      by_run_fact_table=campaigns, current_W40_realbias_hh_ll_stress_table=matrix),
                    checks=CHECKS, unresolved=UNRESOLVED,
                    method=dict(no_ngspice=True, no_network=True, no_historical_writes=True, current_worktree_used=True,
                                raw_scope="integrity only, no new PRBS or design specification verdict", time_unit="s", width_unit="um",
                                endpoint_tolerance_relative=1e-6,
                                snapshot_provenance="in-campaign files directly included by actual deck; execution records hash deck/stimulus but do not independently hash every snapshot",
                                completion_semantics="execution_status=complete means all fixed inputs audited; missing, truncated, unknown and failed historical evidence remain explicit"))
    output.mkdir(parents=True, exist_ok=True)
    (output / "evidence.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    print(json.dumps(inventory), flush=True)
    print(f"Wrote {output / 'evidence.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
