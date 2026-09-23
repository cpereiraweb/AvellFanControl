# Pacote APT local do Avell Thermal

Construir sem sudo: `python3 packaging/build_deb.py`.
Resultado: `dist/avell-thermal_0.1.5_all.deb`.

Instalar, após escolher Automático e Sair no app:

```bash
sudo apt install ./dist/avell-thermal_0.1.5_all.deb
```

O pacote instala dependências, fontesDKMS, app, ícone, entrada de menu e
auxiliares restritos. Não inclui módulo pré-compilado nem binários OEM.
DKMS compila para os kernels com headers instalados; o metapacote
linux-headers-generic mantém headers nas atualizações do Ubuntu deste notebook.
AUTOINSTALL permite aos hooksDKMS recompilar nas futuras instalações de kernel.
Mudanças nas APIs do kernel ainda podem exigir correção no fonte; não há
garantia de compatibilidade com todo kernel futuro.

A instalação encerra controle manual e descarrega o módulo antes de trocá-lo.
Ela compila antes de arquivar os arquivos manuais. Depois, guarda o módulo
manual antigo, auxiliares em/usr/local e configuração antiga de boot em
`/var/lib/avell-thermal/legacy-backup`, com hashes emmanifest.json. Os originais
saem dos caminhos de carga para evitar conflito. Arquivos pertencentes a outro
pacote, symlinks inesperados ou configuração personalizada interrompem a
migração. Nenhum arquivo em/home é alterado pelos scriptsroot.

O atalho local da instalação inicial pode ocultar o novo atalho do sistema.
`python3 packaging/migrate_desktop.py` arquiva somente o atalho do protótipo
que ainda aponta para este projeto. Execute como usuário comum após instalar.
Depois use `avell-thermal` ou o menu de aplicativos. O app em desenvolvimento
também passa a preferir os auxiliares instalados pelo pacote.

Verificar:

```bash
dpkg-query -W avell-thermal
dkms status -m avell-thermal
modinfo -n avell_profiles
cat /sys/kernel/avell_profiles/fan_control
```

O módulo deve vir deupdates/dkms e continuar automático. Não é necessário
reiniciar para usar no kernel atual. O carregamento no boot é registrado em
/usr/lib/modules-load.d/avell-thermal.conf. O app inicia no login somente se a opção “Iniciar ao entrar no Ubuntu” estiver ativada.

Remover com `sudo apt remove avell-thermal`; purgar com
`sudo apt purge avell-thermal`. A remoção primeiro restaura automático e
recusa prosseguir caso o módulo permaneça ocupado; não usa remoção forçada.
DKMS remove apenasavell-thermal/versão. Backups da instalação manual são
mantidos como dados de recuperação e não voltam a ser carregados sozinhos.

Se a compilação/configuração falhar, APT informa falha e não é declarado
sucesso. Consulte/var/lib/dkms/avell-thermal/versão/build/make.log e corrija a
causa antes de `sudo dpkg --configure -a`. Os backups permitem recuperação
manual; não restaure módulo antigo sobre um DKMS ativo sem revisar os caminhos.

Este é um.deb local, não um repositórioAPT publicado. Atualização do código do
app exige instalar um novo.deb; atualização do kernel acionaDKMS automaticamente.
O suporte de hardware continua restrito aAvell A65i/ION A65i/BIOSN.1.09AVE03.
