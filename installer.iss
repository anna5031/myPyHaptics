#define MyAppName "bHaptics Metronome"
#define MyAppVersion "2.0.0"
#define MyAppPublisher "bHaptics Metronome"
#define MyAppExeName1 "bhapticsMetronomeController.exe"
#define MyAppExeName2 "bHapticsRelay.exe"

[Setup]
AppId={{A962A2C4-F7C0-4346-980A-BFA56F4D4A1D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=bHapticsMetronome-setup
SetupIconFile=assets\bMet.ico
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕 화면 아이콘 만들기"; GroupDescription: "추가 작업:"; Flags: unchecked

[Files]
Source: "dist\bhapticsMetronomeController\*"; DestDir: "{app}\bhapticsMetronomeController"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "dist\bHapticsRelay\*"; DestDir: "{app}\bHapticsRelay"; Flags: ignoreversion recursesubdirs createallsubdirs
#ifexist ".env"
Source: ".env"; Flags: dontcopy
#endif
#ifexist ".env.example"
Source: ".env.example"; Flags: dontcopy
#endif

[Icons]
Name: "{autoprograms}\bHaptics Metronome Controller"; Filename: "{app}\bhapticsMetronomeController\{#MyAppExeName1}"; Parameters: "--ui"; WorkingDir: "{app}"
Name: "{autoprograms}\bHaptics Relay"; Filename: "{app}\bHapticsRelay\{#MyAppExeName2}"; WorkingDir: "{app}"
Name: "{autodesktop}\bHaptics Metronome Controller"; Filename: "{app}\bhapticsMetronomeController\{#MyAppExeName1}"; Parameters: "--ui"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{autodesktop}\bHaptics Relay"; Filename: "{app}\bHapticsRelay\{#MyAppExeName2}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\bhapticsMetronomeController\{#MyAppExeName1}"; Parameters: "--ui"; WorkingDir: "{app}"; Description: "bHaptics Metronome Controller 실행"; Flags: nowait postinstall skipifsilent

[Code]
var
  EnvPage: TInputQueryWizardPage;
  MqttKeepaliveValue: string;
  MqttQosValue: string;
  MqttRetainValue: string;
  BhapticsAppNameValue: string;
  BhapticsAppIdValue: string;
  BhapticsApiKeyValue: string;

function TrimQuotes(const S: string): string;
begin
  Result := Trim(S);
  if (Length(Result) >= 2) and
     (((Result[1] = '"') and (Result[Length(Result)] = '"')) or
      ((Result[1] = '''') and (Result[Length(Result)] = ''''))) then
    Result := Copy(Result, 2, Length(Result) - 2);
end;

function EnvValueFromLines(const Key, DefaultValue: string; const Lines: TArrayOfString): string;
var
  I, P: Integer;
  Line, K, V: string;
begin
  Result := DefaultValue;
  for I := 0 to GetArrayLength(Lines) - 1 do
  begin
    Line := Trim(Lines[I]);
    if (Line = '') or (Copy(Line, 1, 1) = '#') then
      continue;

    P := Pos('=', Line);
    if P <= 1 then
      continue;

    K := Trim(Copy(Line, 1, P - 1));
    V := Trim(Copy(Line, P + 1, MaxInt));

    if CompareText(K, Key) = 0 then
    begin
      Result := TrimQuotes(V);
      exit;
    end;
  end;
end;

procedure SetBuiltInDefaults;
begin
  EnvPage.Values[0] := 'mqtt-web.makinteract.com';
  EnvPage.Values[1] := '1883';
  EnvPage.Values[2] := '';
  EnvPage.Values[3] := '';

  MqttKeepaliveValue := '60';
  MqttQosValue := '1';
  MqttRetainValue := 'false';

  BhapticsAppNameValue := 'Hello, bHaptics!';
  BhapticsAppIdValue := '';
  BhapticsApiKeyValue := '';
end;

procedure LoadEnvDefaultsFromFile(const FilePath: string);
var
  Lines: TArrayOfString;
begin
  if not LoadStringsFromFile(FilePath, Lines) then
    exit;

  EnvPage.Values[0] := EnvValueFromLines('MQTT_BROKER', EnvPage.Values[0], Lines);
  EnvPage.Values[1] := EnvValueFromLines('MQTT_PORT', EnvPage.Values[1], Lines);
  MqttKeepaliveValue := EnvValueFromLines('MQTT_KEEPALIVE', MqttKeepaliveValue, Lines);
  MqttQosValue := EnvValueFromLines('MQTT_QOS', MqttQosValue, Lines);
  MqttRetainValue := EnvValueFromLines('MQTT_RETAIN', MqttRetainValue, Lines);
  EnvPage.Values[2] := EnvValueFromLines('MQTT_USERNAME', EnvPage.Values[2], Lines);
  EnvPage.Values[3] := EnvValueFromLines('MQTT_PASSWORD', EnvPage.Values[3], Lines);
  BhapticsAppNameValue := EnvValueFromLines('BHAPTICS_APP_NAME', BhapticsAppNameValue, Lines);
  BhapticsAppIdValue := EnvValueFromLines('BHAPTICS_APP_ID', BhapticsAppIdValue, Lines);
  BhapticsApiKeyValue := EnvValueFromLines('BHAPTICS_API_KEY', BhapticsApiKeyValue, Lines);
end;

procedure LoadDefaultsFromEnvFiles;
var
  TmpEnvPath, TmpExamplePath: string;
begin
  SetBuiltInDefaults;

  TmpEnvPath := ExpandConstant('{tmp}\.env');
  TmpExamplePath := ExpandConstant('{tmp}\.env.example');

#ifexist ".env.example"
  try
    ExtractTemporaryFile('.env.example');
    if FileExists(TmpExamplePath) then
      LoadEnvDefaultsFromFile(TmpExamplePath);
  except
  end;
#endif

#ifexist ".env"
  try
    ExtractTemporaryFile('.env');
    if FileExists(TmpEnvPath) then
      LoadEnvDefaultsFromFile(TmpEnvPath);
  except
  end;
#endif
end;

procedure InitializeWizard;
begin
  EnvPage := CreateInputQueryPage(
    wpSelectDir,
    'MQTT 설정',
    'MQTT 접속 정보 입력',
    '프로젝트의 .env(없으면 .env.example) 값을 기본으로 불러오며, MQTT_BROKER, MQTT_PORT를 입력받습니다. MQTT_USERNAME, MQTT_PASSWORD는 선택 사항입니다.'
  );

  EnvPage.Add('MQTT_BROKER', False);
  EnvPage.Add('MQTT_PORT', False);
  EnvPage.Add('MQTT_USERNAME', False);
  EnvPage.Add('MQTT_PASSWORD', True);

  LoadDefaultsFromEnvFiles;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  PortValue: Integer;
begin
  Result := True;

  if CurPageID <> EnvPage.ID then
    exit;

  if Trim(EnvPage.Values[0]) = '' then
  begin
    MsgBox('MQTT_BROKER 값을 입력하세요.', mbError, MB_OK);
    Result := False;
    exit;
  end;

  if Trim(EnvPage.Values[1]) = '' then
  begin
    MsgBox('MQTT_PORT 값을 입력하세요.', mbError, MB_OK);
    Result := False;
    exit;
  end;

  try
    PortValue := StrToInt(Trim(EnvPage.Values[1]));
  except
    MsgBox('MQTT_PORT는 1 이상의 숫자여야 합니다.', mbError, MB_OK);
    Result := False;
    exit;
  end;

  if PortValue <= 0 then
  begin
    MsgBox('MQTT_PORT는 1 이상의 숫자여야 합니다.', mbError, MB_OK);
    Result := False;
    exit;
  end;

end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  EnvText, EnvPath: string;
begin
  if CurStep <> ssInstall then
    exit;

  EnvPath := ExpandConstant('{app}\.env');
  EnvText :=
    'BHAPTICS_APP_ID=' + BhapticsAppIdValue + #13#10 +
    'BHAPTICS_API_KEY=' + BhapticsApiKeyValue + #13#10 +
    'BHAPTICS_APP_NAME=' + BhapticsAppNameValue + #13#10 + #13#10 +
    'MQTT_BROKER=' + EnvPage.Values[0] + #13#10 +
    'MQTT_PORT=' + EnvPage.Values[1] + #13#10 +
    'MQTT_KEEPALIVE=' + MqttKeepaliveValue + #13#10 +
    'MQTT_QOS=' + MqttQosValue + #13#10 +
    'MQTT_RETAIN=' + MqttRetainValue + #13#10 +
    'MQTT_USERNAME=' + EnvPage.Values[2] + #13#10 +
    'MQTT_PASSWORD=' + EnvPage.Values[3] + #13#10;

  SaveStringToFile(EnvPath, EnvText, False);
end;
