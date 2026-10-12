"""Log the screen position of every left mouse click until Ctrl+C is pressed."""

import argparse
import csv
import ctypes
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
import time

USER32 = ctypes.windll.user32
VK_LBUTTON = 0x01


def cursor_position():
    point = wintypes.POINT()
    if not USER32.GetCursorPos(ctypes.byref(point)):
        raise ctypes.WinError()
    return point.x, point.y


def left_button_down():
    return bool(USER32.GetAsyncKeyState(VK_LBUTTON) & 0x8000)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("mouse-clicks.csv"),
        help="CSV file to write (default: mouse-clicks.csv)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=0.005,
        help="Polling interval in seconds (default: 0.005)",
    )
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("--interval must be greater than zero")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["timestamp", "x", "y"])
        print(f"Logging left clicks to {args.output.resolve()}. Press Ctrl+C to stop.")
        was_down = False
        try:
            while True:
                is_down = left_button_down()
                if is_down and not was_down:
                    x, y = cursor_position()
                    timestamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
                    writer.writerow([timestamp, x, y])
                    file.flush()
                    print(f"{timestamp}  x={x}, y={y}", flush=True)
                was_down = is_down
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print(f"\nSaved click log to {args.output.resolve()}")


if __name__ == "__main__":
    main()
