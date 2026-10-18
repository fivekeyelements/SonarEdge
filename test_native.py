"""Native desktop transport and file isolation checks; no audio changes."""
import copy
import json
import os
import socket
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock
from urllib.request import urlopen
import native_app as native
from webview.util import needs_server


class NativeTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.data_patch = patch.object(native, 'DATA_DIR', self.folder)
        self.data_patch.start()
        self.bridge = SimpleNamespace(preferences=copy.deepcopy(native.core.DEFAULTS),
            state={'sonar': {'connected':True},'music':{'connected':True,'art':'/api/art?v=1'}},
            media=SimpleNamespace(art=b'\xff\xd8\xfftest',art_type='image/jpeg'))
        self.api = native.NativeAPI(self.bridge)

    def tearDown(self):
        self.data_patch.stop()
        self.temp.cleanup()

    def test_interface_uses_files_and_needs_no_server(self):
        uri = native.prepare_ui()
        self.assertTrue(uri.startswith('file:///'))
        self.assertFalse(needs_server([uri]))
        html = (self.folder / 'interface.html').read_text('utf-8')
        self.assertIn('window.SONAR_EDGE_NATIVE=true', html)
        self.assertNotIn('<script src=', html)
        self.assertNotIn('rel="stylesheet"', html)
        self.assertIn('SONAR <span>EDGE</span>', html)

    def test_busy_widget_connection_is_recoverable_and_leaves_its_owner_untouched(self):
        with socket.socket() as occupied:
            occupied.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            occupied.bind(('127.0.0.1', 0))
            occupied.listen()
            port = occupied.getsockname()[1]
            with patch.object(native.core, 'PORT', port), self.assertLogs(level='ERROR'):
                self.assertIsNone(native.start_widget_listener())
            self.assertEqual(occupied.getsockname(), ('127.0.0.1', port))
            native.stop_widget_listener(None)

    def test_available_widget_listener_serves_locally_and_shuts_down(self):
        with patch.object(native.core, 'PORT', 0):
            listener = native.start_widget_listener()
        self.assertIsNotNone(listener)
        try:
            with patch.object(native.core, 'PORT', listener.server_port):
                with urlopen(f'http://127.0.0.1:{listener.server_port}/', timeout=3) as response:
                    self.assertIn('data-icon="gear"', response.read().decode('utf-8'))
        finally:
            native.stop_widget_listener(listener)
        self.assertEqual(listener.socket.fileno(), -1)

    def test_failed_widget_startup_opens_desktop_and_cleans_up_without_a_listener(self):
        class StopBeforeWindow(Exception):
            pass
        bridge = Mock(preferences=copy.deepcopy(native.core.DEFAULTS))
        with patch.object(native.sys, 'argv', ['SonarEdge', '--widget']), \
             patch.object(native, 'single_instance', return_value=True), \
             patch.object(native, 'WindowsStartup'), \
             patch.object(native.core, 'BRIDGE', bridge), \
             patch.object(native.core, 'PORT', 47832), \
             patch.object(native.threading, 'Thread'), \
             patch.object(native, 'start_widget_listener', return_value=None), \
             patch.object(native.webview, 'screens', []), \
             patch.object(native, 'startup_display', return_value=(None, None)), \
             patch.object(native.webview, 'create_window', side_effect=StopBeforeWindow) as create:
            with self.assertRaises(StopBeforeWindow):
                native.main()
        self.assertFalse(create.call_args.kwargs['hidden'])
        self.assertEqual(bridge.app_versions.current, 'desktop')
        self.assertFalse(bridge.app_versions.info()['widgetReady'])
        html = (self.folder / 'interface.html').read_text('utf-8')
        self.assertIn('window.SONAR_EDGE_CHOOSE_VERSION=true', html)
        bridge.meters.stop.assert_called_once()

    def test_native_api_rejects_unknown_paths_and_methods(self):
        for method,path in [('GET','/arbitrary/file'),('POST','/api/background'),('DELETE','/api/preferences'),('GET','/api/launch')]:
            with self.subTest(method=method,path=path):
                with self.assertLogs(level='ERROR'):
                    result=self.api.call(method,path,{})
                self.assertFalse(result['ok'])
                self.assertEqual(result['error'],'Unknown desktop operation')

    def test_native_display_settings_use_the_same_hardware_service_as_the_widget(self):
        with patch.object(native.core,'DISPLAY_BRIGHTNESS') as brightness:
            brightness.info.return_value={'displays':[{'id':'edge','brightness':95}]}
            self.assertEqual(self.api.call('GET','/api/display')['data'],brightness.info.return_value)
            brightness.info.assert_called_once_with()

    def test_state_artwork_uses_local_files_and_returns_a_copy(self):
        state=self.api.call('GET','/api/state',{})
        self.assertTrue(state['ok'])
        self.assertTrue(state['data']['music']['art'].startswith('file:///'))
        self.assertEqual(len(list((self.folder/'artwork').glob('*.jpg'))),1)
        self.assertEqual(self.bridge.state['music']['art'],'/api/art?v=1')
        state['data']['preferences']['accent']='#000000'
        self.assertNotEqual(self.bridge.preferences['accent'],'#000000')

    def test_artwork_cache_is_bounded_and_keeps_current_and_unrelated_files(self):
        folder = self.folder / 'artwork'
        folder.mkdir()
        current = folder / ('a' * 64 + '.jpg')
        current.write_bytes(b'current')
        for number in range(20):
            file = folder / (f'{number:064x}' + '.png')
            file.write_bytes(b'cached')
            os.utime(file, (number + 1, number + 1))
        unrelated = folder / 'keep-me.txt'
        unrelated.write_text('not a generated artwork file', 'utf-8')
        native.trim_artwork_cache(folder, current)
        self.assertTrue(current.exists())
        self.assertTrue(unrelated.exists())
        self.assertEqual(len(list(folder.glob('*.png'))), 15)
        self.assertFalse((folder / (f'{0:064x}' + '.png')).exists())

    def test_local_background_copy_rejects_code_and_deduplicates(self):
        with self.assertRaises(ValueError):native.background_from_bytes(b'<html>bad</html>')
        data=b'GIF89a'+b'test-fixture'
        one=native.background_from_bytes(data)
        two=native.background_from_bytes(data)
        self.assertEqual(one,two)
        self.assertEqual(len(list((self.folder/'backgrounds').iterdir())),1)
        self.assertEqual((self.folder/one['source'].lstrip('/')).read_bytes(),data)

    def test_native_export_uses_selected_path_and_validated_preferences(self):
        destination=self.folder/'chosen.json'
        self.api._window=SimpleNamespace(create_file_dialog=lambda *args,**kwargs:(str(destination),))
        result=self.api.export_settings(copy.deepcopy(native.core.DEFAULTS))
        self.assertTrue(result['ok'])
        self.assertEqual(json.loads(destination.read_text('utf-8')),native.core.DEFAULTS)

    def test_native_import_sanitizes_preferences(self):
        preferences=copy.deepcopy(native.core.DEFAULTS)
        preferences['appearance']['panelOpacity']=100
        source=self.folder/'import.json'
        source.write_text(json.dumps(preferences),'utf-8')
        self.api._window=SimpleNamespace(create_file_dialog=lambda *args,**kwargs:(str(source),))
        result=self.api.import_settings()
        self.assertTrue(result['ok'])
        self.assertEqual(result['data']['appearance']['panelOpacity'],1)

    def test_cancelling_native_file_picker_changes_nothing(self):
        self.api._window=SimpleNamespace(create_file_dialog=lambda *args,**kwargs:None)
        self.assertIsNone(self.api.pick_background()['data'])
        self.assertIsNone(self.api.import_settings()['data'])
        self.assertEqual(list(self.folder.iterdir()),[])

    def test_desktop_and_widget_reload_shared_preferences(self):
        with patch.object(native.core,'ROOT',self.folder):
            bridge=native.core.Bridge()
            try:
                prefs=copy.deepcopy(native.core.DEFAULTS)
                prefs['accent']='#abcdef'
                (self.folder/'preferences.json').write_text(json.dumps(prefs),'utf-8')
                bridge.refresh_preferences()
                self.assertEqual(bridge.preferences['accent'],'#abcdef')
                (self.folder/'preferences.json').write_text('{partial','utf-8')
                bridge.refresh_preferences()
                self.assertEqual(bridge.preferences['accent'],'#abcdef')
            finally:
                bridge.loop.close()


if __name__=='__main__':
    unittest.main(verbosity=2)
