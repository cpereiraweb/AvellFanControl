#!/usr/bin/env python3
"""Build a local all-architecture DEB; ships DKMS sources, never a prebuilt .ko."""
import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]

def build(output,version):
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+',version):
        raise ValueError('Use uma versão numérica X.Y.Z.')
    output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='avell-deb-') as temp:
        tree=Path(temp)/'root';tree.mkdir()
        def put(path,text,mode=0o644):
            p=tree/path;p.parent.mkdir(parents=True,exist_ok=True)
            p.write_text(text);p.chmod(mode)
        def copy(source,target,mode=0o644):
            p=tree/target;p.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ROOT/source,p);p.chmod(mode)
        app='usr/lib/avell-thermal'
        for name in ('app.py','backend.py','tray.py','fan_session.py','paths.py','autostart.py'):
            copy(name,f'{app}/{name}')
        copy('assets/avell-thermal.svg',f'{app}/assets/avell-thermal.svg')
        copy('assets/avell-thermal.svg','usr/share/icons/hicolor/scalable/apps/avell-thermal.svg')
        for name in ('avell-fan','avell-profile'):
            copy('driver/profiles/'+name,f'{app}/privileged/{name}',0o755)
        copy('packaging/migrate_legacy.py',f'{app}/migrate_legacy.py')
        source=f'usr/src/avell-thermal-{version}'
        for name in ('avell_profiles.c','fan_manual.h','Makefile'):
            copy('driver/profiles/'+name,f'{source}/{name}')
        module=tree/source/'avell_profiles.c'
        module.write_text(module.read_text()+f'\nMODULE_VERSION("{version}");\n')
        put(f'{source}/dkms.conf',f'''PACKAGE_NAME="avell-thermal"
PACKAGE_VERSION="{version}"
BUILT_MODULE_NAME[0]="avell_profiles"
DEST_MODULE_LOCATION[0]="/updates/dkms"
AUTOINSTALL="yes"
MAKE[0]="make KDIR=/lib/modules/${{kernelver}}/build"
''')
        put('usr/bin/avell-thermal','#!/bin/sh\nexec /usr/bin/python3 /usr/lib/avell-thermal/app.py "$@"\n',0o755)
        put('usr/share/applications/br.dev.avell.Thermal.desktop','''[Desktop Entry]
Type=Application
Name=Avell Thermal
Comment=Controle das ventoinhas, temperaturas e perfis do notebook
Exec=avell-thermal
Icon=avell-thermal
Terminal=false
Categories=System;Monitor;
Keywords=Avell;temperatura;ventoinha;
''')
        put('usr/lib/modules-load.d/avell-thermal.conf','avell_profiles\n')
        copy('README.md','usr/share/doc/avell-thermal/README.md')
        copy('packaging/README.md','usr/share/doc/avell-thermal/PACKAGING.md')
        put('usr/share/doc/avell-thermal/copyright','''Avell Thermal — local package
Driver sources declare SPDX-License-Identifier: GPL-2.0-only.
See /usr/share/common-licenses/GPL-2 for the driver license.
Other application files: local/private distribution; no additional public license declared.
This package contains no proprietary OEM binaries.
''')
        for name in ('preinst','postinst','prerm','postrm'):
            put('DEBIAN/'+name,(ROOT/'packaging/debian'/name).read_text().replace('@VERSION@',version),0o755)
        size=sum(p.stat().st_size for p in tree.rglob('*') if p.is_file())//1024+1
        put('DEBIAN/control',f'''Package: avell-thermal
Version: {version}
Section: utils
Priority: optional
Architecture: all
Maintainer: Avell Thermal local maintainer <root@localhost>
Installed-Size: {size}
Depends: python3, python3-gi, python3-gi-cairo, gir1.2-gtk-4.0, gir1.2-gtk-3.0, gir1.2-adw-1, gir1.2-ayatanaappindicator3-0.1, pkexec, power-profiles-daemon, dkms (>= 3.0), linux-headers-generic, kmod
Description: Fan and performance controls for the validated Avell A65i notebook
 GTK interface and notification icon, firmware profiles, fan RPM readings,
 and 50-100 percent fan control with automatic fallback. Includes DKMS
 sources restricted to the Avell A65i with BIOS N.1.09AVE03.
''')
        checksums=[]
        for p in sorted(tree.rglob('*')):
            if p.is_file() and 'DEBIAN' not in p.relative_to(tree).parts:
                checksums.append(hashlib.md5(p.read_bytes()).hexdigest()+'  '+str(p.relative_to(tree)))
        put('DEBIAN/md5sums','\n'.join(checksums)+'\n')
        for p in tree.rglob('*'):
            if p.is_dir():p.chmod(0o755)
        artifact=output/f'avell-thermal_{version}_all.deb'
        subprocess.run(['dpkg-deb','--root-owner-group','--build',str(tree),str(artifact)],check=True)
        return artifact

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--version',default='0.1.5')
    parser.add_argument('--output',type=Path,default=ROOT/'dist')
    args=parser.parse_args()
    print(build(args.output.resolve(),args.version))
