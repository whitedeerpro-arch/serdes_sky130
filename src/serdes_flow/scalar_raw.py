"""Read scalar real observables from binary DC/AC raw files.

AC plots retain the complex flag even for real()/imag()-derived observables.
Reject truncation, multiple points and observables with an imaginary part;
this deliberately does not turn complex waveforms into real time series.
"""
import gzip
from pathlib import Path

import numpy as np


def read(path, *, frequency_hz=None):
    path=Path(path);opener=gzip.open if path.suffix=='.gz' else open
    header,names={},[]
    with opener(path,'rb') as f:
        while True:
            line=f.readline()
            if not line:raise ValueError('missing binary raw section')
            text=line.decode('latin1').strip()
            if text=='Variables:':
                for i in range(int(header['No. Variables'])):
                    fields=f.readline().decode('latin1').split()
                    if len(fields)<3 or int(fields[0])!=i:raise ValueError('bad raw variable table')
                    name=fields[1]
                    if name.startswith(('v(','i(')) and name.endswith(')'):name=name[2:-1]
                    names.append(name)
            elif text=='Binary:':
                payload=f.read();break
            elif text=='Values:':raise ValueError('expected binary raw')
            else:
                k,_,v=text.partition(':');header[k.strip()]=v.strip()
    flags=header.get('Flags','').split()
    if 'fastaccess' in flags or int(header.get('No. Points',0))!=1 or len(names)!=int(header['No. Variables']):
        raise ValueError('expected one complete interleaved scalar plot')
    dtype='<c16' if 'complex' in flags else '<f8'
    if len(payload)!=len(names)*np.dtype(dtype).itemsize:raise ValueError('truncated/extra scalar payload')
    values=np.frombuffer(payload,dtype=dtype)
    if not np.all(np.isfinite(values)):raise ValueError('non-finite scalar observable')
    if np.any(np.abs(np.imag(values))>1e-20):raise ValueError('observable is complex, not a real scalar')
    values=np.real(values)
    if len(set(names))!=len(names):raise ValueError('duplicate scalar vector names')
    result=dict(zip(names,map(float,values)))
    if frequency_hz is not None and ('frequency' not in result or not np.isclose(result['frequency'],frequency_hz,rtol=1e-12,atol=0)):
        raise ValueError('wrong scalar AC frequency')
    return result
