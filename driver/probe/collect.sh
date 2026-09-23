#!/bin/bash
# Temporary root-only probe. Writes no persistent system configuration.
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
probe_profiles=0
probe_reuse_snapshot=''
while [ "$#" -gt 0 ]; do
    case "$1" in
        --profiles) probe_profiles=1; shift ;;
        --reuse-snapshot)
            if [ "$#" -lt 2 ] || [[ ! "$2" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{2}-[0-9]{2}-[0-9]{2}$ ]]; then
                echo 'Informe o nome completo do snapshot existente.' >&2; exit 1
            fi
            probe_reuse_snapshot=$2; shift 2 ;;
        *) echo 'Uso: collect.sh [--profiles] [--reuse-snapshot AAAA-MM-DD_HH-MM-SS]' >&2; exit 1 ;;
    esac
done
if [ "$probe_profiles" -eq 1 ] && ! test -r /dev/tty; then
    echo 'A coleta dos estágios requer um terminal interativo.' >&2
    exit 1
fi
if [ "$EUID" -ne 0 ]; then
    echo 'Execute esta coleta com sudo.' >&2
    exit 1
fi
probe_dir=$(cd -- "$(dirname -- "$0")" && pwd)
probe_module="$probe_dir/avell_ec_probe.ko"
if [ -d /sys/module/avell_ec_probe ]; then
    echo 'A sonda já está carregada; nenhuma ação foi feita.' >&2
    exit 1
fi
for probe_conflict in tuxedo_io tuxedo_keyboard uniwill_wmi ec_sys; do
    if [ -d "/sys/module/$probe_conflict" ]; then
        echo "Coleta recusada: módulo concorrente $probe_conflict." >&2
        exit 1
    fi
done
probe_vermagic=$(modinfo -F vermagic "$probe_module")
if [ "${probe_vermagic%% *}" != "$(uname -r)" ]; then
    echo 'Módulo compilado para outro kernel. Recompile antes da coleta.' >&2
    exit 1
fi
probe_loaded=0
cleanup() {
    if [ "$probe_loaded" -eq 1 ]; then
        rmmod avell_ec_probe || echo 'Não foi possível descarregar a sonda.' >&2
    fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
# Follow the notebook's operational rule: snapshot before experimental modules.
# If the backup fails, set -e aborts before loading any module.
if [ -n "$probe_reuse_snapshot" ]; then
    echo "Verificando snapshot existente: $probe_reuse_snapshot (sem criar outro backup)…" >&2
    probe_snapshot_list=$(timeshift --list --scripted 2>&1)
    if ! grep -Fq -- "$probe_reuse_snapshot" <<< "$probe_snapshot_list"; then
        echo 'Snapshot não encontrado. A sonda não será carregada.' >&2
        exit 1
    fi
    echo 'Snapshot confirmado.' >&2
else
    echo 'Criando snapshot Timeshift antes da sonda temporária…' >&2
    timeshift --create --comments 'Antes da sonda EC Avell A65i' --tags O --scripted >&2
fi
confirm_step() {
    local expected=$1 message=$2 answer
    # Each step needs its own token. Do not tcflush /dev/tty: under sudo
    # job control it can suspend the child with SIGTTOU before the prompt.
    printf '\n%s\n' "$message" >&2
    while true; do
        printf 'Digite %s e pressione Enter neste terminal: ' "$expected" >&2
        read -r answer < /dev/tty
        if [ "$answer" = "$expected" ]; then break; fi
        echo 'Confirmação diferente da esperada; a etapa NÃO avançou.' >&2
        echo 'Se já deu o toque solicitado, NÃO pressione o botão físico novamente. Falta apenas digitar a confirmação.' >&2
    done
}
if [ "$probe_profiles" -eq 1 ]; then
    confirm_step INICIAR 'Prepare-se para a leitura inicial. Ainda NÃO pressione o botão físico.'
fi
echo 'Coletando leituras do EC…' >&2
insmod "$probe_module"
probe_loaded=1
echo '['
if [ "$probe_profiles" -eq 1 ]; then
    echo '{"stage":"initial","snapshot":'
    cat /sys/kernel/avell_ec_probe/snapshot
    echo '}'
    for probe_stage in 1 2 3; do
        confirm_step "PASSO$probe_stage" "Agora pressione UMA vez o botão físico de desempenho (toque $probe_stage de 3). Aguarde a indicação estabilizar."
        printf ',{"stage":"after_press_%s","snapshot":\n' "$probe_stage"
        cat /sys/kernel/avell_ec_probe/snapshot
        echo '}'
    done
else
    for probe_sample in 1 2 3; do
        if [ "$probe_sample" -gt 1 ]; then echo ','; fi
        cat /sys/kernel/avell_ec_probe/snapshot
        if [ "$probe_sample" -lt 3 ]; then sleep 2; fi
    done
fi
echo ']'
echo 'Coleta concluída. Descarregando a sonda temporária.' >&2
