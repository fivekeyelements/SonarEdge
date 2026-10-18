#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef AppId
  #define AppId "SonarEdge"
#endif
#ifndef ProductName
  #define ProductName "Sonar Edge"
#endif
#ifndef ProfileName
  #define ProfileName "SonarEdge"
#endif
#ifndef RunValueName
  #define RunValueName "Sonar Edge"
#endif
#ifndef OutputName
  #define OutputName "SonarEdge-Setup-" + AppVersion + "-Windows-x64"
#endif
#define ReleaseDir "..\releases\SonarEdge-" + AppVersion + "-Windows-x64"

[Setup]
AppId={#AppId}
AppName={#ProductName}
AppVersion={#AppVersion}
AppPublisher=Kagi Software
AppPublisherURL=https://github.com/fivekeyelements/SonarEdge
AppSupportURL=https://github.com/fivekeyelements/SonarEdge/issues
AppUpdatesURL=https://github.com/fivekeyelements/SonarEdge/releases
DefaultDirName={localappdata}\Programs\{#ProfileName}
DefaultGroupName={#ProductName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir=..\releases
OutputBaseFilename={#OutputName}
SetupIconFile=..\assets\SonarEdge.ico
UninstallDisplayIcon={app}\SonarEdge.exe
UninstallDisplayName={#ProductName}
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#ProductName} Setup
VersionInfoCompany=Kagi Software
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
CloseApplicationsFilter=SonarEdge.exe
RestartApplications=no
SetupMutex={#AppId}.Setup
UninstallLogging=yes

[Tasks]
Name: autostart; Description: "Start Sonar Edge when I sign in to Windows"; Flags: checkedonce
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: checkedonce

[Files]
Source: "{#ReleaseDir}\SonarEdge.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ReleaseDir}\Sonar Edge XL.icuewidget"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ReleaseDir}\Read me.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ReleaseDir}\iCUE XL setup.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ReleaseDir}\THIRD-PARTY-NOTICES.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ReleaseDir}\licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\packaging\MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: NeedsWebView

[Icons]
; A direct Start menu entry is always created, including upgrades from /NOICONS.
Name: "{userprograms}\{#ProductName}"; Filename: "{app}\SonarEdge.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Sonar Edge"; Filename: "{app}\SonarEdge.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[InstallDelete]
Type: files; Name: "{userprograms}\{#ProductName}\Sonar Edge.lnk"
Type: files; Name: "{userprograms}\{#ProductName}\Sonar Edge Desktop.lnk"
Type: files; Name: "{userprograms}\{#ProductName}\Sonar Edge for iCUE.lnk"
Type: files; Name: "{userprograms}\{#ProductName}\Choose app version.lnk"
Type: files; Name: "{userprograms}\{#ProductName}\iCUE XL setup.lnk"
Type: dirifempty; Name: "{userprograms}\{#ProductName}"
#if AppId == "SonarEdge"
Type: files; Name: "{autodesktop}\Sonar Edge for iCUE.lnk"
#endif

[Run]
Filename: "{app}\SonarEdge.exe"; Description: "Open Sonar Edge"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{app}\installation.json"
Type: files; Name: "{userstartup}\{#ProductName}.lnk"

[Code]
const RunKey = 'Software\Microsoft\Windows\CurrentVersion\Run';
var PreviousStartup, RemoveProfile, StartupConfigured: Boolean;

function CreateEvent(Attributes: LongWord; ManualReset, InitialState: Boolean; Name: String): THandle;
  external 'CreateEventW@kernel32.dll stdcall';
function SetEvent(Handle: THandle): Boolean;
  external 'SetEvent@kernel32.dll stdcall';
function CloseHandle(Handle: THandle): Boolean;
  external 'CloseHandle@kernel32.dll stdcall';

function IsUpdate: Boolean;
begin
  Result := ExpandConstant('{param:UPDATE|0}') = '1';
end;

function NeedsWebView: Boolean;
var V: String;
begin
  Result := not (
    (RegQueryStringValue(HKLM32, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', V) and (V <> '') and (V <> '0.0.0.0')) or
    (RegQueryStringValue(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', V) and (V <> '') and (V <> '0.0.0.0')));
end;

function StopSonarEdge: Boolean;
var Signal: THandle; I: Integer;
begin
  { Isolated installer tests must not close the user's actual companion. }
  if '{#AppId}' <> 'SonarEdge' then begin Result := True; exit; end;
  Signal := CreateEvent(0, True, False, 'Local\SonarEdge.Exit.v1');
  if Signal <> 0 then SetEvent(Signal);
  I := 0;
  while CheckForMutexes('Local\SonarEdge.App.v1,Local\SonarEdge.Desktop.v1,Local\SonarEdge.Widget.v1') and (I < 150) do begin
    Sleep(100); I := I + 1;
  end;
  Result := not CheckForMutexes('Local\SonarEdge.App.v1,Local\SonarEdge.Desktop.v1,Local\SonarEdge.Widget.v1');
  if Signal <> 0 then CloseHandle(Signal);
end;

function InitializeSetup: Boolean;
begin
  PreviousStartup := RegValueExists(HKCU, RunKey, '{#RunValueName}') or FileExists(ExpandConstant('{userstartup}\{#ProductName}.lnk'));
  Result := True;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  if not StopSonarEdge then
    Result := 'Close Sonar Edge and choose Exit companion from its tray icon, then retry. This older version does not support automatic shutdown.'
  else Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var ExitCode: Integer; Enabled: Boolean; Marker: String;
begin
  if CurStep = ssPostInstall then begin
    if NeedsWebView then begin
      if not Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe'), '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then
        RaiseException('Microsoft WebView2 could not start. Run Setup again.');
      if NeedsWebView then RaiseException('WebView2 installation did not finish. Connect to the internet and run Setup again.');
    end;
    Enabled := WizardIsTaskSelected('autostart');
    if IsUpdate then Enabled := PreviousStartup;
    if Enabled then begin
      if not RegWriteStringValue(HKCU, RunKey, '{#RunValueName}', ExpandConstant('"{app}\SonarEdge.exe" --startup')) then
        RaiseException('Windows startup could not be saved.');
    end else RegDeleteValue(HKCU, RunKey, '{#RunValueName}');
    DeleteFile(ExpandConstant('{userstartup}\{#ProductName}.lnk'));
    Marker := '{"appId":"{#AppId}","version":"{#AppVersion}"}';
    if not SaveStringToFile(ExpandConstant('{app}\installation.json'), Marker, False) then
      RaiseException('The installation record could not be saved.');
    StartupConfigured := True;
  end;
  if (CurStep = ssDone) and WizardSilent and (ExpandConstant('{param:LAUNCH|0}') = '1') then
    Exec(ExpandConstant('{app}\SonarEdge.exe'), '', ExpandConstant('{app}'), SW_SHOWNORMAL, ewNoWait, ExitCode);
end;

function GetCustomSetupExitCode: Integer;
begin
  if StartupConfigured then Result := 0 else Result := 1;
end;

function InitializeUninstall: Boolean;
begin
  Result := StopSonarEdge;
  if not Result then begin
    SuppressibleMsgBox('Close Sonar Edge and exit its tray companion, then try uninstalling again.', mbError, MB_OK, IDOK);
    exit;
  end;
  RemoveProfile := ExpandConstant('{param:PURGEDATA|0}') = '1';
  if not UninstallSilent then
    RemoveProfile := MsgBox('Also remove your saved layouts, backgrounds and downloaded updates?'#13#10'Choose No to keep them for a future reinstall.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES;
end;

function IsVersionFolder(Name: String): Boolean;
var I, Dots: Integer;
begin
  Result := False; Dots := 0;
  if (Length(Name) < 5) or (Length(Name) > 32) or (Pos('..', Name) > 0) then exit;
  for I := 1 to Length(Name) do begin
    if Name[I] = '.' then Dots := Dots + 1
    else if (Name[I] < '0') or (Name[I] > '9') then exit;
  end;
  Result := (Dots = 2) and (Name[1] <> '.') and (Name[Length(Name)] <> '.');
end;

procedure RemoveLegacyCopies;
var Base, Folder, Product: String; Guide: AnsiString; Entry: TFindRec; Files: TArrayOfString; I: Integer;
begin
  Base := ExpandConstant('{app}\versions');
  SetArrayLength(Files, 7);
  Files[0] := 'SonarEdge.exe'; Files[1] := 'Read me.txt'; Files[2] := 'iCUE XL setup.txt';
  Files[3] := 'Sonar Edge XL.icuewidget'; Files[4] := 'THIRD-PARTY-NOTICES.txt';
  Files[5] := 'Choose app version.vbs'; Files[6] := 'Start iCUE companion.vbs';
  if FindFirst(Base + '\*', Entry) then try
    repeat
      if IsVersionFolder(Entry.Name) and (Entry.Attributes and FILE_ATTRIBUTE_DIRECTORY <> 0) then begin
        Folder := Base + '\' + Entry.Name;
        if GetVersionNumbersString(Folder + '\SonarEdge.exe', Product) and
           FileExists(Folder + '\Sonar Edge XL.icuewidget') and
           LoadStringFromFile(Folder + '\Read me.txt', Guide) and (Pos('SONAR EDGE ', Guide) = 1) then begin
          for I := 0 to GetArrayLength(Files) - 1 do DeleteFile(Folder + '\' + Files[I]);
          DelTree(Folder + '\licenses', True, True, True);
          RemoveDir(Folder);
        end;
      end;
    until not FindNext(Entry);
  finally FindClose(Entry); end;
  RemoveDir(Base);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var Command, Prefix, DataFolder: String;
begin
  if CurUninstallStep = usUninstall then begin
    Prefix := Lowercase(ExpandConstant('"{app}\'));
    if RegQueryStringValue(HKCU, RunKey, '{#RunValueName}', Command) and (Pos(Prefix, Lowercase(Command)) = 1) then
      RegDeleteValue(HKCU, RunKey, '{#RunValueName}');
    RemoveLegacyCopies;
  end;
  if (CurUninstallStep = usPostUninstall) and RemoveProfile then begin
    DataFolder := ExpandConstant('{localappdata}\{#ProfileName}');
    if CompareText(ExtractFileDir(DataFolder), ExpandConstant('{localappdata}')) = 0 then
      DelTree(DataFolder, True, True, True);
  end;
end;
