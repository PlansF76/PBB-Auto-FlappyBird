# Brick Bronze arcade helper v2

Double-click `Run Bot.cmd`. Switch to Roblox at the arcade gameplay or green Play screen.
Press **F8** to start automatic left-click flapping. F8 also pauses; **F9** exits.
Keep Roblox on the primary monitor with the full cyan arcade visible, at a similar
camera angle to the supplied screenshot. Keep the window and camera stationary
while running. Pause and resume to recalibrate after moving or resizing it.

Close any old bot console before starting this version. The helper uses screenshots
and normal Windows mouse input. It moves your cursor inside the arcade to click.
It pauses when Roblox loses focus. If the bird disappears or the scene stops moving,
it looks for the green Play button and automatically starts another round.

## First-time Windows setup

1. On the GitHub page, click **Code**, choose **Download ZIP**, and extract the
   archive.
2. Install Python 3.11 or newer from [python.org](https://www.python.org/downloads/windows/).
   Enable **Add python.exe to PATH** in the installer.
3. Open the extracted project folder, click its address bar, type `cmd`, and
   press **Enter**.
4. Install the dependencies:

```powershell
python -m pip install -r requirements.txt
```

The launcher uses Python from `PATH`, so the project can be cloned and run on
another Windows machine without editing a user-specific path. The local
`vendor/` directory is retained for offline reference but is not required.

If Windows reports `Python was not found; run without arguments to install from
the Microsoft Store`, try the Python launcher instead:

```powershell
py -3 -m pip install -r requirements.txt
```

If `py` is also unavailable, Python is not installed correctly. Reinstall it
from python.org, enable **Add python.exe to PATH**, then open a new Command
Prompt window and repeat the install command.

Once installation succeeds, open Roblox at the arcade, double-click
`Run Bot.cmd`, focus Roblox, and press **F8**. Press **F8** again to pause and
**F9** to exit. Keep Roblox visible on the primary monitor and do not resize or
move the game window while the helper is running.

The previous threshold rule has been replaced with a controller that predicts
flap/wait paths through moving gaps over 1.1 seconds. It uses an estimated gravity
of 6.78 playfield heights/s^2 and a flap speed of 1.48 heights/s, calibrated from
the supplied recording. It tracks horizontal scroll speed live, keeps checking
the current obstacle until the whole bird clears it, and leaves extra clearance
for imperfect motion estimates. Green feathers are filtered out of leaf detection.

Verification is offline: bird detection on all 329 recording frames, annotated
gap previews, and closed-loop simulations. Simulations predict alternate bird
motion; they do not establish live Roblox performance. Real click handling,
capture delays, camera changes and other game variants can still cause failures.

Each live session records timing, detections and flap decisions in `logs/`. If it
still fails, these logs plus a recording of the bot running will help identify
whether the remaining problem is input delay, missed clicks or motion prediction.

Code is in `flap_bot_v2.py`; the original is preserved as `flap_bot_v1.py`.
The default input-delay estimate is 35 ms. For a consistently delayed response,
try `"Run Bot.cmd" --latency 0.055` from a terminal in this folder. F8 recalibrates
the playfield each time you resume. Do not run both versions simultaneously.

For a no-click screenshot check:

```
python flap_bot_v2.py --inspect "path\to\screenshot.png"
```

This writes `detection-preview.png`, marking the bird and detected gaps.
`v2-video-validation.png` shows six annotated frames from your recording.
`validate_v2.py` reproduces video checks and simulations without sending input.
`simulation-results.json` contains the latest simulation outcomes.

## How to use

<img width="1051" height="558" alt="Screenshot 2026-10-11 183736" src="https://github.com/user-attachments/assets/eeb4f475-8c12-4bfa-b890-69fa62347c09" />
### Stand in front of the middle arcade machine like this because typically this will be the easiest of the three machines found in the Golden Poke Ball Arcade.
Once ready you should press f8, with 'Run Bot.cmd' running in the background. Then the script should automatically press the big green play button. Additionally, I would be wary about testing to see if the script automatically pressed the green play button for the middle arcade machine in order to AFK for long periods of time and continuously gain TIX in the process as the difficult of the other two machines are significantly greater, and ineffective for the script.


## Automatic replay

The launcher now runs `auto_replay.py`, which uses the existing v2 flight detector,
tracker and planner unchanged. Close the old bot console before relaunching.
F8 enables or pauses both flight and replay; F9 exits. Switching away from Roblox
pauses all input until you focus Roblox and press F8 again.

After a loss it identifies the white Play label on green, requires two stable
sightings, clicks once, and reacquires the cyan playfield before resuming. If two
buttons are visible it chooses the middle Play prompt for the flappy-bird
cabinet. Unanswered Play clicks are retried no more often than every 0.75 seconds. It waits when it
cannot confidently find the expected button or playfield. It does not handle
other dialogs or purchases.

Play clicks now release any prior press, move onto the button, wait 200 ms for
hover handling, then hold the left button for 150 ms before releasing. If the
button remains visible, the next retry moves to a second interior point and then
a third, with a 0.75-second minimum between attempts. Flight click timing is
unchanged. Pause, exit and focus loss cancel the menu click; an interrupted
held click is always released. `test_play_click.py` checks the input sequence
with a fake mouse and clock, without issuing desktop input. A live test confirmed
Windows accepted the synthetic down/up events but the first target did not open
the round. The menu click now also posts WM_MOUSEMOVE, LBUTTONDOWN, and
LBUTTONUP to the Roblox child window under the target; alternate interior
points remain as a fallback.

The hover step now uses nonzero relative mouse deltas in a closed five-point
path, then returns to the button center before pressing. This matches the new
observation that ordinary mouse movement can start the game even without a
manual click; Roblox evidently depends on movement/hover events in this menu.

The click path now resolves the visible top-level Roblox window directly instead
of assuming that the current foreground window is Roblox. It brings that exact
window to the front, checks that the button point belongs to a Roblox child
window, and refuses the menu click if Windows reports the terminal or another
window under the pointer. This isolates focus mistakes from button-detection
mistakes.

The supplied screenshots contain several nearby Play prompts. Replay selection
uses the valid prompt nearest the horizontal center of the screen, matching the
middle button you identified. Before pressing, the cursor jiggles through five
small interior points and emits move events so Roblox updates its hover hit test.
Offline tests pass at three image scales.

The replay wait no longer treats F8 as a click cancellation. This matters when
the key is still held briefly after enabling the bot: the old behavior could move
the cursor onto Play and cancel during the hover delay, producing exactly a snap
without a click. F9 and Roblox focus loss still abort immediately. The launcher
now uses `mss.MSS()` so the previous deprecation warning is gone.

Latest restart diagnosis: live testing reproduced a Play click that did not open
a round. A diagnostic using Windows SendInput also failed to activate it; that
alternative is not enabled in the normal launcher. The activation issue remains
unresolved pending confirmation of the manual restart interaction.

Startup handling now waits for a consistently shaped playfield, estimates the
bird's motion during acquisition, and checks for camera/viewport changes during
the first five seconds. The extra start flap is restricted to a stationary bird
with no detected obstacles. A frozen loss screen is remembered to avoid repeated
reacquisition. These startup changes compile and existing offline replay checks
pass, but have not yet been verified across a successful live restart. Acquisition
and loss snapshots are saved as JPEGs in `logs/` for further diagnosis.

`play-label.png` is a reference crop from your screenshot. Offline checks passed
at 75%, 100%, and 125% screenshot size; the gameplay image, plain green image and
text without its green background were rejected. Retry timing also passed.
Live loss-to-restart behavior still needs verification in Roblox.

Replay and flight events are written to `logs/auto-*.csv`. For manual restarting
with the previous version, run `flap_bot_v2.py` directly. `test_replay.py` performs
the offline replay checks without clicking.





