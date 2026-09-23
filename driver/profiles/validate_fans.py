#!/usr/bin/env python3
"""Explicit hardware checks, never called automatically by the app."""
import json
import os
from pathlib import Path
import sys
import time
BASE = Path('/sys/kernel/avell_profiles')
CONTROL = BASE / 'fan_control'

def read(name):
    return json.loads((BASE / name).read_text())

def say(message):
    print(message, file=sys.stderr, flush=True)

def main():
    if os.geteuid() != 0:
        raise SystemExit('Execute com sudo.')
    result = {'test': 'fan-validation-50-70-100', 'sessions': [], 'passed': False}
    try:
        for percent, timeout in ((50, False), (70, True), (100, False)):
            if read('fan_control')['mode'] != 'auto':
                raise RuntimeError('Há uma sessão ativa; retorne ao automático.')
            session = {'percent': percent, 'samples': []}
            result['sessions'].append(session)
            say(f'[{len(result["sessions"])}/3] Capturando configuração antes de {percent}%…')
            session['before'] = read('fan_config')
            session['before_fans'] = read('fans')
            attempted = False
            try:
                attempted = True
                say(f'Preparando {percent}%. Aguarde as escritas/verificações; não use o botão físico nem o app.')
                CONTROL.write_text(f'{percent}\n')
                start = time.monotonic()
                for second in ((3, 10, 20, 36, 45) if timeout else (3, 10)):
                    time.sleep(max(0, start + second - time.monotonic()))
                    sample = {'after_s': second, 'control': read('fan_control'), 'fans': read('fans')}
                    session['samples'].append(sample)
                    f = sample['fans']
                    say(f'{percent}% +{second}s: {sample["control"]["mode"]}; duty {f["duty1_raw"]}/{f["duty2_raw"]}; RPM {f["fan1_rpm"]}/{f["fan2_rpm"]}')
                    if second in (10, 20):
                        if sample['control']['mode'] != 'manual' or any(abs(f[k] - percent*2) > 10 for k in ('duty1_raw', 'duty2_raw')):
                            raise RuntimeError('Potência não mantida ou proteção acionada; interrompendo validação.')
                if timeout:
                    s = read('fan_control')
                    session['timer_passed'] = s['mode'] == 'auto' and s['reason'] == 'timeout'
                    if not session['timer_passed']:
                        raise RuntimeError('Retorno por temporizador não confirmado.')
                else:
                    say('Cancelando manualmente para testar o botão Automático…')
            finally:
                if attempted:
                    CONTROL.write_text('auto\n')
                session['after'] = read('fan_config')
                session['restored'] = session['before'] == session['after']
                session['final_control'] = read('fan_control')
                session['after_fans'] = read('fans')
                say(f'Restauração da sessão {percent}%: {session["restored"]}')
            if not session['restored'] or session['final_control']['mode'] != 'auto':
                raise RuntimeError('A configuração não voltou exatamente ao estado inicial; investigar antes de prosseguir.')
            time.sleep(3)
        result['passed'] = True
        say('VALIDAÇÃO CONCLUÍDA: três potências, cancelamento e retorno temporizado confirmados.')
    except BaseException as exc:
        result['error'] = str(exc) or type(exc).__name__
        say('Validação interrompida: ' + result['error'])
        raise
    finally:
        print(json.dumps(result, indent=2), flush=True)

if __name__ == '__main__':
    main()
