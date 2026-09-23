# Avell Custom Control — evidências estáticas

Data: 22/09/2026. Origem: ZIP baixado pelo usuário da página oficial, filtrada para Ion A65i / Windows 11.

- ZIP: `~/Downloads/AvellCustomControl.zip`, versão 5.24.50.3.
- SHA-256: `99323b22b89881cefd34aa793647c07b16ede04fddbbcb8aec6fef9e87650174`.
- Serviço extraído: `research/oem/unpacked/app/AiStoneService/MyControlCenter/GCUService.exe`.
- SHA-256 do serviço: `8fd823e533235aa6b5857a2d940c2434277f7e8656f38d15d1c9c724ddb30a68`.
- Extração do Inno Setup com innoextract compilado localmente; inspeção .NET com ILSpy 11. Nenhum executável OEM foi executado. As ferramentas auxiliares foram extraídas em `research/tools`, sem instalação global ou sudo.

## O que foi recuperado

As constantes da classe `Define.ECSpec` identificam:

| Finalidade declarada no OEM | Endereços/valor |
|---|---|
| Main fan RPM bytes 1/2 | `0x0464`, `0x0465` |
| Second fan RPM bytes 1/2 | `0x046C`, `0x046B` (ordem declarada no OEM) |
| Controle de modo | `0x0751` |
| Flag FanBoost_Mode | `0x40` |
| Duty L/R | `0x075B`, `0x075C` |
| Project ID | `0x0740` |

As classes `Define.RamFan1_ECSpec` e `Define.RamFan1p5_ECSpec` indicam as tabelas CPU/GPU iniciando em `0x0F00`/`0x0F30` e duty em `0x0F20`/`0x0F50`. Esses endereços coincidem com os usados pelo driver Uniwill da TUXEDO para a família de controle correspondente.

O serviço também contém nomes de métodos `WMIReadECRAM`, `WMIWriteECRAM`, `FanBoostUpdate`, `UserSet_FanBoost`, `SetFanBoost` e `UserSet_FanSpeedCurveSetting`.

## Limites da evidência

Os corpos de vários métodos aparecem como `throw new Exception("Runtime exception")` na descompilação; há proteção/obfuscação. Portanto, nomes e constantes foram recuperados, mas não se comprovou a sequência exata de comandos OEM nem a conversão dos bytes em RPM. O pacote é multimodelo: sua distribuição para o A65i não prova que todas as variantes de tabela se apliquem à máquina.

Não se deve escrever constantes isoladas no EC, nem converter arbitrariamente duty em RPM. A próxima evidência é a DSDT real do notebook, para examinar o método WMI/ACPI implementado e a correspondência dos campos. A leitura direta de `/sys/firmware/acpi/tables/DSDT` retornou PermissionError.

## Próxima coleta, somente leitura

Executado pelo usuário no terminal:

```sh
sudo cat /sys/firmware/acpi/tables/DSDT > /home/cpereiraweb/Code/AvellFanControl/research/DSDT.aml
```

`sudo` autoriza apenas a leitura do arquivo de firmware; o redirecionamento cria uma cópia local com o usuário normal. Não instala módulos nem altera firmware. Após a cópia, descompilar a tabela e conferir os métodos, antes de preparar acesso controlado ao EC.

## DSDT analisada

O usuário coletou a tabela e ela foi descompilada em `DSDT.dsl`. A DSDT confirma o transporte WMI Uniwill descrito em `driver/probe/README.md`. Algumas referências externas à DSDT não foram resolvidas pelo iASL; os métodos `WMBC`, `OEMG`, `RKBC` e `WKBC` e os campos do buffer necessários para esta análise estão definidos na própria tabela. Não houve recompilação ou substituição de ACPI.

Foi compilada uma sonda própria, restrita a leitura, para obter valores reais antes de escrever no EC. A coleta privilegiada ainda depende da execução do usuário. O controle físico das ventoinhas continua pendente dessa validação.
