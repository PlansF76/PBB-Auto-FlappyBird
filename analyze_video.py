"""Offline measurement only: never sends mouse input."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT / "vendor") not in sys.path:
    sys.path.insert(0, str(ROOT / "vendor"))
import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
import flap_bot_v1 as bot  # noqa: E402

VIDEO = r"C:\Users\plans\Videos\Screen Recordings\Screen Recording 2026-10-11 124902.mp4"


def bird_center(a):
    h, w = a.shape[:2]
    left, right = int(w * 0.25), int(w * 0.43)
    roi = a[:, left:right].astype(np.int16)
    r, g, b = roi[:, :, 0], roi[:, :, 1], roi[:, :, 2]
    fg = ~((r < 100) & (g > 190) & (b > 190))
    tan = (r > 180) & (g > 110) & (g < 235) & (b < 190) & (r > g + 12) & (g > b + 15)
    n, labels, stats, centers = cv2.connectedComponentsWithStats(fg.astype(np.uint8), 8)
    candidates = []
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if h * 0.035 < bh < h * 0.15 and w * 0.025 < bw < w * 0.12:
            score = np.count_nonzero(tan & (labels == i))
            if score > h * w * 0.00025:
                candidates.append((score, left + x + bw / 2, y + bh / 2, bw, bh))
    return max(candidates) if candidates else None


if __name__ == "__main__":
    cap = cv2.VideoCapture(VIDEO)
    fps = cap.get(cv2.CAP_PROP_FPS)
    rows = []
    old = []
    box = None
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        im = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        if box is None:
            box = bot.board_bounds(im)
            print("box", box, "fps", fps)
        crop = im.crop(box)
        bird = bird_center(np.asarray(crop))
        state = bot.detect(crop)
        if bird:
            _, x, y, bw, bh = bird
            rows.append([i / fps, x, y, bw, bh])
        if state:
            old.append([i / fps, *state["bird"], state["target"], *(state["obstacle"] or (-1, -1))])
        i += 1
    np.savez(
        Path(__file__).with_name("video-measurements.npz"),
        bird=np.array(rows),
        old=np.array(old),
        box=box,
        fps=fps,
    )
    data = np.array(rows)
    y = data[:, 2]
    t = data[:, 0]
    v = np.diff(y) / np.diff(t)
    print("frames", i, "bird detected", len(rows), "old detected", len(old))
    print(
        "y range",
        y.min(),
        y.max(),
        "velocity percentiles",
        np.percentile(v, [0, 5, 25, 50, 75, 95, 100]),
    )
    print("samples t,y,v:")
    for j in range(len(v)):
        print(f"{t[j+1]:.3f},{y[j+1]:.1f},{v[j]:.1f}")
