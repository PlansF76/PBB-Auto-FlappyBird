# V2 validation — 2026-10-11

Source: `Screen Recording 2026-10-11 124902.mp4`, 1918 by 996 pixels,
30 frames/s, 329 frames (about 10.97 seconds). Playfield bounds were
approximately (399, 72) to (1521, 924).

The old bird detector returned a position in 312/329 frames. V2 returned a
position in 329/329. Six annotated frames were visually checked, including
frames where the bird touches the leaf silhouette. This is detection coverage,
not a manually labeled per-pixel accuracy score. The feather filtering correction
also restored missing gaps and removed false gap edges through the bird.

Clean eight-frame ballistic fits from the recording gave a median gravity near
5775 pixels/s^2, or 6.78 playfield heights/s^2. The initial upward speed is an
approximate 1.48 heights/s, not an exact recovered game constant. Scroll starts
at 0.49 playfield widths/s and is estimated online. The planner keeps a 1.1-second
prediction horizon and adds clearance beyond the estimated bird radius.

Closed-loop simulations at 30 decisions/s passed:

- The 10.9-second recorded obstacle sequence, with an independently simulated bird.
- A 46-second, 30-obstacle generated course using the nominal motion model.
- The same generated course with 10% higher gravity and 50 ms action delay.
- The same generated course with 10% stronger flaps and 50 ms action delay.

The simulator applies clicks at their scheduled sub-frame times and uses the
same motion estimator and planner as the live controller. The recorded-course
test replays detected obstacle positions, not recorded human bird movement.
See `simulation-results.json` for outcomes and `validate_v2.py` for reproduction.

No live Roblox survival test was performed. Simulated collision geometry,
estimated physics, and modeled input timing may differ from the actual game.
Desktop capture measured roughly 16.5 ms median in a 20-capture local benchmark;
actual run timing is recorded in `logs/`. These measurements do not guarantee
indefinite survival or success in another game version/camera layout.

Implementation reference: OpenCV's documented
[connected-component statistics](https://docs.opencv.org/5.0/main_modules/imgproc_shape.html)
are used to separate sprite colors and broad leaf shapes.
