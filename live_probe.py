"""One bounded restart probe. Stops on focus loss or F9. No retry loop."""

import ctypes, time, json, sys
import auto_replay as a
from menu_input import MenuInput
from ctypes import wintypes


class TracedMenuInput(MenuInput):
    def SetCursorPos(self, x, y):
        result = super().SetCursorPos(x, y)
        p = wintypes.POINT()
        self.user.GetPhysicalCursorPos(ctypes.byref(p))
        print(
            "Target",
            x,
            y,
            "physical cursor",
            p.x,
            p.y,
            "screen",
            self.user.GetSystemMetrics(0),
            flush=True,
        )
        return result

    def mouse_event(self, flags, *unused):
        result = super().mouse_event(flags, *unused)
        print(
            "Input",
            flags,
            "accepted",
            result,
            "left held",
            bool(self.user.GetAsyncKeyState(1) & 0x8000),
            flush=True,
        )
        return result


u = ctypes.windll.user32
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass
u.GetForegroundWindow.restype = ctypes.c_void_p
u.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]


def cancelled():
    title = ctypes.create_unicode_buffer(512)
    u.GetWindowTextW(u.GetForegroundWindow(), title, 512)
    return "roblox" not in title.value.lower() or bool(u.GetAsyncKeyState(0x78) & 0x8000)


assert not cancelled(), "Focus Roblox first"
out = a.ROOT / "logs" / "live-probe"
out.mkdir(exist_ok=True)
tracker = a.bot.Tracker()
planner = a.bot.Planner()
rows = []
last_save = -1.0
start = time.perf_counter()
with a.mss.MSS() as s:
    monitor = s.monitors[1]
    full = a.np.asarray(s.grab(monitor))[:, :, :3][:, :, ::-1]
    p = a.PlayDetector().find(full)
    print("Button", p, flush=True)
    if "--manual" in sys.argv:
        print("Waiting up to 75 seconds for one manual left-click in Roblox.", flush=True)
        deadline = time.perf_counter() + 75
        previous = bool(u.GetAsyncKeyState(1) & 0x8000)
        while time.perf_counter() < deadline:
            held = bool(u.GetAsyncKeyState(1) & 0x8000)
            if held and not previous and not cancelled():
                point = wintypes.POINT()
                u.GetPhysicalCursorPos(ctypes.byref(point))
                print("MANUAL CLICK", point.x, point.y, flush=True)
                full = a.np.asarray(s.grab(monitor))[:, :, :3][:, :, ::-1]
                a.bot.Image.fromarray(full).save(out / "manual-click.jpg", quality=85)
                break
            previous = held
            time.sleep(0.005)
        else:
            raise SystemExit("No manual click observed")
        while u.GetAsyncKeyState(1) & 0x8000:
            time.sleep(0.005)
    else:
        assert p is not None, "No Play button"
        sent = a.click_play(
            TracedMenuInput(), monitor["left"] + p[0], monitor["top"] + p[1], cancelled
        )
        print("Press timestamp", sent, flush=True)
    start = time.perf_counter()
    acquired = False
    while time.perf_counter() - start < 18 and not cancelled():
        t = time.perf_counter()
        elapsed = t - start
        full = a.np.asarray(s.grab(monitor))[:, :, :3][:, :, ::-1]
        if elapsed - last_save > (0.30 if elapsed < 4 else 1.0):
            a.bot.Image.fromarray(full).save(out / f"{elapsed:05.2f}.jpg", quality=80)
            last_save = elapsed
        try:
            bounds = a.bot.board_bounds(full)
            x0, y0, x1, y1 = bounds
            state = a.bot.detect(full[y0:y1, x0:x1])
        except ValueError:
            state = None
            bounds = None
        if state:
            if not acquired:
                print("Acquired", elapsed, bounds, state, flush=True)
                acquired = True
            v = tracker.update(state, t)
            act = planner.decide(state, v, tracker.speed, t - tracker.last_click)
            rows.append(dict(t=elapsed, bounds=bounds, state=state, v=v, flap=act))
            if act and not cancelled():
                u.SetCursorPos(
                    int(monitor["left"] + (x0 + x1) / 2), int(monitor["top"] + (y0 + y1) / 2)
                )
                pressed = time.perf_counter()
                u.mouse_event(2, 0, 0, 0, 0)
                try:
                    time.sleep(0.018)
                finally:
                    u.mouse_event(4, 0, 0, 0, 0)
                tracker.clicked(pressed, state["bird"][1], delay=0.020)
        elif elapsed > 6:
            break
        time.sleep(0.006)
    u.mouse_event(4, 0, 0, 0, 0)
(out / "data.json").write_text(json.dumps(rows), encoding="utf-8")
print(
    "Finished",
    len(rows),
    "flight frames;",
    sum(bool(r["state"]["pipes"]) for r in rows),
    "with obstacles",
    flush=True,
)
