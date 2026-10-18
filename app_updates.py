"""User-initiated GitHub release updates with bounded downloads and SHA-256 checks."""
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import threading
from urllib.error import HTTPError
from urllib.parse import urlsplit, unquote
from urllib.request import Request, HTTPSHandler, HTTPRedirectHandler, build_opener

from app_version import VERSION, UPDATE_REPOSITORY
import installation

MAX_INSTALLER = 200 * 1024 * 1024


def repository(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9_.-]{1,100}', value):
        raise ValueError('Enter a GitHub repository as owner/repository')
    if value.split('/')[1] in ('.', '..'):
        raise ValueError('Enter a GitHub repository as owner/repository')
    return value


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r'v?\d{1,6}\.\d{1,6}\.\d{1,6}', value):
        raise ValueError('The release needs a stable version tag such as v1.0.1')
    return tuple(map(int, value.lstrip('v').split('.')))


class GitHubRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        parsed = urlsplit(newurl)
        if parsed.scheme != 'https' or parsed.hostname not in ('github.com', 'api.github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com') or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise ValueError('GitHub returned an unexpected download redirect')
        return super().redirect_request(request, response, code, message, headers, newurl)


def release_candidate(payload, repo, current=VERSION):
    if not isinstance(payload, dict) or payload.get('draft') or payload.get('prerelease'):
        raise ValueError('No stable published release is available')
    tag = payload.get('tag_name')
    numbers = version_tuple(tag)
    version = '.'.join(map(str, numbers))
    if numbers <= version_tuple(current):
        return None
    expected = f'SonarEdge-Setup-{version}-Windows-x64.exe'
    assets = payload.get('assets')
    if not isinstance(assets, list):
        raise ValueError('The release has no Windows installer')
    matches = [a for a in assets if isinstance(a, dict) and a.get('name') == expected and a.get('state') == 'uploaded']
    if len(matches) != 1:
        raise ValueError(f'The publisher must attach {expected} to this release')
    asset = matches[0]
    url = asset.get('browser_download_url', '')
    parsed = urlsplit(url)
    expected_path = '/' + repo + '/releases/download/' + tag + '/' + expected
    if parsed.scheme != 'https' or parsed.hostname != 'github.com' or parsed.port not in (None, 443) or parsed.username or parsed.password or unquote(parsed.path).lower() != expected_path.lower() or parsed.query or parsed.fragment:
        raise ValueError('The installer does not belong to this GitHub release')
    digest = asset.get('digest', '')
    if not isinstance(digest, str) or not re.fullmatch(r'sha256:[0-9a-fA-F]{64}', digest):
        raise ValueError('This release is missing GitHub’s SHA-256 installer digest. Upload the installer again.')
    size = asset.get('size')
    if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= MAX_INSTALLER:
        raise ValueError('The Windows installer has an invalid size')
    return {'version': version, 'name': expected, 'url': url, 'sha256': digest[7:].lower(), 'size': size,
            'notes': str(payload.get('body') or 'No release notes were provided.')[:14000],
            'releaseUrl': f'https://github.com/{repo}/releases/tag/{tag}'}


class AppUpdates:
    def __init__(self, data_dir, executable, current=VERSION, default_repo=UPDATE_REPOSITORY, opener=None, launcher=None):
        self.root = Path(data_dir)
        self.executable = Path(executable)
        self.current = current
        self.repo = repository(default_repo)
        try:
            file = self.root / 'update-source.json'
            if file.stat().st_size < 2048:
                self.repo = repository(json.loads(file.read_text('utf-8'))['repository'])
        except (OSError, ValueError, KeyError, TypeError):
            pass
        self.opener = opener or build_opener(HTTPSHandler(), GitHubRedirect())
        self.launcher = launcher or subprocess.Popen
        self.lock = threading.RLock()
        self.cancel = threading.Event()
        self.candidate = None
        self.state = {'status': 'idle', 'message': 'Check for a new Sonar Edge release.', 'progress': 0}

    def info(self):
        with self.lock:
            return {**copy.deepcopy(self.state), 'repository': self.repo, 'currentVersion': self.current,
                    'installed': bool(installation.installed_directory(self.executable.parent))}

    def _set(self, **changes):
        with self.lock:
            self.state.update(changes)

    def _open(self, url, accept='application/vnd.github+json'):
        return self.opener.open(Request(url, headers={'User-Agent': f'SonarEdge/{self.current}', 'Accept': accept,
                                                    'X-GitHub-Api-Version': '2026-03-10'}), timeout=20)

    def _error(self, error):
        if isinstance(error, HTTPError):
            message = ('No published release was found. The repository must be public.' if error.code == 404 else
                       'GitHub’s request limit was reached. Try again later.' if error.code in (403, 429) else
                       f'GitHub returned an error ({error.code}). Try again later.')
        else:
            message = str(error) or 'The update connection failed. Try again.'
        self._set(status='error', message=message, progress=0)

    def check(self):
        try:
            with self._open(f'https://api.github.com/repos/{self.repo}/releases/latest') as response:
                body = response.read(1024 * 1024 + 1)
                if len(body) > 1024 * 1024:
                    raise ValueError('The release information is too large')
                candidate = release_candidate(json.loads(body), self.repo, self.current)
            with self.lock:
                self.candidate = candidate
                self.state = ({'status': 'available', 'message': f'Sonar Edge {candidate["version"]} is available.',
                               'version': candidate['version'], 'notes': candidate['notes'], 'releaseUrl': candidate['releaseUrl'], 'progress': 0}
                              if candidate else {'status': 'current', 'message': 'You have the latest stable version.', 'progress': 0})
        except Exception as error:
            self._error(error)

    def download_and_install(self):
        partial = None
        try:
            with self.lock:
                candidate = dict(self.candidate)
            folder = self.root / 'updates'
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / candidate['name']
            partial = folder / (candidate['name'] + '.part')
            digest = hashlib.sha256()
            received = 0
            with self._open(candidate['url'], 'application/octet-stream') as response, partial.open('wb') as file:
                while True:
                    if self.cancel.is_set():
                        raise InterruptedError('Update download cancelled.')
                    chunk = response.read(128 * 1024)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > candidate['size'] or received > MAX_INSTALLER:
                        raise ValueError('The update exceeded its published size')
                    file.write(chunk); digest.update(chunk)
                    self._set(progress=round(received / candidate['size'] * 100), message='Downloading the installer…')
            if received != candidate['size'] or digest.hexdigest() != candidate['sha256']:
                raise ValueError('The installer verification failed. Nothing was installed; check for updates and try again.')
            with partial.open('rb') as file:
                if file.read(2) != b'MZ':
                    raise ValueError('The download is not a Windows installer')
            if self.cancel.is_set():
                raise InterruptedError('Update download cancelled.')
            partial.replace(target)
            # Recheck the finalized bytes immediately before launching the installer.
            if hashlib.sha256(target.read_bytes()).hexdigest() != candidate['sha256']:
                raise ValueError('The downloaded installer changed before it could start')
            self.launcher([str(target), '/SILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/UPDATE=1', '/LAUNCH=1'],
                          cwd=folder, creationflags=subprocess.CREATE_NO_WINDOW)
            self._set(status='installing', message='Installing the update. Sonar Edge will close and reopen.', progress=100)
        except InterruptedError as error:
            self._set(status='available', message=str(error), progress=0)
        except Exception as error:
            self._error(error)
        finally:
            if partial:
                partial.unlink(missing_ok=True)

    def command(self, data):
        action = data.get('action')
        with self.lock:
            busy = self.state['status'] in ('checking', 'downloading', 'installing')
            if action == 'cancel' and self.state['status'] == 'downloading':
                self.cancel.set()
                return self.info()
            if busy:
                raise ValueError('An update operation is already running')
            if action == 'source':
                selected = repository(data.get('repository'))
                self.root.mkdir(parents=True, exist_ok=True)
                file = self.root / 'update-source.tmp'
                file.write_text(json.dumps({'repository': selected}), 'utf-8')
                file.replace(self.root / 'update-source.json')
                self.repo = selected
                self.candidate = None
                self.state = {'status': 'idle', 'message': 'Update repository saved.', 'progress': 0}
            elif action == 'check':
                self.state = {'status': 'checking', 'message': 'Checking GitHub Releases…', 'progress': 0}
                threading.Thread(target=self.check, daemon=True, name='SonarEdge-UpdateCheck').start()
            elif action == 'install':
                if not self.candidate:
                    raise ValueError('Check for an update first')
                if not installation.installed_directory(self.executable.parent):
                    raise ValueError('Install Sonar Edge with Setup before using in-app updates')
                self.cancel.clear()
                self._set(status='downloading', message='Starting the download…', progress=0)
                threading.Thread(target=self.download_and_install, daemon=True, name='SonarEdge-UpdateDownload').start()
            else:
                raise ValueError('Unknown update action')
        return self.info()
