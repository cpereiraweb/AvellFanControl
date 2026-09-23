"""Sensores sem privilégios e seleção restrita de perfis via auxiliar autenticado."""
from dataclasses import asdict, dataclass
from pathlib import Path
from paths import helper_path
import platform
import json
import math
import subprocess
import time


def read(path):
    try:
        return Path(path).read_text().strip()
    except (OSError, UnicodeError):
        return None


def command(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=4)
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


@dataclass
class Sensor:
    chip: str
    label: str
    value: float
    path: str


def sensors(root=Path('/sys/class/hwmon'), pattern='temp*_input', scale=1000):
    result = []
    for chip in sorted(root.glob('hwmon*')):
        name = read(chip / 'name') or chip.name
        for p in sorted(chip.glob(pattern)):
            try:
                value = float(read(p)) / scale
                if not math.isfinite(value) or (pattern.startswith('fan') and value < 0):
                    continue
                if pattern.startswith('temp') and not -20 <= value <= 150:
                    continue
                result.append(Sensor(name, read(p.with_name(p.name.replace('_input', '_label'))) or p.stem, value, str(p)))
            except (ValueError, TypeError):
                continue
    return result


class Monitor:
    def __init__(self):
        self.previous = None

    def cpu_usage(self):
        line = (read('/proc/stat') or '').splitlines()
        if not line:
            return None
        # guest/guest_nice já estão contados em user/nice.
        values = list(map(int, line[0].split()[1:9]))
        total, idle = sum(values), values[3] + values[4]
        previous, self.previous = self.previous, (total, idle)
        if previous is None or total <= previous[0]:
            return None
        return max(0, min(100, 100 * (1 - (idle - previous[1]) / (total - previous[0]))))

    def sample(self):
        temps = sensors()
        packages = [s.value for s in temps if s.chip == 'coretemp' and s.label.startswith('Package')]
        cpu = max(packages) if packages else None
        gpu = command(['nvidia-smi', '--query-gpu=temperature.gpu', '--format=csv,noheader,nounits'])
        try:
            gpu = max(float(v) for v in gpu.splitlines()) if gpu else None
        except ValueError:
            gpu = None
        ec_fans = hardware_fans()
        return dict(timestamp=time.time(), cpu=cpu, gpu=gpu, usage=self.cpu_usage(),
                    temperatures=[asdict(s) for s in temps],
                    fans=[asdict(s) for s in sensors(pattern='fan*_input', scale=1)] + ec_fans,
                    profile=command(['powerprofilesctl', 'get']),
                    hardware_profile=hardware_profile(),
                    fan_control=fan_control_state(),
                    epp=read('/sys/devices/system/cpu/cpufreq/policy0/energy_performance_preference'))


def diagnostics(sample=None):
    guids = sorted(p.name for p in Path('/sys/bus/wmi/devices').glob('*'))
    expected = [f'ABBC0F{i:X}-8EA1-11D1-00A0-C90629100000' for i in range(0x6D, 0x73)]
    return dict(
        system=platform.platform(),
        hardware={key: read(Path('/sys/class/dmi/id') / key) for key in
                  ('sys_vendor', 'product_name', 'board_name', 'bios_version')},
        wmi=guids, uniwill_wmi_detected=all(g in guids for g in expected),
        pwm_paths=[str(p) for p in Path('/sys/class/hwmon').glob('hwmon*/pwm*')],
        tuxedo_device=Path('/dev/tuxedo_io').exists(),
        fan_control_available=Path('/sys/kernel/avell_profiles/fan_control').exists(),
        fan_control_validation={'model': 'Avell A65i / N.1.09AVE03',
                                'levels_percent': [50, 70, 100],
                                'continuous_and_helper_failure': True,
                                'hardware_suspend_tested': False,
                                'host_bit2_meaning': 'undocumented; variation separately reported'},
        limitation='Potência de 50–100% com RPM medido; não é alvo exato de RPM. Driver limitado ao modelo/BIOS validados.',
        sample=sample,
    )


PROFILES = {'power-saver': 'Economia', 'balanced': 'Equilibrado', 'performance': 'Desempenho'}


def set_profile(profile):
    if profile not in PROFILES:
        raise ValueError('Perfil inválido')
    result = subprocess.run(['powerprofilesctl', 'set', profile], capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or 'O sistema recusou a alteração de perfil.')
    current = command(['powerprofilesctl', 'get'])
    if current != profile:
        raise RuntimeError('Não foi possível confirmar o perfil aplicado.')


HARDWARE_PROFILES = {'economy': 'Economia', 'balanced': 'Equilibrado', 'turbo': 'Turbo'}
HARDWARE_PROFILE_PATH = Path('/sys/kernel/avell_profiles/profile')
HARDWARE_HELPER = helper_path('avell-profile')


def hardware_profile():
    value = read(HARDWARE_PROFILE_PATH)
    return value if value in HARDWARE_PROFILES else None


def set_hardware_profile(profile):
    if profile not in HARDWARE_PROFILES:
        raise ValueError('Perfil do notebook inválido')
    if hardware_profile() is None:
        raise RuntimeError('Driver do notebook indisponível ou estado não reconhecido.')
    result = subprocess.run(['/usr/bin/pkexec', HARDWARE_HELPER, profile],
                            capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or 'Alteração cancelada ou recusada.')
    if hardware_profile() != profile:
        raise RuntimeError('Não foi possível confirmar o perfil do notebook.')


def hardware_fans():
    path = Path('/sys/kernel/avell_profiles/fans')
    try:
        data = json.loads(read(path) or '{}')
        values = [data['fan1_rpm'], data['fan2_rpm']]
        if any(type(v) is not int or not 0 <= v <= 15000 for v in values):
            return []
        return [asdict(Sensor('Avell EC', f'Ventoinha {i}', value, str(path)))
                for i, value in enumerate(values, 1)]
    except (ValueError, KeyError, TypeError):
        return []


def fan_control_state():
    try:
        state = json.loads(read('/sys/kernel/avell_profiles/fan_control') or '{}')
        if state.get('mode') not in ('auto', 'manual', 'restoring', 'boost'):
            return None
        if type(state.get('percent')) is not int or not 0 <= state['percent'] <= 100:
            return None
        if type(state.get('seconds_remaining')) is not int or not 0 <= state['seconds_remaining'] <= 30:
            return None
        return state
    except (ValueError, TypeError):
        return None


def set_fan_power(value):
    if value != 'auto' and (type(value) is not int or value not in range(50, 101, 5)):
        raise ValueError('Escolha de 50 a 100%, em passos de 5%.')
    state = fan_control_state()
    if state is None:
        raise RuntimeError('Driver de controle das ventoinhas indisponível.')
    result = subprocess.run(['/usr/bin/pkexec', helper_path('avell-fan'), str(value)],
                            capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or 'Alteração cancelada ou recusada pelo driver.')
    state = fan_control_state()
    if not state or (value == 'auto' and state['mode'] != 'auto') or (value != 'auto' and
            (state['mode'] != 'manual' or state['percent'] != value)):
        raise RuntimeError('Controle manual não permaneceu ativo; confira o estado e a temperatura.')
