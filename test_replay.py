import sys

sys.path.insert(0, r"C:\Users\plans\output\brick-bronze-flap")
import auto_replay as a
from PIL import Image
import numpy as np

root = a.ROOT
im = Image.open(
    r"C:\Users\plans\OneDrive\Pictures\Screenshots\Screenshot 2026-10-11 133847.png"
).convert("RGB")
d = a.PlayDetector()
for scale in [0.75, 1.0, 1.25]:
    rgb = np.array(im.resize((round(im.width * scale), round(im.height * scale))))
    p = d.find(rgb)
    assert p is not None and abs(p[0] / scale - 722) < 8 and abs(p[1] / scale - 329) < 8, (scale, p)
    print("Play detection at scale", scale, "PASS")
p = d.find(np.array(im), anchor=(900, 375))
assert p is not None and abs(p[0] - 894) < 8, p
print("Second-button selection PASS")
game = np.array(
    Image.open(
        r"C:\Users\plans\OneDrive\Pictures\Screenshots\Screenshot 2026-10-11 124256.png"
    ).convert("RGB")
)
assert d.find(game) is None
blank = np.full((637, 1122, 3), (76, 164, 100), np.uint8)
assert d.find(blank) is None
without_green = np.array(im)
mask = without_green[:, :, 1] > without_green[:, :, 0].astype(float) * 1.35
without_green[mask] = (0, 0, 0)
assert d.find(without_green) is None
print("Gameplay, plain green, and text without green rejected PASS")
gate = a.ReplayGate()
assert not gate.ready((722, 329), 0)
assert gate.ready((722, 329), 0.2)
gate.clicked(0.2)
assert not gate.ready((722, 329), 1)
assert gate.ready((722, 329), 2)
gate.clicked(2)
assert not gate.ready((722, 329), 2.2)
assert gate.ready((722, 329), 3.3)
assert not gate.ready(None, 4)
assert not gate.ready((722, 329), 4.2)
print("Stable sightings and retry interval PASS")
