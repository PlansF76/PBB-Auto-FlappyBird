"""Screen-based arcade helper. F8 toggle, F9 exit; --inspect never clicks."""

import argparse
from collections import deque
import ctypes
import csv
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
if str(ROOT / "vendor") not in sys.path:
    sys.path.insert(0, str(ROOT / "vendor"))
import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

# Measured from the recording, in playfield heights/widths per second.
GRAVITY, FLAP_SPEED, SCROLL_SPEED = 6.78, 1.48, 0.49
RADIUS_Y, RADIUS_X = 0.048, 0.035


def runs(mask):
    edges = np.diff(np.r_[False, mask, False].astype(np.int8))
    return list(zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)))


def rgb_array(image):
    return np.asarray(image.convert("RGB") if isinstance(image, Image.Image) else image)


def board_bounds(image):
    a = rgb_array(image)
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    cyan = ((r < 110) & (g > 180) & (b > 180)).astype(np.uint8)
    _, _, stats, _ = cv2.connectedComponentsWithStats(cyan, connectivity=4)
    candidates = [s for s in stats[1:] if s[2] > a.shape[1] * 0.25 and s[3] > a.shape[0] * 0.35]
    if not candidates:
        raise ValueError("No cyan playfield found. Show the arcade gameplay first.")
    x, y, w, h, _ = max(candidates, key=lambda s: s[4])
    return int(x), int(y), int(x + w), int(y + h)


def detect(image):
    """Normalized bird and all visible gaps, including clipped obstacles."""
    a = rgb_array(image)
    h, w = a.shape[:2]
    if h > 512:
        a = cv2.resize(a, (round(w * 512 / h), 512), interpolation=cv2.INTER_NEAREST)
    h, w = a.shape[:2]
    lane_left, lane_right = int(w * 0.27), int(w * 0.40)
    lane = a[:, lane_left:lane_right].astype(np.int16)
    r, g, b = lane[:, :, 0], lane[:, :, 1], lane[:, :, 2]
    tan = (r > 175) & (g > 110) & (g < 235) & (b < 190) & (r > g + 12) & (g > b + 15)
    tan = cv2.morphologyEx(tan.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(tan, connectivity=8)
    candidates = []
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if h * 0.025 < bh < h * 0.13 and w * 0.012 < bw < w * 0.10 and area > h * w * 0.00035:
            candidates.append((int(area), i))
    if not candidates:
        return None
    _, idx = max(candidates)
    tx, ty, tw, th, _ = stats[idx]
    foreground = ~((r < 110) & (g > 180) & (b > 180))
    _, fg_labels, fg_stats, _ = cv2.connectedComponentsWithStats(
        foreground.astype(np.uint8), connectivity=8
    )
    seeds = np.argwhere(labels == idx)
    sy, sx = seeds[len(seeds) // 2]
    fx, fy, fw, fh, _ = fg_stats[fg_labels[sy, sx]]
    if h * 0.035 < fh < h * 0.14 and w * 0.025 < fw < w * 0.11:
        bx, by = lane_left + fx + fw / 2, fy + fh / 2
    else:
        bx, by = lane_left + tx + tw / 2 + 1, ty + th / 2 + 2
    r, g, b = [a[:, :, i].astype(np.int16) for i in range(3)]
    green = (g > 115) & (g > r * 1.15) & (g > b * 1.08)
    # Feathers are green too. Only broad leaf components belong to obstacles.
    n, leaf_labels, leaf_stats, _ = cv2.connectedComponentsWithStats(
        green.astype(np.uint8), connectivity=8
    )
    valid = np.zeros(n, dtype=bool)
    for i in range(1, n):
        _, _, lw, lh, area = leaf_stats[i]
        valid[i] = lw > w * 0.055 and area > h * w * 0.0006
    green = valid[leaf_labels]
    cols = (green.sum(axis=0) > h * 0.022).astype(np.uint8)[None, :]
    cols = cv2.morphologyEx(cols, cv2.MORPH_CLOSE, np.ones((1, max(3, int(w * 0.018))), np.uint8))[
        0
    ]
    pipes = []
    for left, right in runs(cols > 0):
        if right - left < w * 0.065:
            continue
        occupied = green[:, left:right].sum(axis=1) > max(2, (right - left) * 0.06)
        occupied = (
            cv2.morphologyEx(
                occupied.astype(np.uint8)[:, None], cv2.MORPH_CLOSE, np.ones((5, 1), np.uint8)
            )[:, 0]
            > 0
        )
        bands = [(lo, hi) for lo, hi in runs(occupied) if hi - lo > h * 0.01]
        gaps = [
            (bands[j][1], bands[j + 1][0])
            for j in range(len(bands) - 1)
            if bands[j + 1][0] - bands[j][1] > h * 0.20
        ]
        if gaps:
            top, bottom = max(gaps, key=lambda p: p[1] - p[0])
        elif len(bands) == 1:
            lo, hi = bands[0]
            top, bottom = (hi, h) if (lo + hi) / 2 < h / 2 else (0, lo)
        else:
            continue
        if 0.24 < (bottom - top) / h < 0.85:
            pipes.append(
                dict(
                    left=float(left / w),
                    right=float(right / w),
                    top=float(top / h),
                    bottom=float(bottom / h),
                )
            )
    return dict(bird=(float(bx / w), float(by / h)), pipes=pipes)


class Tracker:
    """Ballistic fit; duplicate captures and flap discontinuities handled separately."""

    def __init__(self):
        self.samples = deque(maxlen=12)
        self.last_click = -100.0
        self.speed = SCROLL_SPEED
        self.previous_pipes = []
        self.pipe_time = None
        self.velocity = 0.0
        self.effective_flap = -100.0
        self.before_flap_velocity = 0.0

    def clicked(self, t, y, delay=0.0):
        self.before_flap_velocity = self.velocity
        self.last_click = t
        self.effective_flap = t + delay
        self.samples.clear()

    def update(self, state, t):
        y = state["bird"][1]
        if self.pipe_time is not None and 0.01 < t - self.pipe_time < 0.15:
            shifts = []
            for p in state["pipes"]:
                matches = [
                    q
                    for q in self.previous_pipes
                    if abs(q["top"] - p["top"]) < 0.015 and abs(q["bottom"] - p["bottom"]) < 0.015
                ]
                if matches:
                    q = min(matches, key=lambda q: abs(q["right"] - p["right"]))
                    s = (q["right"] - p["right"]) / (t - self.pipe_time)
                    if 0.2 < s < 0.95:
                        shifts.append(s)
            if shifts:
                self.speed = 0.9 * self.speed + 0.1 * float(np.median(shifts))
        if self.previous_pipes != state["pipes"] or self.pipe_time is None:
            self.previous_pipes = state["pipes"]
            self.pipe_time = t
        since = t - self.effective_flap
        if since < 0:
            self.velocity = self.before_flap_velocity + GRAVITY * (t - self.last_click)
            return self.velocity
        if since < 0.055:
            self.velocity = -FLAP_SPEED + GRAVITY * since
            return self.velocity
        if not self.samples or abs(y - self.samples[-1][1]) > 0.0008:
            self.samples.append((t, y))
        while len(self.samples) > 2 and t - self.samples[0][0] > 0.105:
            self.samples.popleft()
        if len(self.samples) >= 2:
            points = np.array(self.samples)
            u = points[:, 0] - t
            z = points[:, 1] - 0.5 * GRAVITY * u * u
            denom = np.sum((u - u.mean()) ** 2)
            if denom > 1e-6:
                v = float(np.sum((u - u.mean()) * (z - z.mean())) / denom)
                self.velocity = float(np.clip(v, -2.3, 3.5))
        elif since < 0.35:
            self.velocity = -FLAP_SPEED + GRAVITY * since
        return self.velocity


class Planner:
    """Predict flap/wait trajectories through moving obstacles over 1.1 seconds."""

    def __init__(self, cooldown=0.23, latency=0.035):
        self.cooldown = cooldown
        self.latency = latency
        self.last_cost = 0.0

    def decide(self, state, velocity, speed, since_click):
        bx, y = state["bird"]
        dt = 1 / 30
        y += velocity * self.latency + 0.5 * GRAVITY * self.latency**2
        velocity += GRAVITY * self.latency
        ys = np.array([y])
        vs = np.array([velocity])
        ages = np.array([since_click + self.latency])
        costs = np.zeros(1)
        first = np.zeros(1, dtype=np.int8)
        for step in range(33):
            t = self.latency + (step + 1) * dt
            can = np.flatnonzero(ages >= self.cooldown)
            count = len(ys)
            ys = np.r_[ys, ys[can]]
            vs = np.r_[vs, np.full(len(can), -FLAP_SPEED)]
            ages = np.r_[ages, np.zeros(len(can))]
            costs = np.r_[costs, costs[can] + 0.00025]
            first = np.r_[first, first[can]]
            if step == 0:
                first[count:] = 1
            ys += vs * dt + 0.5 * GRAVITY * dt * dt
            vs += GRAVITY * dt
            ages += dt
            low, high = RADIUS_Y + 0.014, 1 - RADIUS_Y - 0.014
            upcoming = []
            for p in state["pipes"]:
                left = p["left"] - speed * t
                right = p["right"] - speed * t
                if right >= bx - RADIUS_X:
                    upcoming.append(p)
                if left <= bx + RADIUS_X + 0.008 and right >= bx - RADIUS_X - 0.008:
                    low = max(low, p["top"] + RADIUS_Y + 0.035)
                    high = min(high, p["bottom"] - RADIUS_Y - 0.035)
            if upcoming:
                p = min(upcoming, key=lambda p: p["left"])
                target = (p["top"] + p["bottom"]) / 2
            else:
                target = 0.5
            violation = np.maximum(low - ys, 0) + np.maximum(ys - high, 0)
            costs += 1500 * violation**2 + 20 * (violation > 0) + dt * (ys - target) ** 2
            order = np.argsort(costs)
            keys = np.c_[
                np.round(ys[order] / 0.012),
                np.round(vs[order] / 0.16),
                np.minimum(ages[order], self.cooldown) // 0.055,
                first[order],
            ]
            _, unique = np.unique(keys, axis=0, return_index=True)
            keep = order[np.sort(unique)[:48]]
            ys, vs, ages, costs, first = ys[keep], vs[keep], ages[keep], costs[keep], first[keep]
        best = int(np.argmin(costs))
        self.last_cost = float(costs[best])
        return bool(first[best])


def inspect(path):
    image = Image.open(path).convert("RGB")
    box = board_bounds(image)
    crop = image.crop(box)
    state = detect(crop)
    if state is None:
        raise ValueError("Bird not detected")
    a = np.array(crop)
    h, w = a.shape[:2]
    for p in state["pipes"]:
        cv2.rectangle(
            a,
            (int(p["left"] * w), int(p["top"] * h)),
            (int(p["right"] * w), int(p["bottom"] * h)),
            (255, 0, 0),
            2,
        )
    x, y = state["bird"]
    cv2.circle(a, (int(x * w), int(y * h)), int(RADIUS_Y * h), (255, 0, 0), 2)
    Image.fromarray(a).save(ROOT / "detection-preview.png")
    print(json.dumps(dict(playfield=box, **state), indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inspect")
    parser.add_argument("--cooldown", type=float, default=0.23)
    parser.add_argument(
        "--latency", type=float, default=0.035, help="Input/display delay in seconds"
    )
    args = parser.parse_args()
    if args.inspect:
        return inspect(args.inspect)
    import mss

    user = ctypes.windll.user32
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        user.SetProcessDPIAware()
    user.GetForegroundWindow.restype = ctypes.c_void_p
    user.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]

    def focused():
        title = ctypes.create_unicode_buffer(512)
        user.GetWindowTextW(user.GetForegroundWindow(), title, 512)
        return "roblox" in title.value.lower()

    def down(k):
        return bool(user.GetAsyncKeyState(k) & 0x8000)

    active = False
    previous_f8 = False
    box = None
    missing_since = None
    frozen_since = None
    last_motion = None
    tracker = Tracker()
    planner = Planner(args.cooldown, args.latency)
    ROOT.joinpath("logs").mkdir(exist_ok=True)
    log_path = ROOT / "logs" / time.strftime("run-%Y%m%d-%H%M%S.csv")
    print("V2: F8 start/pause; F9 exit. Start the arcade manually, then F8.", flush=True)
    print(
        "Keep camera/window still. Pauses on lost focus, missing bird or frozen game.", flush=True
    )
    print("Diagnostics:", log_path, flush=True)
    with mss.mss() as capture, log_path.open("w", newline="") as log:
        writer = csv.writer(log)
        writer.writerow(
            ["time", "y", "velocity", "scroll", "flap", "capture_ms", "loop_ms", "cost", "pipes"]
        )
        try:
            while not down(0x78):
                loop_start = time.perf_counter()
                key = down(0x77)
                if key and not previous_f8:
                    active = not active
                    tracker = Tracker()
                    missing_since = None
                    frozen_since = None
                    last_motion = None
                    if active:
                        if not focused():
                            print("Focus Roblox before F8.", flush=True)
                            active = False
                        else:
                            full = np.asarray(capture.grab(capture.monitors[1]))[:, :, :3][
                                :, :, ::-1
                            ]
                            try:
                                x0, y0, x1, y1 = board_bounds(full)
                                monitor = capture.monitors[1]
                                box = dict(
                                    left=x0 + monitor["left"],
                                    top=y0 + monitor["top"],
                                    width=x1 - x0,
                                    height=y1 - y0,
                                )
                            except ValueError as error:
                                print(error, flush=True)
                                active = False
                    print("RUNNING" if active else "PAUSED", flush=True)
                    log.flush()
                previous_f8 = key
                if not active:
                    time.sleep(0.02)
                    continue
                if not focused():
                    active = False
                    print("PAUSED: Roblox lost focus.", flush=True)
                    continue
                frame = np.asarray(capture.grab(box))[:, :, :3][:, :, ::-1]
                captured = time.perf_counter()
                state = detect(frame)
                if state is None:
                    if missing_since is None:
                        missing_since = captured
                    if captured - missing_since > 0.20:
                        active = False
                        Image.fromarray(frame).save(ROOT / "logs" / "last-pause.png")
                        print("PAUSED: bird lost. Restart manually, then F8.", flush=True)
                    time.sleep(0.006)
                    continue
                missing_since = None
                motion = (state["bird"], str(state["pipes"]))
                if motion == last_motion:
                    if frozen_since is None:
                        frozen_since = captured
                    if captured - frozen_since > 0.5:
                        active = False
                        print("PAUSED: game image stopped moving.", flush=True)
                        continue
                else:
                    frozen_since = None
                    last_motion = motion
                velocity = tracker.update(state, captured)
                do_click = planner.decide(
                    state, velocity, tracker.speed, captured - tracker.last_click
                )
                clicked = False
                if do_click and focused() and not down(0x78):
                    user.SetCursorPos(
                        int(box["left"] + box["width"] * 0.53),
                        int(box["top"] + box["height"] * 0.5),
                    )
                    pressed = time.perf_counter()
                    user.mouse_event(0x0002, 0, 0, 0, 0)
                    try:
                        time.sleep(0.018)
                    finally:
                        user.mouse_event(0x0004, 0, 0, 0, 0)
                    tracker.clicked(pressed, state["bird"][1], delay=0.020)
                    clicked = True
                writer.writerow(
                    [
                        round(captured, 4),
                        *map(lambda v: round(v, 5), [state["bird"][1], velocity, tracker.speed]),
                        int(clicked),
                        round((captured - loop_start) * 1000, 2),
                        round((time.perf_counter() - loop_start) * 1000, 2),
                        round(planner.last_cost, 5),
                        json.dumps(state["pipes"]),
                    ]
                )
                if clicked:
                    log.flush()
                time.sleep(max(0, 1 / 60 - (time.perf_counter() - loop_start)))
        except KeyboardInterrupt:
            pass
        finally:
            user.mouse_event(0x0004, 0, 0, 0, 0)
            print("Stopped.", flush=True)


if __name__ == "__main__":
    main()
