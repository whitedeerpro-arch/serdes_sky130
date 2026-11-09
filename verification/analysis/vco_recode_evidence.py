"""Evidence-bounded behavioral slow-end search and adjacent VCO re-coding.

Uses measured bracketed 2 GHz crossings and linear temperature interpolation
within each measured segment. No physical startup or dynamic budget claim.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

_spec = importlib.util.spec_from_file_location('vco_control_windows', Path(__file__).with_name('vco_control_windows.py'))
windows = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(windows)
TEMPS = (-40, 27, 85)
MARGIN = .020


def interp(a, b, t, lo, hi):
    if not lo <= t <= hi: raise ValueError('temperature extrapolation forbidden')
    return a + (b-a)*(t-lo)/(hi-lo)


def feasible_interval(v0, v1, lo, hi, t0, t1):
    """Exact temperature interval where a linear trace lies in the window."""
    if v0 == v1: return [t0, t1] if lo <= v0 <= hi else None
    a = t0 + (lo-v0)*(t1-t0)/(v1-v0)
    b = t0 + (hi-v0)*(t1-t0)/(v1-v0)
    left, right = max(t0, min(a, b)), min(t1, max(a, b))
    return [left, right] if left <= right else None


def trace_at(points, code, t):
    if t in TEMPS:
        return points.get(code, {}).get(t)
    for t0, t1 in zip(TEMPS, TEMPS[1:]):
        if t0 < t < t1:
            row = points.get(code, {})
            if t0 not in row or t1 not in row: return None
            return interp(row[t0], row[t1], t, t0, t1)
    raise ValueError('temperature outside range')


def segment_at(points, code, t, t0, t1):
    row = points.get(code, {})
    if t0 not in row or t1 not in row:
        return None
    return interp(row[t0], row[t1], t, t0, t1)


def startup(points, t, vlo, vhi):
    tested = []
    for code in range(15, -1, -1):
        v = trace_at(points, code, t)
        if v is None:
            return dict(status='unknown_missing_evidence', reason='startup_code_unbracketed', code=code, examined=tested)
        tested.append(dict(code=code, vctrl=v))
        if v <= vhi:
            if v < vlo:
                return dict(status='window_violation_under_model', reason='first_upper_stop_below_lower_edge', code=code, vctrl=v, examined=tested)
            return dict(status='evidenced', code=code, vctrl=v, lower_room_v=v-vlo, upper_room_v=vhi-v, examined=tested)
    return dict(status='window_violation_under_model', reason='no_upper_stop_among_all_codes', examined=tested)


def segments(points, vlo, vhi, margin):
    out = []
    for t0, t1 in zip(TEMPS, TEMPS[1:]):
        for code in range(16):
            row = points.get(code, {})
            if t0 not in row or t1 not in row:
                out.append(dict(code=code, temperature=[t0,t1], status='unknown_missing_evidence',
                                missing_endpoints=[t for t in (t0,t1) if t not in row]))
                continue
            v0, v1 = row[t0], row[t1]
            item = dict(code=code, temperature=[t0,t1], status='measured_segment_interpolated',
                        vctrl_endpoints=[v0,v1], feasible_temperature=feasible_interval(v0,v1,vlo,vhi,t0,t1), crossings=[])
            for edge, threshold, nextcode in (('upper',vhi,code-1), ('lower',vlo,code+1)):
                if v0 == v1 or not min(v0,v1) <= threshold <= max(v0,v1): continue
                t = t0 + (threshold-v0)*(t1-t0)/(v1-v0)
                event = dict(edge=edge, temperature=t, next_code=nextcode)
                if not 0 <= nextcode <= 15:
                    event.update(status='window_violation_under_model', reason='code_limit')
                else:
                    dest = segment_at(points,nextcode,t,t0,t1)
                    if dest is None:
                        event.update(status='unknown_missing_evidence', reason='adjacent_code_unbracketed')
                    else:
                        room = dest-vlo if edge=='upper' else vhi-dest
                        inside = vlo <= dest <= vhi
                        event.update(landing_v=dest, opposite_edge_room_v=room,
                                     status='evidenced' if inside and room >= margin else ('margin_shortfall' if inside else 'window_violation_under_model'),
                                     reason='opposite_edge_room_below_assumption' if inside and room < margin else ('landing_outside_window' if not inside else None))
                item['crossings'].append(event)
            out.append(item)
    return out


def run_profile(points, start, profile, vlo, vhi, margin):
    init = startup(points,start,vlo,vhi)
    if init['status'] != 'evidenced': return dict(status=init['status'], reason=init['reason'], startup=init, events=[])
    code = init['code']; events=[]
    for a,b in zip(profile,profile[1:]):
        now = float(a)
        for _ in range(64):
            t0,t1 = sorted((a,b))
            v0, v1 = segment_at(points,code,now,t0,t1), segment_at(points,code,b,t0,t1)
            if v0 is None or v1 is None:
                return dict(status='unknown_missing_evidence', reason='active_code_segment_unbracketed', code=code, temperature=[now,b], startup=init, events=events)
            # A segment may start exactly on an edge; only movement outwards triggers a switch.
            target = vhi if v1 > vhi else (vlo if v1 < vlo else None)
            if target is None: break
            if v1 == v0: return dict(status='window_violation_under_model',reason='outside_window',startup=init,events=events)
            t = now + (target-v0)*(b-now)/(v1-v0)
            if not min(now,b)-1e-9 <= t <= max(now,b)+1e-9:
                return dict(status='window_violation_under_model',reason='outside_window',startup=init,events=events)
            upper = target == vhi
            dest = code-1 if upper else code+1
            event = dict(temperature=t, edge='upper' if upper else 'lower', old_code=code, new_code=dest)
            if not 0 <= dest <= 15:
                events.append(event); return dict(status='window_violation_under_model',reason='code_limit',startup=init,events=events)
            landing = segment_at(points,dest,t,t0,t1)
            if landing is None:
                events.append(event); return dict(status='unknown_missing_evidence',reason='adjacent_code_unbracketed',startup=init,events=events)
            room = landing-vlo if upper else vhi-landing
            event.update(landing_v=landing,opposite_edge_room_v=room);events.append(event)
            if not vlo <= landing <= vhi or room < margin:
                return dict(status='window_violation_under_model' if not vlo <= landing <= vhi else 'margin_shortfall',reason='landing_outside_window' if not vlo <= landing <= vhi else 'opposite_edge_room_below_assumption',startup=init,events=events)
            code, now = dest, t
        else:
            return dict(status='window_violation_under_model',reason='excessive_switches',startup=init,events=events)
    return dict(status='evidenced_under_model',startup=init,events=events,final_code=code)


def analyse(static, margin=MARGIN):
    from serdes_flow.corners import Condition
    points = {}
    ambiguous = []
    excluded = []
    for cond,row in static['conditions'].items():
        tag,rc=cond.split(':'); c=Condition.parse(tag); chip=f'{c.process}_v{round(c.supply*1000)}:{rc}'
        for code, curve in row['curves'].items():
            xs=curve['crossings']
            if len(xs)==1 and xs[0]['kvco_hz_per_v'] > 0:
                points.setdefault(chip,{}).setdefault(int(code),{})[c.temp]=xs[0]['v']
            elif len(xs)==1:
                excluded.append(dict(condition=cond,code=int(code),reason='nonpositive_kvco',crossing=xs[0]))
            elif len(xs)>1: ambiguous.append(dict(condition=cond,code=int(code),crossings=xs))
    result={}
    for chip in static['fixed_three_temperature']:
        supply=int(chip.split('_v')[1].split(':')[0])/1000
        data=points.get(chip,{})
        result[chip]={}
        for hi_code,drop in windows.DROPS.items():
            vlo,vhi=windows.VLO,supply-drop
            profiles={
                'cold_hot_cold':[-40,27,85,27,-40],
                'hot_cold_hot':[85,27,-40,27,85],
                'room_hot_cold_room':[27,85,27,-40,27],
                'room_cold_hot_room':[27,-40,27,85,27],
            }
            result[chip][hi_code]=dict(vlo=vlo,vhi=vhi,
                startups={str(t):startup(data,t,vlo,vhi) for t in TEMPS},
                segments=segments(data,vlo,vhi,margin),
                profiles={name:run_profile(data,profile[0],profile,vlo,vhi,margin) for name,profile in profiles.items()})
    event_summary = {}
    for hi_code in windows.DROPS:
        events = []
        all_segments = []
        for chip, choices in result.items():
            for segment in choices[hi_code]['segments']:
                all_segments.append(segment)
                for event in segment.get('crossings', []):
                    events.append(dict(chip=chip, code=segment['code'], temperature_interval=segment['temperature'], **event))
        landed = [e for e in events if 'opposite_edge_room_v' in e]
        event_summary[hi_code] = dict(measured_segments=sum(s['status']=='measured_segment_interpolated' for s in all_segments),
                                      segments_missing_evidence=sum(s['status']=='unknown_missing_evidence' for s in all_segments),
                                      events=len(events), landing_evidenced=len(landed),
                                      missing_adjacent=sum(e['status']=='unknown_missing_evidence' for e in events),
                                      minimum_opposite_room_event=min(landed,key=lambda e:e['opposite_edge_room_v']) if landed else None)
    return dict(scope='static ideal thresholds and 30fF/leg proxy; no startup transient, dynamic budget, mismatch or noise qualification',
                model='only same-chip same-code measured bracketed 2 GHz crossings; temperature piecewise linear between measured anchors; adjacent code switching',
                startup_model='runtime-window slow-end simplified coverage only; no class stop thresholds or back-one; not an RTL strategy model',
                margin_v=margin, source_path=static['source_path'], source_sha256=static['source_sha256'],
                fill_path=static['fill_path'], fill_sha256=static['fill_sha256'],
                analyzer_path=str(Path(__file__).resolve()), analyzer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                crossing_analyzer_path=str(Path(windows.__file__).resolve()), crossing_analyzer_sha256=hashlib.sha256(Path(windows.__file__).read_bytes()).hexdigest(),
                fill_partial_rows=static['partial_rows'],ambiguous_crossings=ambiguous,excluded_crossings=excluded,
                boundary_summary=event_summary,chips=result)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source',type=Path,required=True);ap.add_argument('--fill',type=Path,required=True);ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args()
    static=windows.analyse(json.loads(a.source.read_text()),json.loads(a.fill.read_text()),windows.sha(a.source),windows.sha(a.fill),a.source,a.fill)
    data=analyse(static)
    a.out.parent.mkdir(parents=True,exist_ok=True)
    with a.out.open('x') as f:json.dump(data,f,indent=2,allow_nan=False);f.write('\n')
    print(f'{a.out}: {len(data["chips"])} chips; partial rows {len(data["fill_partial_rows"])}')


if __name__=='__main__':main()
