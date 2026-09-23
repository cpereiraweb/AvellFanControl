#!/usr/bin/python3 -I
"""Archive exactly the paths created by the prototype installer. No home edits."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys

class Migration:
    def __init__(self, root=Path('/'), check_owner=True):
        self.root=root
        self.backup=root/'var/lib/avell-thermal/legacy-backup'
        self.check_owner=check_owner

    def paths(self):
        fixed=['usr/local/libexec/avell-fan','usr/local/libexec/avell-profile',
               'usr/local/lib/avell-thermal/avell_profiles.ko',
               'etc/modules-load.d/avell-thermal.conf']
        modules=self.root/'lib/modules'
        return [self.root/p for p in fixed]+list(modules.glob('*/updates/avell-thermal/avell_profiles.ko'))

    def archive(self):
        self.backup.mkdir(mode=0o700,parents=True,exist_ok=True)
        if self.check_owner and (self.backup.stat().st_uid!=0 or self.backup.stat().st_mode & 0o022):
            raise RuntimeError('Diretório de backup não protegido.')
        manifest=self.backup/'manifest.json'
        entries=json.loads(manifest.read_text()) if manifest.exists() else {}
        candidates=[]
        for path in self.paths():
            if not path.exists() and not path.is_symlink():continue
            info=path.lstat()
            if not stat.S_ISREG(info.st_mode) or (self.check_owner and info.st_uid!=0):
                raise RuntimeError(f'Arquivo inesperado; migração interrompida: {path}')
            if self.check_owner:
                owned=subprocess.run(['/usr/bin/dpkg-query','-S',str(path)],capture_output=True).returncode==0
                if owned:raise RuntimeError(f'Outro pacote possui {path}; não será alterado.')
            if path.name=='avell-thermal.conf':
                lines=[l.strip() for l in path.read_text().splitlines() if l.strip() and not l.lstrip().startswith('#')]
                if lines!=['avell_profiles']:raise RuntimeError('Configuração local de módulos foi personalizada; revise antes de migrar.')
            relative=str(path.relative_to(self.root))
            destination=self.backup/relative
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            if destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest()!=digest:
                raise RuntimeError(f'Backup diferente já existe: {destination}')
            candidates.append((path,destination,relative,digest))
        # Save every copy and the manifest before removing any original.
        for path,destination,relative,digest in candidates:
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(path,destination)
            entries[relative]={'sha256':digest}
        temporary=manifest.with_suffix('.tmp')
        temporary.write_text(json.dumps(entries,indent=2)+'\n')
        temporary.replace(manifest)
        for path,_,_,_ in candidates:path.unlink()
        if self.check_owner:
            for k in (self.root/'lib/modules').iterdir():
                if k.is_dir():subprocess.run(['/usr/sbin/depmod','-a',k.name],check=True)
        return len(candidates)

if __name__=='__main__':
    if os.geteuid()!=0 or sys.argv[1:]!=['archive']:raise SystemExit('Uso administrativo: archive')
    print('Arquivos da instalação manual arquivados:',Migration().archive())
