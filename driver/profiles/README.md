# Perfis experimentais do Avell A65i

Validação dos três perfis pelo app concluída em 2026-09-22: o usuário selecionou Turbo
pelo app, autenticou e confirmou LED aceso; selecionou Equilibrado pelo app,
autenticou e confirmou LED apagado. A leitura de
`/sys/kernel/avell_profiles/profile` confirmou `balanced`.
Em seguida, o usuário selecionou Economia pelo app e a leitura do firmware
confirmou `economy`; o perfil independente do Ubuntu estava em `power-saver`.
Efeitos em limites de potência, temperaturas e RPM não foram medidos.
Escopo exato: Avell / A65i / ION A65i / BIOS N.1.09AVE03.

A coleta `research/ec-profiles-repeat2.json` confirmou o ciclo do registro
0x0751: 0x20 → 0xa0 → 0x30 → 0x20. O usuário confirmou LED aceso no
segundo toque (0x30). Nomes provisórios: economy=0xa0, balanced=0x20,
turbo=0x30. Isso não comprova limites de potência específicos de cada modo.

Transporte: DSDT local `_SB.AMW0.WMBC`, método 4, buffer de 8 bytes;
selector byte5=1 para RKBC, zero para WKBC; endereço bytes0/1,
valor byte2. Conferido também em `research/tuxedo-drivers/src/uniwill_wmi.c`
(commit 2c6bf54075fb38a7fdbefc560734281984bf65bc). O módulo é independente.

Só aceita os três bytes observados; rejeita estado atual diferente. Não expõe
escrita arbitrária, curvas, PWM, boost de ventoinha ou limites de potência.
A leitura e escrita usam mutex e falhas de transporte são propagadas.
Após escrita, aguarda 100ms e exige leitura idêntica. Sem retries nem rollback
cego que possam sobrepor um toque físico concorrente. Um erro pode acontecer
após uma escrita efetiva: confira o estado exibido e o botão físico.
O firmware mantém controle automático das ventoinhas. A troca deste byte reproduziu o LED de Turbo/Equilibrado no teste físico.
A equivalência completa de limites de potência com o botão não foi medida.

## Ativar para validar

```bash
make -C driver/profiles
sudo bash driver/profiles/activate.sh 2026-09-22_12-23-34
```

Reutiliza snapshot, verifica módulos concorrentes e kernel; copia auxiliar e
módulo para arquivos root-owned em /usr/local. Carrega o módulo somente nesta
sessão, sem autoload/DKMS e **sem escrita no carregamento**. Módulo externo
causa taint do kernel até reiniciar. Atualização do kernel exige recompilar.

A interface `/sys/kernel/avell_profiles/profile` permite leitura pública e
escrita apenas root. O app usa pkexec no auxiliar instalado, com autenticação
administrativa padrão do sistema, sem sudoers ou execução privilegiada do app.
Os perfis do Ubuntu continuam independentes. O app acompanha o botão por polling.

Partindo de Turbo, selecionar Equilibrado no app, conferir LED apagado e
perfil confirmado; depois Economia e Turbo, conferindo retorno do LED.
Não pressionar o botão físico simultaneamente ao teste pelo app.
Não chamar o ajuste manual de RPM de validado por causa deste teste.

## Desativar

```bash
sudo rmmod avell_profiles
```

Descarregar não escreve no EC: o perfil escolhido permanece até nova seleção
pelo firmware/botão. Fechar o app também não altera o perfil.
Para remover os arquivos instalados após descarregar:

```bash
sudo rm /usr/local/libexec/avell-profile /usr/local/lib/avell-thermal/avell_profiles.ko
```

## Preparação do controle manual

A versão seguinte acrescenta somente leituras: `fans` (RPM dos dois canais,
CPU/GPU e duty bruto) e `fan_config` (flags 07c5/07c6, capacidade 078e, modo
0751 e 96 bytes 0f00–0f5f). RPM usa os bytes alto/baixo definidos no ECSpec;
alto/baixo/alto evita leitura partida. Essa interpretação ainda deve ser
conferida durante a validação das velocidades. Não associa canal a CPU/GPU
sem evidência física.

Atualização sem alterar perfil: `sudo bash driver/profiles/activate.sh
2026-09-22_12-23-34 --replace` (uma única linha). Após carregar, capturar
`cat /sys/kernel/avell_profiles/fan_config > research/fan-config-original.json`.
O arquivo JSON é diagnóstico; um futuro controle deverá salvar a configuração
novamente imediatamente antes de cada sessão manual e restaurá-la ao sair.
Ainda não existe escrita de velocidade nessa versão. A referência universal
Uniwill recebe duty 0–200 (0–100%), não um alvo direto em RPM. Precisamos
validar resposta e retorno automático antes de liberar controle contínuo.


## Teste inicial de ventilação máxima (pendente de hardware)

Captura 2026-09-22: 07c5=0, 07c6=0, 078e=236, 0751=160;
as 96 posições 0f00–0f5f estão zeradas, com tabela customizada desativada.
Leitura inicial: canais 1/2 em 2652/2605 RPM, CPU64°C/GPU45°C.
Tabelas zeradas desativadas não significam curva automática ausente: a curva
padrão é interna ao firmware.

O novo atributo root-only `fan_boost` aceita `test` (15s) e `auto`.
Somente o bit 0x40 em 0751 é alterado, seguindo `set_full_fan_mode` do
TUXEDO e a constante FanBoost do OEM. Nenhuma curva ou duty é escrito.
`boost` significa bit ativado, não comprovação de RPM máximo: a medição
física é necessária. Não confundir este bit com o perfil Turbo (0x30).

O temporizador do kernel tenta limpar o bit após 15s mesmo se o programa
sair. Se ocorrer falha de transporte ao restaurar, tenta novamente a cada
segundo, mantendo o estado sinalizado; não há garantia contra falha do EC.
Suspensão é recusada se a restauração falhar. Descarregamento tenta restaurar
e registra erro se não conseguir; nunca use remoção forçada do módulo.
O teste impede trocas de perfil pelo app enquanto está ativo; a restauração
preserva alterações de outros bits feitas pelo botão físico.

```bash
sudo bash driver/profiles/activate.sh 2026-09-22_12-23-34 --replace
sudo python3 driver/profiles/test_boost.py > research/fan-boost-test.json
```

O segundo comando inicia o teste imediatamente, leva cerca de 25s e mostra
leituras no terminal. Não tocar no botão físico. Confere retorno automático
sem intervenção após 18s e captura novamente a configuração ao final.
Ctrl+C aciona tentativa de retorno imediato; o temporizador permanece como
proteção independente. O teste não instala serviço nem habilita modo manual
permanente. Controle variável em porcentagem continua pendente.

Teste de lógica sem hardware:
`python3 tests/check_boost_logic.py driver/profiles/avell_profiles.c`.

## Controle intermediário experimental (versão atual)

Teste de boost confirmado em hardware: 2945/2861 → 5310/5165 RPM, duty200,
retorno automático, configuração idêntica ao início. Isso valida full-fan,
não valida ainda a nova tabela de velocidades intermediárias.

`fan_control` oferece sessões de 30s entre 50–100%, passos de 5%, mesmo valor
nos dois canais. A janela possui slider e a bandeja presets60/75/100.
Autenticação via auxiliar root-owned `/usr/local/libexec/avell-fan`.
Não é alvo de RPM: o firmware recebe duty percentual, enquanto a rotação é
medida. Fechar/crash do app não renova o prazo: o kernel encerra a sessão.
A versão não mantém controle contínuo nem inicia manual automaticamente.

O driver aceita somente o baseline observado (flags07c5/07c6 zerados,
bit6 da capacidade078e ativo, um dos três perfis conhecidos). Guarda as 96
posições imediatamente antes da sessão. Verifica cada escrita antes de
ativar os bits7/2 de07c5/07c6. Tabela segue o layout universal Uniwill;
primeira zona CPU até85°C, GPU até80°C, demais zonas em100%. Monitor de1s
interrompe em temperatura >=85/80, falha de sensor ou mudança de perfil.
Esses mecanismos ainda exigem validação física; não são garantia contra
travamento do EC/kernel. O primeiro teste deve ser feito sem carga pesada.

Restauração desativa a tabela antes de repor todos os bytes alterados.
Se falhar desativar, tenta full-fan e repete a restauração a cada segundo.
Não descarta o backup até concluir. Estado `restoring` não é sucesso.
Captura longa da tabela é recusada durante modo manual para não atrasar
voluntariamente o monitor. A duração pode variar com latência do EC.
A escolha de perfil no app fica bloqueada durante modo manual; toque físico
provoca retorno ao automático. Suspensão tenta restaurar antes de prosseguir.
Uma referência ao módulo impede descarregamento normal durante uma sessão ou
restauração pendente. Não usar remoção forçada. A referência só é liberada
após restauração completa.

Primeira validação:

```bash
sudo bash driver/profiles/activate.sh 2026-09-22_12-23-34 --replace
sudo python3 driver/profiles/test_manual.py > research/fan-manual-test.json
```

Executar separadamente. Programa70% por30s e observa até45s; a preparação,
restauração e captura de tabelas acrescentam alguns segundos. Registra modo,
duty, RPM e configurações antes/depois. Nenhuma confirmação por teclado.
A atualização futura a partir desta versão requer retornar ao automático e
descarregar explicitamente o módulo: o instalador recusa módulo com
`fan_control` já carregado, evitando atualização durante sessão manual.

Verificações sem hardware:
`python3 tests/check_manual_logic.py`, `python3 tests/check_boost_logic.py
driver/profiles/avell_profiles.c`, e testes unitários Python.

## Investigação após primeiro teste intermediário — revisão 2

`research/fan-manual-test.json` provou restauração completa, mas não sustentou
70%: duty caiu de126 para104 e71 (escala200), apesar do estado interno manual.
Não considerar a versão1 validada para potência fixa.

Foi encontrada uma diferença com a inicialização Uniwill upstream:
`uniwill_keyboard_probe` escreve0741=1 para habilitar manual mode e a remoção
escreve0741=0. No A65i a coleta inicial mostrou0741=4. A revisão2 testa a
hipótese do bit0, preservando o bit2: exige baseline4, grava5 durante a sessão
e restaura somente o bit0 ao final, preservando outros bits concorrentes.
Não modifica0727, cuja habilitação upstream é condicionada a outros modelos.
Fonte: tuxedocomputers/tuxedo-drivers, commit
2c6bf54075fb38a7fdbefc560734281984bf65bc, src/uniwill_keyboard.h.

A verificação periódica agora exige host0741 bit0, flags07c5 bit7 e07c6 bit2.
Depois de5s compara ambos duty reais com percent*2; diferença absoluta >10
(5 pontos percentuais) aborta para automático com reason firmware_override.
Nenhuma reescrita periódica de duty é feita para disputar controle com EC.
A telemetria registra esses flags e as duas primeiras entradas duty das tabelas.
A captura final inclui0741 para verificar restauração dessa configuração.

Executar separadamente:

```bash
sudo bash driver/profiles/activate.sh 2026-09-22_12-23-34 --replace
sudo python3 driver/profiles/test_manual.py > research/fan-manual-test-v2.json
```

O instalador atualizado aceita substituir driver com fan_control somente se
mode=auto; rmmod também é impedido pela referência do módulo em sessão ativa.
Ainda é uma hipótese pendente de teste físico; não afirmar correção concluída.

## Revisão 3: repetibilidade e baseline automático

Revisão2 validou 70% nas duas ventoinhas (duty140, ~4083/3885RPM) e
retorno por timeout. Configuração: tabelas e flags restaurados, mas0741 mudou
4→1 durante manual e→0 ao encerrar. O bit2 foi removido pelo firmware durante
a sessão apesar da escrita com preservação (5). Sua semântica permanece
não identificada; não se deve inventar que seja um alerta ou forçá-lo a1.
O código upstream Linux identifica somente bit0 como ENABLE_MANUAL_CTRL,
bit3 como ITE_KBD_EFFECT_REACTIVE e bit5 como FAN_ABNORMAL nesse byte:
https://github.com/torvalds/linux/blob/master/drivers/platform/x86/uniwill/uniwill-acpi.c

O estado0 atual é automático (bit0 limpo), compatível com a desativação do
TUXEDO, e apresenta resposta térmica normal nas amostras. A revisão3 aceita
baseline0 ou4 observados, recusando outros estados. Continua modificando
somente bit0. Não afirma equivalência semântica completa entre0 e4.
`validate_fans.py` testa50/70/100 em sequência e exige restauração byte a byte,
inclusive0741; a execução parte agora do baseline0 medido. Mantém limites e
proteções anteriores; interrompe ao detectar qualquer resultado inesperado.
Uso contínuo, recuperação após crash/suspensão e instalação definitiva ainda
pendentes. Não carregar outro driver Uniwill/EC simultaneamente.

## Controle contínuo com autorização renovável

Validação `research/fan-validation.json` concluída: 50% duty100 ~3194/3117RPM,
70% duty140 ~4114/3885RPM, 100% duty200 ~5337/5165RPM. Restauração byte a byte
confirmada nas três sessões; cancelamento e timeout aprovados. Não é alvo RPM.

Versão contínua: auxiliar root-owned Python isolado (-I), uma autenticação
pkexec por sessão, comunicação somente por pipes herdados. App envia renew
a cada3s enquanto o loop GTK responde (limite10s). Auxiliar para após12s
sem mensagens ou EOF; kernel continua exigindo renovação do prazo de30s.
Sessões possuem id: auxiliares antigos não podem renovar/cancelar sessões
novas. Guards térmicos/perfil/duty continuam ativos, inclusive nas renovações.
Suspensão restaura manual antes de dormir; a sessão antiga não é retomada.
Fechar a janela mantém o app na bandeja, logo mantém manual; **Sair** encerra.
Um crash/kill deve provocar restauração por EOF ou timeout. Não existe
restauração de controle manual após reboot. A seleção Automático encerra o
auxiliar existente sem pedir nova autenticação; iniciar outra potência abre
uma nova sessão autenticada. A UI usa estado do driver como fonte de verdade.

Validação adicional: `sudo python3 driver/profiles/validate_session.py >
research/fan-session-validation.json` (uma linha). Sustenta70% por mais de30s,
fecha IPC e compara configuração; depois mata o auxiliar para exercitar o
prazo do kernel. Não usar app/botão durante a rotina. Só considerar o modo
contínuo validado em hardware após analisar esse JSON.

## Critério de restauração revisto após observação passiva

Após o teste contínuo, o registro0741 foi medido como0 em automático. Na
investigação seguinte, antes de qualquer nova escrita nossa, voltou a4 em
automático, com flags07c5/07c6 desativados e duty variável do firmware. Oito
leituras passivas confirmaram4. Isso é evidência de que o bit2 pode variar
fora da sessão manual; não identifica sua função nem prova segurança universal.

O verificador antigo misturava estado observado do firmware com configurações
controladas pelo app e abortava antes do teste de crash. O novo verificador
mantém `exact_match=false` quando0741 muda0↔4, registra a diferença e exige
bit0 manual desativado, ambas flags de tabela zeradas, todas96 posições
restauradas, perfil e capacidades idênticos. Qualquer outra diferença falha.
A variação do bit2 nunca é apagada do relatório nem corrigida por escrita.
Somente o resultado `controls_restored` usa este critério; não afirmar que o
byte completo voltou ao valor inicial quando `exact_match` for falso.

Rodar novamente `sudo python3 driver/profiles/validate_session.py >
research/fan-session-validation-v2.json` em uma linha. Não precisa recarregar
módulo: apenas o verificador mudou. Testes em tests/test_restoration.py cobrem
bit0 ativo, outros bits desconhecidos, tabela divergente e dados incompletos.

## Resultado do modo contínuo

`research/fan-session-validation-v2.json`: passed=true. Contínuo70% por41,9s,
duty140 nos dois canais, ~4114/3885RPM; EOF restaurou controles e tabelas,
reportando0741 bit2 separadamente. Auxiliar morto porSIGKILL: watchdog confirmou
retorno por timeout, configuração completamente idêntica nessa segunda sessão.
Último estado observadoauto. Isso não constitui teste físico de suspensão ou
reboot, nem comprova a função do bit2. Instalação de boot para kernel atual
preparada em install_boot.sh; sem DKMS e sem aplicar manual no carregamento.
