"""Least-privilege, current-user logon tasks that launch Sonar Edge directly."""
import argparse
import csv
import io
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
import xml.etree.ElementTree as ET
from task_scheduler_xml import task_xml

NAMESPACE='http://schemas.microsoft.com/windows/2004/02/mit/task'
ET.register_namespace('',NAMESPACE)


def system_tool(name):
    return str(Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32'/name)


def current_sid():
    result=subprocess.run([system_tool('whoami.exe'),'/user','/fo','csv','/nh'],
        capture_output=True,timeout=10,creationflags=subprocess.CREATE_NO_WINDOW,check=True)
    sid=next(csv.reader(io.StringIO(result.stdout.decode('utf-8',errors='replace'))))[1]
    if not re.fullmatch(r'S-1-\d+(?:-\d+)+',sid):
        raise OSError('Windows could not identify your sign-in account.')
    return sid


class ScheduledStartup:
    def __init__(self,profile='SonarEdge',sid=None,marker=None):
        if not re.fullmatch(r'[A-Za-z0-9]{1,64}',profile):
            raise ValueError('Invalid startup profile')
        self.sid=sid or current_sid()
        if not re.fullmatch(r'S-1-\d+(?:-\d+)+',self.sid):raise ValueError('Invalid sign-in account')
        self.name='KagiSoftware.'+profile+'-'+self.sid
        self.marker=Path(marker or (Path(os.environ['LOCALAPPDATA'])/profile/'startup-task-name.txt'))

    def _run(self,*args):
        return subprocess.run([system_tool('schtasks.exe'),*args],capture_output=True,
            timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)

    def query(self):
        document=task_xml(self.name)
        if document is None:return None
        root=ET.fromstring(document)
        for item in root.iter():item.tag=item.tag.rsplit('}',1)[-1]
        if root.tag!='Task':raise OSError('Windows returned an invalid startup task.')
        principal=root.find('Principals/Principal')
        action=root.find('Actions/Exec')
        trigger=root.find('Triggers/LogonTrigger')
        if principal is None or action is None or trigger is None:
            raise OSError('Windows startup needs to be enabled again in Settings.')
        return {'target':action.findtext('Command',''),'arguments':action.findtext('Arguments',''),
                'directory':action.findtext('WorkingDirectory',''),
                'enabled':root.findtext('Settings/Enabled','true')!='false' and trigger.findtext('Enabled','true')!='false',
                'sid':principal.findtext('UserId',''),'logon':principal.findtext('LogonType',''),
                'runLevel':principal.findtext('RunLevel','LeastPrivilege'),'delay':trigger.findtext('Delay','PT0S')}

    def xml(self,executable,enabled=True):
        executable=Path(executable).resolve()
        def add(parent,name,text=None):
            item=ET.SubElement(parent,'{'+NAMESPACE+'}'+name)
            if text is not None:item.text=text
            return item
        root=ET.Element('{'+NAMESPACE+'}Task',{'version':'1.2'})
        registration=add(root,'RegistrationInfo')
        add(registration,'Author','Kagi Software')
        add(registration,'Description','Start Sonar Edge after this user signs in to Windows.')
        trigger=add(add(root,'Triggers'),'LogonTrigger')
        add(trigger,'Enabled','true');add(trigger,'Delay','PT5S');add(trigger,'UserId',self.sid)
        principal=add(add(root,'Principals'),'Principal');principal.set('id','User')
        add(principal,'UserId',self.sid);add(principal,'LogonType','InteractiveToken');add(principal,'RunLevel','LeastPrivilege')
        settings=add(root,'Settings')
        for name,value in (('MultipleInstancesPolicy','IgnoreNew'),('DisallowStartIfOnBatteries','false'),
            ('StopIfGoingOnBatteries','false'),('StartWhenAvailable','true'),('RunOnlyIfNetworkAvailable','false'),
            ('Enabled','true' if enabled else 'false'),('ExecutionTimeLimit','PT0S')):add(settings,name,value)
        actions=add(root,'Actions');actions.set('Context','User');action=add(actions,'Exec')
        add(action,'Command',str(executable));add(action,'Arguments','--startup');add(action,'WorkingDirectory',str(executable.parent))
        return ET.tostring(root,encoding='utf-16',xml_declaration=True)

    def enable(self,executable,enabled=True):
        executable=Path(executable).resolve()
        with TemporaryDirectory(prefix='SonarEdge-startup-') as folder:
            file=Path(folder)/'startup.xml';file.write_bytes(self.xml(executable,enabled))
            result=self._run('/Create','/TN',self.name,'/XML',str(file),'/F')
        if result.returncode:
            logging.error('Windows logon task registration failed: %r',result.stderr[:600])
            raise OSError('Windows could not enable startup. Check that Task Scheduler is running, then try again.')
        # Record successful registration even if the following read-back fails,
        # so the uninstaller can still remove this account's task.
        self.marker.parent.mkdir(parents=True,exist_ok=True)
        temporary=self.marker.with_suffix('.tmp')
        temporary.write_text(self.name,'ascii')
        temporary.replace(self.marker)
        state=self.query()
        expected={'target':str(executable),'arguments':'--startup','directory':str(executable.parent),
                  'enabled':enabled,'sid':self.sid,'logon':'InteractiveToken','runLevel':'LeastPrivilege','delay':'PT5S'}
        if state!=expected:
            logging.error('Startup task verification mismatch: actual=%r expected=%r',state,expected)
            raise OSError('Windows did not confirm the startup task. Try enabling startup again.')
        return state

    def delete(self):
        state=self.query()
        if state is not None:
            if state['sid']!=self.sid:raise OSError('The startup task belongs to another Windows account.')
            result=self._run('/Delete','/TN',self.name,'/F')
            if result.returncode:raise OSError('Windows could not remove Sonar Edge startup. Try again.')
        self.marker.unlink(missing_ok=True)

    def run(self):
        result=self._run('/Run','/TN',self.name)
        if result.returncode:raise OSError('Windows could not launch the startup task.')


def installer_cli():
    parser=argparse.ArgumentParser()
    parser.add_argument('--configure-startup',choices=('enable','disable'),required=True)
    parser.add_argument('--startup-profile',choices=('SonarEdge','SonarEdgeInstallTest'),default='SonarEdge')
    args=parser.parse_args()
    folder=Path(os.environ['LOCALAPPDATA'])/args.startup_profile
    folder.mkdir(parents=True,exist_ok=True)
    logging.basicConfig(filename=folder/'startup-setup.log',level=logging.INFO)
    try:
        task=ScheduledStartup(args.startup_profile)
        if args.configure_startup=='enable':task.enable(sys.executable)
        else:task.delete()
        # The installer uses an isolated product name in lifecycle tests.
        from windows_shortcuts import startup_folder
        import winreg
        product='Sonar Edge' if args.startup_profile=='SonarEdge' else 'Sonar Edge Install Test'
        (startup_folder()/(product+'.lnk')).unlink(missing_ok=True)
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Run',0,winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key,product)
        except FileNotFoundError:pass
        return 0
    except Exception:
        logging.exception('Could not configure Windows logon startup')
        return 1
