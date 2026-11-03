; Niezapominajka – instalator Windows (Inno Setup 6)
; Budowa: ISCC packaging\windows\installer.iss  (po zbudowaniu folderu dist-win\Niezapominajka)
#define AppName "Niezapominajka"
#define AppVersion "1.0.2"
#define AppPublisher "Maksymilian Staszewski"
#define AppURL "https://github.com/maksiu0284/niezapominajka"
#define AppPort "8000"

[Setup]
AppId={{6C2E7A4B-5D1F-4E8B-9A3C-2B7F1E0D4A61}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=..\..\LICENSE
OutputDir=..\..\dist-win
OutputBaseFilename=Niezapominajka-{#AppVersion}-instalator
SetupIconFile=niezapominajka.ico
UninstallDisplayIcon={app}\Niezapominajka.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Languages]
Name: "polish"; MessagesFile: "compiler:Languages\Polish.isl"

[Tasks]
Name: "desktopicon"; Description: "Skrót na pulpicie"; GroupDescription: "Skróty:"
Name: "autostart"; Description: "Uruchamiaj Niezapominajkę po zalogowaniu do Windows (zalecane dla komputera-serwera)"; GroupDescription: "Uruchamianie:"
Name: "firewall"; Description: "Zezwól telefonom i innym komputerom w sieci firmowej na połączenie (zapora Windows, port {#AppPort})"; GroupDescription: "Sieć:"

[Dirs]
; Dane w %ProgramData%\Niezapominajka. Uprawnienia ustawia icacls w sekcji [Run]:
; tylko Administratorzy, SYSTEM i konto, które instaluje program (dawniej: wszyscy użytkownicy).
Name: "{commonappdata}\Niezapominajka"

[Files]
Source: "..\..\dist-win\Niezapominajka\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\Niezapominajka.exe"
Name: "{group}\Folder danych"; Filename: "{commonappdata}\Niezapominajka"
Name: "{group}\Odinstaluj {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\Niezapominajka.exe"; Tasks: desktopicon
Name: "{commonstartup}\{#AppName}"; Filename: "{app}\Niezapominajka.exe"; Parameters: "--bez-przegladarki"; Tasks: autostart

[Run]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Niezapominajka"""; Flags: runhidden; Tasks: firewall
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""Niezapominajka"" dir=in action=allow protocol=TCP localport={#AppPort} profile=private,domain"; Flags: runhidden; Tasks: firewall
; Uprawnienia folderu danych – także dla folderu z poprzednich wersji (dane zostają, zmieniają się tylko prawa dostępu).
; *S-1-5-32-544 = Administratorzy, *S-1-5-18 = SYSTEM (identyfikatory działają w każdej wersji językowej Windows).
Filename: "{sys}\icacls.exe"; Parameters: """{commonappdata}\Niezapominajka"" /inheritance:r /grant:r *S-1-5-32-544:(OI)(CI)F *S-1-5-18:(OI)(CI)F ""{username}"":(OI)(CI)M"; Flags: runhidden waituntilterminated; StatusMsg: "Ustawianie uprawnień folderu danych..."
Filename: "{sys}\icacls.exe"; Parameters: """{commonappdata}\Niezapominajka\*"" /reset /T /C /Q"; Flags: runhidden waituntilterminated
Filename: "{app}\Niezapominajka.exe"; Description: "Uruchom Niezapominajkę"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C taskkill /IM Niezapominajka.exe /F"; Flags: runhidden; RunOnceId: "StopApp"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Niezapominajka"""; Flags: runhidden; RunOnceId: "DelFirewall"

[Messages]
polish.FinishedLabel=Instalacja zakończona. Niezapominajka działa w tle – jej ikona jest w zasobniku obok zegara. Dane programu są w folderze %ProgramData%\Niezapominajka i nie są usuwane przy odinstalowaniu.
