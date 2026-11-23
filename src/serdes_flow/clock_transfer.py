"""Complete causal clock-event coverage within an explicitly bounded input span.

Published delays are observational; event coverage and amplitude gates are
separate. A low-amplitude periodic signal is not declared a qualified clock.
"""
import numpy as np

from . import clock,stage_metrics


def analyze(t,yin,yout,input_start,input_stop,max_delay,*,minimum_pp_v=None):
    """Every input event in [start,stop] needs exactly one causal output event.

    The waveform must extend max_delay after input_stop, so the last required
    event has its full response interval. Outputs near the left boundary may
    belong to an earlier input; they are associated but not counted as core
    inputs. This avoids silently accepting a lost first or last required edge.
    """
    if input_stop<=input_start or input_stop+max_delay>t[-1]:raise ValueError('incomplete clock-transfer response window')
    result=stage_metrics.propagation(t,yin,yout,input_start,input_stop+max_delay,max_delay)
    for polarity,label in ((1,'rising'),(-1,'falling')):
        required=clock.edges(t,yin,polarity,input_start,input_stop)
        mapped=np.asarray(result[label]['input_times_s'])
        if len(required)<3:raise ValueError('insufficient required input events')
        counts=[int(np.count_nonzero(np.abs(mapped-ref)<1e-18)) for ref in required]
        if any(n!=1 for n in counts):raise ValueError(f'{label}: first/intermediate/last input event lacks unique output')
        result[label]['required_input_events']=len(required)
        result[label]['required_input_times_s']=required.tolist()
    cycles=clock.cycle_amplitudes(t,yout,input_start,input_stop+max_delay)
    if cycles is None:raise ValueError('no complete output clock cycles')
    amplitude_pass=None if minimum_pp_v is None else bool(cycles['min_pp_v']>=minimum_pp_v)
    return dict(input_window_s=[input_start,input_stop],output_observation_stop_s=input_stop+max_delay,
                max_causal_delay_s=max_delay,edges_complete=True,output_cycles=cycles,
                minimum_pp_gate_v=minimum_pp_v,amplitude_pass=amplitude_pass,
                clock_qualified=bool(amplitude_pass) if minimum_pp_v is not None else None,
                propagation=result)
