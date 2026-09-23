"""Resolve only the fixed privileged helpers, preferring the packaged installation."""
from pathlib import Path

def helper_path(name):
    if name not in ('avell-fan','avell-profile'):
        raise ValueError('Auxiliar inválido')
    packaged=Path('/usr/lib/avell-thermal/privileged')/name
    return str(packaged if packaged.is_file() else Path('/usr/local/libexec')/name)
