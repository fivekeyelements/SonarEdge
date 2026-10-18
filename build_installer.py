"""Compile the standard per-user installer after build_native.py."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
from app_version import VERSION

ROOT=Path(__file__).resolve().parent


def compiler():
    candidates=[os.environ.get('SONAR_EDGE_ISCC'),shutil.which('ISCC.exe'),
                ROOT/'build/tools/inno/ISCC.exe',
                Path(os.environ.get('ProgramFiles(x86)',r'C:\Program Files (x86)'))/'Inno Setup 6/ISCC.exe',
                Path(os.environ.get('LOCALAPPDATA',''))/'Programs/Inno Setup 6/ISCC.exe']
    result=next((Path(p) for p in candidates if p and Path(p).is_file()),None)
    if not result:raise RuntimeError('Install Inno Setup 6.7.3 or set SONAR_EDGE_ISCC to ISCC.exe')
    return result


def build(test=False):
    args=[str(compiler()),'/Qp',f'/DAppVersion={VERSION}']
    name=f'SonarEdge-Setup-{VERSION}-Windows-x64'
    if test:
        name=f'SonarEdge-TestSetup-{VERSION}-Windows-x64'
        args += ['/DAppId=SonarEdgeInstallTest','/DProductName=Sonar Edge Install Test',
                 '/DProfileName=SonarEdgeInstallTest','/DRunValueName=Sonar Edge Install Test',f'/DOutputName={name}']
    subprocess.run([*args,str(ROOT/'installer/SonarEdge.iss')],cwd=ROOT,check=True)
    result=ROOT/'releases'/(name+'.exe')
    if not test:
        files=[result,ROOT/'releases'/f'SonarEdge-{VERSION}-Windows-x64.zip']
        (ROOT/'releases/SHA256SUMS.txt').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in files),'utf-8')
    print(result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--test',action='store_true')
    build(parser.parse_args().test)
