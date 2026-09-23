# Validação do driver — 22/09/2026

Fonte: https://github.com/tuxedocomputers/tuxedo-drivers

Commit analisado: `2c6bf54075fb38a7fdbefc560734281984bf65bc`.
Checkout em `research/tuxedo-drivers`; compilação em `research/driver-build.log`.

## Resultado

Compilação dos módulos concluída para `7.0.0-31-generic`, sem instalação ou carregamento. Secure Boot está desativado. A compilação em si não comprova suporte ao notebook.

Há um bloqueio de compatibilidade no código upstream:

- `src/tuxedo_keyboard.c`: a inicialização chama `tuxedo_is_compatible()`.
- `src/tuxedo_compatibility_check/tuxedo_compatibility_check.c`: aceita fabricante TUXEDO ou determinadas CPUs antigas. A lista Intel termina nas gerações anteriores à Raptor Lake, além de modelos Atom/Xeon específicos.
- Máquina local: GenuineIntel, família 6, modelo 183 (`0xB7`), i9-13900HX. `sys_vendor`, `board_vendor` e `chassis_vendor` são `Avell`.
- Portanto, com esse código e esses identificadores, a verificação não aceita a máquina. Essa conclusão vem da inspeção do predicado; não se tentou carregar o módulo para provocar a recusa.

Os seis GUIDs WMI de Uniwill estão presentes, mas isso só identifica o transporte. O controle de ventoinha depende de características do EC, incluindo o registrador de recursos `0x078e` e exceções por placa. Nenhuma entrada A65i/ION A65i foi encontrada.

Não se removeu o bloqueio nem se escreveu em registradores. Carregar os módulos completos também não deve ser descrito como operação apenas de leitura: a inicialização do driver pode alterar estado do hardware.

## Consulta preparada

`python3 tuxedo_probe.py` consulta somente ioctls de leitura, se `/dev/tuxedo_io` já estiver disponível com permissão. Atualmente informa dispositivo ausente. Não chama sudo, não carrega módulos e não altera permissões.

Para avançar no controle real, falta obter suporte específico ao A65i ou validar o protocolo deste EC com evidência do firmware/controlador OEM. Um patch que apenas aceite a marca Avell não resolve essa validação. A próxima investigação pode usar o pacote do Control Center/driver original correspondente ao A65i para cruzar o protocolo e os registradores, ou uma confirmação upstream para esta placa/BIOS.
