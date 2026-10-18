import hashlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from urllib.request import Request
import app_updates as updates


def payload(body=b'MZ'+b'installer'*100):
    return {'tag_name':'v1.9.0','draft':False,'prerelease':False,'body':'Changes <stay plain text>',
            'assets':[{'name':'SonarEdge-Setup-1.9.0-Windows-x64.exe','state':'uploaded','size':len(body),
                       'digest':'sha256:'+hashlib.sha256(body).hexdigest(),
                       'browser_download_url':'https://github.com/example/SonarEdge/releases/download/v1.9.0/SonarEdge-Setup-1.9.0-Windows-x64.exe'}]}


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.opener=Mock()
        self.launcher=Mock()
        self.manager=updates.AppUpdates(self.root,self.root/'SonarEdge.exe',current='1.8.0',
                                       default_repo='example/SonarEdge',opener=self.opener,launcher=self.launcher)

    def tearDown(self):self.temp.cleanup()

    def test_only_stable_newer_versions_can_be_selected(self):
        release=payload()
        self.assertEqual(updates.release_candidate(release,'example/SonarEdge','1.8.0')['version'],'1.9.0')
        self.assertIsNone(updates.release_candidate(release,'example/SonarEdge','1.9.0'))
        self.assertIsNone(updates.release_candidate(release,'example/SonarEdge','2.0.0'))
        for tag in ('../../evil','v1.9.0-beta','1.9','1.9.0;shutdown'):
            release['tag_name']=tag
            with self.assertRaises(ValueError):updates.release_candidate(release,'example/SonarEdge')

    def test_wrong_repo_missing_hash_bad_size_and_ambiguous_assets_are_rejected(self):
        for change in ({'browser_download_url':'http://127.0.0.1/evil.exe'},
                       {'browser_download_url':'https://github.com/someone/Else/releases/download/v1.9.0/SonarEdge-Setup-1.9.0-Windows-x64.exe'},
                       {'digest':None},{'size':updates.MAX_INSTALLER+1},{'size':True}):
            release=payload();release['assets'][0].update(change)
            with self.assertRaises(ValueError):updates.release_candidate(release,'example/SonarEdge')
        release=payload();release['assets']*=2
        with self.assertRaises(ValueError):updates.release_candidate(release,'example/SonarEdge')
        for flag in ('draft','prerelease'):
            release=payload();release[flag]=True
            with self.assertRaises(ValueError):updates.release_candidate(release,'example/SonarEdge')

    def test_check_reads_public_release_and_source_cannot_be_an_arbitrary_url(self):
        self.opener.open.return_value=io.BytesIO(json.dumps(payload()).encode())
        self.manager.check()
        self.assertEqual(self.manager.info()['status'],'available')
        self.assertEqual(self.opener.open.call_args.args[0].full_url,'https://api.github.com/repos/example/SonarEdge/releases/latest')
        for repo in ('https://evil.example','../private','owner/../repo','owner/repo?token=secret'):
            with self.assertRaises(ValueError):self.manager.command({'action':'source','repository':repo})
        self.manager.command({'action':'source','repository':'another/Project'})
        restored=updates.AppUpdates(self.root,self.root/'SonarEdge.exe')
        self.assertEqual(restored.repo,'another/Project')

    def test_verified_installer_launches_with_upgrade_and_reopen_flags(self):
        body=b'MZ'+b'installer'*100
        self.manager.candidate=updates.release_candidate(payload(body),'example/SonarEdge')
        self.opener.open.return_value=io.BytesIO(body)
        self.manager.download_and_install()
        self.assertEqual(self.manager.info()['status'],'installing')
        command=self.launcher.call_args.args[0]
        self.assertEqual(Path(command[0]).read_bytes(),body)
        self.assertIn('/UPDATE=1',command);self.assertIn('/LAUNCH=1',command)
        self.assertFalse(self.launcher.call_args.kwargs.get('shell',False))
        self.assertEqual(self.launcher.call_args.kwargs['env']['PYINSTALLER_RESET_ENVIRONMENT'],'1')
        self.assertEqual(list((self.root/'updates').glob('*.part')),[])

    def test_corrupt_truncated_oversize_and_non_executable_downloads_never_run(self):
        for downloaded,expected in [(b'MZbad',b'MZgood'),(b'MZshort',b'MZlongerpayload'),
                                    (b'MZoversized',b'MZtiny'),(b'<html>',b'<html>')]:
            self.manager.candidate=updates.release_candidate(payload(expected),'example/SonarEdge')
            self.opener.open.return_value=io.BytesIO(downloaded)
            self.manager.download_and_install()
            self.assertEqual(self.manager.info()['status'],'error')
            self.launcher.assert_not_called()
            self.assertEqual(list((self.root/'updates').glob('*.part')),[])

    def test_cancel_and_portable_mode_do_not_launch_installers(self):
        self.manager.candidate=updates.release_candidate(payload(),'example/SonarEdge')
        with patch.object(updates.installation,'installed_directory',return_value=None):
            with self.assertRaises(ValueError):self.manager.command({'action':'install'})
        self.manager.cancel.set()
        self.opener.open.return_value=io.BytesIO(b'MZinstaller')
        self.manager.download_and_install()
        self.assertEqual(self.manager.info()['status'],'available')
        self.launcher.assert_not_called()

    def test_redirects_cannot_escape_https_github_download_hosts(self):
        redirect=updates.GitHubRedirect()
        for url in ('http://github.com/evil','https://evil.example/installer','https://github.com@evil.example/installer','https://github.com:8443/installer'):
            with self.assertRaises(ValueError):redirect.redirect_request(Request('https://github.com/example'),None,302,'',{},url)


if __name__=='__main__':unittest.main(verbosity=2)
