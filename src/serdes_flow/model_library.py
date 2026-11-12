"""Opt-in SKY130 device-family library reduction for nominal simulations.

Keep complete files for selected device families and all shared parameter files,
in their original include order. No parameter/model expressions are rewritten.
This is not a general SPICE optimizer; statistical sections are deliberately
unsupported until sample identity has been validated.
"""
import hashlib
import json
from pathlib import Path
import re
import shlex


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def family(path):
    match = re.match(r'(sky130_fd_(?:pr|bs_flash)__.+?)(?:__|\.)', Path(path).name.lower())
    return match[1] if match else None


def build(library, section, devices, output_dir):
    """Write a self-contained single-section library and a small manifest.

    `devices` are exact PDK subcircuit/model names, including sky130_fd_pr__.
    Request every family needed by the DUT; this first implementation does not
    infer dependencies from arbitrary parameterized project netlists. Unknown
    requests, unsupported directives, missing includes and cycles fail closed.
    The original library and any in-flight decks are never modified.
    """
    library = Path(library).resolve()
    devices = sorted(set(x.lower() for x in devices))
    if not devices or any(not re.fullmatch(r'sky130_fd_pr__\w+', x) for x in devices):
        raise ValueError('explicit SKY130 primitive names required')
    if not re.fullmatch(r'(?:tt|ss|ff|sf|fs)(?:_(?:hh|ll|hl|lh))?|hh|ll|hl|lh', section):
        raise ValueError('only nominal MOS/passive sections supported; MC identity is unqualified')
    selected = {family(x + '.spice') for x in devices}
    # The installed and project overlay libraries use this same tree layout.
    root = library.parents[2]
    kept, skipped, active, definitions = {}, {}, set(), set()

    def expand(path, selected_section=None):
        path = path.resolve()
        if not path.is_relative_to(root):
            raise ValueError('include leaves the model tree: ' + str(path))
        if (path, selected_section) in active:
            raise ValueError('recursive model include: ' + str(path))
        key = str(path.relative_to(root))
        fam = family(path)
        if fam and fam != 'sky130_fd_pr__model' and fam not in selected:
            skipped[key] = digest(path)
            return ''
        content = path.read_text()
        kept[key] = digest(path)
        active.add((path, selected_section))
        output, current, found = [], None, False
        for line in content.splitlines(keepends=True):
            stripped = line.strip()
            if not stripped or stripped.startswith('*'):
                if current is None or current == selected_section:
                    output.append(line)
                continue
            words = shlex.split(stripped, comments=False) if stripped.lower().startswith(('.lib ', '.include ', '.inc ', '.endl')) else []
            if words and words[0].lower() == '.lib' and len(words) == 2:
                if current is not None or selected_section is None:
                    raise ValueError('unexpected nested/unselected section: ' + str(path))
                current = words[1].lower()
                found |= current == selected_section
                continue
            if words and words[0].lower() == '.endl':
                if current is None:
                    raise ValueError('unmatched .endl: ' + str(path))
                current = None
                continue
            if current is not None and current != selected_section:
                continue
            if words and words[0].lower() in ('.include', '.inc', '.lib'):
                expected = 3 if words[0].lower() == '.lib' else 2
                if len(words) != expected or any(c in words[1] for c in '{}$'):
                    raise ValueError('unsupported model include: ' + stripped)
                child = Path(words[1])
                if not child.is_absolute():
                    child = path.parent / child
                output.append(expand(child, words[2].lower() if expected == 3 else None))
                continue
            if re.match(r'(?i)^\.(?:control|end)\b', stripped):
                raise ValueError('circuit/control directive inside model library: ' + str(path))
            match = re.match(r'(?i)^\.(?:subckt|model)\s+(\S+)', stripped)
            if match:
                definitions.add(match[1].lower())
            output.append(line)
        if current is not None or (selected_section is not None and not found):
            raise ValueError('unterminated/missing library section: ' + selected_section)
        active.remove((path, selected_section))
        return '* source: ' + key + '\n' + ''.join(output) + '\n'

    body = expand(library, section)
    missing = set(devices) - definitions
    if missing:
        raise ValueError('requested primitive definitions missing: ' + ', '.join(sorted(missing)))
    for key, expected in kept.items():
        if digest(root / key) != expected:
            raise ValueError('model input changed while reducing: ' + key)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=False)
    reduced = out / 'sky130.lib.spice'
    reduced.write_text('.lib ' + section + '\n' + body + '.endl ' + section + '\n')
    manifest = dict(status='nominal_family_reduction_requires_electrical_comparison',
                    original=str(library), original_sha256=digest(library), model_root=str(root),
                    section=section, devices=devices, kept_files=kept, skipped_family_files=skipped,
                    reduced_sha256=digest(reduced), original_kept_bytes=sum((root / p).stat().st_size for p in kept),
                    reduced_bytes=reduced.stat().st_size, generator_sha256=digest(__file__),
                    limits=['explicit primitive family selection; shared definitions retained',
                            'no MC/sample-identity or arbitrary project-netlist dependency inference',
                            'no change to original PDK or automatic bench adoption'])
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return reduced
