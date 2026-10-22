"""Shared ctypes declarations. Imported lazily only on Windows."""
from __future__ import annotations

import ctypes
from ctypes import wintypes as wt

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

ULONG_PTR = ctypes.c_size_t
LRESULT = ctypes.c_ssize_t

# Marker stored in dwExtraInfo of every event we inject ("PFRG").
INJECT_MAGIC = 0x50465247


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wt.DWORD), ("scanCode", wt.DWORD), ("flags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("flags", wt.DWORD), ("hwndActive", wt.HWND),
                ("hwndFocus", wt.HWND), ("hwndCapture", wt.HWND), ("hwndMenuOwner", wt.HWND),
                ("hwndMoveSize", wt.HWND), ("hwndCaret", wt.HWND), ("rcCaret", wt.RECT)]


WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wt.WPARAM, wt.LPARAM)
WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR),
                ("lpszClassName", wt.LPCWSTR)]


class SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wt.HWND),
                ("lpVerb", wt.LPCWSTR), ("lpFile", wt.LPCWSTR), ("lpParameters", wt.LPCWSTR),
                ("lpDirectory", wt.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wt.HINSTANCE),
                ("lpIDList", ctypes.c_void_p), ("lpClass", wt.LPCWSTR), ("hkeyClass", wt.HKEY),
                ("dwHotKey", wt.DWORD), ("hIconOrMonitor", wt.HANDLE), ("hProcess", wt.HANDLE)]


def _sig(fn, res, *args):
    fn.restype = res
    fn.argtypes = list(args)


_sig(user32.SendInput, wt.UINT, wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
_sig(user32.SetWindowsHookExW, wt.HHOOK, ctypes.c_int, HOOKPROC, wt.HINSTANCE, wt.DWORD)
_sig(user32.UnhookWindowsHookEx, wt.BOOL, wt.HHOOK)
_sig(user32.CallNextHookEx, LRESULT, wt.HHOOK, ctypes.c_int, wt.WPARAM, wt.LPARAM)
_sig(user32.GetMessageW, wt.BOOL, ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT)
_sig(user32.TranslateMessage, wt.BOOL, ctypes.POINTER(wt.MSG))
_sig(user32.DispatchMessageW, LRESULT, ctypes.POINTER(wt.MSG))
_sig(user32.PostThreadMessageW, wt.BOOL, wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM)
_sig(user32.PeekMessageW, wt.BOOL, ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT, wt.UINT)
_sig(user32.GetForegroundWindow, wt.HWND)
_sig(user32.GetWindowThreadProcessId, wt.DWORD, wt.HWND, ctypes.POINTER(wt.DWORD))
_sig(user32.GetKeyboardLayout, wt.HKL, wt.DWORD)
_sig(user32.ToUnicodeEx, ctypes.c_int, wt.UINT, wt.UINT, ctypes.POINTER(ctypes.c_ubyte),
     wt.LPWSTR, ctypes.c_int, wt.UINT, wt.HKL)
_sig(user32.GetKeyState, ctypes.c_short, ctypes.c_int)
_sig(user32.GetAsyncKeyState, ctypes.c_short, ctypes.c_int)
_sig(user32.VkKeyScanW, ctypes.c_short, wt.WCHAR)
_sig(user32.MapVirtualKeyW, wt.UINT, wt.UINT, wt.UINT)
_sig(user32.GetWindowTextW, ctypes.c_int, wt.HWND, wt.LPWSTR, ctypes.c_int)
_sig(user32.GetWindowTextLengthW, ctypes.c_int, wt.HWND)
_sig(user32.GetClassNameW, ctypes.c_int, wt.HWND, wt.LPWSTR, ctypes.c_int)
_sig(user32.IsWindowVisible, wt.BOOL, wt.HWND)
_sig(user32.EnumWindows, wt.BOOL, WNDENUMPROC, wt.LPARAM)
_sig(user32.GetGUIThreadInfo, wt.BOOL, wt.DWORD, ctypes.POINTER(GUITHREADINFO))
_sig(user32.ClientToScreen, wt.BOOL, wt.HWND, ctypes.POINTER(wt.POINT))
_sig(user32.GetCursorPos, wt.BOOL, ctypes.POINTER(wt.POINT))
_sig(user32.SetCursorPos, wt.BOOL, ctypes.c_int, ctypes.c_int)
_sig(user32.SendMessageTimeoutW, LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM, wt.UINT, wt.UINT,
     ctypes.POINTER(ULONG_PTR))
_sig(user32.GetSystemMetrics, ctypes.c_int, ctypes.c_int)

_sig(user32.OpenClipboard, wt.BOOL, wt.HWND)
_sig(user32.CloseClipboard, wt.BOOL)
_sig(user32.EmptyClipboard, wt.BOOL)
_sig(user32.GetClipboardData, wt.HANDLE, wt.UINT)
_sig(user32.SetClipboardData, wt.HANDLE, wt.UINT, wt.HANDLE)
_sig(user32.IsClipboardFormatAvailable, wt.BOOL, wt.UINT)
_sig(user32.EnumClipboardFormats, wt.UINT, wt.UINT)
_sig(user32.RegisterClipboardFormatW, wt.UINT, wt.LPCWSTR)
_sig(user32.GetClipboardSequenceNumber, wt.DWORD)
_sig(user32.AddClipboardFormatListener, wt.BOOL, wt.HWND)
_sig(user32.RemoveClipboardFormatListener, wt.BOOL, wt.HWND)
_sig(user32.GetClipboardOwner, wt.HWND)
_sig(user32.GetOpenClipboardWindow, wt.HWND)

_sig(user32.RegisterClassW, wt.ATOM, ctypes.POINTER(WNDCLASSW))
_sig(user32.CreateWindowExW, wt.HWND, wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int,
     ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID)
_sig(user32.DestroyWindow, wt.BOOL, wt.HWND)
_sig(user32.DefWindowProcW, LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
_sig(user32.PostMessageW, wt.BOOL, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
_sig(user32.PostQuitMessage, None, ctypes.c_int)

_sig(kernel32.GetModuleHandleW, wt.HMODULE, wt.LPCWSTR)
_sig(kernel32.GetCurrentThreadId, wt.DWORD)
_sig(kernel32.GlobalAlloc, wt.HGLOBAL, wt.UINT, ctypes.c_size_t)
_sig(kernel32.GlobalLock, wt.LPVOID, wt.HGLOBAL)
_sig(kernel32.GlobalUnlock, wt.BOOL, wt.HGLOBAL)
_sig(kernel32.GlobalSize, ctypes.c_size_t, wt.HGLOBAL)
_sig(kernel32.GlobalFree, wt.HGLOBAL, wt.HGLOBAL)
_sig(kernel32.OpenProcess, wt.HANDLE, wt.DWORD, wt.BOOL, wt.DWORD)
_sig(kernel32.CloseHandle, wt.BOOL, wt.HANDLE)
_sig(kernel32.QueryFullProcessImageNameW, wt.BOOL, wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD))
_sig(kernel32.WaitForSingleObject, wt.DWORD, wt.HANDLE, wt.DWORD)
_sig(kernel32.GetExitCodeProcess, wt.BOOL, wt.HANDLE, ctypes.POINTER(wt.DWORD))
_sig(shell32.ShellExecuteExW, wt.BOOL, ctypes.POINTER(SHELLEXECUTEINFOW))

WM_QUIT = 0x0012
WM_CLOSE = 0x0010
WM_DESTROY = 0x0002
WM_CLIPBOARDUPDATE = 0x031D
HWND_MESSAGE = wt.HWND(-3)
