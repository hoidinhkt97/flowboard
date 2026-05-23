; Custom NSIS script for Flowboard installer/uninstaller

; Run after uninstall: delete user data folder if user confirms
!macro customUnInstall
  ; Read AppData path from HKCU registry — $APPDATA resolves to C:\ProgramData
  ; when running elevated, so we read HKCU directly for the correct user path.
  ReadRegStr $R0 HKCU "Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders" "AppData"
  StrCpy $R0 "$R0\flowboard-desktop"

  IfFileExists "$R0\*.*" 0 skip_delete
    MessageBox MB_YESNO|MB_ICONQUESTION \
      "Bạn có muốn xóa toàn bộ dữ liệu Flowboard (boards, projects, media)?$\n$\n$R0" \
      IDNO skip_delete
      RMDir /r "$R0"
  skip_delete:
!macroend
