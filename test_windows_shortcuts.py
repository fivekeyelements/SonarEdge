"""Real ShellLink roundtrip and atomic update checks in a temporary folder."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import windows_shortcuts as shortcuts


class ShortcutTests(unittest.TestCase):
    def test_unicode_paths_preserve_target_arguments_and_working_directory(self):
        with TemporaryDirectory() as folder:
            base=Path(folder)
            executable=base/'app with spaces あ'/'SonarEdge.exe'
            executable.parent.mkdir()
            executable.write_bytes(b'MZ-fixture')
            link=base/'Startup'/'Sonar Edge.lnk'
            shortcuts.write_shortcut(link,executable,'--startup')
            self.assertEqual(shortcuts.read_shortcut(link),{'target':str(executable.resolve()),'arguments':'--startup','directory':str(executable.parent.resolve())})
            self.assertEqual(list(link.parent.iterdir()),[link])

    def test_failed_update_keeps_the_previous_shortcut(self):
        with TemporaryDirectory() as folder:
            link=Path(folder)/'Sonar Edge.lnk'
            link.write_bytes(b'original shortcut')
            with patch.object(shortcuts,'check',side_effect=OSError('COM failure')):
                with self.assertRaises(OSError):shortcuts.write_shortcut(link,Path(folder)/'SonarEdge.exe','--startup')
            self.assertEqual(link.read_bytes(),b'original shortcut')
            self.assertEqual(list(link.parent.iterdir()),[link])
