"""Offline detection and simulated closed-loop checks; never controls the mouse."""

import json
from pathlib import Path
import time
import flap_bot_v2 as bot
import cv2
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).parent
VIDEO = r"C:\Users\plans\Videos\Screen Recordings\Screen Recording 2026-10-11 124902.mp4"


def video_check():
    cap = cv2.VideoCapture(VIDEO)
    fps = cap.get(cv2.CAP_PROP_FPS)
    states = []
    box = None
    i = 0
    elapsed = []
    old_valid = 0
    import flap_bot_v1 as old

    sheet = Image.new("RGB", (1000, 1200))
    draw = ImageDraw.Draw(sheet)
    samples = [0, 40, 90, 150, 220, 275]
    while True:
        ok, bgr = cap.read()
        if not ok:
            break
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        if box is None:
            box = bot.board_bounds(rgb)
        x0, y0, x1, y1 = box
        crop = rgb[y0:y1, x0:x1]
        start = time.perf_counter()
        state = bot.detect(crop)
        elapsed.append(time.perf_counter() - start)
        states.append(state)
        if old.detect(Image.fromarray(crop)):
            old_valid += 1
        if i in samples:
            k = samples.index(i)
            a = crop.copy()
            h, w = a.shape[:2]
            if state:
                for p in state["pipes"]:
                    cv2.rectangle(
                        a,
                        (int(p["left"] * w), int(p["top"] * h)),
                        (int(p["right"] * w), int(p["bottom"] * h)),
                        (255, 0, 0),
                        3,
                    )
                x, y = state["bird"]
                cv2.circle(a, (int(x * w), int(y * h)), int(bot.RADIUS_Y * h), (255, 0, 0), 3)
            sheet.paste(Image.fromarray(a).resize((500, 380)), ((k % 2) * 500, (k // 2) * 400))
            draw.text(
                ((k % 2) * 500, (k // 2) * 400 + 380),
                f'{i/fps:.2f}s - {len(state["pipes"]) if state else "MISSING"} gaps',
                fill="white",
            )
        i += 1
    sheet.save(ROOT / "v2-video-validation.png")
    result = dict(
        frames=i,
        detected=sum(s is not None for s in states),
        old_detected=old_valid,
        missing_frames=[i for i, s in enumerate(states) if s is None],
        detection_ms_median=float(np.median(elapsed) * 1000),
        states=states,
        fps=fps,
        box=box,
    )
    (ROOT / "video-v2-states.json").write_text(json.dumps(result), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "states"}, indent=2), flush=True)
    return result


def simulate(
    pipes_at,
    duration,
    y=0.5,
    v=0.0,
    gravity=bot.GRAVITY,
    impulse=bot.FLAP_SPEED,
    latency=0.035,
    observed=True,
    fps=30,
):
    planner = bot.Planner(latency=latency)
    tracker = bot.Tracker()
    dt = 1 / fps
    pending = []
    clicks = []
    last = -100.0
    decisions = []
    for step in range(int(duration / dt)):
        t = step * dt
        pipes = pipes_at(t)
        state = dict(bird=(1 / 3, y), pipes=pipes)
        if observed:
            velocity = tracker.update(state, t)
        else:
            velocity = v
        start = time.perf_counter()
        action = planner.decide(state, velocity, tracker.speed, t - last)
        decisions.append(time.perf_counter() - start)
        if action and not pending:
            pending.append(t + latency)
            last = t
            clicks.append(t)
            tracker.clicked(t, y, delay=latency)
        if pending and pending[0] <= t + dt:
            before = max(0.0, pending.pop(0) - t)
            y += v * before + 0.5 * gravity * before * before
            v = -impulse
            after = dt - before
            y += v * after + 0.5 * gravity * after * after
            v += gravity * after
        else:
            y += v * dt + 0.5 * gravity * dt * dt
            v += gravity * dt
        low, high = bot.RADIUS_Y, 1 - bot.RADIUS_Y
        for p in pipes_at(t + dt):
            if p["left"] <= 1 / 3 + bot.RADIUS_X and p["right"] >= 1 / 3 - bot.RADIUS_X:
                low = max(low, p["top"] + bot.RADIUS_Y)
                high = min(high, p["bottom"] - bot.RADIUS_Y)
        if y < low or y > high:
            return dict(
                passed=False,
                seconds=round(t, 3),
                y=y,
                low=low,
                high=high,
                velocity=v,
                estimated=velocity,
                clicks=len(clicks),
                planner_ms=float(np.median(decisions) * 1000),
            )
    return dict(
        passed=True,
        seconds=duration,
        clicks=len(clicks),
        planner_ms=float(np.median(decisions) * 1000),
    )


def random_pipes(seed=7, count=30):
    rng = np.random.default_rng(seed)
    centers = rng.uniform(0.25, 0.75, count)

    def at(t):
        result = []
        for i, center in enumerate(centers):
            left = 1.05 + i * 0.74 - bot.SCROLL_SPEED * t
            if left < 1.02 and left + 0.235 > -0.01:
                result.append(
                    dict(left=left, right=left + 0.235, top=center - 0.204, bottom=center + 0.204)
                )
        return result

    return at


def recorded_course():
    data = json.loads((ROOT / "video-v2-states.json").read_text())

    # Only obstacle positions are replayed. The simulated bird follows our
    # controller, not the human's recorded positions or clicks.
    def at(t):
        index = min(int(t * data["fps"]), len(data["states"]) - 1)
        state = data["states"][index]
        return state["pipes"] if state else []

    return data, at


if __name__ == "__main__":
    import sys

    if "--simulation-only" not in sys.argv:
        video_check()
    tests = {}
    data, course = recorded_course()
    tests["recorded_course"] = simulate(course, 10.9, y=data["states"][0]["bird"][1], v=0.3)
    print("recorded_course", tests["recorded_course"], flush=True)
    for name, g, j, delay in [
        ("nominal", bot.GRAVITY, bot.FLAP_SPEED, 0.035),
        ("faster_fall", bot.GRAVITY * 1.10, bot.FLAP_SPEED, 0.05),
        ("stronger_flap", bot.GRAVITY, bot.FLAP_SPEED * 1.10, 0.05),
    ]:
        tests[name] = simulate(random_pipes(), 46, gravity=g, impulse=j, latency=delay)
        print(name, tests[name], flush=True)
    (ROOT / "simulation-results.json").write_text(json.dumps(tests, indent=2), encoding="utf-8")
