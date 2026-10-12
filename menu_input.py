"""Checked Windows input for menu clicks, including a real absolute move event."""

import ctypes


class MouseInput(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_int32),
        ("dy", ctypes.c_int32),
        ("mouseData", ctypes.c_uint32),
        ("dwFlags", ctypes.c_uint32),
        ("time", ctypes.c_uint32),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class InputUnion(ctypes.Union):
    _fields_ = [("mi", MouseInput)]


class Input(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint32), ("data", InputUnion)]


class MenuInput:
    def __init__(self):
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.user.GetForegroundWindow.restype = ctypes.c_void_p
        self.user.BringWindowToTop.argtypes = [ctypes.c_void_p]
        self.user.SetForegroundWindow.argtypes = [ctypes.c_void_p]
        self.user.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(Input), ctypes.c_int]
        self.user.SendInput.restype = ctypes.c_uint

    def send(self, flags, x=0, y=0):
        packet = Input(0, InputUnion(mi=MouseInput(x, y, 0, flags, 0, 0)))
        sent = self.user.SendInput(1, ctypes.byref(packet), ctypes.sizeof(Input))
        if sent != 1:
            raise OSError(ctypes.get_last_error(), "Windows did not accept the menu input event")
        return sent

    def SetCursorPos(self, x, y):
        left = self.user.GetSystemMetrics(76)
        top = self.user.GetSystemMetrics(77)
        width = self.user.GetSystemMetrics(78)
        height = self.user.GetSystemMetrics(79)
        return self.send(
            0xC001,
            round((x - left) * 65535 / max(1, width - 1)),
            round((y - top) * 65535 / max(1, height - 1)),
        )

    def GetForegroundWindow(self):
        return self.user.GetForegroundWindow()

    def BringWindowToTop(self, hwnd):
        return self.user.BringWindowToTop(hwnd)

    def SetForegroundWindow(self, hwnd):
        return self.user.SetForegroundWindow(hwnd)

    def mouse_event(self, flags, *unused):
        return self.send(flags)
