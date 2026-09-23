#!/usr/bin/env python3
"""User-only migration of the prototype shortcut; never touch unrelated shortcuts."""
import os
from pathlib import Path
import time

if os.geteuid()==0:
    raise SystemExit('Execute como usuário comum, sem sudo.')
project=Path(__file__).resolve().parents[1]
entry=Path.home()/'.local/share/applications/br.dev.avell.Thermal.desktop'
system=Path('/usr/share/applications/br.dev.avell.Thermal.desktop')
if not system.is_file():raise SystemExit('Instale o pacote antes de migrar o atalho.')
if entry.exists():
    expected='Exec=/usr/bin/python3 '+str(project/'app.py')
    if expected not in entry.read_text().splitlines():
        raise SystemExit('Atalho local diferente do protótipo; preservado para revisão.')
    saved=entry.with_name(entry.name+'.prototype-backup-'+str(time.time_ns()))
    entry.rename(saved)
    print('Atalho antigo arquivado:',saved)
else:print('Atalho de sistema já tem prioridade.')
