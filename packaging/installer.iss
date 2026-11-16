; Inno Setup 6 - installer di EWA. Compilare con:  ISCC packaging\installer.iss [/DMyAppVersion=1.2.3]
; Prima serve la cartella dist\EWA prodotta da PyInstaller (vedi build.py).

#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#define MyAppName "EWA " + Chr(8212) + " Everything in Windows but AI"
#define IconShell SourcePath + "..\ewa\assets\icons\shell.ico"

[Setup]
AppId={{6F1B7C52-3A9E-4D0B-9C47-EA5A0C0DE001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=EWA
VersionInfoVersion={#MyAppVersion}
DefaultDirName={localappdata}\Programs\EWA
DefaultGroupName=EWA
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=EWA-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\EWA.exe
#if FileExists(IconShell)
SetupIconFile={#IconShell}
#endif

[Languages]
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"

[Tasks]
Name: "desktopicon"; Description: "Crea le icone sul desktop"; GroupDescription: "Collegamenti:"; Flags: unchecked
Name: "installollama"; Description: "Installa Ollama (necessario per Marv) tramite winget"; GroupDescription: "Marv:"; Check: not OllamaInstalled

[Files]
Source: "..\dist\EWA\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Calcolatrice"; Filename: "{app}\Calcolatrice.exe"
Name: "{group}\Sveglie e orologio"; Filename: "{app}\Sveglie e orologio.exe"
Name: "{group}\Fotocamera"; Filename: "{app}\Fotocamera.exe"
Name: "{group}\Blocco note"; Filename: "{app}\Blocco note.exe"
Name: "{group}\Terminale EWA"; Filename: "{app}\EWA.exe"
Name: "{group}\Disinstalla EWA"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Calcolatrice"; Filename: "{app}\Calcolatrice.exe"; Tasks: desktopicon
Name: "{autodesktop}\Sveglie e orologio"; Filename: "{app}\Sveglie e orologio.exe"; Tasks: desktopicon
Name: "{autodesktop}\Fotocamera"; Filename: "{app}\Fotocamera.exe"; Tasks: desktopicon
Name: "{autodesktop}\Blocco note"; Filename: "{app}\Blocco note.exe"; Tasks: desktopicon
Name: "{autodesktop}\Terminale EWA"; Filename: "{app}\EWA.exe"; Tasks: desktopicon

[Run]
Filename: "winget"; Parameters: "install -e --id Ollama.Ollama --accept-source-agreements --accept-package-agreements"; StatusMsg: "Installazione di Ollama tramite winget..."; Flags: waituntilterminated; Tasks: installollama
Filename: "{app}\EWA.exe"; Parameters: "--setup"; Description: "Prepara Marv: avvia Ollama e scarica il modello gemma4:e2b (circa 5 GB)"; WorkingDir: "{app}"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C taskkill /IM MarvHub.exe /F"; Flags: runhidden; RunOnceId: "KillMarvHub"

[Code]
function OllamaInstalled: Boolean;
begin
  Result :=
    FileExists(ExpandConstant('{localappdata}\Programs\Ollama\ollama.exe')) or
    FileExists(ExpandConstant('{autopf}\Ollama\ollama.exe')) or
    (FileSearch('ollama.exe', GetEnv('PATH')) <> '');
end;

// Se MarvHub e' in esecuzione (aggiornamento) i suoi file sono bloccati: lo chiudiamo.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{cmd}'), '/C taskkill /IM MarvHub.exe /F', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := '';
end;
