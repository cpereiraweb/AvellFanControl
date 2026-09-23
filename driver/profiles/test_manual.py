#!/usr/bin/env python3
"""Explicit hardware validation: one 70% session and autonomous return to firmware."""
import json
import os
from pathlib import Path
import sys
import time
BASE = Path('/sys/kernel/avell_profiles')

def main():
    if os.geteuid() != 0:
        raise SystemExit('Execute com sudo.')
    control = BASE / 'fan_control'
    data = {'test': 'manual-v2-host-bit-70-percent-30s', 'samples': []}
    def state():
        return json.loads(control.read_text())
    def sample(stage):
        record = dict(stage=stage, time=time.monotonic(), control=state(),
                      fans=json.loads((BASE / 'fans').read_text()))
        data['samples'].append(record)
        print(f"{stage}: {record['control']} | {record['fans']}", file=sys.stderr, flush=True)
    if state()['mode'] != 'auto':
        raise SystemExit('Retorne ao automático antes de testar.')
    sample('before')
    data['config_before'] = json.loads((BASE / 'fan_config').read_text())
    attempted = False
    try:
        print('Preparando 70% nas duas ventoinhas; a programação pode levar alguns segundos…', file=sys.stderr, flush=True)
        attempted = True
        control.write_text('70\n')
        start = time.monotonic()
        for seconds in (3, 10, 20, 35, 45):
            time.sleep(max(0, start + seconds - time.monotonic()))
            sample(f'after_{seconds}s')
        manual_samples = [s for s in data['samples'] if s['control']['mode'] == 'manual']
        later = [s for s in manual_samples if s['stage'] in ('after_10s', 'after_20s')]
        data['power_maintained'] = len(later) == 2 and all(
            abs(s['fans']['duty1_raw'] - 140) <= 10 and abs(s['fans']['duty2_raw'] - 140) <= 10
            for s in later)
        data['autonomous_return'] = state()['mode'] == 'auto'
        if not data['autonomous_return']:
            raise RuntimeError('Retorno automático ainda não confirmado.')
    finally:
        try:
            if attempted:
                print('Conferindo restauração…', file=sys.stderr, flush=True)
                control.write_text('auto\n')
            sample('final')
            data['config_after'] = json.loads((BASE / 'fan_config').read_text())
            data['configuration_restored'] = data['config_before'] == data['config_after']
        finally:
            print(json.dumps(data, indent=2), flush=True)
    print('Coleta concluída; analisar duty, RPM e restauração no JSON.', file=sys.stderr, flush=True)

if __name__ == '__main__':
    main()
