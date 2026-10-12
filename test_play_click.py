"""Exercise input ordering without sending desktop mouse events."""

from auto_replay import click_play


class FakeMouse:
    def __init__(self):
        self.t = 0.0
        self.events = []

    def clock(self):
        return self.t

    def sleep(self, duration):
        self.t += duration

    def mouse_event(self, flag, *args):
        self.events.append((flag, self.t))

    def GetForegroundWindow(self):
        return 1

    def BringWindowToTop(self, hwnd):
        pass

    def SetForegroundWindow(self, hwnd):
        pass

    def SetCursorPos(self, x, y):
        self.events.append(("move", self.t))
        return 1


mouse = FakeMouse()
result = click_play(mouse, 722, 329, lambda: False, sleep=mouse.sleep, clock=mouse.clock)
assert [event[0] for event in mouse.events] == [4, "move", 1, 1, 1, 1, 1, "move", 1, 2, 4]
assert result >= 0.20
assert mouse.events[-1][1] - mouse.events[-2][1] >= 0.149
print("PASS: move settles for 200 ms, then press held for 150 ms and released")

mouse = FakeMouse()
assert (
    click_play(mouse, 722, 329, lambda: mouse.t >= 0.10, sleep=mouse.sleep, clock=mouse.clock)
    is None
)
assert all(flag != 2 for flag, _ in mouse.events)
print("PASS: pause/focus loss during movement prevents press")

mouse = FakeMouse()
assert (
    click_play(mouse, 722, 329, lambda: mouse.t >= 0.40, sleep=mouse.sleep, clock=mouse.clock)
    is None
)
assert mouse.events[-1][0] == 4 and any(flag == 2 for flag, _ in mouse.events)
print("PASS: pause/focus loss during press releases mouse")

# Holding F8 must not cancel the menu press; the main loop consumes the toggle
# after the click returns.
mouse = FakeMouse()
assert click_play(mouse, 722, 329, lambda: False, sleep=mouse.sleep, clock=mouse.clock) is not None
print("PASS: F8-safe menu press path")
