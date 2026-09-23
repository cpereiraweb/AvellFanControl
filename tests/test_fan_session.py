import importlib.machinery
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from fan_session import FanSession

loader = importlib.machinery.SourceFileLoader('avell_fan_helper', str(Path(__file__).resolve().parents[1]/'driver/profiles/avell-fan'))
spec = importlib.util.spec_from_loader(loader.name, loader)
helper = importlib.util.module_from_spec(spec)
loader.exec_module(helper)

class FakeControl:
    def __init__(self):
        self.writes = []
        self.sid = 9
    def write_text(self, value):
        self.writes.append(value)
    def read_text(self):
        return json.dumps({'mode':'manual','percent':70,'session_id':self.sid})

class SessionTests(unittest.TestCase):
    def test_eof_restores_only_its_session(self):
        control=FakeControl()
        with patch.object(helper,'CONTROL',control), patch.object(helper.select,'select',side_effect=[([],[],[]),([0],[],[]),([0],[],[])]), patch.object(helper.os,'read',side_effect=[b'renew\n',b'']), patch('builtins.print'):
            helper.session('70')
        self.assertEqual(control.writes,['70\n','renew 9\n','auto 9\n'])

    def test_heartbeat_timeout_restores(self):
        control=FakeControl()
        with patch.object(helper,'CONTROL',control), patch.object(helper.select,'select',return_value=([],[],[])), patch('builtins.print'):
            helper.session('70')
        self.assertEqual(control.writes,['70\n','auto 9\n'])

    def test_closed_app_before_auth_does_not_start(self):
        control=FakeControl()
        with patch.object(helper,'CONTROL',control), patch.object(helper.select,'select',return_value=([0],[],[])), patch.object(helper.os,'read',return_value=b''):
            helper.session('70')
        self.assertEqual(control.writes,[])

    def test_invalid_ipc_restores(self):
        control=FakeControl()
        with patch.object(helper,'CONTROL',control), patch.object(helper.select,'select',side_effect=[([],[],[]),([0],[],[])]), patch.object(helper.os,'read',return_value=b'run arbitrary\n'), patch('builtins.print'):
            with self.assertRaises(ValueError):
                helper.session('70')
        self.assertEqual(control.writes,['70\n','auto 9\n'])

    def test_old_helper_does_not_cancel_a_new_session(self):
        control=FakeControl()
        def eof(fd,n):
            control.sid=10
            return b''
        with patch.object(helper,'CONTROL',control), patch.object(helper.select,'select',side_effect=[([],[],[]),([0],[],[])]), patch.object(helper.os,'read',side_effect=eof), patch('builtins.print'):
            helper.session('70')
        self.assertEqual(control.writes,['70\n'])

    def test_invalid_percent_never_authenticates(self):
        s=FanSession()
        with patch('fan_session.subprocess.Popen') as launch:
            for value in (-1,0,45,71,101,True,'70'):
                with self.assertRaises(ValueError):s.start(value)
            launch.assert_not_called()

    def test_shutdown_rejects_new_session(self):
        s=FanSession();s.shutdown()
        with patch('fan_session.subprocess.Popen') as launch:
            with self.assertRaises(RuntimeError):s.start(70)
            launch.assert_not_called()
