"""Explicit local noise overlays; never modify the installed PDK."""
import hashlib
from pathlib import Path
import re

VARACTOR='sky130_fd_pr__cap_var_lvt'
NOISY_VARACTOR=VARACTOR+'_noisy'


def varactor_rg(source,output):
    """Clone the installed varactor and enable rg Johnson noise.

    ngspice manual3.3.4: behavioral resistors require the noisy=1 flag.
    Keep every electrical expression and original parameter name unchanged;
    rename only the subcircuit header/end so the original remains available.
    This is a simulation overlay, not a new physical varactor revision.
    """
    source,output=Path(source),Path(output)
    text=source.read_text()
    matches=list(re.finditer(r'(?im)^rg\s+p2\s+c1\s+r=.*$',text))
    if len(matches)!=1 or re.search(r'\bnoisy\s*=',matches[0][0],re.I):
        raise ValueError('Varactor rg anchor changed; inspect the model')
    match=matches[0]
    patched=text[:match.start()]+match[0]+' noisy=1'+text[match.end():]
    patched,n=re.subn(r'(?im)^(\.subckt\s+)'+VARACTOR+r'(\s)',r'\g<1>'+NOISY_VARACTOR+r'\2',patched)
    patched,m=re.subn(r'(?im)^(\.ends\s+)'+VARACTOR+r'\b',r'\g<1>'+NOISY_VARACTOR,patched)
    if n!=1 or m!=1:raise ValueError('Varactor header/end changed')
    output.parent.mkdir(parents=True,exist_ok=True)
    if output.exists():raise FileExistsError(output)
    output.write_text(patched)
    return dict(original=str(source),original_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                generated=str(output),generated_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                cell=NOISY_VARACTOR,change='rg noisy=1; header/end alias only',
                manual='https://ngspice.sourceforge.io/docs/ngspice-45-manual.pdf')
