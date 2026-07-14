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
Filename: "{app}\SkyDesk.exe"; Description: "Launch SkyDesk"; Flags: nowait postinstall skipifsilent