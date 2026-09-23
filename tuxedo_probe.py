"""Consulta restrita de tuxedo_io. Não carrega módulos nem emite ioctls de escrita.

ABI: tuxedo-drivers/src/tuxedo_io/tuxedo_io_ioctl.h, commit
2c6bf54075fb38a7fdbefc560734281984bf65bc. O tamanho no ioctl é de
ponteiro, embora o payload inteiro tenha 32 bits.
"""
import fcntl
import json
import os
from pathlib import Path
import struct


def read_request(magic, number):
    return (2 << 30) | (struct.calcsize('P') << 16) | (magic << 8) | number


READS = {
    'uniwill_interface': read_request(0xEC, 0x06),
    'model_id': read_request(0xEF, 0x01),
    'fan1_raw': read_request(0xEF, 0x10),
    'fan2_raw': read_request(0xEF, 0x11),
    'cpu_ec_temperature': read_request(0xEF, 0x12),
    'gpu_ec_temperature': read_request(0xEF, 0x13),
}


def probe():
    path = Path('/dev/tuxedo_io')
    result = {'device': str(path), 'read_only': True, 'fan_control_validated': False}
    try:
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
    except OSError as exc:
        return {**result, 'available': False, 'error': str(exc)}
    try:
        values = {}
        for name, request in READS.items():
            payload = bytearray(4)
            fcntl.ioctl(fd, request, payload, True)
            values[name] = struct.unpack('=i', payload)[0]
            if name == 'uniwill_interface' and values[name] != 1:
                return {**result, 'available': False, 'error': 'Interface Uniwill não confirmada.'}
        return {**result, 'available': True, 'raw_values': values,
                'note': 'Valores brutos do driver, não RPM. Leituras não comprovam compatibilidade das escritas nem resposta física das ventoinhas.'}
    except OSError as exc:
        return {**result, 'available': False, 'error': str(exc)}
    finally:
        os.close(fd)


if __name__ == '__main__':
    print(json.dumps(probe(), ensure_ascii=False, indent=2))
