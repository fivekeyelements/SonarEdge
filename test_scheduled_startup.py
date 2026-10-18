"""Round-trip a disabled, isolated task through the actual Windows scheduler."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import uuid
from scheduled_startup import ScheduledStartup


class ScheduledStartupTests(unittest.TestCase):
    def test_native_registration_keeps_user_scope_unicode_path_and_security_mode(self):
        with TemporaryDirectory() as folder:
            folder=Path(folder).resolve()
            target=folder/'Music & Sonar 音楽'/'SonarEdge.exe'
            task=ScheduledStartup('SonarEdgeTest'+uuid.uuid4().hex,marker=folder/'marker.txt')
            self.assertIsNone(task.query())
            try:
                state=task.enable(target,enabled=False)
                self.assertFalse(state['enabled'])  # Never run a fixture at logon.
                self.assertEqual(state['target'],str(target))
                self.assertEqual(state['directory'],str(target.parent))
                self.assertEqual(state['arguments'],'--startup')
                self.assertEqual(state['sid'],task.sid)
                self.assertEqual(state['logon'],'InteractiveToken')
                self.assertEqual(state['runLevel'],'LeastPrivilege')
                self.assertEqual(state['delay'],'PT5S')
                self.assertEqual(task.marker.read_text('ascii'),task.name)
            finally:task.delete()
            self.assertIsNone(task.query())
            self.assertFalse(task.marker.exists())
            task.delete()  # Idempotent, and no other task is affected.


if __name__=='__main__':unittest.main(verbosity=2)
