"""AppIndicator GTK3 isolado da janela GTK4; IPC apenas por pipes herdados."""
import json
import os
from pathlib import Path
import sys

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('AyatanaAppIndicator3', '0.1')
from gi.repository import AyatanaAppIndicator3 as Indicator, GLib, Gtk

from backend import PROFILES, HARDWARE_PROFILES


def emit(action, **data):
    try:
        print(json.dumps(dict(action=action, **data)), flush=True)
    except BrokenPipeError:
        Gtk.main_quit()


def main():
    icon = str(Path(__file__).parent / 'assets/avell-thermal.svg')
    indicator = Indicator.Indicator.new('avell-thermal', icon, Indicator.IndicatorCategory.HARDWARE)
    indicator.set_title('Avell Thermal')
    menu = Gtk.Menu()

    def item(label, action=None):
        widget = Gtk.MenuItem(label=label)
        if action:
            widget.connect('activate', lambda _: emit(action))
        else:
            widget.set_sensitive(False)
        menu.append(widget)
        return widget

    item('Abrir Avell Thermal', 'show')
    menu.append(Gtk.SeparatorMenuItem())
    cpu = item('CPU: aguardando leitura…')
    gpu = item('GPU: aguardando leitura…')
    profile = item('Perfil: aguardando leitura…')
    selector = Gtk.MenuItem(label='Perfil de desempenho (Ubuntu)')
    profile_menu = Gtk.Menu()
    selector.set_submenu(profile_menu)
    menu.append(selector)
    profile_items = {}
    updating = False
    group = None
    def selected(widget, key):
        if not updating and widget.get_active():
            # Do not display an unconfirmed selection while the request runs.
            for entry in profile_items.values():
                entry.set_sensitive(False)
            emit('profile', value=key)
    for key, title in PROFILES.items():
        entry = Gtk.RadioMenuItem.new_with_label(group, title)
        group = entry.get_group()
        entry.set_sensitive(False)
        entry.connect('toggled', selected, key)
        profile_menu.append(entry)
        profile_items[key] = entry
    hardware_status = item('Notebook: aguardando driver…')
    hardware_selector = Gtk.MenuItem(label='Perfil do notebook (experimental)')
    hardware_menu = Gtk.Menu()
    hardware_selector.set_submenu(hardware_menu)
    menu.append(hardware_selector)
    hardware_items = {}
    hardware_group = None
    def hardware_selected(widget, key):
        if not updating and widget.get_active():
            for entry in list(profile_items.values()) + list(hardware_items.values()):
                entry.set_sensitive(False)
            emit('hardware_profile', value=key)
    for key, title in HARDWARE_PROFILES.items():
        entry = Gtk.RadioMenuItem.new_with_label(hardware_group, title)
        hardware_group = entry.get_group()
        entry.set_sensitive(False)
        entry.connect('toggled', hardware_selected, key)
        hardware_menu.append(entry)
        hardware_items[key] = entry
    fan_status = item('Ventoinhas: aguardando leitura…')
    fan_mode_status = item('Controle manual: aguardando driver…')
    fan_selector = Gtk.MenuItem(label='Potência das ventoinhas')
    fan_menu = Gtk.Menu()
    fan_selector.set_submenu(fan_menu)
    menu.append(fan_selector)
    fan_actions = {}
    for value, title in [('auto', 'Automático'), (60, '60% contínuo'), (75, '75% contínuo'), (100, '100% contínuo')]:
        entry = Gtk.MenuItem(label=title, sensitive=False)
        entry.connect('activate', lambda _, v=value: emit('fan_power', value=v))
        fan_menu.append(entry)
        fan_actions[value] = entry
    menu.append(Gtk.SeparatorMenuItem())
    item('Salvar diagnóstico', 'export')
    item('Sair', 'quit')
    menu.show_all()
    indicator.set_menu(menu)
    indicator.set_status(Indicator.IndicatorStatus.ACTIVE)
    indicator.connect('connection-changed', lambda obj, connected: emit('connected', value=connected))
    emit('connected', value=indicator.props.connected)
    buffer = bytearray()

    def incoming(fd, condition):
        nonlocal updating
        chunk = os.read(fd, 65536)
        if not chunk:
            Gtk.main_quit()
            return False
        buffer.extend(chunk)
        while b'\n' in buffer:
            line, _, rest = buffer.partition(b'\n')
            buffer[:] = rest
            try:
                data = json.loads(line)
                def temperature(key):
                    value = data.get(key)
                    return 'indisponível' if value is None else f'{value:.0f} °C'
                readings = data.get('fans') or []
                fan_status.set_label('Ventoinhas: ' + (' / '.join(f"{s['value']:.0f} RPM" for s in readings) if readings else 'RPM indisponível'))
                cpu.set_label('CPU: ' + temperature('cpu'))
                gpu.set_label('GPU NVIDIA: ' + temperature('gpu'))
                profile.set_label('Perfil: ' + PROFILES.get(data.get('profile'), 'indisponível'))
                hardware_status.set_label('Notebook: ' + HARDWARE_PROFILES.get(data.get('hardware_profile'), 'driver indisponível'))
                state = data.get('fan_control') or {}
                mode = state.get('mode')
                fan_mode_status.set_label('Controle: ' + ((f"{state['percent']}% · contínuo" if data.get('fan_session_active') else f"{state['percent']}% · {state['seconds_remaining']} s") if mode == 'manual' else
                    {'auto': 'automático', 'restoring': 'restaurando automático', 'boost': 'máximo temporizado'}.get(mode, 'indisponível')))
                for value, entry in fan_actions.items():
                    entry.set_sensitive(bool(mode) and not data.get('changing', False) and (value == 'auto' or (state.get('lease_supported') and mode in ('auto', 'manual'))))
                updating = True
                try:
                    for key, entry in profile_items.items():
                        entry.set_sensitive(data.get('profile') in PROFILES and not data.get('changing', False))
                        if data.get('profile') == key:
                            entry.set_active(True)
                    for key, entry in hardware_items.items():
                        entry.set_sensitive(data.get('hardware_profile') in HARDWARE_PROFILES and mode in (None, 'auto') and not data.get('changing', False))
                        if data.get('hardware_profile') == key:
                            entry.set_active(True)
                finally:
                    updating = False
                indicator.set_label('' if data.get('cpu') is None else f"{data['cpu']:.0f} °C", '100 °C')
            except (ValueError, TypeError):
                continue
        return True

    GLib.io_add_watch(sys.stdin.fileno(), GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, incoming)
    Gtk.main()
    indicator.set_status(Indicator.IndicatorStatus.PASSIVE)


if __name__ == '__main__':
    main()
