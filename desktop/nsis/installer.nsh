; Custom NSIS script for Flowboard installer/uninstaller

; Run after uninstall: delete user data folder if user confirms
!macro customUnInstall
  MessageBox MB_YESNO|MB_ICONQUESTION \
    "Bạn có muốn xóa toàn bộ dữ liệu Flowboard (boards, projects, media)?$\n$\n$APPDATA\flowboard-desktop" \
    IDNO skip_delete
    RMDir /r "$APPDATA\flowboard-desktop"
  skip_delete:
!macroend
