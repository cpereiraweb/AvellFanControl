"""Teste explícito na sessão GNOME: registro, leituras, ocultar, reabrir e sair."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gio, GLib, Gtk
import app

failures = []
client = Gio.bus_get_sync(Gio.BusType.SESSION, None)


def call(bus, path, interface, method, parameters=None):
    return client.call_sync(bus, path, interface, method, parameters, None,
                            Gio.DBusCallFlags.NONE, 3000, None).unpack()


def application():
    return Gtk.Window.get_toplevels().get_item(0).get_application()


def check():
    try:
        a = application()
        assert a.tray_connected, 'Indicador não conectado ao painel'
        assert a.sample is not None, 'Sem leitura dos sensores'
        assert set(a.hardware_buttons) == {'economy', 'balanced', 'turbo'}
        if a.sample.get('hardware_profile') is None:
            assert all(not b.get_sensitive() for b in a.hardware_buttons.values()), 'Perfis habilitados sem driver'
        items = call('org.kde.StatusNotifierWatcher', '/StatusNotifierWatcher',
                     'org.freedesktop.DBus.Properties', 'Get',
                     GLib.Variant('(ss)', ('org.kde.StatusNotifierWatcher', 'RegisteredStatusNotifierItems')))[0]
        matches = [s for s in items if 'avell_thermal' in s]
        assert len(matches) == 1, f'Indicador duplicado ou ausente: {matches}'
        bus, path = matches[0].split('@', 1)
        menu = call(bus, path, 'org.freedesktop.DBus.Properties', 'Get',
                    GLib.Variant('(ss)', ('org.kde.StatusNotifierItem', 'Menu')))[0]
        layout = call(bus, menu, 'com.canonical.dbusmenu', 'GetLayout',
                      GLib.Variant('(iias)', (0, -1, ['label'])))[1]
        children = [v.unpack() if hasattr(v, 'unpack') else v for v in layout[2]]
        def find(label):
            return next(v[0] for v in children if v[1].get('label') == label)
        assert any(v[1].get('label', '').startswith('CPU: ') for v in children)
        find('Perfil do notebook (experimental)')
        a.window.close()
        assert not a.window.get_visible(), 'Fechar não ocultou a janela'
        call(bus, menu, 'com.canonical.dbusmenu', 'Event',
             GLib.Variant('(isvu)', (find('Abrir Avell Thermal'), 'clicked', GLib.Variant('i', 0), 0)))
        GLib.timeout_add(500, finish, bus, menu, find('Sair'))
    except Exception as exc:
        failures.append(str(exc))
        application().quit()
    return False


def finish(bus, menu, quit_id):
    try:
        assert application().window.get_visible(), 'Menu não reabriu a janela'
        call(bus, menu, 'com.canonical.dbusmenu', 'Event',
             GLib.Variant('(isvu)', (quit_id, 'clicked', GLib.Variant('i', 0), 0)))
        print('PASS: indicador registrado; sensores; fechar para bandeja; reabrir e sair pelo menu')
    except Exception as exc:
        failures.append(str(exc))
        application().quit()
    return False


GLib.timeout_add_seconds(4, check)
app.main()
if failures:
    raise SystemExit('; '.join(failures))
