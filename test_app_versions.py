"""Mode selection and iframe transport checks; never changes live audio."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch
from unittest.mock import Mock
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
import app_versions as versions
import server


class AppVersionTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.folder=Path(self.temp.name)
        self.modes=versions.AppVersions(self.folder,self.folder,command=['C:/Sonar Edge/SonarEdge.exe'])

    def tearDown(self):
        self.temp.cleanup()

    def test_choice_persists_and_explicit_shortcuts_override_it(self):
        self.assertEqual(versions.launch_version(self.folder),'desktop')
        self.modes.perform({'action':'default','mode':'iframe'})
        self.assertEqual(versions.launch_version(self.folder),'iframe')
        self.assertEqual(versions.launch_version(self.folder,desktop=True),'desktop')
        self.assertEqual(versions.launch_version(self.folder,widget=True),'iframe')
        self.assertEqual(self.modes.info()['default'],'iframe')
        self.assertEqual(list(self.folder.glob('*.tmp')),[])

    def test_corrupt_choices_fall_back_and_cannot_inject_commands(self):
        for value in ({'default':'--evil'},[],None):
            (self.folder/'app-version.json').write_text(json.dumps(value),'utf-8')
            self.assertEqual(versions.preferred_version(self.folder),'desktop')
        for request in ({'action':'open','mode':'anything.exe'},{'action':'default','mode':'bad'},{'action':'shell'}):
            with self.assertRaises(ValueError):self.modes.perform(request)

    def test_each_version_launches_an_explicit_mode_without_shell_or_port_inheritance(self):
        with patch.object(versions.subprocess,'Popen') as launch,patch.dict(versions.os.environ,{'SONAR_EDGE_WIDGET_PORT':'1234'}):
            for mode,argument in [('desktop','--desktop'),('iframe','--widget')]:
                self.modes.perform({'action':'open','mode':mode})
                args,kwargs=launch.call_args
                self.assertEqual(args[0],['C:/Sonar Edge/SonarEdge.exe',argument])
                self.assertNotIn('SONAR_EDGE_WIDGET_PORT',kwargs['env'])
                self.assertEqual(kwargs['env']['PYINSTALLER_RESET_ENVIRONMENT'],'1')
                self.assertFalse(kwargs.get('shell',False))

    def test_widget_actions_only_open_bundled_files(self):
        with self.assertRaises(ValueError):self.modes.perform({'action':'widget'})
        widget=self.folder/'Sonar Edge XL.icuewidget'
        widget.write_bytes(b'fixture')
        self.assertTrue(self.modes.info()['widgetAvailable'])
        with patch.object(versions.subprocess,'Popen') as launch:
            self.modes.perform({'action':'widget','path':'C:/untrusted.exe'})
            self.assertEqual(launch.call_args.args[0],['explorer.exe','/select,',str(widget)])

    def test_startup_choice_is_native_only_and_is_not_part_of_layout_export(self):
        service=Mock()
        service.info.return_value={'available':True,'enabled':True}
        self.modes.startup=service
        result=self.modes.perform({'action':'default','mode':'iframe','startup':True})
        service.set_enabled.assert_called_once_with(True)
        self.assertTrue(result['startup']['enabled'])
        self.assertEqual(json.loads((self.folder/'app-version.json').read_text('utf-8')),{'default':'iframe'})
        with self.assertRaises(ValueError):self.modes.perform({'action':'default','mode':'desktop','startup':'yes'})

    def test_iframe_is_embeddable_and_app_actions_keep_csrf_protection(self):
        listener=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        port=listener.server_port
        with patch.object(server,'PORT',port),patch.object(server.BRIDGE,'app_versions',self.modes):
            thread=threading.Thread(target=listener.serve_forever,daemon=True)
            thread.start()
            try:
                base=f'http://127.0.0.1:{port}'
                with urlopen(base+'/?icue=xl') as response:
                    html=response.read().decode('utf-8')
                    self.assertIn('id="chatmix"',html)
                    self.assertIn('/visuals.js',html)
                    self.assertIsNone(response.headers.get('X-Frame-Options'))
                with urlopen(base+'/api/app') as response:
                    self.assertEqual(json.load(response)['iframeHtml'],versions.IFRAME_HTML)
                with urlopen(base+'/embed') as response:
                    self.assertIn('sonar-edge-ready',response.read().decode('utf-8'))
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(base+'/api/app',data=b'{"action":"open","mode":"desktop"}',headers={'Content-Type':'application/json'}))
                self.assertEqual(error.exception.code,403)
            finally:
                listener.shutdown();thread.join();listener.server_close()


if __name__=='__main__':unittest.main(verbosity=2)
