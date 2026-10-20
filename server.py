"""Edge Audio: loopback-only Sonar + MusicBee control bridge for an iCUE iframe."""
import asyncio
from edge_brightness import EdgeBrightness
import copy
import hmac
import hashlib
import ipaddress
import json
import logging
import math
import mimetypes
import os
import re
from pathlib import Path
import secrets
import ssl
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import Request, build_opener, HTTPSHandler, ProxyHandler

from winrt.windows.media import MediaPlaybackAutoRepeatMode
from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager
from winrt.windows.storage.streams import DataReader
import musicbee_bridge
from audio_meters import AudioMeters
import artwork_palette
from app_version import VERSION
from system_volume import SystemVolume

RESOURCE_ROOT = Path(__file__).resolve().parent
ROOT = Path(os.environ.get('SONAR_EDGE_DATA_DIR', str(RESOURCE_ROOT)))
PORT = int(os.environ.get('SONAR_EDGE_WIDGET_PORT', '47831'))
TOKEN = secrets.token_urlsafe(32)
CHANNELS = {'master': 'Master', 'game': 'game', 'chat': 'chatRender',
            'media': 'media', 'aux': 'aux', 'mic': 'chatCapture'}
DEFAULTS = {
    'layout': 'compact', 'playerSide': 'right', 'showClock': True, 'playerApp': 'musicbee', 'autoEdge': True,
    'accent': '#8de4c7',
    'showArtwork': True,
    'background': {'kind': 'gradient', 'source': '', 'color': '#101318', 'color2': '#243a3b',
                   'dim': 0.2, 'blur': 0, 'fit': 'cover', 'angle': 135},
    'appearance': {'panelColor': '#191e26', 'panelOpacity': 0.94, 'textColor': '#eeeef3',
                   'mutedColor': '#b7c2cf', 'roundness': 20, 'font': 'system', 'textScale': 1, 'artworkSize': 256},
    'channels': [
        {'id': 'master', 'label': 'Master', 'color': '#e6e7ee', 'visible': True},
        {'id': 'game', 'label': 'Game', 'color': '#a7b8ff', 'visible': True},
        {'id': 'chat', 'label': 'Chat', 'color': '#f5c58a', 'visible': True},
        {'id': 'media', 'label': 'Media', 'color': '#8de4c7', 'visible': True},
        {'id': 'aux', 'label': 'Aux', 'color': '#c9a6ee', 'visible': False},
        {'id': 'mic', 'label': 'Microphone', 'color': '#f0a5b8', 'visible': True},
    ],
    'shortcuts': ['mic', 'media', 'musicbee', 'sonar'],
    'shortcutLabels': True, 'shortcutAppearance': {},
    'showMeters': True, 'showChatMix': True,
    'hiddenDevices': {'render': [], 'capture': []}, 'masterVolumeTarget': 'sonar',
    'artworkEffects': {'colors': 'music', 'playerBackground': 'off', 'appBackground': 'off', 'mixerBackground': 'match',
                      'motion': True, 'intensity': .45, 'blur': 52},
}


def validate_preferences(value):
    if not isinstance(value, dict):
        raise ValueError('Invalid settings')
    result = copy.deepcopy(DEFAULTS)
    if value.get('masterVolumeTarget') in ('sonar','windows'):
        result['masterVolumeTarget'] = value['masterVolumeTarget']
    hidden = value.get('hiddenDevices',{})
    if not isinstance(hidden,dict):raise ValueError('Invalid audio device visibility settings')
    for flow in ('render','capture'):
        ids = hidden.get(flow,[])
        if not isinstance(ids,list) or len(ids)>256 or any(not isinstance(i,str) or not 0<len(i)<=256 for i in ids):
            raise ValueError('Choose up to 256 valid hidden audio devices per list')
        result['hiddenDevices'][flow] = list(dict.fromkeys(ids))
    for key, choices in [('layout', ['compact', 'balanced', 'mixer', 'music']),
                         ('playerSide', ['left', 'right'])]:
        if value.get(key) in choices:
            result[key] = value[key]
    result['showClock'] = bool(value.get('showClock', True))
    result['autoEdge'] = value.get('autoEdge', True) is not False
    result['showMeters'] = value.get('showMeters', True) is not False
    result['showChatMix'] = value.get('showChatMix', True) is not False
    def color(s, default):
        return s if isinstance(s, str) and len(s) == 7 and s[0] == '#' and all(c in '0123456789abcdefABCDEF' for c in s[1:]) else default
    result['accent'] = color(value.get('accent'), result['accent'])
    result['showArtwork'] = bool(value.get('showArtwork', True))
    player = value.get('playerApp', 'musicbee')
    if isinstance(player, str) and 0 < len(player) <= 255:
        result['playerApp'] = player
    def bounded(v, fallback, low, high):
        try:
            number = float(v)
            return max(low, min(high, number)) if math.isfinite(number) else fallback
        except (TypeError, ValueError):
            return fallback
    background = value.get('background', {})
    if isinstance(background, dict):
        bg = result['background']
        if background.get('kind') in ('gradient', 'solid', 'image', 'video'):
            bg['kind'] = background['kind']
        bg['color'] = color(background.get('color'), bg['color'])
        bg['color2'] = color(background.get('color2'), bg['color2'])
        for key, low, high in [('dim', 0, 0.95), ('blur', 0, 24), ('angle', 0, 360)]:
            bg[key] = bounded(background.get(key), bg[key], low, high)
        if background.get('fit') in ('cover', 'contain', 'fill'):
            bg['fit'] = background['fit']
        source = background.get('source', '')
        if isinstance(source, str) and len(source) <= 4000:
            parsed = urlsplit(source)
            if source == '' or re.fullmatch(r'/backgrounds/[a-f0-9]{64}\.(png|jpg|webp|gif|mp4|webm)', source) or (parsed.scheme in ('https', 'http') and parsed.hostname and not parsed.username and not parsed.password):
                bg['source'] = source
            else:
                raise ValueError('Choose an uploaded background or an HTTP image/video URL')
    appearance = value.get('appearance', {})
    if isinstance(appearance, dict):
        ap = result['appearance']
        for key in ('panelColor', 'textColor', 'mutedColor'):
            ap[key] = color(appearance.get(key), ap[key])
        ap['panelOpacity'] = bounded(appearance.get('panelOpacity'), ap['panelOpacity'], 0.15, 1)
        ap['roundness'] = bounded(appearance.get('roundness'), ap['roundness'], 0, 36)
        if type(appearance.get('textScale')) in (int, float) and appearance['textScale'] in (1, 1.12, 1.25):
            ap['textScale'] = appearance['textScale']
        if type(appearance.get('artworkSize')) is int and appearance['artworkSize'] in (168, 224, 256):
            ap['artworkSize'] = appearance['artworkSize']
        if appearance.get('font') in ('system', 'rounded', 'mono'):
            ap['font'] = appearance['font']
    effects = value.get('artworkEffects', {})
    if isinstance(effects, dict):
        fx = result['artworkEffects']
        for key, choices in [('colors', ('off', 'music', 'all')),
                             ('playerBackground', ('off', 'colors', 'artwork')),
                             ('mixerBackground', ('match', 'off', 'colors', 'artwork')),
                             ('appBackground', ('off', 'colors', 'artwork'))]:
            if effects.get(key) in choices:
                fx[key] = effects[key]
        fx['motion'] = effects.get('motion', True) is not False
        fx['intensity'] = bounded(effects.get('intensity'), fx['intensity'], .1, .8)
        fx['blur'] = bounded(effects.get('blur'), fx['blur'], 24, 90)
    incoming = value.get('channels', [])
    if not isinstance(incoming, list) or len(incoming) != 6 or {c.get('id') for c in incoming if isinstance(c, dict)} != set(CHANNELS):
        raise ValueError('Settings must contain each mixer channel once')
    lookup = {c['id']: c for c in DEFAULTS['channels']}
    result['channels'] = [dict(id=c['id'], label=str(c.get('label') or lookup[c['id']]['label'])[:24],
                               color=color(c.get('color'), lookup[c['id']]['color']), visible=bool(c.get('visible')))
                          for c in incoming]
    if not any(c['visible'] for c in result['channels']):
        raise ValueError('Keep at least one channel visible')
    actions = {'mic', 'media', 'master', 'musicbee', 'sonar', 'playpause', 'previous', 'next', 'stop'}
    shortcuts = value.get('shortcuts', result['shortcuts'])
    if not isinstance(shortcuts, list) or len(shortcuts) > 8 or any(not isinstance(s, str) or s not in actions for s in shortcuts):
        raise ValueError('Choose up to eight valid quick actions')
    result['shortcuts'] = shortcuts
    result['shortcutLabels'] = value.get('shortcutLabels', True) is not False
    styles = value.get('shortcutAppearance', {})
    if isinstance(styles, dict):
        allowed_icons = {'mic', 'volume', 'muted', 'music', 'headphones', 'sliders', 'play', 'pause', 'previous', 'next', 'stop', 'external'}
        for action, style in styles.items():
            if action in actions and isinstance(style, dict):
                clean = {}
                if isinstance(style.get('label'), str):
                    clean['label'] = style['label'].strip()[:24]
                if isinstance(style.get('icon'), str) and style['icon'] in allowed_icons:
                    clean['icon'] = style['icon']
                result['shortcutAppearance'][action] = clean
    return result


def load_preferences():
    try:
        return validate_preferences(json.loads((ROOT / 'preferences.json').read_text('utf-8')))
    except (OSError, ValueError, TypeError):
        return copy.deepcopy(DEFAULTS)


class Sonar:
    def __init__(self):
        self.base = None
        self.opener = build_opener(ProxyHandler({}))
        self.local_tls = build_opener(ProxyHandler({}), HTTPSHandler(context=ssl._create_unverified_context()))
        self.catalog = None
        self.catalog_at = 0
        self.audio_cache = []
        self.audio_cache_at = 0
        self.chatmix_path = None
        self.chatmix_cache = None
        self.chatmix_retry_at = 0

    def chatmix_state(self, force=False):
        if not force and time.monotonic() < self.chatmix_retry_at:
            return self.chatmix_cache
        paths = [self.chatmix_path] if self.chatmix_path else ['/v1/chatMix', '/chatMix']
        for path in paths:
            try:
                data = self.request(path)
                balance = data.get('balance')
                if type(balance) not in (float, int) or not math.isfinite(balance) or not -1 <= balance <= 1:
                    raise ValueError('Sonar returned an invalid ChatMix balance')
                status = data.get('state', 'unavailable')
                self.chatmix_path = path
                self.chatmix_retry_at = 0
                self.chatmix_cache = {'balance': balance, 'state': status, 'available': True,
                    'canControl': status == 'enabled', 'message': {'finiteWheel':'Controlled by headset',
                        'differentDeviceSelected':'Game and Chat need the same output device',
                        'noDeviceSelected':'Choose a Game and Chat output device'}.get(status, '' if status == 'enabled' else 'ChatMix is unavailable')}
                return self.chatmix_cache
            except HTTPError as error:
                if error.code != 404:
                    raise
        self.chatmix_path = None
        self.chatmix_retry_at = time.monotonic() + 20
        self.chatmix_cache = {'available': False, 'canControl': False, 'message': 'ChatMix is unavailable in this Sonar version'}
        return self.chatmix_cache

    def audio_devices(self):
        if time.monotonic() - self.audio_cache_at >= 3:
            self.audio_cache = self.request('/audioDevices')
            self.audio_cache_at = time.monotonic()
        return self.audio_cache

    @staticmethod
    def loopback_url(url):
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or parsed.username or parsed.password:
            raise ValueError('Invalid local Sonar address')
        if parsed.hostname != 'localhost' and not ipaddress.ip_address(parsed.hostname).is_loopback:
            raise ValueError('Sonar must run on this PC')
        return url.rstrip('/')

    def discover(self):
        for relative in ['SteelSeries/GG/coreProps.json', 'SteelSeries/SteelSeries Engine 3/coreProps.json']:
            path = Path(os.environ.get('PROGRAMDATA', r'C:\ProgramData')) / relative
            if not path.exists():
                continue
            props = json.loads(path.read_text('utf-8'))
            url = self.loopback_url('https://' + props['ggEncryptedAddress'])
            with self.local_tls.open(url + '/subApps', timeout=3) as response:
                app = json.load(response)['subApps']['sonar']
            if not app.get('isRunning') or not app.get('isReady'):
                raise RuntimeError('Start SteelSeries GG and enable Sonar')
            self.base = self.loopback_url(app['metadata']['webServerAddress'])
            return
        raise RuntimeError('SteelSeries GG was not found on this PC')

    def request(self, path, method='GET'):
        if not self.base:
            self.discover()
        try:
            request = Request(self.base + path, method=method, data=b'' if method == 'PUT' else None)
            with self.opener.open(request, timeout=3) as response:
                body = response.read()
                return json.loads(body) if body else None
        except (OSError, ValueError):
            # GG chooses a different port after restarting; discover again next time.
            self.base = None
            raise

    def state(self):
        status = self.request('/v1/status')
        mode = status['mode']
        volumes = self.request('/volumeSettings/' + ('classic' if mode == 'classic' else 'streamer'))
        devices = {d['virtualAudioDevice']: d for d in status.get('devices', [])}
        try:
            audio = {d['id']: d for d in self.audio_devices()}
        except (OSError, ValueError, RuntimeError):
            audio = {d['id']: d for d in self.audio_cache}
        channels = {}
        for key, internal in CHANNELS.items():
            branch = volumes['masters'] if key == 'master' else volumes['devices'].get(internal, {})
            volume = branch.get('classic', {}) if mode == 'classic' else branch.get('stream', {}).get('monitoring', {})
            device = devices.get(internal, {})
            device_id = device.get('streamRedirectionDevice', '')
            endpoint = audio.get(device_id, {})
            channels[key] = {'volume': volume.get('volume', 0), 'muted': volume.get('muted', False),
                             'available': bool(volume), 'enabled': device.get('isChannelEnabled', True),
                             'preset': device.get('config', {}), 'deviceId': device_id,
                             'deviceName': endpoint.get('friendlyName', ''),
                             'deviceAvailable': endpoint.get('state', 'active') == 'active' if endpoint else None,
                             'canRoute': key != 'master' and (mode == 'classic' or key == 'mic')}
        return {'connected': True, 'mode': mode, 'mix': 'monitoring' if mode != 'classic' else 'classic',
                'channels': channels, 'chatMix': copy.deepcopy(self.chatmix_cache), 'updated': time.time()}

    def catalog_data(self):
        if self.catalog is None or time.monotonic() - self.catalog_at >= 30:
            configs = self.request('/configs')
            self.catalog = {'presets': [{k: c.get(k) for k in ['id', 'name', 'virtualAudioDevice', 'isFavorite']} for c in configs]}
            self.catalog_at = time.monotonic()
        return {**self.catalog, 'devices': [
            {k: d.get(k) for k in ['id', 'friendlyName', 'dataFlow']} for d in self.audio_devices()
            if d.get('role') == 'none' and d.get('state', 'active') == 'active']}

    def command(self, data):
        if data.get('action') == 'chatmix':
            balance = data.get('value')
            if type(balance) not in (int, float) or not math.isfinite(balance) or not -1 <= balance <= 1:
                raise ValueError('ChatMix balance must be between Game and Chat')
            current = self.chatmix_state(force=True)
            if not current.get('canControl'):
                raise ValueError(current.get('message', 'ChatMix is controlled by your headset'))
            self.request(f'{self.chatmix_path}?balance={round(balance,4)}', 'PUT')
            self.chatmix_state(force=True)
            return self.state()
        key = data.get('channel')
        if key not in CHANNELS:
            raise ValueError('Unknown Sonar channel')
        action = data.get('action')
        mode = self.request('/mode')
        internal = CHANNELS[key]
        if action in ('volume', 'mute'):
            if action == 'volume':
                value = float(data['value'])
                if not math.isfinite(value) or not 0 <= value <= 1:
                    raise ValueError('Volume must be between 0 and 100%')
                value = str(round(value, 4))
            else:
                if not isinstance(data.get('value'), bool):
                    raise ValueError('Invalid mute value')
                value = str(data['value']).lower()
            if mode == 'classic':
                path = f'/volumeSettings/classic/{internal}/{"Volume" if action == "volume" else "Mute"}/{value}'
            else:
                path = f'/volumeSettings/streamer/monitoring/{internal}/{"volume" if action == "volume" else "isMuted"}/{value}'
        elif action == 'preset':
            preset = next((p for p in self.catalog_data()['presets']
                           if p['id'] == data.get('value') and p['virtualAudioDevice'] == internal), None)
            if not preset:
                raise ValueError('Choose a preset for this channel')
            path = '/configs/' + quote(preset['id'], safe='') + '/select'
        elif action == 'device':
            flow = 'capture' if key == 'mic' else 'render'
            device = next((d for d in self.catalog_data()['devices'] if d['id'] == data.get('value') and d['dataFlow'] == flow), None)
            if key == 'master' or not device:
                raise ValueError('Choose an available device for this channel')
            if mode != 'classic' and key != 'mic':
                raise ValueError('Per-channel output selection is available in Sonar Classic mode')
            path = f'/{"classicRedirections" if mode == "classic" else "streamRedirections"}/{key}/deviceId/' + quote(device['id'], safe='')
        else:
            raise ValueError('Unknown Sonar action')
        self.request(path, 'PUT')
        return self.state()


class Media:
    def __init__(self):
        self.manager = None
        self.art_key = None
        self.art = b''
        self.art_type = 'image/jpeg'
        self.art_version = 0
        self.palette = None
        self.palette_retry_at = 0

    async def session(self):
        if self.manager is None:
            self.manager = await GlobalSystemMediaTransportControlsSessionManager.request_async()
        selected = BRIDGE.preferences.get('playerApp', 'musicbee')
        if selected == 'auto':
            return self.manager.get_current_session()
        for session in self.manager.get_sessions():
            source = session.source_app_user_model_id.lower()
            if (selected == 'musicbee' and ('musicbee' in source or 'mbxhub' in source)) or source == selected.lower():
                return session
        return None

    @staticmethod
    def friendly(source):
        low = source.lower()
        for match, name in [('musicbee', 'MusicBee'), ('mbxhub', 'MusicBee'), ('spotify', 'Spotify'),
                            ('foobar', 'foobar2000'), ('vlc', 'VLC'), ('zunemusic', 'Media Player'),
                            ('applemusic', 'Apple Music'), ('itunes', 'iTunes'), ('tidal', 'TIDAL'),
                            ('chrome', 'Chrome'), ('msedge', 'Edge'), ('firefox', 'Firefox')]:
            if match in low:
                return name
        return source.rsplit('!', 1)[-1].removesuffix('.exe')[:60]

    async def players(self):
        if self.manager is None:
            self.manager = await GlobalSystemMediaTransportControlsSessionManager.request_async()
        result = [{'id': 'musicbee', 'name': 'MusicBee'}, {'id': 'auto', 'name': 'Windows active media app'}]
        seen = {'musicbee'}
        for session in self.manager.get_sessions():
            source = session.source_app_user_model_id
            name = self.friendly(source)
            if name == 'MusicBee' or source in seen:
                continue
            seen.add(source)
            result.append({'id': source, 'name': name})
        selected = BRIDGE.preferences.get('playerApp', 'musicbee')
        if selected not in {p['id'] for p in result}:
            result.append({'id': selected, 'name': self.friendly(selected) + ' (not running)'})
        return result

    async def state(self):
        session = await self.session()
        if session is None:
            self.art_key = None
            selected = BRIDGE.preferences.get('playerApp', 'musicbee')
            name = 'MusicBee' if selected == 'musicbee' else 'Media player' if selected == 'auto' else self.friendly(selected)
            return {'connected': False, 'name': name, 'message': 'Open the selected app with Windows media controls enabled'}
        props = await session.try_get_media_properties_async()
        info = session.get_playback_info()
        timeline = session.get_timeline_properties()
        key = (session.source_app_user_model_id, props.title, props.artist, props.album_title)
        if key != self.art_key:
            self.art = b''
            try:
                if props.thumbnail:
                    stream = await props.thumbnail.open_read_async()
                    try:
                        if stream.size <= 5 * 1024 * 1024:
                            reader = DataReader(stream)
                            try:
                                await reader.load_async(stream.size)
                                buf = bytearray(stream.size)
                                reader.read_bytes(buf)
                                self.art = bytes(buf)
                                self.art_type = stream.content_type or 'image/jpeg'
                            finally:
                                reader.detach_stream()
                                reader.close()
                    finally:
                        stream.close()
            except Exception:
                logging.exception('Artwork unavailable')
            self.art_key = key
            self.art_version += 1
            self.palette = await asyncio.to_thread(artwork_palette.from_image, self.art)
            self.palette_retry_at = time.monotonic() + 3
        # The Windows image runtime or the media thumbnail can still be warming
        # up at launch. A transient failure must not cache the fallback forever.
        if self.art and self.palette is None and time.monotonic() >= self.palette_retry_at:
            self.palette = await asyncio.to_thread(artwork_palette.from_image, self.art)
            self.palette_retry_at = time.monotonic() + 3
        controls = info.controls
        result = {
            'connected': True, 'source': session.source_app_user_model_id, 'name': self.friendly(session.source_app_user_model_id),
            'title': props.title, 'artist': props.artist, 'album': props.album_title,
            'playing': int(info.playback_status) == 4, 'playbackStatus': int(info.playback_status),
            'position': timeline.position.total_seconds(), 'duration': timeline.end_time.total_seconds(),
            'shuffle': info.is_shuffle_active, 'repeat': int(info.auto_repeat_mode) if info.auto_repeat_mode is not None else None,
            'art': f'/api/art?v={self.art_version}' if self.art else None,
            'palette': self.palette,
            'controls': {name: bool(getattr(controls, attr)) and
                         (name != 'shuffle' or info.is_shuffle_active is not None) and
                         (name != 'repeat' or info.auto_repeat_mode is not None)
                         for name, attr in {
                'playpause': 'is_play_pause_toggle_enabled', 'previous': 'is_previous_enabled',
                'next': 'is_next_enabled', 'stop': 'is_stop_enabled', 'seek': 'is_playback_position_enabled',
                'shuffle': 'is_shuffle_enabled', 'repeat': 'is_repeat_enabled'}.items()},
            'updated': time.time(),
        }
        if result['name'] == 'MusicBee':
            extra = await asyncio.to_thread(musicbee_bridge.state)
            if extra:
                result.update({key: extra[key] for key in ('position', 'duration', 'volume', 'playing')})
                result['controls'].update(seek=extra['duration'] > 0, volume=True)
                result['musicbeeHelper'] = True
        return result

    async def command(self, data):
        action = data.get('action')
        session = await self.session()
        is_musicbee = (session and self.friendly(session.source_app_user_model_id) == 'MusicBee') or (session is None and BRIDGE.preferences.get('playerApp') == 'musicbee')
        if action in ('volume', 'seek') and is_musicbee:
            extra = await asyncio.to_thread(musicbee_bridge.state)
            if extra:
                value = data.get('value')
                maximum = 1 if action == 'volume' else extra['duration']
                if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= maximum or (action == 'seek' and maximum <= 0):
                    raise ValueError('Choose a valid player volume or track position')
                await asyncio.to_thread(musicbee_bridge.request, action, value)
                return await self.state()
        if action == 'volume':
            raise ValueError('The selected player does not report volume. MusicBee needs the Sonar Edge helper.')
        fallback = {'playpause': '/PlayPause', 'previous': '/Previous', 'next': '/Next', 'stop': '/Stop',
                    'volumeup': '/VolumeUp', 'volumedown': '/VolumeDown'}
        if action in ('volumeup', 'volumedown') or session is None:
            if BRIDGE.preferences.get('playerApp') != 'musicbee' and not (session and self.friendly(session.source_app_user_model_id) == 'MusicBee'):
                raise ValueError('The selected player does not expose its volume through Windows media controls')
            if action not in fallback:
                raise ValueError('MusicBee media session is unavailable')
            launch_app('musicbee', fallback[action])
            await asyncio.sleep(0.15)
            return await self.state()
        info = session.get_playback_info()
        capabilities = {'playpause': 'is_play_pause_toggle_enabled', 'play': 'is_play_enabled', 'pause': 'is_pause_enabled', 'previous': 'is_previous_enabled',
                        'next': 'is_next_enabled', 'stop': 'is_stop_enabled', 'seek': 'is_playback_position_enabled',
                        'shuffle': 'is_shuffle_enabled', 'repeat': 'is_repeat_enabled'}
        if action not in capabilities or not getattr(info.controls, capabilities[action]):
            raise ValueError('MusicBee does not expose this control right now')
        if action == 'shuffle':
            if info.is_shuffle_active is None:
                raise ValueError('The MusicBee media plugin does not report shuffle state')
            ok = await session.try_change_shuffle_active_async(not info.is_shuffle_active)
        elif action == 'repeat':
            if info.auto_repeat_mode is None:
                raise ValueError('The MusicBee media plugin does not report repeat state')
            current = int(info.auto_repeat_mode) if info.auto_repeat_mode is not None else 0
            ok = await session.try_change_auto_repeat_mode_async(MediaPlaybackAutoRepeatMode((current + 1) % 3))
        elif action == 'seek':
            position = float(data.get('value', 0))
            duration = session.get_timeline_properties().end_time.total_seconds()
            if not math.isfinite(position) or not 0 <= position <= duration or duration <= 0:
                raise ValueError('MusicBee is not reporting a seekable timeline')
            ok = await session.try_change_playback_position_async(int(position * 10_000_000))
        else:
            method = {'playpause': 'try_toggle_play_pause_async', 'play': 'try_play_async', 'pause': 'try_pause_async', 'previous': 'try_skip_previous_async',
                      'next': 'try_skip_next_async', 'stop': 'try_stop_async'}[action]
            ok = await getattr(session, method)()
        if not ok:
            raise RuntimeError('MusicBee did not accept that command')
        await asyncio.sleep(0.12)
        return await self.state()


def launch_app(app, argument=None):
    if app == 'musicbee':
        from windows_apps import running_executable
        running = running_executable('MusicBee.exe')
        candidates = [Path.home() / 'Musicbee/MusicBee.exe', Path(r'C:\Program Files (x86)\MusicBee\MusicBee.exe'),
                      Path(r'C:\Program Files\MusicBee\MusicBee.exe')]
        if running:
            candidates.insert(0, running)
    elif app == 'sonar':
        candidates = [Path(r'C:\Program Files\SteelSeries\GG\SteelSeriesGG.exe')]
    else:
        raise ValueError('Unknown app')
    executable = next((p for p in candidates if p.exists()), None)
    if not executable:
        raise ValueError(f'{app} was not found')
    subprocess.Popen([str(executable)] + ([argument] if argument else []), cwd=executable.parent,
                     creationflags=subprocess.CREATE_NO_WINDOW)


class Bridge:
    def __init__(self):
        self.sonar = Sonar()
        self.media = Media()
        self.meters = AudioMeters()
        self.system_volume = SystemVolume()
        self.preferences = load_preferences()
        self.preferences_stamp = self._preferences_stamp()
        self.state = {'sonar': {'connected': False, 'message': 'Connecting to Sonar…'},
                      'music': {'connected': False, 'message': 'Connecting to MusicBee…'}}
        self.loop = asyncio.new_event_loop()
        self.ready = threading.Event()
        self.sonar_lock = None
        self.media_lock = None
        self.system_volume_lock = None
        self.app_versions = None
        self.updater = None

    def _preferences_stamp(self):
        try:
            return (ROOT / 'preferences.json').stat().st_mtime_ns
        except OSError:
            return 0

    def refresh_preferences(self):
        stamp = self._preferences_stamp()
        if stamp and stamp != self.preferences_stamp:
            try:
                self.preferences = validate_preferences(json.loads((ROOT / 'preferences.json').read_text('utf-8')))
                self.preferences_stamp = stamp
            except (OSError, ValueError, TypeError):
                pass

    async def poll_sonar(self):
        while True:
            self.refresh_preferences()
            async with self.sonar_lock:
                try:
                    self.state['sonar'] = await asyncio.to_thread(self.sonar.state)
                    try:
                        self.state['sonar']['chatMix'] = await asyncio.to_thread(self.sonar.chatmix_state)
                    except (OSError, ValueError, RuntimeError):
                        self.state['sonar']['chatMix'] = {'available': False, 'canControl': False, 'message': 'ChatMix is unavailable'}
                    self.meters.configure(self.sonar.audio_cache)
                except Exception as error:
                    self.state['sonar'] = {'connected': False, 'message': 'Sonar is unavailable. Open GG and enable Sonar.', 'detail': str(error)}
                    self.meters.configure([])
            await asyncio.sleep(0.8)

    async def poll_media(self):
        while True:
            async with self.media_lock:
                try:
                    self.state['music'] = await self.media.state()
                except Exception as error:
                    self.state['music'] = {'connected': False, 'message': 'MusicBee media controls are unavailable.', 'detail': str(error)}
            await asyncio.sleep(0.7)

    async def poll_system_volume(self):
        while True:
            async with self.system_volume_lock:
                self.state['systemVolume'] = await asyncio.to_thread(self.system_volume.state)
            await asyncio.sleep(.3)

    def run(self):
        asyncio.set_event_loop(self.loop)
        self.sonar_lock = asyncio.Lock()
        self.media_lock = asyncio.Lock()
        self.system_volume_lock = asyncio.Lock()
        self.ready.set()
        self.meters.start()
        self.loop.create_task(self.poll_sonar())
        self.loop.create_task(self.poll_media())
        self.loop.create_task(self.poll_system_volume())
        self.loop.run_forever()

    async def dispatch(self, path, data):
        if path == '/api/system-volume':
            async with self.system_volume_lock:
                result = await asyncio.to_thread(self.system_volume.command,data)
                self.state['systemVolume'] = result
                return result
        if path == '/api/display':
            return await asyncio.to_thread(DISPLAY_BRIGHTNESS.command, data)
        if path == '/api/update':
            if not self.updater:
                raise ValueError('Open the installed Sonar Edge app to use updates')
            return await asyncio.to_thread(self.updater.command, data)
        if path == '/api/app':
            if not self.app_versions:
                raise ValueError('Open the packaged Sonar Edge app to choose a version')
            return await asyncio.to_thread(self.app_versions.perform, data)
        if path == '/api/sonar':
            async with self.sonar_lock:
                result = await asyncio.to_thread(self.sonar.command, data)
                self.state['sonar'] = result
                return result
        if path == '/api/music':
            async with self.media_lock:
                result = await self.media.command(data)
                self.state['music'] = result
                return result
        if path == '/api/catalog':
            async with self.sonar_lock:
                return await asyncio.to_thread(self.sonar.catalog_data)
        if path == '/api/players':
            async with self.media_lock:
                return await self.media.players()
        if path == '/api/preferences':
            prefs = validate_preferences(data)
            temp = ROOT / ('preferences-' + secrets.token_hex(6) + '.tmp')
            temp.write_text(json.dumps(prefs, indent=2, ensure_ascii=False), 'utf-8')
            temp.replace(ROOT / 'preferences.json')
            self.preferences = prefs
            self.preferences_stamp = self._preferences_stamp()
            return prefs
        if path == '/api/validate-preferences':
            return validate_preferences(data)
        if path == '/api/launch':
            launch_app(data.get('app'))
            return {'ok': True}
        raise ValueError('Unknown action')


BRIDGE = Bridge()
DISPLAY_BRIGHTNESS = EdgeBrightness()


class Handler(BaseHTTPRequestHandler):
    server_version = 'SonarEdge/' + VERSION

    def log_message(self, fmt, *args):
        if args and str(args[1]) not in ('200', '304'):
            logging.info(fmt, *args)

    def valid_host(self):
        return self.headers.get('Host') in (f'127.0.0.1:{PORT}', f'localhost:{PORT}')

    def send(self, status, body, content_type='application/json; charset=utf-8'):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=True).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        if not self.valid_host():
            return self.send(403, {'error': 'Local access only'})
        path = urlsplit(self.path).path
        if path == '/api/session':
            return self.send(200, {'token': TOKEN, 'preferences': BRIDGE.preferences, 'version': VERSION,
                                  'appVersion': BRIDGE.app_versions.info() if BRIDGE.app_versions else None})
        if path == '/api/app':
            return self.send(200, BRIDGE.app_versions.info() if BRIDGE.app_versions else None)
        if path == '/api/display':
            return self.send(200, DISPLAY_BRIGHTNESS.info())
        if path == '/api/update':
            return self.send(200, BRIDGE.updater.info() if BRIDGE.updater else None)
        if path == '/api/state':
            return self.send(200, {**BRIDGE.state, 'preferences': BRIDGE.preferences})
        if path == '/api/meters':
            return self.send(200, BRIDGE.meters.snapshot())
        if path == '/embed':
            return self.send(200, (RESOURCE_ROOT / 'widget/index.html').read_bytes(), 'text/html; charset=utf-8')
        if path == '/api/art':
            return self.send(200 if BRIDGE.media.art else 404, BRIDGE.media.art, BRIDGE.media.art_type)
        if path.startswith('/backgrounds/') and re.fullmatch(r'/backgrounds/[a-f0-9]{64}\.(png|jpg|webp|gif|mp4|webm)', path):
            file = ROOT / path.lstrip('/')
            if file.is_file():
                return self.send(200, file.read_bytes(), mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
            return self.send(404, {'error': 'Background not found'})
        if path == '/api/players':
            try:
                data = asyncio.run_coroutine_threadsafe(BRIDGE.dispatch(path, {}), BRIDGE.loop).result(8)
                return self.send(200, data)
            except Exception as error:
                return self.send(503, {'error': str(error)})
        if path == '/api/catalog':
            try:
                data = asyncio.run_coroutine_threadsafe(BRIDGE.dispatch(path, {}), BRIDGE.loop).result(12)
                return self.send(200, data)
            except Exception as error:
                return self.send(503, {'error': str(error)})
        files = {'/': 'index.html', '/index.html': 'index.html', '/style.css': 'style.css', '/appearance.css': 'appearance.css', '/readable.css': 'readable.css', '/effects.css': 'effects.css', '/visuals.js': 'visuals.js',
                 '/app.js': 'app.js', '/icon.svg': 'icon.svg'}
        if path not in files:
            return self.send(404, {'error': 'Not found'})
        file = RESOURCE_ROOT / 'web' / files[path]
        return self.send(200, file.read_bytes(), (mimetypes.guess_type(file.name)[0] or 'text/plain') + '; charset=utf-8')

    def do_POST(self):
        if not self.valid_host():
            return self.send(403, {'error': 'Local access only'})
        origin = self.headers.get('Origin')
        if origin and origin not in (f'http://127.0.0.1:{PORT}', f'http://localhost:{PORT}'):
            return self.send(403, {'error': 'Open Edge Audio on this PC'})
        if self.headers.get('Sec-Fetch-Site') == 'cross-site':
            return self.send(403, {'error': 'Cross-site control is disabled'})
        if not hmac.compare_digest(self.headers.get('X-Edge-Token', ''), TOKEN):
            return self.send(403, {'error': 'Reconnect the panel and try again'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if urlsplit(self.path).path == '/api/background':
                if not 0 < length <= 64 * 1024 * 1024:
                    raise ValueError('Choose a background file smaller than 64 MB')
                body = self.rfile.read(length)
                if len(body) != length:
                    raise ValueError('The background upload was interrupted')
                ext = ('png' if body.startswith(b'\x89PNG\r\n\x1a\n') else 'jpg' if body.startswith(b'\xff\xd8\xff')
                       else 'gif' if body.startswith((b'GIF87a', b'GIF89a')) else 'webp' if body[:4] == b'RIFF' and body[8:12] == b'WEBP'
                       else 'mp4' if body[4:8] == b'ftyp' else 'webm' if body.startswith(b'\x1aE\xdf\xa3') else None)
                if not ext:
                    raise ValueError('Use PNG, JPEG, GIF, WebP, MP4, or WebM')
                folder = ROOT / 'backgrounds'
                folder.mkdir(exist_ok=True)
                name = hashlib.sha256(body).hexdigest() + '.' + ext
                (folder / name).write_bytes(body)
                return self.send(200, {'source': '/backgrounds/' + name, 'kind': 'video' if ext in ('mp4', 'webm') else 'image'})
            limit = 256*1024 if urlsplit(self.path).path in ('/api/preferences','/api/validate-preferences') else 16000
            if length <= 0 or length > limit or 'application/json' not in self.headers.get('Content-Type', ''):
                return self.send(400, {'error': 'Invalid request'})
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('Invalid request')
            future = asyncio.run_coroutine_threadsafe(BRIDGE.dispatch(urlsplit(self.path).path, data), BRIDGE.loop)
            return self.send(200, future.result(15))
        except (ValueError, KeyError, TypeError) as error:
            return self.send(400, {'error': str(error)})
        except Exception as error:
            logging.exception('Command failed')
            return self.send(503, {'error': str(error) or 'The app did not respond. Try again.'})


def main():
    logging.basicConfig(filename=ROOT / 'edge-audio.log', level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s')
    try:
        server = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    except OSError:
        # The launcher is safe to open repeatedly.
        return
    threading.Thread(target=BRIDGE.run, daemon=True, name='media-bridge').start()
    (ROOT / 'bridge.pid').write_text(str(os.getpid()), 'ascii')
    logging.info('Edge Audio ready at http://127.0.0.1:%s', PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        BRIDGE.meters.stop()
        (ROOT / 'bridge.pid').unlink(missing_ok=True)


if __name__ == '__main__':
    main()
