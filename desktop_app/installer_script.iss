[Setup]
AppName=SkyDesk
AppVersion=1.0
AppPublisher=Sky Financia
DefaultDirName={autopf}\SkyDesk
DefaultGroupName=SkyDesk
UninstallDisplayIcon={app}\SkyDesk.exe
OutputDir=installer_output
OutputBaseFilename=SkyDeskSetup
Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=admin

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "dist\SkyDesk.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\SkyDesk"; Filename: "{app}\SkyDesk.exe"
Name: "{autodesktop}\SkyDesk"; Filename: "{app}\SkyDesk.exe"; Tasks: desktopicon
Name: "{group}\Uninstall SkyDesk"; Filename: "{uninstallexe}"

[Run]
Filename: "netsh"; Parameters: "advfirewall firewall add rule name=""SkyDesk Screen"" dir=in action=allow protocol=TCP localport=9001 program=""{app}\SkyDesk.exe"" enable=yes"; Flags: runhidden
Filename: "netsh"; Parameters: "advfirewall firewall add rule name=""SkyDesk Control"" dir=in action=allow protocol=TCP localport=9002 program=""{app}\SkyDesk.exe"" enable=yes"; Flags: runhidden
Filename: "{app}\SkyDesk.exe"; Description: "Launch SkyDesk"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "netsh"; Parameters: "advfirewall firewall delete rule name=""SkyDesk Screen"""; Flags: runhidden
Filename: "netsh"; Parameters: "advfirewall firewall delete rule name=""SkyDesk Control"""; Flags: runhidden