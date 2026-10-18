"""Exercise install, upgrade, uninstall and data retention in an isolated test app."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import winreg
from app_version import VERSION

ROOT=Path(__file__).resolve().parent
UNINSTALL_KEY=r'Software\Microsoft\Windows\CurrentVersion\Uninstall\SonarEdgeInstallTest_is1'
RUN_KEY=r'Software\Microsoft\Windows\CurrentVersion\Run'
RUN_NAME='Sonar Edge Install Test'
LEGACY_MENU_LINKS=('Sonar Edge Desktop.lnk','Sonar Edge for iCUE.lnk',
                   'Choose app version.lnk','iCUE XL setup.lnk')


def read_value(key,name):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,key) as handle:return winreg.QueryValueEx(handle,name)[0]
    except FileNotFoundError:return None


def run(command):
    result=subprocess.run([str(p) for p in command],timeout=90)
    assert result.returncode==0,f'Installer exit {result.returncode}: {command[0]}'


def wait_removed(path):
    deadline=time.monotonic()+25
    while path.exists() and time.monotonic()<deadline:time.sleep(.2)
    assert not path.exists(),f'Uninstaller did not remove {path}'


def verify():
    setup=ROOT/'releases'/f'SonarEdge-TestSetup-{VERSION}-Windows-x64.exe'
    assert setup.is_file()
    assert read_value(UNINSTALL_KEY,'UninstallString') is None,'An earlier test installation is still registered'
    profile=Path(os.environ['LOCALAPPDATA'])/'SonarEdgeInstallTest'
    assert not profile.exists(),'The isolated test profile already exists; inspect it before retrying'
    before=read_value(RUN_KEY,'Sonar Edge')
    scratch=ROOT/'build/installer-check'
    scratch.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='lifecycle-',dir=scratch) as folder:
        location=Path(folder).resolve()
        assert location.is_relative_to(scratch.resolve())
        app=location/'Program'
        common=[setup,'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',f'/DIR={app}','/TASKS=autostart']
        try:
            run([*common,f'/LOG={location/"install.log"}'])
            assert (app/'SonarEdge.exe').is_file() and (app/'unins000.exe').is_file()
            assert json.loads((app/'installation.json').read_text('utf-8-sig'))['appId']=='SonarEdgeInstallTest'
            assert read_value(UNINSTALL_KEY,'DisplayVersion')==VERSION
            assert read_value(RUN_KEY,RUN_NAME)==f'"{app}\\SonarEdge.exe" --startup'
            menu=Path(os.environ['APPDATA'])/'Microsoft/Windows/Start Menu/Programs/Sonar Edge Install Test'
            assert {p.name for p in menu.glob('*.lnk')}=={'Sonar Edge.lnk'},'Fresh install created extra Start menu shortcuts'
            # Recreate the older installer's entries to exercise upgrade cleanup.
            for name in LEGACY_MENU_LINKS:shutil.copy2(menu/'Sonar Edge.lnk',menu/name)
            profile.mkdir()
            saved=profile/'preferences.json'
            saved.write_text('{"custom":"keep my layout"}','utf-8')
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,RUN_KEY,0,winreg.KEY_SET_VALUE) as key:winreg.DeleteValue(key,RUN_NAME)
            run([*common,'/UPDATE=1',f'/LOG={location/"upgrade.log"}'])
            assert {p.name for p in menu.glob('*.lnk')}=={'Sonar Edge.lnk'},'Upgrade left redundant Start menu shortcuts'
            assert read_value(RUN_KEY,RUN_NAME) is None,'An update re-enabled disabled startup'
            assert saved.read_text('utf-8')=='{"custom":"keep my layout"}'
            # Enable through the installer, then verify uninstall removes its entry.
            run(common)
            run([app/'unins000.exe','/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART'])
            wait_removed(app)
            assert read_value(UNINSTALL_KEY,'UninstallString') is None
            assert read_value(RUN_KEY,RUN_NAME) is None
            assert saved.is_file(),'Default uninstall discarded saved settings'
            run(common)
            run([app/'unins000.exe','/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/PURGEDATA=1'])
            wait_removed(app)
            assert not profile.exists(),'Explicit data removal left the test profile behind'
            assert read_value(RUN_KEY,'Sonar Edge')==before,'The test touched the real startup entry'
            print('Installer verified: registration, shortcuts, upgrade, startup choices, uninstall and optional data removal.')
        finally:
            registered=read_value(UNINSTALL_KEY,'UninstallString')
            if registered:
                uninstaller=Path(registered[1:].split('"')[0] if registered.startswith('"') else registered.split()[0])
                if uninstaller.is_file():
                    run([uninstaller,'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/PURGEDATA=1'])
                    wait_removed(app)


if __name__=='__main__':verify()
