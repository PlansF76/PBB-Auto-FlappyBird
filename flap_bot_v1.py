"""Windows screen-based arcade helper. F8 toggle; F9 exit. No game injection."""

import argparse
import ctypes
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageGrab, ImageDraw


def runs(mask):
    edges = np.diff(np.r_[False, mask, False].astype(int))
    return list(zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)))


def board_bounds(image):
    a = np.asarray(image.convert("RGB")).astype(np.int16)
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    cyan = (r < 100) & (g > 190) & (b > 190)
    ys = np.flatnonzero(cyan.sum(axis=1) > image.width * 0.25)
    if not len(ys):
        raise ValueError("No cyan playfield found. Show the arcade gameplay first.")
    y0, y1 = int(ys[0]), int(ys[-1]) + 1
    xs = np.flatnonzero(cyan[y0:y1].sum(axis=0) > (y1 - y0) * 0.35)
    if not len(xs):
        raise ValueError("Could not locate playfield edges.")
    return int(xs[0]), y0, int(xs[-1]) + 1, y1


def detect(image):
    a = np.asarray(image.convert("RGB")).astype(np.int16)
    h, w = a.shape[:2]
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    tan = (r > 180) & (g > 110) & (g < 235) & (b < 190) & (r > g + 12) & (g > b + 15)
    tan[:, : int(w * 0.25)] = False
    tan[:, int(w * 0.44) :] = False
    yy, xx = np.nonzero(tan)
    if len(xx) < w * h * 0.0003:
        return None
    # The bird occupies a fixed horizontal lane; reject overlays and scattered pixels.
    bx, by = float(np.median(xx)), float(np.median(yy))
    if np.percentile(yy, 95) - np.percentile(yy, 5) > h * 0.16:
        return None
    green = (g > 115) & (g > r * 1.15) & (g > b * 1.08)
    columns = green.sum(axis=0) > max(5, h * 0.012)
    groups = [(l, rr) for l, rr in runs(columns) if rr - l > w * 0.025 and rr > bx - w * 0.035]
    target, ceiling, floor = h * 0.55, 0.0, float(h)
    obstacle = None
    if groups:
        left, right = min(groups, key=lambda item: item[0])
        occupied = green[:, left:right].sum(axis=1) > max(2, (right - left) * 0.035)
        gaps = [(lo, hi) for lo, hi in runs(~occupied) if hi - lo > h * 0.16 and lo > 0 and hi < h]
        if gaps:
            ceiling, floor = max(gaps, key=lambda pair: pair[1] - pair[0])
            target = (ceiling + floor) / 2
            obstacle = (left, right)
    return dict(bird=(bx, by), target=target, ceiling=ceiling, floor=floor, obstacle=obstacle)


def inspect(path):
    im = Image.open(path).convert("RGB")
    box = board_bounds(im)
    state = detect(im.crop(box))
    if state is None:
        raise ValueError("Bird not detected in reference image.")
    draw = ImageDraw.Draw(im)
    draw.rectangle(box, outline="red", width=3)
    x, y = state["bird"]
    x += box[0]
    y += box[1]
    draw.ellipse((x - 12, y - 12, x + 12, y + 12), outline="red", width=3)
    target = box[1] + state["target"]
    draw.line((box[0], target, box[2], target), fill="red", width=3)
    out = Path(__file__).with_name("detection-preview.png")
    im.save(out)
    print("Playfield:", box, "\nDetection:", state, "\nPreview:", out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inspect", help="Check a saved screenshot without clicking")
    parser.add_argument("--lead", type=float, default=0.12, help="Prediction seconds; default .12")
    parser.add_argument(
        "--cooldown", type=float, default=0.19, help="Minimum seconds between flaps"
    )
    args = parser.parse_args()
    if args.inspect:
        inspect(args.inspect)
        return
    user = ctypes.windll.user32
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        user.SetProcessDPIAware()
    user.GetForegroundWindow.restype = ctypes.c_void_p
    user.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]

    def roblox_focused():
        title = ctypes.create_unicode_buffer(512)
        user.GetWindowTextW(user.GetForegroundWindow(), title, 512)
        return "roblox" in title.value.lower()

    def down(key):
        return bool(user.GetAsyncKeyState(key) & 0x8000)

    active, previous_f8, box = False, False, None
    last_y, last_t, last_click, velocity, misses = None, 0.0, 0.0, 0.0, 0
    print("Focus Roblox. Start the arcade round, then press F8. F8 pauses; F9 exits.", flush=True)
    print("Keep the game window in place. Mouse moves to the playfield when flapping.", flush=True)
    try:
        while not down(0x78):  # F9
            f8 = down(0x77)
            if f8 and not previous_f8:
                active = not active
                last_y, velocity, misses = None, 0.0, 0
                if active:
                    if not roblox_focused():
                        print("Focus Roblox before pressing F8.", flush=True)
                        active = False
                    else:
                        try:
                            box = board_bounds(ImageGrab.grab())
                        except ValueError as error:
                            print(error, flush=True)
                            active = False
                print("RUNNING" if active else "PAUSED", flush=True)
            previous_f8 = f8
            if not active:
                time.sleep(0.03)
                continue
            if not roblox_focused():
                active = False
                print("PAUSED: Roblox lost focus.", flush=True)
                continue
            frame = ImageGrab.grab(bbox=box)
            state = detect(frame)
            now = time.perf_counter()
            if state is None:
                misses += 1
                last_y = None
                if misses >= 8:
                    active = False
                    print("PAUSED: bird lost. Restart the round manually, then F8.", flush=True)
                time.sleep(0.02)
                continue
            misses = 0
            x, y = state["bird"]
            if last_y is not None:
                measured = (y - last_y) / max(now - last_t, 0.001)
                velocity = 0.55 * velocity + 0.45 * measured
            last_y, last_t = y, now
            radius = frame.height * 0.046
            predicted = y + max(velocity, 0) * args.lead
            needs_flap = predicted > state["target"] + frame.height * 0.015
            has_headroom = y - radius > state["ceiling"] + frame.height * 0.06
            if (
                needs_flap
                and has_headroom
                and now - last_click >= args.cooldown
                and roblox_focused()
            ):
                user.SetCursorPos(int(box[0] + frame.width * 0.5), int(box[1] + frame.height * 0.5))
                user.mouse_event(0x0002, 0, 0, 0, 0)
                try:
                    time.sleep(0.012)
                finally:
                    user.mouse_event(0x0004, 0, 0, 0, 0)
                last_click = time.perf_counter()
            time.sleep(0.005)
    except KeyboardInterrupt:
        pass
    finally:
        user.mouse_event(0x0004, 0, 0, 0, 0)
        print("Stopped.", flush=True)


if __name__ == "__main__":
    main()
