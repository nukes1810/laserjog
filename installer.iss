; Inno Setup script: builds LightCut-Setup.exe from the PyInstaller output in dist\LightCut

[Setup]
AppName=LightCut
AppVersion=1.0.0
AppPublisher=nukes1810
DefaultDirName={autopf}\LightCut
DefaultGroupName=LightCut
OutputDir=output
OutputBaseFilename=LightCut-Setup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\LightCut.exe

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "dist\LightCut\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\LightCut"; Filename: "{app}\LightCut.exe"
Name: "{group}\Uninstall LightCut"; Filename: "{uninstallexe}"
Name: "{autodesktop}\LightCut"; Filename: "{app}\LightCut.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\LightCut.exe"; Description: "Launch LightCut"; Flags: nowait postinstall skipifsilent
