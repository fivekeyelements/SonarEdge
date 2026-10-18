"""Native desktop transport and file isolation checks; no audio changes."""
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
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

    def test_native_api_rejects_unknown_paths_and_methods(self):
        for method,path in [('GET','/arbitrary/file'),('POST','/api/background'),('DELETE','/api/preferences'),('GET','/api/launch')]:
            result=self.api.call(method,path,{})
            self.assertFalse(result['ok'])

    def test_state_artwork_uses_local_files_and_returns_a_copy(self):
        state=self.api.call('GET','/api/state',{})
        self.assertTrue(state['ok'])
        self.assertTrue(state['data']['music']['art'].startswith('file:///'))
        self.assertEqual(len(list((self.folder/'artwork').glob('*.jpg'))),1)
        self.assertEqual(self.bridge.state['music']['art'],'/api/art?v=1')
        state['data']['preferences']['accent']='#000000'
        self.assertNotEqual(self.bridge.preferences['accent'],'#000000')

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
