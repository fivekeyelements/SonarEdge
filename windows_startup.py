"""Per-user Windows Startup shortcut; starts the EXE with its working directory."""
import hashlib
import os
from pathlib import Path
import re
import secrets
import shutil
import sys
import winreg
import installation
from windows_shortcuts import startup_folder, read_shortcut, write_shortcut

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
VALUE_NAME = 'Sonar Edge'
PACKAGE_FILES = ('Sonar Edge XL.icuewidget', 'Read me.txt', 'iCUE XL setup.txt',
                 'THIRD-PARTY-NOTICES.txt')


class WindowsStartup:
    def __init__(self, package_dir, version, executable=None, install_root=None, available=None):
        if not re.fullmatch(r'\d+\.\d+\.\d+', version):
            raise ValueError('Invalid release version')
        self.package_dir = Path(package_dir)
        self.executable = Path(executable or sys.executable).resolve()
        self.version = version
        self.install_root = Path(install_root or (Path(os.environ['LOCALAPPDATA']) / 'Programs/SonarEdge/versions'))
        self.available = bool(getattr(sys, 'frozen', False)) if available is None else available
        self.shortcut = startup_folder() / 'Sonar Edge.lnk'

    def registered_command(self):
        if self.shortcut.is_file():
            try:
                link = read_shortcut(self.shortcut)
                if Path(link['target']).name.lower() == 'sonaredge.exe' and link['arguments'] == '--startup':
                    return f'"{link["target"]}" --startup'
            except OSError:
                pass
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                value, kind = winreg.QueryValueEx(key, VALUE_NAME)
                return value if kind == winreg.REG_SZ and isinstance(value, str) else ''
        except FileNotFoundError:
            return ''

    def info(self):
        return {'available': self.available, 'enabled': bool(self.registered_command()),
                'method':'startup-folder' if self.shortcut.is_file() else 'registry'}

    @staticmethod
    def remove_legacy_entry():
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, VALUE_NAME)
        except FileNotFoundError:
            pass

    def deploy(self):
        registered = installation.registered_executable()
        if registered:
            return registered
        if installation.installed_directory(self.executable.parent):
            return self.executable
        target_dir = (self.install_root / self.version).resolve()
        target = target_dir / 'SonarEdge.exe'
        if target == self.executable:
            return target
        target_dir.mkdir(parents=True, exist_ok=True)
        if not target.exists() or hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(self.executable.read_bytes()).digest():
            temporary = target_dir / ('SonarEdge-' + secrets.token_hex(6) + '.tmp')
            try:
                shutil.copy2(self.executable, temporary)
                temporary.replace(target)
            except PermissionError:
                raise ValueError('Close the installed Sonar Edge instance, then enable startup again.')
            finally:
                temporary.unlink(missing_ok=True)
        for name in PACKAGE_FILES:
            source = self.package_dir / name
            if source.is_file():
                shutil.copy2(source, target_dir / name)
        licenses = self.package_dir / 'licenses'
        if licenses.is_dir():
            shutil.copytree(licenses, target_dir / 'licenses', dirs_exist_ok=True)
        return target

    def set_enabled(self, enabled):
        if not isinstance(enabled, bool):
            raise ValueError('Choose whether Sonar Edge starts with Windows')
        if enabled:
            if not self.available:
                raise ValueError('Use the packaged SonarEdge.exe to enable Windows startup')
            target = self.deploy()
            command = f'"{target}" --startup'
            if len(command) > 260:
                raise ValueError('The Windows startup path is too long')
            expected={'target':str(target),'arguments':'--startup','directory':str(target.parent)}
            try:
                current=read_shortcut(self.shortcut) if self.shortcut.is_file() else None
            except OSError:
                current=None
            if current != expected:
                write_shortcut(self.shortcut,target,'--startup')
            self.remove_legacy_entry()
        else:
            self.shortcut.unlink(missing_ok=True)
            self.remove_legacy_entry()
        return self.info()

    def refresh_if_enabled(self):
        # A new portable release refreshes the managed startup copy, while a
        # disabled entry stays disabled. Running older versions never downgrades it.
        command = self.registered_command()
        if command and self.available:
            registered = installation.registered_executable()
            if registered and registered != self.executable:
                return
            match = re.search(r'[\\/](\d+\.\d+\.\d+)[\\/]SonarEdge\.exe" --startup$', command)
            current = tuple(map(int, self.version.split('.')))
            if not match or current >= tuple(map(int, match.group(1).split('.'))):
                self.set_enabled(True)
