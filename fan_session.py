"""Unprivileged client for the root-owned fan session helper."""
from paths import helper_path
import json
import select
import subprocess
import threading
import time

class FanSession:
    def __init__(self):
        self.process = None
        self.thread = None
        self.stop_event = threading.Event()
        self.last_touch = time.monotonic()
        self.closing = False
        self.lock = threading.Lock()

    def touch(self):
        self.last_touch = time.monotonic()

    def start(self, percent):
        if type(percent) is not int or percent not in range(50, 101, 5):
            raise ValueError('Potência inválida.')
        self.stop(wait=True)
        with self.lock:
            if self.closing:
                raise RuntimeError('Aplicativo encerrando.')
            self.stop_event.clear()
            p = subprocess.Popen(['/usr/bin/pkexec', helper_path('avell-fan'), '--session', str(percent)],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.process = p
        try:
            deadline = time.monotonic() + 120
            line = b''
            while b'\n' not in line:
                if self.closing or self.stop_event.is_set():
                    raise RuntimeError('Sessão cancelada.')
                if time.monotonic() >= deadline:
                    raise TimeoutError('Tempo de autenticação/aplicação excedido.')
                if not select.select([p.stdout], [], [], 0.5)[0]:
                    continue
                chunk = p.stdout.read1(4096)
                if not chunk:
                    raise RuntimeError('Sessão não iniciada: autenticação cancelada, temperatura alta ou driver indisponível.')
                line += chunk
                if len(line) > 4096:
                    raise RuntimeError('Resposta inválida do auxiliar.')
            state = json.loads(line)
            if state['mode'] != 'manual' or state['percent'] != percent:
                raise RuntimeError('Controle manual não confirmado.')
            self.touch()
            self.thread = threading.Thread(target=self._heartbeat, args=(p,), daemon=True)
            self.thread.start()
        except BaseException:
            self.stop(wait=True)
            raise

    def _heartbeat(self, p):
        try:
            while not self.stop_event.wait(3):
                if p.poll() is not None or time.monotonic() - self.last_touch > 10:
                    break
                p.stdin.write(b'renew\n')
                p.stdin.flush()
        except (OSError, ValueError):
            pass
        finally:
            try:
                p.stdin.close()
            except (OSError, ValueError):
                pass
            try:
                p.wait(timeout=50)
            except subprocess.TimeoutExpired:
                # No more renewals. Kernel lease still bounds the manual session.
                pass

    def stop(self, wait=False):
        self.stop_event.set()
        p = self.process
        if p is None:
            return
        try:
            p.stdin.close()  # EOF requests automatic restoration; no new authentication.
        except (OSError, ValueError):
            pass
        if wait:
            p.wait(timeout=55)
            if self.thread and self.thread is not threading.current_thread():
                self.thread.join(timeout=2)
            p.stdout.close()
            p.stderr.close()
            self.process = None
            self.thread = None

    def shutdown(self):
        with self.lock:
            self.closing = True
        self.stop(wait=False)

    def active(self):
        return self.process is not None and self.process.poll() is None and not self.stop_event.is_set()

SESSION = FanSession()
