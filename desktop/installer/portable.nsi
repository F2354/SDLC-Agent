; SDLC Agent - single-file portable launcher (NSIS).
;
; Goal: produce ONE exe that runs with no installation.
; On first run it extracts the app to %LOCALAPPDATA%\SDLC-Agent\<version>
; and launches it. Later runs skip extraction (extract-once, fast startup).

Unicode true
Name "SDLC Agent"
OutFile "${__FILEDIR__}\..\release\SDLC-Agent.exe"

SilentInstall silent
RequestExecutionLevel user
ShowInstDetails nevershow
SetCompressor /SOLID lzma

!define APP_VERSION "0.2.0"
!define STAGE_DIR "${__FILEDIR__}\..\release\win-unpacked"

Var TargetDir

Function .onInit
    ; Version in the path: upgrades extract into a fresh directory.
    StrCpy $TargetDir "$LOCALAPPDATA\SDLC-Agent\${APP_VERSION}"
FunctionEnd

Section
    IfFileExists "$TargetDir\SDLC Agent.exe" 0 extract
    Goto launch
extract:
    CreateDirectory "$TargetDir"
    SetOutPath "$TargetDir"
    File /r "${STAGE_DIR}\*.*"
launch:
    Exec '"$TargetDir\SDLC Agent.exe"'
SectionEnd
