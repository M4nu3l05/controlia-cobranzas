; Inno Setup script - Controlia Cobranzas
; Requiere tener compilado: dist\ControliaCobranzas\ControliaCobranzas.exe

#define MyAppName "Controlia Cobranzas"
#define MyAppVersion "1.0.5"
#define MyAppPublisher "Controlia"
#define MyAppExeName "ControliaCobranzas.exe"
#define MyAppId "{{1D6E7720-33C0-4745-BFB7-C1EC5A46A57C}"
#define MyAppIconFile "..\assets\app_icon.ico"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=..\legal\terminos.txt
OutputDir=output
OutputBaseFilename=ControliaCobranzas_Setup_{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
#ifexist MyAppIconFile
SetupIconFile={#MyAppIconFile}
#endif
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=admin

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo en el escritorio"; GroupDescription: "Accesos directos:"; Flags: unchecked

[Files]
Source: "..\dist\ControliaCobranzas\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\ControliaCobranzas\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\backend_url.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\assets\app_icon.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\legal\terminos.txt"; DestDir: "{app}\legal"; Flags: ignoreversion
Source: "..\legal\privacidad.txt"; DestDir: "{app}\legal"; Flags: ignoreversion
Source: "..\legal\privacidad.txt"; DestDir: "{tmp}"; Flags: dontcopy

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\app_icon.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\app_icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Ejecutar {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
var
  PrivacyPage: TWizardPage;
  PrivacyMemo: TRichEditViewer;
  PrivacyAccepted: TNewCheckBox;

procedure InitializeWizard;
var
  PrivacyTextRaw: AnsiString;
  PrivacyText: String;
begin
  PrivacyPage := CreateCustomPage(
    wpLicense,
    'Política de Privacidad',
    'Debes leer y aceptar la Política de Privacidad para continuar con la instalación.'
  );

  PrivacyMemo := TRichEditViewer.Create(PrivacyPage);
  PrivacyMemo.Parent := PrivacyPage.Surface;
  PrivacyMemo.Left := 0;
  PrivacyMemo.Top := 0;
  PrivacyMemo.Width := PrivacyPage.SurfaceWidth;
  PrivacyMemo.Height := PrivacyPage.SurfaceHeight - 52;
  PrivacyMemo.ReadOnly := True;
  PrivacyMemo.ScrollBars := ssVertical;

  ExtractTemporaryFile('privacidad.txt');
  if LoadStringFromFile(ExpandConstant('{tmp}\privacidad.txt'), PrivacyTextRaw) then
  begin
    { privacidad.txt está en UTF-8; decodificamos explícitamente para evitar texto corrupto }
    PrivacyText := UTF8Decode(PrivacyTextRaw);
    PrivacyMemo.Text := PrivacyText;
  end
  else
    PrivacyMemo.Text := 'No fue posible cargar la Política de Privacidad.';

  PrivacyAccepted := TNewCheckBox.Create(PrivacyPage);
  PrivacyAccepted.Parent := PrivacyPage.Surface;
  PrivacyAccepted.Left := 0;
  PrivacyAccepted.Top := PrivacyMemo.Height + 12;
  PrivacyAccepted.Width := PrivacyPage.SurfaceWidth;
  PrivacyAccepted.Caption := 'He leído y acepto la Política de Privacidad.';
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;

  if CurPageID = PrivacyPage.ID then
  begin
    if not PrivacyAccepted.Checked then
    begin
      MsgBox(
        'Debes aceptar la Política de Privacidad para continuar.',
        mbError,
        MB_OK
      );
      Result := False;
    end;
  end;
end;
