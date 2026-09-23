#!/bin/bash
# Install only the already validated module for this exact running kernel.
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
[ "$EUID" = 0 ] || { echo 'Execute com sudo.' >&2; exit 1; }
base=$(cd -- "$(dirname -- "$0")" && pwd)
kernel=$(uname -r)
vermagic=$(modinfo -F vermagic "$base/avell_profiles.ko")
[ "${vermagic%% *}" = "$kernel" ] || { echo 'Recompile para o kernel atual antes de instalar.' >&2; exit 1; }
[ -d /sys/module/avell_profiles ] || { echo 'Ative e valide o driver antes de instalar.' >&2; exit 1; }
python3 -I -c 'import json; from pathlib import Path; s=json.loads(Path("/sys/kernel/avell_profiles/fan_control").read_text()); assert s["mode"]=="auto" and s.get("lease_supported"), "Retorne ao automático antes de instalar."'
cmp -- "$base/avell_profiles.ko" /usr/local/lib/avell-thermal/avell_profiles.ko || { echo 'Módulo compilado difere do ativado/validado. Pare e revise a versão.' >&2; exit 1; }
for module in avell_ec_probe tuxedo_io tuxedo_keyboard uniwill_wmi ec_sys; do
    [ ! -d "/sys/module/$module" ] || { echo "Módulo concorrente: $module" >&2; exit 1; }
done
[ "$(cat /sys/class/dmi/id/product_name)" = A65i ] || exit 1
[ "$(cat /sys/class/dmi/id/bios_version)" = N.1.09AVE03 ] || exit 1
install -d -o root -g root -m 0755 "/lib/modules/$kernel/updates/avell-thermal" /etc/modules-load.d /usr/local/libexec
install -o root -g root -m 0644 "$base/avell_profiles.ko" "/lib/modules/$kernel/updates/avell-thermal/avell_profiles.ko"
install -o root -g root -m 0755 "$base/avell-profile" /usr/local/libexec/avell-profile
install -o root -g root -m 0755 "$base/avell-fan" /usr/local/libexec/avell-fan
depmod -a "$kernel"
resolved=$(modinfo -n avell_profiles)
[ "$(readlink -f "$resolved")" = "$(readlink -f "/lib/modules/$kernel/updates/avell-thermal/avell_profiles.ko")" ] || { echo "Módulo inesperado: $resolved" >&2; exit 1; }
printf '%s\n' '# Avell A65i N.1.09AVE03: carregar interface, sem iniciar controle manual.' avell_profiles > /etc/modules-load.d/avell-thermal.conf
chmod 0644 /etc/modules-load.d/avell-thermal.conf
chown root:root /etc/modules-load.d/avell-thermal.conf
modprobe --dry-run --verbose avell_profiles
echo "Instalação concluída para $kernel. Ao iniciar, as ventoinhas permanecem em automático."
echo 'Após atualizar o kernel, será necessário recompilar/reativar e instalar para a nova versão.'
