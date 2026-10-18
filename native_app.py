"""One Sonar Edge app: desktop window, system tray and local iCUE widget controls."""
import argparse
import asyncio
import copy
import ctypes
import hashlib
import json
import logging
import mimetypes
import os
from pathlib import Path
import re
import shutil
import sys
import threading

APP_NAME = 'Sonar Edge'
from app_version import VERSION
ASSETS = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get('SONAR_EDGE_DATA_DIR') or (Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'SonarEdge'))
DATA_DIR.mkdir(parents=True, exist_ok=True)
os.environ['SONAR_EDGE_DATA_DIR'] = str(DATA_DIR)
if '--widget' in sys.argv:
    os.environ['SONAR_EDGE_WIDGET_PORT'] = '47832'

# Windowed executables have no console streams. Keep dependency errors diagnosable.
if sys.stdout is None:
    sys.stdout = open(DATA_DIR / 'runtime.log', 'a', encoding='utf-8')
if sys.stderr is None:
    sys.stderr = sys.stdout

# Set this before .NET caches monitor bounds or creates any windows. The EXE
# also declares PerMonitorV2 in its manifest; this covers development launches.
_dpi = ctypes.WinDLL('user32', use_last_error=True)
_dpi.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
_dpi.SetProcessDpiAwarenessContext.restype = ctypes.c_bool
_dpi.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))

import webview
import server as core
from window_controls import WindowControls
from desktop_tray import DesktopTray
from display_selection import startup_display
from app_versions import AppVersions, launch_version, WIDGET_UNAVAILABLE
from windows_startup import WindowsStartup
import app_shutdown
from app_updates import AppUpdates


def background_from_bytes(body):
    if not 0 < len(body) <= 64 * 1024 * 1024:
        raise ValueError('Choose a background smaller than 64 MB')
    ext = ('png' if body.startswith(b'\x89PNG\r\n\x1a\n') else 'jpg' if body.startswith(b'\xff\xd8\xff')
           else 'gif' if body.startswith((b'GIF87a', b'GIF89a')) else 'webp' if body[:4] == b'RIFF' and body[8:12] == b'WEBP'
           else 'mp4' if body[4:8] == b'ftyp' else 'webm' if body.startswith(b'\x1aE\xdf\xa3') else None)
    if not ext:
        raise ValueError('Use PNG, JPG, GIF, WebP, MP4, or WebM')
    folder = DATA_DIR / 'backgrounds'
    folder.mkdir(exist_ok=True)
    name = hashlib.sha256(body).hexdigest() + '.' + ext
    target = folder / name
    if not target.exists():
        target.write_bytes(body)
    return {'source': '/backgrounds/' + name, 'kind': 'video' if ext in ('mp4', 'webm') else 'image'}


def trim_artwork_cache(folder, current, keep=16):
    try:
        older = [p for p in folder.iterdir() if p != current and
                 re.fullmatch(r'[a-f0-9]{64}\.(jpg|png|webp|gif)', p.name)]
        older.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return
    for stale in older[keep - 1:]:
        try:
            stale.unlink()
        except OSError:
            pass


def prepare_ui(choose_version=False):
    html = (ASSETS / 'web/index.html').read_text('utf-8')
    css = '\n'.join((ASSETS / 'web' / f).read_text('utf-8') for f in ('style.css', 'appearance.css', 'readable.css', 'effects.css'))
    script = '\n'.join((ASSETS / 'web' / f).read_text('utf-8') for f in ('native.js', 'visuals.js', 'app.js'))
    script = script.replace('</script', '<\\/script')
    html = re.sub(r'<link rel="(?:icon|stylesheet)"[^>]*>', '', html)
    html = html.replace('<script src="/app.js" defer></script>', '')
    html = html.replace('<script src="/visuals.js" defer></script>', '')
    config = 'window.SONAR_EDGE_NATIVE=true;window.SONAR_EDGE_DATA_ROOT=' + json.dumps(DATA_DIR.as_uri()) + ';'
    config += 'window.SONAR_EDGE_CHOOSE_VERSION=' + json.dumps(choose_version) + ';'
    html = html.replace('</head>', '<style>' + css + '</style><script>' + config + '</script></head>')
    html = html.replace('</body>', '<script>' + script + '</script></body>')
    html = html.replace('Edge Audio', 'Sonar Edge').replace('edge-audio', 'sonar-edge')
    # An explicit file URI prevents pywebview from starting its optional HTTP server.
    target = DATA_DIR / 'interface.html'
    target.write_text(html, 'utf-8')
    return target.as_uri()


def migrate_development_settings():
    # Only a development checkout has preferences next to the sources. The release
    # does not package preferences, backgrounds, logs, account paths, or app caches.
    if getattr(sys, 'frozen', False) or (DATA_DIR / 'preferences.json').exists():
        return
    old = ASSETS / 'preferences.json'
    if old.exists():
        try:
            preferences = core.validate_preferences(json.loads(old.read_text('utf-8')))
            (DATA_DIR / 'preferences.json').write_text(json.dumps(preferences, indent=2), 'utf-8')
            for source in (ASSETS / 'backgrounds').glob('*'):
                if re.fullmatch(r'[a-f0-9]{64}\.(png|jpg|webp|gif|mp4|webm)', source.name):
                    target = DATA_DIR / 'backgrounds' / source.name
                    target.parent.mkdir(exist_ok=True)
                    if not target.exists():
                        shutil.copy2(source, target)
            core.BRIDGE.preferences = preferences
        except (OSError, ValueError):
            logging.exception('Could not import development preferences')


class NativeAPI:
    def __init__(self, bridge=None):
        self._bridge = bridge or core.BRIDGE
        self._window = None
        self._controls = None
        self._art_key = None
        self._art_uri = None
        self._art_lock = threading.Lock()

    def _result(self, func):
        try:
            return {'ok': True, 'data': func()}
        except Exception as error:
            logging.exception('Desktop operation failed')
            return {'ok': False, 'error': str(error) or 'The app did not respond'}

    def _state(self):
        result = copy.deepcopy(self._bridge.state)
        result['preferences'] = copy.deepcopy(self._bridge.preferences)
        music = result.get('music', {})
        if music.get('connected') and music.get('art') and self._bridge.media.art:
            with self._art_lock:
                body = self._bridge.media.art
                digest = hashlib.sha256(body).hexdigest()
                if digest != self._art_key:
                    ext = {'image/png': '.png', 'image/webp': '.webp', 'image/gif': '.gif'}.get(self._bridge.media.art_type, '.jpg')
                    folder = DATA_DIR / 'artwork'
                    folder.mkdir(exist_ok=True)
                    path = folder / (digest + ext)
                    if not path.exists():
                        path.write_bytes(body)
                    trim_artwork_cache(folder, path)
                    self._art_key, self._art_uri = digest, path.as_uri()
                music['art'] = self._art_uri
        else:
            music['art'] = None
        return result

    def call(self, method, path, data=None):
        def run():
            if method == 'GET':
                if path == '/api/session':
                    return {'token': 'native', 'preferences': copy.deepcopy(self._bridge.preferences), 'version': VERSION,
                            'appVersion': self._bridge.app_versions.info() if getattr(self._bridge, 'app_versions', None) else None}
                if path == '/api/app':
                    return self._bridge.app_versions.info()
                if path == '/api/update':
                    return self._bridge.updater.info()
                if path == '/api/state':
                    return self._state()
                if path == '/api/meters':
                    return self._bridge.meters.snapshot()
                if path not in ('/api/catalog', '/api/players'):
                    raise ValueError('Unknown desktop operation')
            elif method == 'POST':
                if path not in ('/api/sonar', '/api/music', '/api/preferences', '/api/validate-preferences', '/api/launch', '/api/app', '/api/update'):
                    raise ValueError('Unknown desktop operation')
            else:
                raise ValueError('Unknown desktop operation')
            if not isinstance(data, dict):
                raise ValueError('Invalid request')
            if not self._bridge.ready.wait(5):
                raise RuntimeError('The audio controls are still starting')
            future = asyncio.run_coroutine_threadsafe(self._bridge.dispatch(path, data), self._bridge.loop)
            return future.result(16)
        return self._result(run)

    def pick_background(self):
        def pick():
            paths = self._window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=False,
                file_types=('Backgrounds (*.png;*.jpg;*.jpeg;*.webp;*.gif;*.mp4;*.webm)',))
            if not paths:
                return None
            path = Path(paths[0])
            if path.stat().st_size > 64 * 1024 * 1024:
                raise ValueError('Choose a background smaller than 64 MB')
            return background_from_bytes(path.read_bytes())
        return self._result(pick)

    def install_musicbee_helper(self):
        def install():
            source = ASSETS / 'musicbee/mb_SonarEdge.dll'
            folder = Path(os.environ['APPDATA']) / 'MusicBee/Plugins'
            folder.mkdir(parents=True, exist_ok=True)
            destination = folder / source.name
            if destination.exists() and destination.read_bytes() == source.read_bytes():
                return {'message': 'MusicBee helper is installed. Restart MusicBee to activate it.'}
            try:
                shutil.copyfile(source, destination)
            except PermissionError:
                raise ValueError('Close MusicBee, then install the helper again.')
            return {'message': 'MusicBee helper installed. Restart MusicBee to activate music progress and volume.'}
        return self._result(install)

    def export_settings(self, preferences):
        def save():
            data = core.validate_preferences(preferences)
            paths = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename='Sonar Edge settings.json', file_types=('JSON (*.json)',))
            if not paths:
                return None
            Path(paths[0]).write_text(json.dumps(data, indent=2, ensure_ascii=False), 'utf-8')
            return True
        return self._result(save)

    def import_settings(self):
        def load():
            paths = self._window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=False, file_types=('JSON (*.json)',))
            if not paths:
                return None
            path = Path(paths[0])
            if path.stat().st_size > 16000:
                raise ValueError('Choose a Sonar Edge settings file')
            return core.validate_preferences(json.loads(path.read_text('utf-8-sig')))
        return self._result(load)

    def window_action(self, action, data=None):
        return self._result(lambda: self._controls.perform(action, data))


_mutex = None
_instance_events = {}


def start_widget_listener():
    from http.server import ThreadingHTTPServer
    try:
        listener = ThreadingHTTPServer(('127.0.0.1', core.PORT), core.Handler)
    except OSError:
        logging.exception('iCUE connection unavailable on local port %s; desktop controls remain available', core.PORT)
        return None
    threading.Thread(target=listener.serve_forever, daemon=True, name='SonarEdge-iCUE').start()
    return listener


def stop_widget_listener(listener):
    if listener is not None:
        listener.shutdown()
        listener.server_close()


def single_instance(widget=False, choose=False, silent=False):
    global _mutex
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CreateEventW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.CreateEventW.restype = ctypes.c_void_p
    for mode, name in (('desktop', 'ShowDesktop'), ('iframe', 'ShowWidget'), ('choose', 'ChooseVersion')):
        _instance_events[mode] = kernel.CreateEventW(None, False, False, 'Local\\SonarEdge.' + name + '.v1')
    _mutex = kernel.CreateMutexW(None, False, 'Local\\SonarEdge.App.v1')
    if ctypes.get_last_error() == 183:
        mode = 'choose' if choose else 'iframe' if widget else 'desktop'
        kernel.SetEvent.argtypes = [ctypes.c_void_p]
        if not silent:
            kernel.SetEvent(_instance_events[mode])
        return False
    if not _mutex or not all(_instance_events.values()):
        raise ctypes.WinError(ctypes.get_last_error())
    return True


def main():
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument('--edge', action='store_true', help='Prefer the Xeneon Edge (the default)')
    parser.add_argument('--windowed', action='store_true', help='Open a normal window for this launch')
    parser.add_argument('--widget', action='store_true', help='Keep Sonar Edge in the system tray for iCUE')
    parser.add_argument('--desktop', action='store_true', help='Open the standalone desktop version')
    parser.add_argument('--choose', action='store_true', help='Choose the desktop or iCUE iframe version')
    parser.add_argument('--startup', action='store_true', help='Start the saved version after Windows sign-in')
    parser.add_argument('--diagnose', metavar='FILE', help=argparse.SUPPRESS)
    args = parser.parse_args()
    logging.basicConfig(filename=DATA_DIR / 'sonar-edge.log', level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s')
    migrate_development_settings()
    if args.startup:
        # Give Windows time to restore the Edge display and launch audio apps.
        threading.Event().wait(6)
    mode = launch_version(DATA_DIR, widget=args.widget,
                          desktop=args.desktop or args.edge or args.windowed or args.choose or bool(args.diagnose))
    widget = mode == 'iframe'
    core.PORT = 47832
    if not args.diagnose and not single_instance(widget=args.widget, choose=args.choose, silent=args.startup):
        return
    # Initialize the shared CLR image runtime before WebView2/tray startup and
    # background artwork decoding can race to initialize it on different threads.
    import clr
    clr.AddReference('System.Drawing')
    bridge = core.BRIDGE
    package_dir = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else ASSETS
    startup = WindowsStartup(package_dir, VERSION)
    if not args.diagnose:
        try:
            startup.refresh_if_enabled()
        except (OSError, ValueError):
            logging.exception('Could not refresh the Windows startup copy')
    bridge.app_versions = AppVersions(DATA_DIR, package_dir, mode, startup=startup)
    bridge.updater = AppUpdates(DATA_DIR, Path(sys.executable))
    threading.Thread(target=bridge.run, daemon=True, name='SonarEdge-Audio').start()
    bridge.ready.wait(5)
    api = NativeAPI(bridge)
    if args.diagnose:
        async def collect():
            async with bridge.sonar_lock:
                try:
                    bridge.state['sonar'] = await asyncio.to_thread(bridge.sonar.state)
                    bridge.state['sonar']['chatMix'] = await asyncio.to_thread(bridge.sonar.chatmix_state)
                    bridge.meters.configure(bridge.sonar.audio_cache)
                except Exception as error:
                    bridge.state['sonar'] = {'connected': False, 'error': str(error)}
            async with bridge.media_lock:
                try:
                    bridge.state['music'] = await bridge.media.state()
                except Exception as error:
                    bridge.state['music'] = {'connected': False, 'error': str(error)}
            await asyncio.sleep(.1)
            return {**api._state(), 'meters': bridge.meters.snapshot()}
        result = asyncio.run_coroutine_threadsafe(collect(), bridge.loop).result(20)
        Path(args.diagnose).write_text(json.dumps({'version': VERSION, 'transport': 'native', 'state': result}, indent=2), 'utf-8')
        bridge.meters.stop()
        return
    listener = start_widget_listener()
    bridge.app_versions.widget_ready = listener is not None
    if listener is None:
        widget = False
        bridge.app_versions.current = 'desktop'
    closing = threading.Event()
    try:
        screens = webview.screens
        edge_index, edge = startup_display(screens, bridge.preferences.get('autoEdge', True), args.windowed)
        options = {'screen': edge} if edge is not None else {}
        window = webview.create_window(APP_NAME, url=prepare_ui(args.choose or listener is None or not (DATA_DIR / 'app-version.json').exists()), js_api=api, width=1600, height=510,
                                       min_size=(960, 310), background_color='#101318', text_select=False, hidden=widget, **options)
        api._window = window
        api._controls = WindowControls(window)
        tray_icon = Path(sys.executable) if getattr(sys, 'frozen', False) else ASSETS / 'assets/SonarEdge.ico'
        desktop_tray = DesktopTray(window, tray_icon,
            on_view=lambda view: setattr(bridge.app_versions, 'current', view),
            find_widget=lambda: bridge.app_versions.perform({'action': 'widget'}))
        def open_view(view):
            if view == 'iframe' and not bridge.app_versions.widget_ready:
                raise ValueError(WIDGET_UNAVAILABLE)
            return api._controls._ui(lambda form: desktop_tray.restore() if view == 'desktop' else desktop_tray.hide())
        bridge.app_versions.open_view = open_view
        window.events.before_show += desktop_tray.attach
        if edge is not None:
            def open_on_edge():
                result = api.window_action('move', {'display': edge_index, 'fullscreen': True})
                if result['ok']:
                    logging.info('Opened automatically on Xeneon Edge (%s x %s)', edge.width, edge.height)
            window.events.loaded += open_on_edge
        window.events.loaded += lambda: logging.info('Sonar Edge interface loaded; shared desktop and iCUE controls')
        window.events.loaded += lambda: app_shutdown.listen(lambda: api._controls._ui(lambda form: desktop_tray.exit()))
        def listen_for_views():
            kernel = ctypes.WinDLL('kernel32')
            kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            while not closing.is_set():
                for mode, event in _instance_events.items():
                    if kernel.WaitForSingleObject(event, 0) == 0:
                        try:
                            bridge.app_versions.open_view('desktop' if mode == 'choose' else mode)
                            if mode == 'choose':
                                window.evaluate_js('void openSettings("version")')
                        except Exception:
                            logging.exception('Could not open the requested Sonar Edge view')
                closing.wait(.2)
        window.events.loaded += lambda: threading.Thread(target=listen_for_views, daemon=True,
                                                         name='SonarEdge-Views').start()
        logging.info('%s %s starting', APP_NAME, VERSION)
        webview.start(gui='edgechromium', http_server=False, private_mode=False,
                      storage_path=str(DATA_DIR / 'WebView2'))
    finally:
        closing.set()
        stop_widget_listener(listener)
        bridge.meters.stop()
        bridge.loop.call_soon_threadsafe(bridge.loop.stop)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        logging.exception('Desktop app failed to start')
        ctypes.windll.user32.MessageBoxW(None,
            'Sonar Edge could not start. Run Sonar Edge Setup again to check the WebView2 runtime. Details are in LocalAppData\\SonarEdge\\sonar-edge.log.',
            APP_NAME, 0x10)
