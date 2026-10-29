Unicode True
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"
!include "x64.nsh"
Name "Respect 批量创作"
OutFile "${OUTPUT}"
InstallDir "$LOCALAPPDATA\Programs\Respect-Batch-User"
InstallDirRegKey HKCU "Software\Respect\BatchUser" "InstallDir"
RequestExecutionLevel user
CRCCheck force
SetCompressor /SOLID lzma
VIProductVersion "${VERSION}"
VIAddVersionKey "ProductName" "Respect Batch"
VIAddVersionKey "FileDescription" "Respect 批量创作安装程序"
VIAddVersionKey "FileVersion" "${VERSION}"
Var UpdatePid
Var UpdateMode
Var Failure
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\RespectBatch-User.exe"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "SimpChinese"

Function Fail
  SetErrorLevel 2
  MessageBox MB_OK|MB_ICONSTOP "$Failure"
  Quit
FunctionEnd

!macro CheckRunning
  System::Call 'kernel32::OpenMutexW(i 0x100000, i 0, w "Local\Respect.Batch.User") p.r0'
  ${If} $0 != 0
    System::Call 'kernel32::CloseHandle(p r0)'
    StrCpy $Failure "批量版仍在运行，请先等待任务完成并关闭程序。Studio 无需关闭。"
    Call Fail
  ${EndIf}
!macroend

Function .onInit
  SetShellVarContext current
  ${IfNot} ${RunningX64}
    StrCpy $Failure "需要 64 位 Windows 10 或 Windows 11。"
    Call Fail
  ${EndIf}
  ${GetParameters} $0
  ClearErrors
  ${GetOptions} $0 "/BATCHUPDATE=" $UpdatePid
  ${IfNot} ${Errors}
    StrCpy $UpdateMode 1
    SetSilent silent
    ${If} $UpdatePid <= 0
      StrCpy $Failure "更新进程参数无效。"
      Call Fail
    ${EndIf}
    System::Call 'kernel32::OpenProcess(i 0x100000, i 0, i $UpdatePid) p.r1 ?e'
    Pop $2
    ${If} $1 != 0
      System::Call 'kernel32::WaitForSingleObject(p r1, i 60000) i.r2'
      System::Call 'kernel32::CloseHandle(p r1)'
      ${If} $2 != 0
        StrCpy $Failure "批量版尚未退出，更新未开始。"
        Call Fail
      ${EndIf}
    ${Else}
      ${If} $2 != 87
        StrCpy $Failure "无法确认批量版已退出，请手动运行安装器。"
        Call Fail
      ${EndIf}
    ${EndIf}
    Sleep 500
    IfFileExists "$INSTDIR\RespectBatch-User.exe" +3 0
      StrCpy $Failure "未找到原批量版安装目录，请手动运行安装器。"
      Call Fail
  ${EndIf}
  !insertmacro CheckRunning
FunctionEnd

Section "Respect Batch"
  !insertmacro CheckRunning
  IfFileExists "$INSTDIR\Respect-Studio.exe" 0 +3
    StrCpy $Failure "此目录属于 Studio，请为批量版选择独立目录。"
    Call Fail
  SetOutPath "$INSTDIR"
  ClearErrors
  File /oname=RespectBatch-User.exe.new "${PAYLOAD}\RespectBatch-User.exe"
  File /oname=batch-build.json.new "${PAYLOAD}\batch-build.json"
  ${If} ${Errors}
    StrCpy $Failure "无法写入更新文件，原程序保留，请检查空间和目录权限。"
    Call Fail
  ${EndIf}
  Delete "$INSTDIR\RespectBatch-User.exe.previous"
  Delete "$INSTDIR\batch-build.json.previous"
  ClearErrors
  IfFileExists "$INSTDIR\RespectBatch-User.exe" 0 +2
    Rename "$INSTDIR\RespectBatch-User.exe" "$INSTDIR\RespectBatch-User.exe.previous"
  ${If} ${Errors}
    StrCpy $Failure "原程序仍被占用，未覆盖文件，请关闭旧版后重试。"
    Call Fail
  ${EndIf}
  IfFileExists "$INSTDIR\batch-build.json" 0 +2
    Rename "$INSTDIR\batch-build.json" "$INSTDIR\batch-build.json.previous"
  ${IfNot} ${Errors}
    Rename "$INSTDIR\batch-build.json.new" "$INSTDIR\batch-build.json"
    Rename "$INSTDIR\RespectBatch-User.exe.new" "$INSTDIR\RespectBatch-User.exe"
  ${EndIf}
  ${If} ${Errors}
    Delete "$INSTDIR\RespectBatch-User.exe"
    IfFileExists "$INSTDIR\batch-build.json.previous" 0 +2
      Delete "$INSTDIR\batch-build.json"
    Rename "$INSTDIR\RespectBatch-User.exe.previous" "$INSTDIR\RespectBatch-User.exe"
    Rename "$INSTDIR\batch-build.json.previous" "$INSTDIR\batch-build.json"
    StrCpy $Failure "安装未完成，已尝试恢复原文件，请检查目录权限。"
    Call Fail
  ${EndIf}
  Delete "$INSTDIR\RespectBatch-User.exe.previous"
  Delete "$INSTDIR\batch-build.json.previous"
  WriteUninstaller "$INSTDIR\Uninstall-Batch.exe"
  CreateDirectory "$SMPROGRAMS\Respect 批量创作"
  CreateShortcut "$SMPROGRAMS\Respect 批量创作\Respect 批量创作.lnk" "$INSTDIR\RespectBatch-User.exe"
  CreateShortcut "$DESKTOP\Respect 批量创作.lnk" "$INSTDIR\RespectBatch-User.exe"
  WriteRegStr HKCU "Software\Respect\BatchUser" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\RespectBatchUser" "DisplayName" "Respect 批量创作"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\RespectBatchUser" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\RespectBatchUser" "UninstallString" '$\"$INSTDIR\Uninstall-Batch.exe$\"'
SectionEnd

Function .onInstSuccess
  ${If} $UpdateMode == 1
    Exec '$\"$INSTDIR\RespectBatch-User.exe$\"'
  ${EndIf}
FunctionEnd

Section "Uninstall"
  SetShellVarContext current
  Delete "$INSTDIR\RespectBatch-User.exe"
  Delete "$INSTDIR\batch-build.json"
  Delete "$INSTDIR\Uninstall-Batch.exe"
  Delete "$DESKTOP\Respect 批量创作.lnk"
  Delete "$SMPROGRAMS\Respect 批量创作\Respect 批量创作.lnk"
  RMDir "$SMPROGRAMS\Respect 批量创作"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "Software\Respect\BatchUser"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\RespectBatchUser"
SectionEnd
