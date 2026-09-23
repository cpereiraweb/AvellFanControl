"""Teste explícito: altera os 3 perfis reais pelo menu, restaurando o inicial."""
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gio, GLib, Gtk
import app
from backend import command, set_profile, PROFILES

original = command(['powerprofilesctl', 'get'])
if original not in PROFILES:
    raise SystemExit('Perfil inicial indisponível; teste cancelado.')
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
targets = iter(PROFILES)
failure = []


def call(dest, path, interface, method, parameters=None):
    return bus.call_sync(dest, path, interface, method, parameters, None,
                         Gio.DBusCallFlags.NONE, 3000, None).unpack()


def application():
    return Gtk.Window.get_toplevels().get_item(0).get_application()


def flatten(node):
    yield node
    for child in node[2]:
        yield from flatten(child.unpack() if hasattr(child, 'unpack') else child)


def choose():
    try:
        target = next(targets, None)
        if target is None:
            application().quit()
            return False
        items = call('org.kde.StatusNotifierWatcher', '/StatusNotifierWatcher',
                     'org.freedesktop.DBus.Properties', 'Get',
                     GLib.Variant('(ss)', ('org.kde.StatusNotifierWatcher', 'RegisteredStatusNotifierItems')))[0]
        dest, path = next(v for v in items if 'avell_thermal' in v).split('@', 1)
        menu = call(dest, path, 'org.freedesktop.DBus.Properties', 'Get',
                    GLib.Variant('(ss)', ('org.kde.StatusNotifierItem', 'Menu')))[0]
        root = call(dest, menu, 'com.canonical.dbusmenu', 'GetLayout',
                    GLib.Variant('(iias)', (0, -1, ['label', 'enabled', 'toggle-state'])))[1]
        entry = next(v for v in flatten(root) if v[1].get('label') == PROFILES[target])
        call(dest, menu, 'com.canonical.dbusmenu', 'Event',
             GLib.Variant('(isvu)', (entry[0], 'clicked', GLib.Variant('i', 0), 0)))
        GLib.timeout_add(250, verify, target, time.monotonic() + 12)
    except Exception as exc:
        failure.append(str(exc))
        application().quit()
    return False


def verify(target, deadline):
    a = application()
    if (not a.changing and a.sample and a.sample['profile'] == target
            and command(['powerprofilesctl', 'get']) == target):
        print('PASS menu → perfil real:', target, flush=True)
        GLib.idle_add(choose)
        return False
    if time.monotonic() > deadline:
        failure.append('Perfil não confirmado: ' + target)
        a.quit()
        return False
    return True


GLib.timeout_add_seconds(4, choose)
try:
    app.main()
finally:
    set_profile(original)
    print('Perfil original restaurado:', original)
if failure:
    raise SystemExit('; '.join(failure))
