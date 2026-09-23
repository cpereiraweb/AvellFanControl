import errno
import struct
import unittest
from unittest.mock import patch
from tuxedo_probe import probe, READS


class ProbeTests(unittest.TestCase):
    def test_only_read_requests(self):
        self.assertTrue(all(request >> 30 == 2 for request in READS.values()))
        self.assertEqual(READS['model_id'], 0x8008EF01 if struct.calcsize('P') == 8 else 0x8004EF01)

    def test_missing_driver_is_reported(self):
        with patch('tuxedo_probe.os.open', side_effect=FileNotFoundError(errno.ENOENT, 'ausente')):
            result = probe()
        self.assertFalse(result['available'])
        self.assertTrue(result['read_only'])

    def test_unknown_interface_stops_probe_and_closes_device(self):
        with patch('tuxedo_probe.os.open', return_value=42), patch('tuxedo_probe.os.close') as close, patch('tuxedo_probe.fcntl.ioctl') as ioctl:
            self.assertFalse(probe()['available'])
            self.assertEqual(ioctl.call_count, 1)
            close.assert_called_once_with(42)
