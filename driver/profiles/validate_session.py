#!/usr/bin/env python3
"""Hardware validation: >30s continuous session, EOF, and forced helper death."""
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import time
from restoration import assess_restoration
BASE=Path('/sys/kernel/avell_profiles')

def read(name):return json.loads((BASE/name).read_text())
def log(message):print(message,file=sys.stderr,flush=True)

def main():
    if os.geteuid()!=0:raise SystemExit('Execute com sudo.')
    result={'test':'continuous-session-and-crash','sessions':[],'passed':False}
    proc=None
    try:
        for fault in (False,True):
            if read('fan_control')['mode']!='auto':raise RuntimeError('Retorne ao automático antes do teste.')
            record={'test':'helper-killed' if fault else 'continuous-and-eof','before':read('fan_config'),'samples':[]}
            result['sessions'].append(record)
            log('Preparando sessão70%: '+record['test'])
            proc=subprocess.Popen(['/usr/local/libexec/avell-fan','--session','70'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=sys.stderr)
            if not select.select([proc.stdout],[],[],90)[0]:raise RuntimeError('Auxiliar não confirmou início.')
            ready=json.loads(proc.stdout.readline())
            if ready['mode']!='manual':raise RuntimeError('Modo manual não confirmado.')
            record['session_id']=ready['session_id']
            if fault:
                log('Simulando falha do auxiliar. O temporizador do kernel deve restaurar o automático.')
                proc.kill();proc.wait(timeout=5)
                deadline=time.monotonic()+65
                while time.monotonic()<deadline:
                    state=read('fan_control')
                    if state['mode']=='auto':break
                    time.sleep(3)
                if state['mode']!='auto' or state['reason']!='timeout':
                    raise RuntimeError('Retorno após falha não confirmado.')
                record['watchdog_passed']=True
            else:
                start=time.monotonic()
                while time.monotonic()-start<42:
                    proc.stdin.write(b'renew\n');proc.stdin.flush()
                    time.sleep(3)
                    s={'elapsed':round(time.monotonic()-start,1),'control':read('fan_control'),'fans':read('fans')}
                    record['samples'].append(s)
                    if s['control']['mode']!='manual':raise RuntimeError('Sessão contínua interrompida: '+str(s['control']))
                    if s['elapsed']>5 and any(abs(s['fans'][k]-140)>10 for k in ('duty1_raw','duty2_raw')):
                        raise RuntimeError('Potência não mantida.')
                    log(f"Contínuo {s['elapsed']}s: {s['fans']['fan1_rpm']}/{s['fans']['fan2_rpm']} RPM")
                log('Fechando a comunicação, como ao sair do app…')
                proc.stdin.close();proc.wait(timeout=55)
                if proc.returncode:raise RuntimeError('Auxiliar terminou com erro.')
                record['continuous_passed']=True
            record['after']=read('fan_config')
            record['restoration']=assess_restoration(record['before'],record['after'])
            record['exact_match']=record['restoration']['exact_match']
            record['controls_restored']=record['restoration']['controls_restored']
            record['final_control']=read('fan_control')
            if not record['controls_restored'] or record['final_control']['mode']!='auto':
                raise RuntimeError('Controles/tabelas não restaurados; investigar antes de continuar.')
            if record['restoration'].get('observed_bit2_variation'):
                log('Controles restaurados; variação isolada do bit2 de0741 registrada separadamente.')
            proc.stdout.close()
            if not proc.stdin.closed:proc.stdin.close()
            proc=None
            log('Tabelas e controles automáticos confirmados.')
        result['passed']=True
        log('VALIDAÇÃO CONTÍNUA CONCLUÍDA.')
    except BaseException as exc:
        result['error']=str(exc) or type(exc).__name__
        raise
    finally:
        try:
            if proc is not None:
                if not proc.stdin.closed:proc.stdin.close()
                proc.wait(timeout=55)
            (BASE/'fan_control').write_text('auto\n')
            result['final_state']=read('fan_control')
        finally:
            print(json.dumps(result,indent=2),flush=True)

if __name__=='__main__':main()
