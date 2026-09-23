import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from backend import Monitor, sensors, set_profile


class BackendTests(unittest.TestCase):
    def test_missing_and_invalid_sensors_do_not_become_zero(self):
        with tempfile.TemporaryDirectory() as folder:
            chip = Path(folder) / 'hwmon9'
            chip.mkdir()
            (chip / 'name').write_text('coretemp')
            (chip / 'temp1_label').write_text('Package id 0')
            (chip / 'temp1_input').write_text('87000')
            (chip / 'temp2_input').write_text('invalid')
            (chip / 'temp3_input').write_text('999000')
            result = sensors(Path(folder))
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0].value, 87)
            self.assertEqual(result[0].label, 'Package id 0')
            self.assertEqual(sensors(Path(folder), 'fan*_input', 1), [])

    def test_cpu_uses_deltas_and_does_not_double_count_guest(self):
        monitor = Monitor()
        with patch('backend.read', side_effect=['cpu 100 0 0 100 0 0 0 0 50 0', 'cpu 150 0 0 150 0 0 0 0 100 0']):
            self.assertIsNone(monitor.cpu_usage())
            self.assertEqual(monitor.cpu_usage(), 50)

    def test_arbitrary_profile_never_reaches_subprocess(self):
        with patch('backend.subprocess.run') as run:
            with self.assertRaises(ValueError):
                set_profile('--help')
            run.assert_not_called()

    def test_profile_is_verified_after_write(self):
        with patch('backend.subprocess.run') as run, patch('backend.command', return_value='performance'):
            run.return_value.returncode = 0
            with self.assertRaises(RuntimeError):
                set_profile('balanced')


if __name__ == '__main__':
    unittest.main()
