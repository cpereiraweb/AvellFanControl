"""Per-user desktop session startup preference."""
import os
from pathlib import Path


def entry_path():
    config = os.environ.get('XDG_CONFIG_HOME', '')
    base = Path(config) if config and Path(config).is_absolute() else Path.home() / '.config'
    return base / 'autostart/br.dev.avell.Thermal.desktop'


def enabled():
    path = entry_path()
    if not path.is_file():
        return False
    lines = path.read_text().splitlines()
    return 'Hidden=true' not in lines and 'X-GNOME-Autostart-enabled=false' not in lines


def set_enabled(value):
    path = entry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = '''[Desktop Entry]
Type=Application
Name=Avell Thermal
Exec=/usr/bin/avell-thermal --background
TryExec=/usr/bin/avell-thermal
Icon=avell-thermal
Terminal=false
'''
    text += 'Hidden=' + ('false' if value else 'true') + '\n'
    temporary = path.with_suffix('.tmp')
    temporary.write_text(text)
    temporary.replace(path)
