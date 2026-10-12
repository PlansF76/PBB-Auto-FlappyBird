"""Automatic replay wrapper; uses the unchanged v2 detector and flight planner."""

import argparse
import ctypes
import csv
import json
import time
import flap_bot_v2 as bot
import cv2
import numpy as np
import mss

ROOT = bot.ROOT


def post_menu_click(user, x, y, roblox_hwnd=None):
    """Send a client-area click to the Roblox window beneath the button."""
    try:

        class Point(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        user.WindowFromPoint.argtypes = [Point]
        user.WindowFromPoint.restype = ctypes.c_void_p
        user.ScreenToClient.argtypes = [ctypes.c_void_p, ctypes.POINTER(Point)]
        user.PostMessageW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_size_t,
            ctypes.c_ssize_t,
        ]
        point = Point(int(x), int(y))
        hwnd = user.WindowFromPoint(point)
        if not hwnd:
            return False
        if roblox_hwnd:
            user.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            user.GetAncestor.restype = ctypes.c_void_p
            root = user.GetAncestor(hwnd, 2)  # GA_ROOT
            if root != roblox_hwnd:
                return False
        if not user.ScreenToClient(hwnd, ctypes.byref(point)):
            return False
        packed = (point.y << 16) | (point.x & 0xFFFF)
        user.PostMessageW(hwnd, 0x0200, 0, packed)  # WM_MOUSEMOVE
        user.PostMessageW(hwnd, 0x0201, 0x0001, packed)  # WM_LBUTTONDOWN
        user.PostMessageW(hwnd, 0x0202, 0, packed)  # WM_LBUTTONUP
        return True
    except (AttributeError, ctypes.ArgumentError):
        return False


def click_play(user, x, y, cancelled, roblox_hwnd=None, sleep=time.sleep, clock=time.perf_counter):
    """Let Roblox process cursor movement before pressing its menu button."""

    def wait(seconds):
        until = clock() + seconds
        while clock() < until:
            if cancelled():
                return False
            sleep(min(0.01, max(0.0, until - clock())))
        return not cancelled()

    if cancelled():
        return None
    # Ensure Roblox remains the active window. SetCursorPos moves the pointer
    # but does not activate a window, and Roblox can otherwise discard the UI
    # click when the launcher console was the last foreground window.
    try:
        hwnd = roblox_hwnd or user.GetForegroundWindow()
        if hwnd:
            user.BringWindowToTop(hwnd)
            user.SetForegroundWindow(hwnd)
    except AttributeError:
        pass
    # Ensure this is a fresh press, even after a round ended during input.
    user.mouse_event(0x0004, 0, 0, 0, 0)
    if not user.SetCursorPos(int(x), int(y)):
        return None
    # Jiggle with nonzero relative deltas so Roblox receives genuine mouse
    # movement. Zero-distance events and SetCursorPos alone can leave its 3-D
    # GUI hit test unaware that the pointer entered the Play prompt.
    for dx, dy in ((-4, 0), (8, 0), (-4, -3), (0, 6), (0, -3)):
        user.mouse_event(0x0001, int(dx), int(dy), 0, 0)
        if not wait(0.045):
            return None
    if not user.SetCursorPos(int(x), int(y)):
        return None
    user.mouse_event(0x0001, 1, 0, 0, 0)
    if not wait(0.10):
        return None
    pressed = clock()
    user.mouse_event(0x0002, 0, 0, 0, 0)
    try:
        completed = wait(0.15)
    finally:
        user.mouse_event(0x0004, 0, 0, 0, 0)
    # Roblox versions that ignore injected hardware-style events can still
    # receive these ordinary client-area messages from the active child window.
    post_menu_click(user, x, y, roblox_hwnd)
    return pressed if completed else None


class PlayDetector:
    def __init__(self):
        image = cv2.imread(str(ROOT / "play-label.png"))
        if image is None:
            raise RuntimeError("Missing play-label.png")
        self.template = (image.min(axis=2) > 220).astype(np.uint8) * 255

    def find(self, rgb, anchor=None):
        h, w = rgb.shape[:2]
        shrink = min(1.0, 1122 / w)
        a = cv2.resize(rgb, (round(w * shrink), round(h * shrink))) if shrink < 1 else rgb
        white = (a.min(axis=2) > 220).astype(np.uint8) * 255
        r, g, b = [a[:, :, i].astype(np.int16) for i in range(3)]
        green = (g > 100) & (g > r * 1.35) & (g > b * 1.15) & (r < 150)
        candidates = []
        for scale in np.linspace(0.55, 1.65, 23):
            tw, th = round(self.template.shape[1] * scale), round(self.template.shape[0] * scale)
            if tw >= a.shape[1] or th >= a.shape[0]:
                continue
            template = cv2.resize(self.template, (tw, th), interpolation=cv2.INTER_NEAREST)
            scores = cv2.matchTemplate(white, template, cv2.TM_CCOEFF_NORMED)
            for _ in range(3):
                _, score, _, (x, y) = cv2.minMaxLoc(scores)
                if score < 0.79:
                    break
                x0 = max(0, x - tw // 2)
                x1 = min(a.shape[1], x + tw + tw // 2)
                area = green[y : y + th, x0:x1]
                if area.size and area.mean() > 0.62:
                    candidates.append(((x + tw / 2) / shrink, (y + th / 2) / shrink))
                scores[max(0, y - th // 2) : y + th, max(0, x - tw // 2) : x + tw] = -1
        if not candidates:
            return None
        if anchor is None:
            # Several cabinets can expose Play prompts. The user's flappy-bird
            # prompt is the middle one, so select the candidate nearest the
            # horizontal center of the screen.
            return min(candidates, key=lambda p: abs(p[0] - w * 0.5))
        return min(
            candidates, key=lambda p: ((p[0] - anchor[0]) / w) ** 2 + ((p[1] - anchor[1]) / h) ** 2
        )


class ReplayGate:
    def __init__(self):
        self.previous = None
        self.last_click = -100.0

    def ready(self, button, now):
        old = self.previous
        self.previous = button
        return (
            button is not None
            and old is not None
            and now - self.last_click >= 0.75
            and np.hypot(button[0] - old[0], button[1] - old[1]) <= 20
        )

    def clicked(self, now):
        self.last_click = now
        self.previous = None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cooldown", type=float, default=0.23)
    parser.add_argument("--latency", type=float, default=0.035)
    parser.add_argument("--inspect", help="Check Play recognition without clicking")
    args = parser.parse_args()
    detector = PlayDetector()
    if args.inspect:
        rgb = np.array(bot.Image.open(args.inspect).convert("RGB"))
        point = detector.find(rgb)
        print("Play button:", point)
        if point:
            cv2.circle(rgb, tuple(map(int, point)), 18, (255, 0, 0), 3)
        bot.Image.fromarray(rgb).save(ROOT / "replay-preview.png")
        return
    user = ctypes.windll.user32
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        user.SetProcessDPIAware()
    user.GetForegroundWindow.restype = ctypes.c_void_p
    user.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    user.EnumWindows.argtypes = [ctypes.c_void_p, ctypes.c_ssize_t]
    user.EnumWindows.restype = ctypes.c_bool
    user.IsWindowVisible.argtypes = [ctypes.c_void_p]
    user.IsWindowVisible.restype = ctypes.c_bool

    def roblox_window():
        found = []
        CALLBACK = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_ssize_t)

        def visit(hwnd, _):
            if not user.IsWindowVisible(hwnd):
                return True
            title = ctypes.create_unicode_buffer(512)
            user.GetWindowTextW(hwnd, title, 512)
            if "roblox" in title.value.lower():
                found.append(hwnd)
                return False
            return True

        user.EnumWindows(CALLBACK(visit), 0)
        return found[0] if found else None

    def focused():
        title = ctypes.create_unicode_buffer(512)
        user.GetWindowTextW(user.GetForegroundWindow(), title, 512)
        return "roblox" in title.value.lower()

    def down(key):
        return bool(user.GetAsyncKeyState(key) & 0x8000)

    def cancel_replay():
        nonlocal active, previous_f8
        # F8 may still be physically held while the start toggle is being
        # processed. Do not cancel a click because of that key; F9/focus loss
        # remain immediate aborts.
        if down(0x78) or not focused():
            active = False
            return True
        return False

    def click(x, y, hold=0.018):
        if not focused() or down(0x78) or down(0x77):
            return None
        user.SetCursorPos(int(x), int(y))
        pressed = time.perf_counter()
        user.mouse_event(0x0002, 0, 0, 0, 0)
        try:
            time.sleep(hold)
        finally:
            user.mouse_event(0x0004, 0, 0, 0, 0)
        return pressed

    active = False
    waiting = True
    previous_f8 = False
    box = None
    stable_box = None
    stable_count = 0
    restarted = False
    missing_since = None
    frozen_since = None
    last_motion = None
    blocked_scene = None
    acquisition_tracker = bot.Tracker()
    acquisition_since = None
    acquired_at = -100.0
    next_bounds_check = 0.0
    round_number = 0
    play_attempt = 0
    gate = ReplayGate()
    tracker = bot.Tracker()
    planner = bot.Planner(args.cooldown, args.latency)
    roblox_hwnd = roblox_window()
    ROOT.joinpath("logs").mkdir(exist_ok=True)
    log_path = ROOT / "logs" / time.strftime("auto-%Y%m%d-%H%M%S.csv")
    print(
        "AUTO REPLAY: F8 start/pause; F9 exit. Focus Roblox on the arcade or Play screen.",
        flush=True,
    )
    print("Flight controls are unchanged. Focus loss pauses everything.", flush=True)
    with mss.MSS() as capture, log_path.open("w", newline="") as log:
        writer = csv.writer(log)
        writer.writerow(["time", "event", "y", "velocity", "scroll", "flap", "loop_ms", "pipes"])
        log.flush()
        try:
            while not down(0x78):
                started = time.perf_counter()
                key = down(0x77)
                if key and not previous_f8:
                    active = not active
                    waiting = True
                    stable_box = None
                    stable_count = 0
                    restarted = False
                    blocked_scene = None
                    acquisition_tracker = bot.Tracker()
                    acquisition_since = None
                    play_attempt = 0
                    gate = ReplayGate()
                    roblox_hwnd = roblox_window()
                    if active and (not focused() or not roblox_hwnd):
                        active = False
                    print(
                        "ENABLED: looking for arcade or Play." if active else "PAUSED", flush=True
                    )
                previous_f8 = key
                if not active:
                    time.sleep(0.02)
                    continue
                if not focused():
                    active = False
                    print("PAUSED: Roblox lost focus.", flush=True)
                    continue
                if waiting:
                    monitor = capture.monitors[1]
                    full = np.asarray(capture.grab(monitor))[:, :, :3][:, :, ::-1]
                    # Prefer the playfield fast path so template matching cannot delay
                    # taking control of a newly started round.
                    bounds = None
                    state = None
                    try:
                        bounds = bot.board_bounds(full)
                        x0, y0, x1, y1 = bounds
                        state = bot.detect(full[y0:y1, x0:x1])
                    except ValueError:
                        pass
                    # During the camera transition, poll the board quickly instead
                    # of spending hundreds of milliseconds matching menu text.
                    button = (
                        detector.find(full, None)
                        if state is None and time.perf_counter() - gate.last_click > 1.8
                        else None
                    )
                    now = time.perf_counter()
                    if button is not None:
                        stable_box = None
                        stable_count = 0
                        if gate.ready(button, now):
                            # Roblox's visible label can be a few pixels below
                            # the clickable center at different UI scales. Try
                            # the center and two safely interior offsets, one
                            # per verified retry while the button remains.
                            offsets = ((0, 10), (-24, 12), (24, 12))
                            dx, dy = offsets[play_attempt % len(offsets)]
                            target = (
                                monitor["left"] + button[0] + dx,
                                monitor["top"] + button[1] + dy,
                            )
                            pressed = click_play(user, *target, cancel_replay, roblox_hwnd)
                            if pressed is not None:
                                gate.clicked(time.perf_counter())
                                restarted = True
                                blocked_scene = None
                                acquisition_tracker = bot.Tracker()
                                acquisition_since = None
                                play_attempt += 1
                                writer.writerow([now, "play", target[0], target[1], play_attempt])
                                log.flush()
                                message = (
                                    f"REPLAY: sent Play press at {target}; "
                                    "waiting for the new round."
                                )
                                print(message, flush=True)
                        time.sleep(0.02)
                        continue
                    gate.ready(None, now)
                    if state is None:
                        stable_box = None
                        stable_count = 0
                        acquisition_since = None
                        time.sleep(0.02)
                        continue
                    scene = (bounds, state["bird"], str(state["pipes"]))
                    if scene == blocked_scene:
                        time.sleep(0.05)
                        continue
                    if not 1.15 < (x1 - x0) / max(1, y1 - y0) < 1.50:
                        stable_box = None
                        stable_count = 0
                        acquisition_since = None
                        time.sleep(0.02)
                        continue
                    acquisition_tracker.update(state, now)
                    if (
                        stable_box is not None
                        and max(abs(a - b) for a, b in zip(bounds, stable_box)) <= 4
                    ):
                        stable_count += 1
                    else:
                        stable_count = 1
                        acquisition_since = now
                    stable_box = bounds
                    if (
                        stable_count < 3
                        or acquisition_since is None
                        or now - acquisition_since < 0.12
                    ):
                        time.sleep(0.015)
                        continue
                    box = dict(
                        left=x0 + monitor["left"],
                        top=y0 + monitor["top"],
                        width=x1 - x0,
                        height=y1 - y0,
                    )
                    tracker = acquisition_tracker
                    missing_since = None
                    frozen_since = None
                    last_motion = None
                    waiting = False
                    stable_count = 0
                    # Only send a start tap if the new bird is stationary. An
                    # unconditional flap used to disrupt already-running rounds.
                    stationary = len(tracker.samples) <= 1
                    if restarted and stationary and not state["pipes"]:
                        pressed = click(
                            box["left"] + box["width"] * 0.53, box["top"] + box["height"] * 0.5
                        )
                        if pressed is not None:
                            tracker.clicked(pressed, state["bird"][1], delay=0.020)
                    restarted = False
                    play_attempt = 0
                    acquired_at = now
                    next_bounds_check = now + 0.15
                    round_number += 1
                    bot.Image.fromarray(full).save(
                        ROOT / "logs" / f"acquired-{round_number}.jpg", quality=75
                    )
                    writer.writerow(
                        [
                            now,
                            "acquired",
                            state["bird"][1],
                            tracker.velocity,
                            "",
                            "",
                            "",
                            json.dumps(bounds),
                        ]
                    )
                    log.flush()
                    print("RUNNING: arcade acquired.", flush=True)
                    continue
                if started < acquired_at + 5 and started >= next_bounds_check:
                    monitor = capture.monitors[1]
                    full = np.asarray(capture.grab(monitor))[:, :, :3][:, :, ::-1]
                    next_bounds_check = started + 0.20
                    try:
                        bounds = bot.board_bounds(full)
                        x0, y0, x1, y1 = bounds
                        old_bounds = (
                            box["left"] - monitor["left"],
                            box["top"] - monitor["top"],
                            box["left"] - monitor["left"] + box["width"],
                            box["top"] - monitor["top"] + box["height"],
                        )
                        if (
                            max(abs(a - b) for a, b in zip(bounds, old_bounds)) > 4
                            and 1.15 < (x1 - x0) / max(1, y1 - y0) < 1.50
                        ):
                            box = dict(
                                left=x0 + monitor["left"],
                                top=y0 + monitor["top"],
                                width=x1 - x0,
                                height=y1 - y0,
                            )
                            tracker = bot.Tracker()
                            writer.writerow(
                                [started, "recalibrated", "", "", "", "", "", json.dumps(bounds)]
                            )
                            log.flush()
                    except ValueError:
                        pass
                frame = np.asarray(capture.grab(box))[:, :, :3][:, :, ::-1]
                captured = time.perf_counter()
                cyan = (frame[:, :, 0] < 110) & (frame[:, :, 1] > 180) & (frame[:, :, 2] > 180)
                state = bot.detect(frame) if cyan.mean() >= 0.35 else None
                if state is None:
                    if missing_since is None:
                        missing_since = captured
                    if captured - missing_since > 0.20:
                        waiting = True
                        stable_box = None
                        stable_count = 0
                        acquisition_since = None
                        acquisition_tracker = bot.Tracker()
                        bot.Image.fromarray(frame).save(ROOT / "logs" / "last-loss.jpg", quality=75)
                        writer.writerow([captured, "lost"])
                        log.flush()
                        print("REPLAY: waiting for Play or the arcade.", flush=True)
                    time.sleep(0.006)
                    continue
                missing_since = None
                motion = (state["bird"], str(state["pipes"]))
                if motion == last_motion:
                    if frozen_since is None:
                        frozen_since = captured
                    if captured - frozen_since > 0.5:
                        waiting = True
                        stable_box = None
                        stable_count = 0
                        monitor = capture.monitors[1]
                        bounds = (
                            box["left"] - monitor["left"],
                            box["top"] - monitor["top"],
                            box["left"] - monitor["left"] + box["width"],
                            box["top"] - monitor["top"] + box["height"],
                        )
                        blocked_scene = (bounds, state["bird"], str(state["pipes"]))
                        acquisition_since = None
                        acquisition_tracker = bot.Tracker()
                        bot.Image.fromarray(frame).save(
                            ROOT / "logs" / "last-frozen.jpg", quality=75
                        )
                        print("REPLAY: scene stopped; checking for Play.", flush=True)
                        continue
                else:
                    frozen_since = None
                    last_motion = motion
                velocity = tracker.update(state, captured)
                do_click = planner.decide(
                    state, velocity, tracker.speed, captured - tracker.last_click
                )
                clicked = False
                if do_click:
                    pressed = click(
                        box["left"] + box["width"] * 0.53, box["top"] + box["height"] * 0.5
                    )
                    if pressed is not None:
                        tracker.clicked(pressed, state["bird"][1], delay=0.020)
                        clicked = True
                writer.writerow(
                    [
                        captured,
                        "flight",
                        state["bird"][1],
                        velocity,
                        tracker.speed,
                        int(clicked),
                        round((time.perf_counter() - started) * 1000, 2),
                        json.dumps(state["pipes"]),
                    ]
                )
                if clicked:
                    log.flush()
                time.sleep(max(0, 1 / 60 - (time.perf_counter() - started)))
        except KeyboardInterrupt:
            pass
        finally:
            user.mouse_event(0x0004, 0, 0, 0, 0)
            print("Stopped.", flush=True)


if __name__ == "__main__":
    main()
