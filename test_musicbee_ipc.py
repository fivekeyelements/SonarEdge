"""Real C# plugin / Python named-pipe interoperability and timeout checks."""
from pathlib import Path
import subprocess
import time
import unittest
from unittest.mock import patch
import musicbee_bridge

ROOT = Path(__file__).resolve().parent

class MusicBeeIPCTests(unittest.TestCase):
    def test_real_plugin_abi_and_controls(self):
        compiler = Path(r'C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe')
        host = ROOT / 'build/MusicBeeTestHost.exe'
        host.parent.mkdir(exist_ok=True)
        subprocess.run([str(compiler), '/nologo', '/target:exe', '/platform:x86',
                        '/reference:System.Windows.Forms.dll', '/reference:System.Web.Extensions.dll',
                        '/out:' + str(host), str(ROOT/'musicbee/SonarEdgePlugin.cs'),
                        str(ROOT/'musicbee/TestHost.cs')], check=True)
        process = subprocess.Popen([str(host)], stdout=subprocess.PIPE, text=True)
        isolated = patch('musicbee_bridge.pipe_name',return_value=musicbee_bridge.pipe_name()+'.Test.'+str(process.pid))
        isolated.start()
        self.addCleanup(isolated.stop)
        try:
            self.assertIn('ready', process.stdout.readline())
            for _ in range(15):
                state = musicbee_bridge.state()
                if state:
                    break
                time.sleep(.1)
            self.assertIsNotNone(state)
            self.assertEqual(state['duration'], 240)
            self.assertAlmostEqual(state['volume'], .42, places=5)
            self.assertEqual(musicbee_bridge.request('seek', 60)['position'], 60)
            self.assertAlmostEqual(musicbee_bridge.request('volume', .21)['volume'], .21, places=5)
            for action, value in [('seek',241),('seek',-1),('volume',2),('volume',True),('launch',None)]:
                with self.assertRaises(ValueError):
                    musicbee_bridge.request(action,value)
            self.assertAlmostEqual(musicbee_bridge.state()['volume'],.21,places=5)
        finally:
            process.terminate()
            process.wait(5)
            process.stdout.close()
        started = time.monotonic()
        self.assertIsNone(musicbee_bridge.state())
        self.assertLess(time.monotonic()-started, 1.5)

if __name__ == '__main__':
    unittest.main(verbosity=2)
