; maple_reload.ahk (AHK v2) - Reload Maple document without stealing focus
; Usage: AutoHotkey64.exe maple_reload.ahk "save"
;        AutoHotkey64.exe maple_reload.ahk "reload" "C:\path\to\file.mw"

#SingleInstance Force

action := A_Args.Has(1) ? A_Args[1] : ""
filePath := A_Args.Has(2) ? A_Args[2] : ""

if (action = "") {
    ExitApp
}

SetTitleMatchMode 2

FindMapleJavaHwnd() {
    if WinExist("Maple ahk_class AutoHotkeyGUI") {
        wrapperHwnd := WinGetID()
        childHwnd := DllCall("FindWindowEx", "Ptr", wrapperHwnd, "Ptr", 0, "Str", "SunAwtFrame", "Ptr", 0, "Ptr")
        if (childHwnd != 0)
            return childHwnd
    }
    if WinExist("Maple ahk_class SunAwtFrame")
        return WinGetID()
    return 0
}

javaHwnd := FindMapleJavaHwnd()
if (javaHwnd = 0) {
    ExitApp 1
}

maple := "ahk_id " javaHwnd

if (action = "save") {
    ControlSend "^s", , maple
    Sleep 500
}

if (action = "reload") {
    origHwnd := WinGetID("A")

    ControlSend "^{F4}", , maple
    Sleep 300

    if (filePath != "") {
        Run filePath
        Sleep 1200

        javaHwnd := FindMapleJavaHwnd()
        if (javaHwnd != 0) {
            ControlSend "!y", , "ahk_id " javaHwnd
        }

        Sleep 500
        try WinActivate("ahk_id " origHwnd)
    }
}

ExitApp
