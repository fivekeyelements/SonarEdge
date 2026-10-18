"""Exercise real per-user registry operations on an isolated non-startup test key."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import uuid
import winreg
import windows_startup as startup
from windows_shortcuts import write_shortcut


class FakeScheduler:
    sid='S-1-5-21-1234'
    def __init__(self,folder):
        self.marker=folder/'startup-task-name.txt'
        self.state=None
    def query(self):return self.state
    def enable(self,target):
        target=Path(target).resolve()
        self.state={'target':str(target),'arguments':'--startup','directory':str(target.parent),
                    'enabled':True,'sid':self.sid,'logon':'InteractiveToken','runLevel':'LeastPrivilege','delay':'PT5S'}
        self.marker.write_text('isolated task')
    def delete(self):
        self.state=None
        self.marker.unlink(missing_ok=True)


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.folder=Path(self.temp.name)
        self.package=self.folder/'portable'
        self.package.mkdir()
        self.executable=self.package/'SonarEdge.exe'
        self.executable.write_bytes(b'MZ-test-app')
        (self.package/'Sonar Edge XL.icuewidget').write_bytes(b'widget-fixture')
        (self.package/'preferences.json').write_text('private')
        self.key='Software\\SonarEdgeTest-'+uuid.uuid4().hex
        self.key_patch=patch.object(startup,'RUN_KEY',self.key)
        self.key_patch.start()
        self.folder_patch=patch.object(startup,'startup_folder',return_value=self.folder/'Startup')
        self.folder_patch.start()
        self.install_patch=patch.object(startup.installation,'registered_executable',return_value=None)
        self.install_patch.start()
        self.scheduler=FakeScheduler(self.folder)
        self.task_patch=patch.object(startup,'ScheduledStartup',return_value=self.scheduler)
        self.task_patch.start()
        self.manager=startup.WindowsStartup(self.package,'1.7.0',executable=self.executable,
                                            install_root=self.folder/'installed',available=True)

    def tearDown(self):
        try:winreg.DeleteKey(winreg.HKEY_CURRENT_USER,self.key)
        except FileNotFoundError:pass
        self.key_patch.stop()
        self.folder_patch.stop()
        self.install_patch.stop()
        self.task_patch.stop()
        self.temp.cleanup()

    def test_enable_installs_clean_copy_and_registers_direct_exe(self):
        self.assertFalse(self.manager.info()['enabled'])
        self.assertTrue(self.manager.set_enabled(True)['enabled'])
        target=self.folder/'installed/1.7.0/SonarEdge.exe'
        self.assertEqual(target.read_bytes(),b'MZ-test-app')
        self.assertEqual(self.manager.registered_command(),f'"{target.resolve()}" --startup')
        self.assertEqual(self.scheduler.query()['target'],str(target.resolve()))
        self.assertFalse(self.manager.shortcut.exists())
        self.assertEqual(self.manager.info()['method'],'logon-task')
        with self.assertRaises(FileNotFoundError):winreg.OpenKey(winreg.HKEY_CURRENT_USER,self.key)
        self.assertTrue((target.parent/'Sonar Edge XL.icuewidget').exists())
        self.assertFalse((target.parent/'preferences.json').exists())

    def test_disable_removes_only_this_app_and_preserves_other_startup_values(self):
        self.manager.set_enabled(True)
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,self.key,0,winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key,'Another app',0,winreg.REG_SZ,'untouched')
        self.assertFalse(self.manager.set_enabled(False)['enabled'])
        self.assertFalse(self.manager.shortcut.exists())
        self.manager.set_enabled(False)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,self.key) as key:
            self.assertEqual(winreg.QueryValueEx(key,'Another app')[0],'untouched')

    def test_new_release_updates_without_downgrading_or_enabling_disabled_startup(self):
        self.manager.refresh_if_enabled()
        self.assertFalse(self.manager.info()['enabled'])
        self.manager.set_enabled(True)
        newer=startup.WindowsStartup(self.package,'1.8.0',executable=self.executable,
                                     install_root=self.folder/'installed',available=True)
        newer.refresh_if_enabled()
        self.assertIn('1.8.0',newer.registered_command())
        self.manager.refresh_if_enabled()
        self.assertIn('1.8.0',self.manager.registered_command())

    def test_running_managed_copy_does_not_copy_over_itself(self):
        self.manager.set_enabled(True)
        folder=self.folder/'installed/1.7.0'
        installed=startup.WindowsStartup(folder,'1.7.0',executable=folder/'SonarEdge.exe',
                                         install_root=self.folder/'installed',available=True)
        installed.refresh_if_enabled()
        self.assertTrue(installed.info()['enabled'])

    def test_invalid_values_and_development_launches_cannot_register(self):
        with self.assertRaises(ValueError):self.manager.set_enabled('yes')
        self.manager.available=False
        with self.assertRaises(ValueError):self.manager.set_enabled(True)
        with self.assertRaises(ValueError):startup.WindowsStartup(self.package,'../../bad')
        self.assertFalse(self.manager.info()['enabled'])

    def test_registered_install_is_used_and_portable_releases_do_not_retarget_it(self):
        target=self.folder/'real-install/SonarEdge.exe'
        self.install_patch.stop()
        with patch.object(startup.installation,'registered_executable',return_value=target):
            self.assertEqual(self.manager.deploy(),target)
            self.manager.set_enabled(True)
            before=self.manager.registered_command()
            self.manager.refresh_if_enabled()
            self.assertEqual(self.manager.registered_command(),before)
        self.install_patch.start()

    def test_legacy_run_entry_migrates_to_one_logon_task(self):
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,self.key,0,winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key,startup.VALUE_NAME,0,winreg.REG_SZ,f'"{self.executable}" --startup')
            winreg.SetValueEx(key,'Another app',0,winreg.REG_SZ,'untouched')
        self.manager.refresh_if_enabled()
        self.assertIsNotNone(self.scheduler.query())
        self.assertFalse(self.manager.shortcut.exists())
        self.assertEqual(self.manager.info()['method'],'logon-task')
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,self.key) as key:
            with self.assertRaises(FileNotFoundError):winreg.QueryValueEx(key,startup.VALUE_NAME)
            self.assertEqual(winreg.QueryValueEx(key,'Another app')[0],'untouched')

    def test_startup_folder_migrates_only_after_task_is_confirmed(self):
        write_shortcut(self.manager.shortcut,self.executable,'--startup')
        with patch.object(self.scheduler,'enable',side_effect=OSError('Registration failed')):
            with self.assertRaises(OSError):self.manager.set_enabled(True)
        self.assertTrue(self.manager.shortcut.exists())
        self.manager.refresh_if_enabled()
        self.assertFalse(self.manager.shortcut.exists())
        self.assertTrue(self.manager.info()['enabled'])

    def test_externally_disabled_task_stays_disabled_on_app_launch(self):
        self.manager.set_enabled(True)
        self.scheduler.state['enabled']=False
        self.manager.refresh_if_enabled()
        self.assertFalse(self.manager.info()['enabled'])


if __name__=='__main__':unittest.main(verbosity=2)
