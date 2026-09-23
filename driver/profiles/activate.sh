#!/bin/bash
# Manual experimental activation: no autoload, no EC setting on load.
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
[ "$EUID" = 0 ] || { echo 'Execute com sudo.' >&2; exit 1; }
replace=0
if [ "$#" = 2 ] && [ "$2" = --replace ]; then replace=1; set -- "$1"; fi
[ "$#" = 1 ] && [[ "$1" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{2}-[0-9]{2}-[0-9]{2}$ ]] || exit 2
if [ -d /sys/module/avell_profiles ] && [ "$replace" = 0 ]; then
    echo "Driver já carregado; use --replace para atualizar." >&2; exit 1
fi
for module in avell_ec_probe tuxedo_io tuxedo_keyboard uniwill_wmi ec_sys; do
    [ ! -d "/sys/module/$module" ] || { echo "Módulo concorrente: $module" >&2; exit 1; }
done
base=$(cd -- "$(dirname -- "$0")" && pwd)
vermagic=$(modinfo -F vermagic "$base/avell_profiles.ko")
[ "${vermagic%% *}" = "$(uname -r)" ] || { echo 'Recompile para o kernel atual.' >&2; exit 1; }
echo 'Verificando snapshot existente (não será criado outro backup)…' >&2
snapshots=$(timeout 60 timeshift --list --scripted 2>&1) || { echo 'Falha ao consultar snapshots.' >&2; exit 1; }
grep -Fq -- "$1" <<< "$snapshots" || { echo 'Snapshot não encontrado.' >&2; exit 1; }
# Copy privileged artifacts to root-owned storage; never elevate app.py.
install -d -o root -g root -m 0755 /usr/local/libexec /usr/local/lib/avell-thermal
install -o root -g root -m 0755 "$base/avell-profile" /usr/local/libexec/avell-profile
install -o root -g root -m 0755 "$base/avell-fan" /usr/local/libexec/avell-fan
install -o root -g root -m 0644 "$base/avell_profiles.ko" /usr/local/lib/avell-thermal/avell_profiles.next.ko
had_driver=0
if [ -d /sys/module/avell_profiles ]; then
    # Do not unload a driver while a fan test/manual session is running.
    if [ -e /sys/kernel/avell_profiles/fan_boost ]; then
        boost=$(cat /sys/kernel/avell_profiles/fan_boost)
        [ "$boost" = auto ] || { echo 'Aguarde o fim do teste de ventilação antes de atualizar.' >&2; exit 1; }
    fi
    if [ -e /sys/kernel/avell_profiles/fan_control ]; then
        python3 -I -c 'import json; s=json.load(open("/sys/kernel/avell_profiles/fan_control")); raise SystemExit(0 if s["mode"] == "auto" else "Retorne ao automático antes de atualizar.")'
    fi
    rmmod avell_profiles
    had_driver=1
fi
if ! insmod /usr/local/lib/avell-thermal/avell_profiles.next.ko; then
    if [ "$had_driver" = 1 ]; then insmod /usr/local/lib/avell-thermal/avell_profiles.ko; fi
    exit 1
fi
mv /usr/local/lib/avell-thermal/avell_profiles.next.ko /usr/local/lib/avell-thermal/avell_profiles.ko
if ! cat /sys/kernel/avell_profiles/profile; then
    rmmod avell_profiles
    echo 'Estado não reconhecido; módulo descarregado.' >&2
    exit 1
fi
echo 'Driver ativo nesta sessão. Nenhum perfil foi alterado. Abra o Avell Thermal.' >&2
