import numpy as np
import pytest

from serdes_flow import serial


def waveform(bits, delay=.2):
    t=np.linspace(-1, len(bits)+2, (len(bits)+3)*1000+1)
    indices=np.floor(t-delay).astype(int)
    levels=2*np.asarray(bits,dtype=int)-1
    y=.2*levels[np.clip(indices,0,len(bits)-1)]
    return t,y


def test_fixed_phase_matches_edges_and_samples_without_training(monkeypatch):
    bits=np.array([0,0,1,1,0,1,1,0,0,1,0,0]);t,y=waveform(bits)
    monkeypatch.setattr(serial,'_training_delay',lambda *a: (_ for _ in ()).throw(AssertionError('training called')))
    m,d=serial.fixed_phase_window(t,y,serial.Sequence(bits,0,1),delay_ui=.2,first_bit=2,end_bit=10)
    assert m['functional'] and m['phase_fitted'] is False and m['scope']=='local_window_only'
    assert m['bit_errors']==m['missing_transitions']==m['extra_crossings']==0
    assert d['bit_index']==list(range(2,10))
    assert d['payload_transition_bits']==[2,4,5,7,9]
    assert max(abs(x) for x in d['edge_residual_ui'])<.002
    assert min(d['signed_margin_v'])==pytest.approx(.2)


def test_missing_transition_and_extra_crossings_are_reported():
    bits=np.array([0,0,1,1,0,1,1,0,0,1,0,0]);t,y=waveform(bits)
    y[(t>=4.2)&(t<5.2)]=.2  # suppress expected falling edge at bit 4
    y[(t>=6.4)&(t<6.5)]=-.2  # unrequested short negative pulse
    m,d=serial.fixed_phase_window(t,y,serial.Sequence(bits,0,1),delay_ui=.2,first_bit=2,end_bit=10)
    assert not m['functional']
    assert m['missing_transitions']>=1
    assert m['extra_crossings']>=2
    assert 4 not in d['payload_transition_bits']


def test_incomplete_samples_or_matching_window_are_rejected():
    bits=np.array([0,0,1,1,0,1,1,0,0,1,0,0]);t,y=waveform(bits)
    seq=serial.Sequence(bits,0,1)
    for keep in (t>=1.9,t<=9.6):
        with pytest.raises(ValueError,match='coverage'):
            serial.fixed_phase_window(t[keep],y[keep],seq,delay_ui=.2,first_bit=2,end_bit=10)


def test_fixed_phase_is_not_refitted_to_shifted_payload():
    bits=np.array([0,0,1,1,0,1,1,0,0,1,0,0]);t,y=waveform(bits,delay=.5)
    seq=serial.Sequence(bits,0,1)
    actual,_=serial.fixed_phase_window(t,y,seq,delay_ui=.5,first_bit=2,end_bit=10)
    wrong,details=serial.fixed_phase_window(t,y,seq,delay_ui=.2,first_bit=2,end_bit=10)
    assert actual['functional'] and wrong['delay_ui']==.2
    assert min(details['edge_residual_ui'])==pytest.approx(.3,abs=.002)
    assert wrong['phase_fitted'] is False


def test_historical_matching_preserves_half_open_extra_span():
    bits=np.array([0,0,1,1,0,1,1,0,0,1,0,0]);t,y=waveform(bits)
    edge_t,edge_pol=serial.crossings(t,y);seq=serial.Sequence(bits,0,1)
    residual,transitions,missing,extra=serial._match_edges(edge_t,edge_pol,seq,.2,2,10)
    assert transitions==[2,4,5,7,9]
    assert missing==extra==0
    assert np.max(np.abs(residual))<.002


@pytest.mark.parametrize('dtype', [np.uint8, np.bool_])
def test_unsigned_and_boolean_bits_match_signed_results(dtype):
    bits=np.array([0,0,1,1,0,1,1,0,0,1,0,0]);t,y=waveform(bits)
    signed=serial.fixed_phase_window(t,y,serial.Sequence(bits,0,1),delay_ui=.2,first_bit=2,end_bit=10)
    converted=serial.fixed_phase_window(t,y,serial.Sequence(bits.astype(dtype),0,1),delay_ui=.2,first_bit=2,end_bit=10)
    assert converted==signed
    assert converted[0]['functional']
    assert min(converted[1]['signed_margin_v'])==pytest.approx(.2)


def test_fractional_bits_rejected_before_integer_conversion():
    bits=np.array([0.,0.,1.,1.,.5,1.,1.,0.,0.,1.]);t,y=waveform(np.rint(bits))
    with pytest.raises(ValueError,match='invalid sequence'):
        serial.fixed_phase_window(t,y,serial.Sequence(bits,0,1),delay_ui=.2,first_bit=2,end_bit=9)


def test_scalar_bits_rejected_cleanly():
    t=np.array([0.,1.]);y=np.array([-.2,.2])
    with pytest.raises(ValueError,match='one-dimensional'):
        serial.fixed_phase_window(t,y,serial.Sequence(np.array(1),0,1),delay_ui=.2,first_bit=1,end_bit=2)


def test_nonfinite_waveform_and_bits_are_rejected():
    bits=np.array([0,0,1,1,0,1,1,0,0,1,0,0],dtype=float);t,y=waveform(bits)
    bad=y.copy();bad[4]=np.nan
    with pytest.raises(ValueError,match='waveform'):
        serial.fixed_phase_window(t,bad,serial.Sequence(bits,0,1),delay_ui=.2,first_bit=2,end_bit=10)
    bits[4]=np.nan
    with pytest.raises(ValueError,match='invalid sequence'):
        serial.fixed_phase_window(t,y,serial.Sequence(bits,0,1),delay_ui=.2,first_bit=2,end_bit=10)
