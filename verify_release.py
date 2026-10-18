"""Check the share package and optionally update this checkout's desktop links."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent
from app_version import VERSION
NAME = f'SonarEdge-{VERSION}-Windows-x64'
RELEASE = ROOT / 'releases' / NAME


def verify():
    archive = RELEASE.parent / (NAME + '.zip')
    with zipfile.ZipFile(archive) as package:
        assert package.testzip() is None
        names = package.namelist()
        assert f'{NAME}/SonarEdge.exe' in names
        assert f'{NAME}/Sonar Edge XL.icuewidget' in names
        assert f'{NAME}/Choose app version.vbs' in names
        assert not any(Path(name).name in ('preferences.json', 'app-version.json', 'interface.html', 'runtime.log', 'sonar-edge.log')
                       or '/backgrounds/' in name or '/artwork/' in name for name in names)
    with tempfile.TemporaryDirectory(prefix='SonarEdge-check-') as folder:
        environment = os.environ.copy()
        environment['SONAR_EDGE_DATA_DIR'] = folder
        environment.pop('SONAR_EDGE_WIDGET_PORT', None)
        report = Path(folder) / 'diagnostic.json'
        result = subprocess.run([str(RELEASE / 'SonarEdge.exe'), '--diagnose', str(report)],
                                env=environment, timeout=35)
        assert result.returncode == 0 and report.is_file()
        data = json.loads(report.read_text('utf-8'))
        assert data['version'] == VERSION and data['transport'] == 'native'
        meters=data['state']['meters']
        assert set(meters['levels']) == {'master','game','chat','media','aux','mic'}
        assert all(v is None or isinstance(v,(int,float)) and 0 <= v <= 1 for v in meters['levels'].values())
        print(json.dumps({'version': VERSION, 'sonarConnected': data['state']['sonar']['connected'],
                          'musicConnected': data['state']['music']['connected'],
                          'liveMeters': meters['connected'], 'albumPalette': bool(data['state']['music'].get('palette')),
                          'packageFiles': len(names), 'zipMB': round(archive.stat().st_size / 1024 / 1024, 1)}))


def update_existing_links():
    # Our previously generated .lnk files contain these fixed-length paths in
    # both LinkInfo and Unicode strings. Equal-length updates preserve offsets.
    desktop = Path(os.environ['USERPROFILE']) / 'Desktop'
    for name in ('Sonar Edge.lnk', 'Sonar Edge for iCUE.lnk'):
        link = desktop / name
        if not link.exists():
            continue
        body = link.read_bytes()
        changed = body
        for version in ('1.1.0', '1.2.0', '1.2.1', '1.2.2', '1.3.0', '1.4.0', '1.5.0', '1.6.0'):
            old = f'SonarEdge-{version}-Windows-x64'
            for encoding in ('utf-8', 'utf-16-le'):
                changed = changed.replace(old.encode(encoding), NAME.encode(encoding))
        if name == 'Sonar Edge.lnk':
            # Whitespace arguments preserve existing .lnk offsets while allowing
            # the normal shortcut to follow the user's saved app version.
            changed=changed.replace('--edge'.encode('utf-16-le'),'      '.encode('utf-16-le'))
        if changed != body:
            assert len(changed) == len(body)
            link.write_bytes(changed)
        print(f'{name}: {VERSION}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--shortcuts', action='store_true')
    args = parser.parse_args()
    verify()
    if args.shortcuts:
        update_existing_links()
