"""Worked example: add contact columns without changing inverter W/L or nets.

Only an untouched student builder in a prepared DS-01 sandbox is modified.
"""
import argparse
import json
from pathlib import Path

from run import BUILDER, sha, verify


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('workspace', type=Path)
    a = p.parse_args()
    work = a.workspace.resolve()
    manifest = verify(work)
    target = work / 'student' / BUILDER
    if sha(target) != manifest['inputs_sha256'][str(BUILDER)]:
        raise ValueError('student has edited the builder; preserve that work and prepare a new sandbox')
    text = target.read_text()
    original = '''    for x, y, kind in ((1.80, 3.00, "n"), (4.15, 3.00, "n"),
                       (1.80, 9.50, "p"), (4.15, 13.50, "p")):
        t.append(f"CF {'ndiffc' if kind == 'n' else 'pdiffc'} {x} {y}")
        t.append(f"VIA {x} {y}")'''
    replacement = '''    # Contact pitch must satisfy BOTH diffusion-contact and mcon spacing.
    # A continuous LI/M1 column joins the contacts and avoids tiny isolated
    # metal islands. Device diffusion and channel geometry remain unchanged.
    for x, low, high, kind in ((1.80, NY1, NY2, "n"), (4.15, NY1, NY2, "n"),
                               (1.80, PY1, PY2, "p"), (4.15, PY1, PY2, "p")):
        count = int((high - low - 0.70) / 0.40 + 1e-8) + 1
        centers = [round(low + 0.35 + 0.40 * k, 4) for k in range(count)]
        for y in centers:
            t.append(f"CF {'ndiffc' if kind == 'n' else 'pdiffc'} {x} {y}")
            t.append(f"VIA {x} {y}")
        for layer in ("locali", "m1"):
            t.append(f"R {layer} {x - .175} {centers[0] - .175} {x + .175} {centers[-1] + .175}")'''
    if text.count(original) != 1:
        raise ValueError('seed contact block changed; review the new geometry first')
    target.write_text(text.replace(original, replacement))
    plan = dict(nfet_contacts_per_source_or_drain=9, pfet_contacts_per_source_or_drain=19,
                sd_contacts_total=56, contact_pitch_um=.40, edge_margin_um=.35,
                nfet_total_w_um=4, pfet_total_w_um=8, channel_l_um=.15, fingers=1,
                scope='Contact coverage exercise; no current-capacity or speed qualification')
    (work / 'student/contact_plan.json').write_text(json.dumps(plan, indent=2) + '\n')
    print('Modified only', target)
    print(json.dumps(plan, indent=2))


if __name__ == '__main__':
    main()
