"""Explicit desktop / iCUE entry points. Never runs a shell or changes routing."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys

IFRAME_URL = 'http://127.0.0.1:47832/embed'
IFRAME_HTML = ('<iframe src="' + IFRAME_URL + '" title="Sonar Edge" '
               'style="position:fixed;inset:0;width:100%;height:100%;border:0;margin:0;" '
               'allow="fullscreen"></iframe>')
WIDGET_UNAVAILABLE = ('The iCUE connection is unavailable. Another app may be using it. '
                      'Desktop controls remain available; try restarting Sonar Edge.')


def preferred_version(data_dir):
    try:
        file = Path(data_dir) / 'app-version.json'
        value = json.loads(file.read_text('utf-8')) if file.stat().st_size < 1024 else {}
        return value['default'] if value.get('default') in ('desktop', 'iframe') else 'desktop'
    except (OSError, ValueError, TypeError, AttributeError):
        return 'desktop'


def launch_version(data_dir, *, widget=False, desktop=False):
    return 'iframe' if widget else 'desktop' if desktop else preferred_version(data_dir)


class AppVersions:
    def __init__(self, data_dir, package_dir, current='desktop', command=None, startup=None, open_view=None):
        self.data_dir = Path(data_dir)
        self.package_dir = Path(package_dir)
        self.current = current
        self.startup = startup
        self.open_view = open_view
        self.widget_ready = True
        self.command = command or ([sys.executable] if getattr(sys, 'frozen', False)
                                  else [sys.executable, str(self.package_dir / 'native_app.py')])

    def info(self):
        return {'current': self.current, 'default': preferred_version(self.data_dir),
                'widgetAvailable': (self.package_dir / 'Sonar Edge XL.icuewidget').is_file(),
                'guideAvailable': (self.package_dir / 'iCUE XL setup.txt').is_file(),
                'widgetReady': self.widget_ready,
                'widgetError': None if self.widget_ready else WIDGET_UNAVAILABLE,
                'iframeUrl': IFRAME_URL, 'iframeHtml': IFRAME_HTML,
                'startup': self.startup.info() if self.startup else {'available': False, 'enabled': False}}

    def perform(self, data):
        action = data.get('action')
        if action == 'default':
            mode = data.get('mode')
            if mode not in ('desktop', 'iframe'):
                raise ValueError('Choose Desktop or iCUE iframe')
            if 'startup' in data:
                if not isinstance(data['startup'], bool):
                    raise ValueError('Choose whether Sonar Edge starts with Windows')
                if self.startup:
                    self.startup.set_enabled(data['startup'])
                elif data['startup']:
                    raise ValueError('Use the packaged SonarEdge.exe to enable Windows startup')
            self.data_dir.mkdir(parents=True, exist_ok=True)
            temporary = self.data_dir / ('app-version-' + secrets.token_hex(6) + '.tmp')
            temporary.write_text(json.dumps({'default': mode}), 'utf-8')
            temporary.replace(self.data_dir / 'app-version.json')
            return self.info()
        if action == 'open':
            mode = data.get('mode')
            if mode not in ('desktop', 'iframe'):
                raise ValueError('Choose Desktop or iCUE iframe')
            if mode == 'iframe' and not self.widget_ready:
                raise ValueError(WIDGET_UNAVAILABLE)
            if self.open_view is None:
                raise ValueError('The app window is still starting. Try again.')
            self.open_view(mode)
            self.current = mode
            return {'message': 'Sonar Edge is running in the tray. Add Sonar Edge XL in iCUE and choose XL.'
                    if mode == 'iframe' else 'Desktop opened. In iCUE, use Screen Setup > Desktop.'}
        if action in ('widget', 'guide'):
            file = self.package_dir / ('Sonar Edge XL.icuewidget' if action == 'widget' else 'iCUE XL setup.txt')
            if not file.is_file():
                raise ValueError('Extract the complete Sonar Edge ZIP to use this option')
            if action == 'widget':
                subprocess.Popen(['explorer.exe', '/select,', str(file)])
            else:
                os.startfile(str(file))
            return {'ok': True}
        raise ValueError('Unknown app version action')
