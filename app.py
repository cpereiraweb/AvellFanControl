#!/usr/bin/env python3
"""Avell Thermal — interface GTK4 para diagnóstico e gestão térmica."""
import argparse
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

import autostart
from fan_session import SESSION
from backend import (Monitor, PROFILES, HARDWARE_PROFILES, diagnostics, set_profile,
                     set_hardware_profile, set_fan_power)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--diagnose', action='store_true', help='Diagnóstico JSON, sem abrir janela')
    parser.add_argument('--smoke-test', action='store_true', help='Abre a interface e encerra após uma leitura')
    parser.add_argument('--background', action='store_true', help='Inicia na área de notificação')
    args = parser.parse_args()
    if args.diagnose:
        print(json.dumps(diagnostics(Monitor().sample()), ensure_ascii=False, indent=2))
        return

    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')
    from gi.repository import Adw, GLib, Gtk, Gdk

    class App(Adw.Application):
        def __init__(self):
            super().__init__(application_id='br.dev.avell.Thermal')
            self.pool = ThreadPoolExecutor(max_workers=1)
            self.monitor = Monitor()
            self.history = deque(maxlen=90)
            self.sample = None
            self.busy = False
            self.changing = False
            self.closed = False
            self.tray = None
            self.tray_connected = False
            self.tray_buffer = bytearray()
            self.background_pending = args.background

        def label(self, text, css=None):
            widget = Gtk.Label(label=text, xalign=0)
            widget.set_wrap(True)
            if css:
                widget.add_css_class(css)
            return widget

        def do_activate(self):
            if self.get_active_window():
                self.get_active_window().present()
                return
            Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_DARK)
            css = Gtk.CssProvider()
            css.load_from_data(b'.metric {font-size: 38px; font-weight: 700;} .cardbox {padding: 20px; border-radius: 16px; background: alpha(@card_bg_color, .8);} .accent {color: #62d5b4;} .warning-text {color: #f5be6f;}')
            Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            self.window = Adw.ApplicationWindow(application=self, title='Avell Thermal', default_width=860, default_height=760)
            self.window.connect('close-request', self.close_window)
            outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            header = Adw.HeaderBar()
            header.set_title_widget(Adw.WindowTitle(title='Avell Thermal', subtitle='Controle térmico · A65i'))
            export = Gtk.Button(icon_name='document-save-symbolic', tooltip_text='Salvar diagnóstico')
            export.connect('clicked', self.export)
            header.pack_end(export)
            leave = Gtk.Button(icon_name='application-exit-symbolic', tooltip_text='Sair do Avell Thermal')
            leave.connect('clicked', lambda _: self.quit())
            header.pack_start(leave)
            outer.append(header)
            self.toast = Adw.ToastOverlay()
            scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=22,
                          margin_top=22, margin_bottom=24, margin_start=28, margin_end=28)
            box.append(self.label('Acompanhe o calor. Ajuste o desempenho.', 'title-1'))
            box.append(self.label('Sensores reais do notebook • atualização a cada 2 segundos', 'dim-label'))
            metrics = Gtk.Box(spacing=14, homogeneous=True)
            self.values = {}
            for key, title in [('cpu', 'PROCESSADOR'), ('gpu', 'GPU NVIDIA'), ('usage', 'USO DA CPU')]:
                card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
                card.add_css_class('cardbox')
                card.append(self.label(title, 'caption'))
                self.values[key] = self.label('—', 'metric')
                card.append(self.values[key])
                metrics.append(card)
            box.append(metrics)
            graphbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            graphbox.add_css_class('cardbox')
            graphbox.append(self.label('Temperatura da CPU', 'heading'))
            self.chart = Gtk.DrawingArea(content_height=150)
            self.chart.set_draw_func(self.draw)
            graphbox.append(self.chart)
            graphbox.append(self.label('Últimas 90 leituras · escala de 30 a 110 °C', 'dim-label'))
            box.append(graphbox)
            fans = Adw.PreferencesGroup(title='Ventoinhas', description='Potência das duas ventoinhas enquanto o app estiver aberto, inclusive na bandeja. Retorna ao automático ao sair ou por proteção térmica.')
            self.fanrow = Adw.ActionRow(title='Modo das ventoinhas', subtitle='Consultando o driver…')
            self.fanrow.add_prefix(Gtk.Image(icon_name='dialog-information-symbolic'))
            fans.add(self.fanrow)
            self.rpmrow = Adw.ActionRow(title='Rotação', subtitle='Aguardando leitura dos sensores…')
            fans.add(self.rpmrow)
            self.fan_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 50, 100, 5)
            self.fan_scale.set_value(70)
            self.fan_scale.set_digits(0)
            self.fan_scale.connect('value-changed', lambda scale: scale.set_value(round(scale.get_value() / 5) * 5))
            self.fan_scale.set_hexpand(True)
            power_controls = Gtk.Box(spacing=8, margin_top=16)
            power_controls.append(self.fan_scale)
            self.fan_apply = Gtk.Button(label='Aplicar potência', sensitive=False)
            self.fan_apply.connect('clicked', lambda _: self.change_fans(int(self.fan_scale.get_value())))
            self.fan_auto = Gtk.Button(label='Automático', sensitive=False)
            self.fan_auto.connect('clicked', lambda _: self.change_fans('auto'))
            power_controls.append(self.fan_apply)
            power_controls.append(self.fan_auto)
            fans.add(power_controls)
            box.append(fans)
            hardware = Adw.PreferencesGroup(title='Perfil do notebook', description='Controle experimental equivalente ao botão físico.')
            self.hardware_row = Adw.ActionRow(title='Perfil do firmware', subtitle='Consultando o driver…')
            hardware.add(self.hardware_row)
            hardware_buttons = Gtk.Box(spacing=8, homogeneous=True, margin_top=16)
            self.hardware_buttons = {}
            for key, title in HARDWARE_PROFILES.items():
                button = Gtk.Button(label=title, sensitive=False)
                button.connect('clicked', self.change_hardware_profile, key)
                self.hardware_buttons[key] = button
                hardware_buttons.append(button)
            hardware.add(hardware_buttons)
            box.append(hardware)
            power = Adw.PreferencesGroup(title='Perfil de energia', description='Altera a política de energia do Ubuntu. Não define a velocidade das ventoinhas.')
            self.powerrow = Adw.ActionRow(title='Perfil atual', subtitle='Consultando o sistema…')
            power.add(self.powerrow)
            buttons = Gtk.Box(spacing=8, homogeneous=True, margin_top=16)
            self.buttons = {}
            for key, title in PROFILES.items():
                button = Gtk.Button(label=title)
                button.connect('clicked', self.change_profile, key)
                self.buttons[key] = button
                buttons.append(button)
            power.add(buttons)
            box.append(power)
            startup = Adw.PreferencesGroup(title='Inicialização')
            self.startup_row = Adw.SwitchRow(title='Iniciar ao entrar no Ubuntu',
                subtitle='Abre na área de notificação, sem aplicar potência ou trocar perfis.')
            self.startup_row.set_active(autostart.enabled())
            self.startup_row.connect('notify::active', self.change_autostart)
            startup.add(self.startup_row)
            box.append(startup)
            self.status = self.label('Conectando aos sensores…', 'dim-label')
            box.append(self.status)
            box.append(self.label('Criado por Claudio Pereira e Codex Astra 6 em 2026-09-22', 'dim-label'))
            scroll.set_child(box)
            self.toast.set_child(scroll)
            outer.append(self.toast)
            self.toast.set_vexpand(True)
            self.window.set_content(outer)
            self.window.present()
            if not args.smoke_test:
                self.start_tray()
            self.refresh()
            self.timer = GLib.timeout_add_seconds(2, self.refresh)

        def change_autostart(self, row, _spec):
            try:
                autostart.set_enabled(row.get_active())
            except OSError as exc:
                row.handler_block_by_func(self.change_autostart)
                row.set_active(not row.get_active())
                row.handler_unblock_by_func(self.change_autostart)
                self.toast.add_toast(Adw.Toast(title=f'Não foi possível salvar a preferência: {exc}'))

        def start_tray(self):
            try:
                self.tray = subprocess.Popen([sys.executable, str(Path(__file__).with_name('tray.py'))],
                                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0)
                self.tray_watch = GLib.io_add_watch(self.tray.stdout.fileno(),
                    GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, self.tray_message)
            except OSError as exc:
                self.toast.add_toast(Adw.Toast(title=f'Ícone de notificação indisponível: {exc}'))

        def close_window(self, window):
            if self.tray_connected:
                window.set_visible(False)
                return True
            return False

        def tray_message(self, fd, condition):
            chunk = os.read(fd, 65536)
            if not chunk:
                self.tray_connected = False
                self.tray_watch = None
                if not self.closed:
                    self.window.present()
                    self.toast.add_toast(Adw.Toast(title='Ícone de notificação indisponível; a janela permanecerá acessível.'))
                return False
            self.tray_buffer.extend(chunk)
            while b'\n' in self.tray_buffer:
                line, _, rest = self.tray_buffer.partition(b'\n')
                self.tray_buffer[:] = rest
                try:
                    data = json.loads(line)
                except (ValueError, UnicodeError):
                    continue
                action = data.get('action')
                if action == 'connected':
                    self.tray_connected = bool(data.get('value'))
                    if self.tray_connected and self.background_pending:
                        self.window.set_visible(False)
                        self.background_pending = False
                    if not self.tray_connected:
                        self.window.present()
                elif action == 'show':
                    self.window.present()
                elif action == 'export':
                    self.export(None)
                elif action == 'profile' and data.get('value') in PROFILES:
                    self.change_profile(None, data['value'])
                elif action == 'hardware_profile' and data.get('value') in HARDWARE_PROFILES:
                    self.change_hardware_profile(None, data['value'])
                elif action == 'fan_power':
                    self.change_fans(data.get('value'))
                elif action == 'quit':
                    self.quit()
            return True

        def update_tray(self, sample):
            if self.tray is not None and self.tray.poll() is None:
                payload = {key: sample.get(key) for key in ('cpu', 'gpu', 'profile', 'hardware_profile', 'fans', 'fan_control')}
                payload['changing'] = self.changing
                payload['fan_session_active'] = SESSION.active()
                try:
                    self.tray.stdin.write((json.dumps(payload) + '\n').encode())
                except (OSError, ValueError):
                    pass

        def refresh(self):
            if self.closed:
                return False
            SESSION.touch()
            if not self.busy and not self.changing:
                self.busy = True
                future = self.pool.submit(self.monitor.sample)
                future.add_done_callback(lambda f: GLib.idle_add(self.received, f))
            return True

        def received(self, future):
            self.busy = False
            if self.closed:
                return False
            try:
                self.sample = future.result()
                self.update_tray(self.sample)
                for key, widget in self.values.items():
                    value = self.sample[key]
                    widget.set_label('—' if value is None else f'{value:.0f}' + (' %' if key == 'usage' else ' °C'))
                self.history.append(self.sample['cpu'])
                self.chart.queue_draw()
                fans = self.sample['fans']
                self.rpmrow.set_subtitle(' · '.join(f"{s['chip']} / {s['label']}: {s['value']:.0f} RPM" for s in fans) if fans else 'RPM não exposto pelo driver atual')
                control = self.sample.get('fan_control')
                mode = control.get('mode') if control else None
                text = {'auto': 'Automático — firmware', 'boost': 'Ventilação máxima temporizada',
                        'restoring': 'Restaurando automático…'}.get(mode, 'Driver indisponível')
                if mode == 'manual':
                    text = f"Manual: {control['percent']}% · contínuo" if SESSION.active() else f"Manual temporizado: {control['percent']}% · {control['seconds_remaining']} s restantes"
                self.fanrow.set_subtitle(text)
                self.fan_apply.set_sensitive(bool(control and control.get('lease_supported')) and mode in ('auto', 'manual') and not self.changing)
                self.fan_auto.set_sensitive(mode is not None and not self.changing)
                hardware_profile = self.sample.get('hardware_profile')
                self.hardware_row.set_subtitle(HARDWARE_PROFILES.get(hardware_profile, 'Driver indisponível ou estado não reconhecido'))
                for key, button in self.hardware_buttons.items():
                    button.set_sensitive(hardware_profile is not None and not self.changing and mode in (None, 'auto'))
                    if key == hardware_profile:
                        button.add_css_class('suggested-action')
                    else:
                        button.remove_css_class('suggested-action')
                profile = self.sample['profile']
                self.powerrow.set_subtitle(PROFILES.get(profile, 'Indisponível'))
                for key, button in self.buttons.items():
                    button.set_sensitive(profile is not None and not self.changing)
                    if key == profile:
                        button.add_css_class('suggested-action')
                    else:
                        button.remove_css_class('suggested-action')
                self.status.set_label('Atualizado às ' + datetime.now().strftime('%H:%M:%S') + ' • Preferência da CPU: ' + (self.sample['epp'] or 'indisponível'))
            except Exception as exc:
                self.update_tray({})
                for widget in self.values.values():
                    widget.set_label('—')
                self.status.set_label(f'Falha na leitura: {exc}')
            if args.smoke_test:
                self.quit()
            return False

        def draw(self, area, cr, width, height):
            cr.set_line_width(1)
            for temp in (40, 60, 80, 100):
                y = height - (temp - 30) / 80 * height
                cr.set_source_rgba(.6, .7, .75, .15)
                cr.move_to(0, y)
                cr.line_to(width, y)
                cr.stroke()
                cr.set_source_rgba(.65, .7, .75, .9)
                cr.set_font_size(11)
                cr.move_to(4, y - 4)
                cr.show_text(str(temp) + ' °C')
            cr.set_source_rgb(.38, .84, .70)
            cr.set_line_width(2.5)
            started = False
            for i, value in enumerate(self.history):
                if value is None:
                    started = False
                    continue
                x = 45 + i / 89 * (width - 50)
                y = max(0, min(height, height - (value - 30) / 80 * height))
                if started:
                    cr.line_to(x, y)
                else:
                    cr.move_to(x, y)
                started = True
            cr.stroke()

        def change_fans(self, value):
            if self.changing:
                return
            if value != 'auto' and (type(value) is not int or value not in range(50, 101, 5)):
                return
            self.changing = True
            self.fan_apply.set_sensitive(False)
            self.fan_auto.set_sensitive(False)
            self.fanrow.set_subtitle('Aguardando autenticação e aplicação; pode levar alguns segundos…')
            for widget in list(self.buttons.values()) + list(self.hardware_buttons.values()):
                widget.set_sensitive(False)
            self.update_tray(self.sample or {})
            def apply():
                if value == 'auto':
                    if SESSION.process is not None:
                        SESSION.stop(wait=True)
                        from backend import fan_control_state
                        current = fan_control_state()
                        if current and current['mode'] == 'auto':
                            return
                    set_fan_power('auto')
                else:
                    SESSION.start(value)
            future = self.pool.submit(apply)
            future.add_done_callback(lambda f: GLib.idle_add(self.fans_done, f))

        def fans_done(self, future):
            self.changing = False
            if self.closed:
                return False
            try:
                future.result()
                message = 'Comando das ventoinhas confirmado pelo driver.'
            except Exception as exc:
                message = f'Controle das ventoinhas: {exc}'
            self.toast.add_toast(Adw.Toast(title=message, timeout=8))
            self.refresh()
            return False

        def change_hardware_profile(self, button, profile):
            if self.changing or profile not in HARDWARE_PROFILES:
                return
            self.changing = True
            self.update_tray(self.sample or {})
            for widget in list(self.buttons.values()) + list(self.hardware_buttons.values()):
                widget.set_sensitive(False)
            future = self.pool.submit(set_hardware_profile, profile)
            future.add_done_callback(lambda f: GLib.idle_add(self.profile_done, f, True))

        def change_profile(self, button, profile):
            if self.changing or profile not in PROFILES:
                return
            self.changing = True
            self.update_tray(self.sample or {})
            for widget in list(self.buttons.values()) + list(self.hardware_buttons.values()):
                widget.set_sensitive(False)
            future = self.pool.submit(set_profile, profile)
            future.add_done_callback(lambda f: GLib.idle_add(self.profile_done, f))

        def profile_done(self, future, hardware=False):
            self.changing = False
            if self.closed:
                return False
            try:
                future.result()
                message = 'Perfil do notebook confirmado pelo firmware.' if hardware else 'Perfil de energia aplicado.'
            except Exception as exc:
                message = f'Não foi possível alterar o perfil: {exc}'
            self.toast.add_toast(Adw.Toast(title=message, timeout=6))
            self.refresh()
            return False

        def export(self, button):
            folder = Path.home() / '.local/state/avell-thermal'
            try:
                folder.mkdir(parents=True, exist_ok=True)
                path = folder / ('diagnostico-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.json')
                path.write_text(json.dumps(diagnostics(self.sample), ensure_ascii=False, indent=2) + '\n')
                self.toast.add_toast(Adw.Toast(title=f'Diagnóstico salvo em {path}', timeout=8))
            except OSError as exc:
                self.toast.add_toast(Adw.Toast(title=f'Falha ao salvar: {exc}'))

        def do_shutdown(self):
            self.closed = True
            SESSION.shutdown()
            if getattr(self, 'tray_watch', None):
                GLib.source_remove(self.tray_watch)
            if self.tray is not None:
                self.tray.stdin.close()
                try:
                    self.tray.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.tray.terminate()
                    self.tray.wait(timeout=2)
                self.tray.stdout.close()
            if hasattr(self, 'timer'):
                GLib.source_remove(self.timer)
            self.pool.shutdown(wait=False, cancel_futures=True)
            Adw.Application.do_shutdown(self)

    App().run([sys.argv[0]])


if __name__ == '__main__':
    main()
