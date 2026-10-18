"""Build a reproducible desktop EXE and a clean, shareable release ZIP."""
import importlib.metadata as metadata
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile
from build_musicbee import build as build_musicbee
from app_version import VERSION

ROOT = Path(__file__).resolve().parent
RELEASE = ROOT / 'releases' / f'SonarEdge-{VERSION}-Windows-x64'
RELEASE.mkdir(parents=True, exist_ok=True)
manifest=ROOT/'widget/manifest.json'
import json
widget=json.loads(manifest.read_text('utf-8'))
widget['version']=VERSION
manifest.write_text(json.dumps(widget,indent=2)+'\n','utf-8')
resource=ROOT/'version-info.txt'
text=resource.read_text('utf-8')
import re
numbers=','.join(VERSION.split('.'))+',0'
text=re.sub(r'(filevers|prodvers)=\([0-9,]+\)',lambda m:m.group(1)+'=('+numbers+')',text)
text=re.sub(r"(StringStruct\('(?:FileVersion|ProductVersion)',')[^']+",lambda m:m.group(1)+VERSION,text)
resource.write_text(text,'utf-8')
build_musicbee()
subprocess.run(['npx.cmd', '--yes', 'icuewidget-cli@0.5.0', 'package', str(ROOT / 'widget'),
                '-o', str(RELEASE / 'Sonar Edge XL.icuewidget')], cwd=ROOT, check=True)
subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm',
                '--distpath', str(RELEASE), '--workpath', str(ROOT / 'build/native'),
                str(ROOT / 'SonarEdge.spec')], cwd=ROOT, check=True)
for file in (ROOT / 'packaging').iterdir():
    if file.is_file() and file.name not in ('Install.ps1','Install Sonar Edge.cmd'):
        shutil.copy2(file, RELEASE / file.name)

packages = ['pywebview', 'pythonnet', 'clr_loader', 'cffi', 'pycparser', 'bottle', 'proxy_tools',
            'typing_extensions', 'winrt-runtime', 'winrt-Windows.Media.Control', 'winrt-Windows.Media',
            'winrt-Windows.Storage.Streams', 'winrt-Windows.Foundation', 'winrt-Windows.Foundation.Collections']
notices = [f'Sonar Edge {VERSION} - bundled third-party components', '',
           'The executable includes Python 3.12 and the following runtime components.',
           'Full license texts supplied by each installed distribution are in licenses/.', '']
license_folder = RELEASE / 'licenses'
license_folder.mkdir(exist_ok=True)
for package in packages:
    distribution = metadata.distribution(package)
    notices.append(f'{distribution.metadata["Name"]} {distribution.version}')
    for file in distribution.files or []:
        name = str(file).lower()
        if 'license' not in name and 'copying' not in name and 'notice' not in name:
            continue
        source = Path(distribution.locate_file(file))
        if source.is_file() and source.suffix.lower() in ('', '.txt', '.md', '.rst'):
            destination = license_folder / distribution.metadata['Name'] / file.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
python_license = Path(sys.base_prefix) / 'LICENSE.txt'
if python_license.exists():
    shutil.copy2(python_license, license_folder / 'Python-LICENSE.txt')
(RELEASE / 'THIRD-PARTY-NOTICES.txt').write_text('\n'.join(notices) + '\n', 'utf-8')

archive = ROOT / 'releases' / (RELEASE.name + '.zip')
allowed = {'SonarEdge.exe', 'Read me.txt', 'THIRD-PARTY-NOTICES.txt', 'Sonar Edge XL.icuewidget',
           'iCUE XL setup.txt'}
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
    for file in RELEASE.rglob('*'):
        relative = file.relative_to(RELEASE)
        if file.is_file() and (relative.parts[0] in allowed or relative.parts[0] == 'licenses'):
            z.write(file, str(Path(RELEASE.name) / relative))
print(f'Release: {archive}')
