#!/usr/bin/env python3
"""Explicit, root-only 15-second full-fan test. No custom tables or duty writes."""
import json
import os
from pathlib import Path
import sys
import time

BASE = Path('/sys/kernel/avell_profiles')

def main():
    if os.geteuid() != 0:
        raise SystemExit('Execute com sudo.')
    control = BASE / 'fan_boost'
    if control.read_text().strip() != 'auto':
        raise SystemExit('Ventilação máxima já ativa; nenhuma alteração feita.')
    data = {'test': 'full-fan-15s', 'samples': []}
    def sample(stage):
        data['samples'].append(dict(stage=stage, time=time.monotonic(),
            profile=(BASE / 'profile').read_text().strip(),
            mode=control.read_text().strip(),
            fans=json.loads((BASE / 'fans').read_text())))
        print(stage + ': ' + str(data['samples'][-1]['fans']), file=sys.stderr, flush=True)
    sample('before')
    data['config_before'] = json.loads((BASE / 'fan_config').read_text())
    armed = False
    try:
        print('Iniciando ventilação máxima por 15 segundos. Não toque no botão físico.', file=sys.stderr, flush=True)
        armed = True
        control.write_text('test\n')
        start = time.monotonic()
        for elapsed in (2, 7, 12, 18, 23):
            time.sleep(max(0, start + elapsed - time.monotonic()))
            sample(f'after_{elapsed}s')
        data['timer_restored_auto'] = control.read_text().strip() == 'auto'
        if not data['timer_restored_auto']:
            raise RuntimeError('Temporizador não confirmou retorno automático.')
    finally:
        try:
            if armed:
                control.write_text('auto\n')
            sample('final')
            data['config_after'] = json.loads((BASE / 'fan_config').read_text())
            data['config_unchanged'] = data['config_before'] == data['config_after']
        finally:
            print(json.dumps(data, indent=2), flush=True)
    print('Teste concluído; modo automático confirmado.', file=sys.stderr)

if __name__ == '__main__':
    main()
