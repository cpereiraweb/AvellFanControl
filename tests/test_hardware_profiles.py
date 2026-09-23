import unittest
from unittest.mock import patch
import backend


class HardwareProfilesTests(unittest.TestCase):
    def test_unknown_firmware_state_is_unavailable(self):
        with patch('backend.read', return_value='unknown'):
            self.assertIsNone(backend.hardware_profile())

    def test_invalid_request_cannot_launch_privileged_helper(self):
        with patch('backend.subprocess.run') as run:
            with self.assertRaises(ValueError):
                backend.set_hardware_profile('0x40')
            run.assert_not_called()

    def test_missing_driver_cannot_launch_helper(self):
        with patch('backend.hardware_profile', return_value=None), patch('backend.subprocess.run') as run:
            with self.assertRaises(RuntimeError):
                backend.set_hardware_profile('turbo')
            run.assert_not_called()

    def test_success_requires_readback(self):
        with patch('backend.hardware_profile', side_effect=['turbo', 'balanced']), patch('backend.subprocess.run') as run:
            run.return_value.returncode = 0
            backend.set_hardware_profile('balanced')
            self.assertEqual(run.call_args.args[0], ['/usr/bin/pkexec', backend.HARDWARE_HELPER, 'balanced'])

    def test_readback_mismatch_is_failure(self):
        with patch('backend.hardware_profile', return_value='turbo'), patch('backend.subprocess.run') as run:
            run.return_value.returncode = 0
            with self.assertRaises(RuntimeError):
                backend.set_hardware_profile('balanced')

    def test_authentication_cancel_is_failure(self):
        with patch('backend.hardware_profile', return_value='turbo'), patch('backend.subprocess.run') as run:
            run.return_value.returncode = 126
            run.return_value.stderr = ''
            with self.assertRaises(RuntimeError):
                backend.set_hardware_profile('balanced')


class FanTelemetryTests(unittest.TestCase):
    def test_unavailable_is_not_zero_rpm(self):
        for value in (None, '{}', 'invalid', '{"fan1_rpm": 3000}',
                      '{"fan1_rpm": -1, "fan2_rpm": 2000}'):
            with patch('backend.read', return_value=value):
                self.assertEqual(backend.hardware_fans(), [])

    def test_two_real_readings_and_stopped_fan(self):
        with patch('backend.read', return_value='{"fan1_rpm": 3000, "fan2_rpm": 0}'):
            self.assertEqual([s['value'] for s in backend.hardware_fans()], [3000, 0])


class ManualControlTests(unittest.TestCase):
    def test_rejects_invalid_power_before_authentication(self):
        for value in (0, 49, 101, 71, True, '70', '--help'):
            with patch('backend.subprocess.run') as run:
                with self.assertRaises(ValueError):
                    backend.set_fan_power(value)
                run.assert_not_called()

    def test_missing_driver_does_not_authenticate(self):
        with patch('backend.fan_control_state', return_value=None), patch('backend.subprocess.run') as run:
            with self.assertRaises(RuntimeError):
                backend.set_fan_power(70)
            run.assert_not_called()

    def test_confirmed_duty(self):
        with patch('backend.fan_control_state', side_effect=[{'mode': 'auto'}, {'mode': 'manual', 'percent': 70}]), patch('backend.subprocess.run') as run:
            run.return_value.returncode = 0
            backend.set_fan_power(70)
            self.assertEqual(run.call_args.args[0], ['/usr/bin/pkexec', backend.helper_path('avell-fan'), '70'])

    def test_guard_return_to_auto_is_not_success(self):
        with patch('backend.fan_control_state', return_value={'mode': 'auto'}), patch('backend.subprocess.run') as run:
            run.return_value.returncode = 0
            with self.assertRaises(RuntimeError):
                backend.set_fan_power(70)
