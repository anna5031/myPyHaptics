[Setup]
AppId={{A7E6A92D-10D8-4F14-AAD0-6E6F2E0B68D1}
AppName=myPyHaptics
AppVersion=0.1.0
AppPublisher=myPyHaptics
DefaultDirName={autopf}\myPyHaptics
DefaultGroupName=myPyHaptics
UninstallDisplayIcon={app}\subscribe.exe
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
OutputDir=..\release
OutputBaseFilename=myPyHaptics-setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicons"; Description: "Create desktop icons"; GroupDescription: "Additional icons"

[Files]
Source: "..\dist311\publish.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist311\subscribe.exe"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
Name: "{userappdata}\myPyHaptics"

[Icons]
Name: "{group}\Publisher"; Filename: "{app}\publish.exe"; WorkingDir: "{userappdata}\myPyHaptics"
Name: "{group}\Subscriber"; Filename: "{app}\subscribe.exe"; WorkingDir: "{userappdata}\myPyHaptics"
Name: "{autodesktop}\myPyHaptics Publisher"; Filename: "{app}\publish.exe"; Tasks: desktopicons; WorkingDir: "{userappdata}\myPyHaptics"
Name: "{autodesktop}\myPyHaptics Subscriber"; Filename: "{app}\subscribe.exe"; Tasks: desktopicons; WorkingDir: "{userappdata}\myPyHaptics"

[Run]
Filename: "{app}\publish.exe"; Description: "Launch Publisher"; WorkingDir: "{userappdata}\myPyHaptics"; Flags: nowait postinstall skipifsilent

[Code]
var
  CredentialsPage: TInputQueryWizardPage;
  EnvAppId: string;
  EnvApiKey: string;
  EnvAppName: string;

procedure InitializeWizard;
begin
  CredentialsPage :=
    CreateInputQueryPage(
      wpSelectTasks,
      'bHaptics Credentials',
      'Enter bHaptics API settings',
      'These values are saved to %APPDATA%\myPyHaptics\.env and used by subscribe.exe.'
    );

  CredentialsPage.Add('BHAPTICS_APP_ID:', False);
  CredentialsPage.Add('BHAPTICS_API_KEY:', True);
  CredentialsPage.Add('BHAPTICS_APP_NAME:', False);
  CredentialsPage.Values[2] := 'Hello, bHaptics!';
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = CredentialsPage.ID then
  begin
    EnvAppId := Trim(CredentialsPage.Values[0]);
    EnvApiKey := Trim(CredentialsPage.Values[1]);
    EnvAppName := Trim(CredentialsPage.Values[2]);

    if EnvAppId = '' then
    begin
      MsgBox('BHAPTICS_APP_ID is required.', mbError, MB_OK);
      Result := False;
      exit;
    end;

    if EnvApiKey = '' then
    begin
      MsgBox('BHAPTICS_API_KEY is required.', mbError, MB_OK);
      Result := False;
      exit;
    end;

    if EnvAppName = '' then
      EnvAppName := 'Hello, bHaptics!';
  end;
end;

procedure WriteEnvFile;
var
  EnvPath: string;
  EnvBody: string;
begin
  EnvPath := ExpandConstant('{userappdata}\myPyHaptics\.env');
  ForceDirectories(ExtractFileDir(EnvPath));
  EnvBody :=
    'BHAPTICS_APP_ID=' + EnvAppId + #13#10 +
    'BHAPTICS_API_KEY=' + EnvApiKey + #13#10 +
    'BHAPTICS_APP_NAME=' + EnvAppName + #13#10;

  if not SaveStringToFile(EnvPath, EnvBody, False) then
    MsgBox('Failed to write .env file at:' + #13#10 + EnvPath, mbError, MB_OK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    WriteEnvFile;
end;
