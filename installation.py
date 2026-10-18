"""Find the registered per-user installation without moving portable copies."""
import json
from pathlib import Path
import winreg
from app_version import INSTALL_APP_ID

UNINSTALL_KEY = rf'Software\Microsoft\Windows\CurrentVersion\Uninstall\{INSTALL_APP_ID}_is1'


def installed_directory(folder):
    folder = Path(folder)
    try:
        marker = folder / 'installation.json'
        if marker.stat().st_size > 2048:
            return None
        data = json.loads(marker.read_text('utf-8-sig'))
        if data.get('appId') == INSTALL_APP_ID and (folder/'unins000.exe').is_file() and (folder/'SonarEdge.exe').is_file():
            return folder.resolve()
    except (OSError, ValueError, AttributeError):
        pass
    return None


def registered_executable():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
            location, _ = winreg.QueryValueEx(key, 'InstallLocation')
        folder = installed_directory(location)
        return folder / 'SonarEdge.exe' if folder else None
    except (OSError, TypeError):
        return None
