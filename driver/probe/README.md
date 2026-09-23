# Sonda temporária de leitura — A65i

Esta etapa valida o transporte antes de implementar controles. Não é um controlador de ventoinhas.

## Evidência da máquina

A DSDT fornecida pelo usuário contém `_SB.AMW0`, cujo `_WDG` associa o GUID `ABBC0F6F-8EA1-11D1-00A0-C90629100000` ao método `WMBC`. Esse método aceita a operação 4 e passa seu buffer para `OEMG`. O seletor de leitura é `SAC1 == 0x0100`, correspondente ao byte 5 igual a 1. O método `RKBC` usa os dois primeiros bytes como endereço e retorna os bytes lidos em `SA00/SA01`.

O firmware retorna `FEFEFEFE...` quando o EC está ocupado, indisponível ou houve timeout. A sonda rejeita essa resposta, resultados ACPI inválidos ou curtos e não entrega valores parciais.

## Escopo

- Apenas consultas a 16 endereços fixos de temperatura, bytes de tacômetro, modo, identificador e recursos.
- Não contém API de escrita de registrador, parâmetros para escolher endereços, comando de boost, ajuste de potência ou curva.
- Apenas leitura de `/sys/kernel/avell_ec_probe/snapshot`, restrita a root.
- Usa o método de firmware para a transação de leitura; o próprio firmware movimenta seu mailbox de comunicação. Isso não equivale a acesso passivo à RAM, mas não solicita alterações de configuração térmica.
- Carregar/descarregar não consulta o EC. As consultas só acontecem ao ler o atributo.
- Restringe a máquina pelos identificadores Avell / A65i / ION A65i / N.1.09AVE03 e pela presença do GUID.
- Sem serviço, autoload, DKMS, instalação em `/lib/modules`, substituição de driver ou mudanças no boot.
- Um módulo externo pode marcar o kernel como tainted até reiniciar; isso é comportamento normal do Linux para módulos externos, não prova de falha.

## Execução pelo usuário

Compilado com `make -C driver/probe`, para `7.0.0-31-generic`, com `W=1`. Não foi carregado pelo assistente.

```sh
sudo bash /home/cpereiraweb/Code/AvellFanControl/driver/probe/collect.sh > /home/cpereiraweb/Code/AvellFanControl/research/ec-probe.json
```

O script cria primeiro um snapshot Timeshift, conforme a regra operacional do notebook em `~/Code/Ubuntu25/CLAUDE.md`, e só carrega o módulo se o snapshot concluir. Em seguida coleta três amostras com intervalo de dois segundos e descarrega a sonda. A limpeza também é solicitada em interrupção ou erro; falha de descarregamento é informada no terminal. O sistema continua usando o controle térmico do firmware.

Se ocorrer erro, o JSON pode estar incompleto: não interpretar como sucesso nem repetir cegamente. O script recusa versões de kernel diferentes e módulos concorrentes conhecidos. Não há garantia de detectar outros processos de acesso direto ao EC.

Os bytes do tacômetro ainda não são apresentados como RPM: faltam validar a ordem/conversão e observar valores reais neste firmware. Antes disso, a interface não deve inventar valores de RPM ou habilitar controles.

## Mapear os três estágios do botão físico

```sh
cd /home/cpereiraweb/Code/AvellFanControl
sudo bash driver/probe/collect.sh --profiles > research/ec-profiles.json
```

O script exige `INICIAR` antes da leitura inicial e pede três toques individuais no botão. Após cada toque, aguarde a indicação estabilizar e digite o token solicitado (`PASSO1`, `PASSO2`, `PASSO3`), seguido de Enter no terminal. Teclas pendentes são descartadas antes de cada pedido; Enter sozinho não avança. Ele captura o estado após cada toque, formando uma volta completa se o botão efetivamente alternar três estados em sequência. O usuário informou três estágios e LED aceso no último; o nome Turbo ainda é hipótese do usuário, não confirmado pelo software.

Para repetir imediatamente a coleta, `--reuse-snapshot AAAA-MM-DD_HH-MM-SS` verifica o snapshot existente via Timeshift e evita um novo backup. O snapshot `2026-09-22_12-23-34` foi concluído às 12:30:34. A coleta inicial foi preservada; a repetição deve usar outro arquivo de saída, por exemplo `research/ec-profiles-repeat.json`.

São incluídos o byte de modo `0x0751`, índice OEM `0x07AB`, flags de aplicação `0x0741` e de perfil customizado `0x0727`. Não se presume que o perfil de energia do Ubuntu corresponda ao modo OEM. As únicas mudanças de modo durante essa coleta são as solicitadas pelo usuário através do botão físico.
