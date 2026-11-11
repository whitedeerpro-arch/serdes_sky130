"""Exact additive series implementation of an already bounded voltage PWL.

Plateau segments shorten the tables scanned by each ngspice voltage source.
This generalizes the retime-demand series renderer without changing archived
campaign code or its compression tolerance.
"""
import numpy as np


def parts(t,y,count):
    t,y=np.asarray(t,dtype=float),np.asarray(y,dtype=float)
    if (t.ndim!=1 or t.shape!=y.shape or len(t)<2 or t[0]!=0 or
            not np.all(np.isfinite(t)) or not np.all(np.isfinite(y)) or
            np.any(np.diff(t)<=0) or type(count) is not int or count<1):
        raise ValueError('invalid compressed PWL')
    actual=min(count,len(t)-1);bounds=np.linspace(0,len(t)-1,actual+1,dtype=int);out=[]
    for index,(a,b) in enumerate(zip(bounds[:-1],bounds[1:])):
        tt=t[a:b+1].copy();yy=y[a:b+1].copy() if index==0 else y[a:b+1]-y[a]
        if a:tt,yy=np.r_[0.,tt],np.r_[0.,yy]
        out.append((tt,yy))
    out.extend([(np.array([0.,t[-1]]),np.array([0.,0.])) for _ in range(count-actual)])
    error=float(np.max(np.abs(sum((np.interp(t,a,b) for a,b in out),np.zeros_like(y))-y)))
    if error>1e-12:raise ValueError('inexact additive PWL reconstruction')
    return out,error


def declarations(node,prefix,count):
    lines=[]
    for i in range(count):
        left=node if i==0 else f'{prefix}_node{i}'
        right='0' if i==count-1 else f'{prefix}_node{i+1}'
        lines.append(f'{prefix}_{i} {left} {right} PWL(0 0 1n 0)')
    return lines


def commands(prefix,segments):
    result=[]
    for i,(t,y) in enumerate(segments):
        source=f'{prefix}_{i}';values=np.column_stack((t,y)).ravel()
        result.append(f'alter {source} dc={y[0]:.17e}')
        if len(values)<=360:
            result.append('alter @'+source+'[pwl] = [ '+' '.join(f'{v:.17e}' for v in values)+' ]')
        else:
            result += [f'let replay_pwl=vector({len(values)})']+[f'let replay_pwl[{j}]={v:.17e}' for j,v in enumerate(values)]
            result += ['alter @'+source+'[pwl] = replay_pwl','unlet replay_pwl']
    return result
