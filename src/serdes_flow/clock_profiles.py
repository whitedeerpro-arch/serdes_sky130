"""Normalize uniform-default or explicitly sized extra clock-buffer stages."""
import json
import math


def normalize_extra(profile, count):
    """Return count [wn, wt, r] triples; None means historical 24/16/400."""
    if type(count) is not int or count <= 0:
        raise ValueError('count must be a positive integer')
    if isinstance(profile, str):
        try: profile=json.loads(profile)
        except (ValueError,TypeError) as exc: raise ValueError('invalid stage profile JSON') from exc
    if profile is None: profile=[[24,16,400] for _ in range(count)]
    if not isinstance(profile,list) or len(profile)!=count: raise ValueError('profile stage count mismatch')
    result=[]
    for triple in profile:
        if not isinstance(triple,list) or len(triple)!=3: raise ValueError('each stage must be a three-number list')
        values=[]
        for x in triple:
            if type(x) not in (int,float) or not math.isfinite(x) or x<=0: raise ValueError('stage parameters must be positive finite numbers')
            values.append(int(x) if x==int(x) else x)
        result.append(values)
    return result
