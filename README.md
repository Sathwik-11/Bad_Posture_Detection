# bad-posture-detection

Real-time sitting posture monitoring from a **side-mounted webcam** (sagittal
plane), with a push notification every 6 hours summarising how long you
actually slouched — measured against the time the camera was really on, not
against the clock.

- **MediaPipe Pose** finds the ear, shoulder and hip of whichever side faces the
  camera (chosen by landmark visibility — no left/right shoulder comparison,
  which only works from the front).
- **Craniovertebral angle (CVA)** detects forward head / craned neck.
- **Torso lean off vertical** detects slouching.
- Samples once per second into SQLite, and only flags bad posture once the
  condition has held for 5 consecutive samples, so reaching for your coffee
  doesn't count.
- Every 6 hours, if bad posture exceeded the alert threshold, you get a push via
  [ntfy.sh](https://ntfy.sh) with the numbers plus corrective tips.

## Before you run this (first-run requirements)

A few things are only needed *once*, on the very first run on a given machine
— worth knowing before you clone this onto a server, container, or a locked-
down network:

- **Internet access, once.** The MediaPipe pose model (`pose_landmarker_lite.task`,
  ~6 MB) is not bundled with the pip package; it's downloaded into `models/`
  the first time the detector starts (see `ensure_model()` in
  `src/posture_detector.py`). Behind a firewall/proxy that blocks
  `storage.googleapis.com`, this download will fail and the app won't start.
  Fix: allow that host once, or manually place a `.task` bundle at the path
  `POSE_MODEL_PATH` points to.
- **A display, unless you pass `--no-window`.** The default run opens a live
  OpenCV preview window (`cv2.imshow`), which needs an X11/Wayland session on
  Linux or an actual desktop on Windows/macOS. On a headless server or inside
  most containers, use `python main.py --no-window`.
- **An interactive terminal for first-time calibration.** If `calibration.json`
  doesn't exist yet, `main.py` automatically launches the guided calibration
  flow, which calls `input()` to confirm the measured thresholds. Running that
  non-interactively (CI, a piped script, `stdin` closed) will raise `EOFError`.
  To avoid it: either run `python main.py --calibrate` interactively once to
  generate `calibration.json`, or place a pre-generated `calibration.json`
  (see `calibration.json.example` for the shape) in the project root before
  the first run — its mere presence skips the automatic prompt.
- **A webcam at `CAMERA_INDEX`.** Default is `0`; if that's the wrong device,
  `main.py` raises a clear `RuntimeError` telling you to change `CAMERA_INDEX`
  in `.env`.

## Camera placement (this matters)

The detection math assumes a **profile view**:

```
        wall
         |                     [ you ]  <- facing your monitor
         |                        |
    [ webcam ] ----- 3-5 ft ----->|      (camera looks at your side)
      ~shoulder height
```

- Place the camera to your **left or right**, not in front of you.
- Roughly **shoulder height**, level (not tilted up or down).
- **3–5 feet (1–1.5 m)** away.
- Your **ear, shoulder and hip must all be in frame** — hips included, so frame
  from mid-thigh to above the head.
- Keep it in the same place between runs; moving it changes the measured angles
  and invalidates calibration.

## Setup

Python 3.11+ is required.

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

The MediaPipe Tasks pose model (`pose_landmarker_lite.task`, ~6 MB) is not
bundled with the package; it downloads automatically into `models/` the first
time the detector starts. Point `POSE_MODEL_PATH` at a different `.task` bundle
(e.g. `pose_landmarker_full.task`) if you want more accuracy at a higher CPU
cost.

### Configure

```bash
cp .env.example .env     # Windows: copy .env.example .env
```

Then edit `.env`. The one value you must change is `NTFY_TOPIC`:

```env
NOTIFICATION_METHOD=ntfy
NTFY_TOPIC=posture-7f3a9c21b8e4d6
```

ntfy.sh needs no account and no API key — which also means **anyone who guesses
your topic name can read your notifications**. Use a long random string, e.g.:

```bash
python -c "import secrets; print('posture-' + secrets.token_hex(8))"
```

### Subscribe to your topic

Pick either:

- **Phone:** install the ntfy app ([Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy),
  [iOS](https://apps.apple.com/us/app/ntfy/id1625396347)), tap **+**, enter your
  topic name.
- **Browser/desktop:** open `https://ntfy.sh/<your-topic>` and allow
  notifications.

Verify end to end:

```bash
python main.py --test-notification
```

### Other notification methods

| `NOTIFICATION_METHOD` | Behaviour |
| --- | --- |
| `ntfy` (default) | HTTP POST to `https://ntfy.sh/<topic>`; falls back to a desktop toast if the network fails. |
| `desktop` | Local toast via plyer only, no network. |
| `email` | Optional SMTP path; requires `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SENDER_EMAIL`, `RECIPIENT_EMAIL`. Falls back to a desktop toast. |

## Calibrate

Thresholds default to clinical-ish values (CVA good ≥ 53°, bad < 48°; torso good
≤ 15°, bad > 25°), but your camera angle and body proportions shift the numbers.
Calibration measures *your* good posture and derives thresholds from it.

```bash
python main.py --calibrate
```

Sit up straight, ears over shoulders, back supported. After a 3-second
countdown it averages 5 seconds of frames, prints the proposed thresholds, and
on confirmation writes `calibration.json` (see `calibration.json.example`).
Calibration runs automatically on the first launch; delete `calibration.json` to
fall back to the `.env`/default thresholds.

## Run

```bash
python main.py
```

A preview window opens with the pose skeleton, live CVA and torso angles, a
colour-coded status (green = good, yellow = borderline, red = bad) and a running
session bad-posture timer. The scheduler starts in the background at the same
time. Quit with **q** in the window or **Ctrl+C**; both stop the camera and the
scheduler cleanly.

Useful flags:

| Flag | Purpose |
| --- | --- |
| `--calibrate` | Run calibration first. |
| `--summary` | Print the trailing-window summary as JSON and exit. |
| `--test-notification` | Send one notification now and exit. |
| `--no-window` | Headless: log samples without the preview window. |
| `--no-scheduler` | Monitor without the periodic summary job. |
| `--verbose` | Debug logging. |

## What the notification says

> You were tracked for 3h 10m in the past 6 hours (camera on for 53% of the
> window). Bad posture: 42m (22% of tracked time). Main issue: forward head /
> craned neck (30m). Tips: Do 10 slow chin tucks… Raise the monitor so the top
> third of the screen is at eye level.

Nothing is sent when bad posture stayed under
`BAD_POSTURE_ALERT_THRESHOLD_MINUTES` (default 30), so a quiet phone means
either good posture or a camera that was barely on.

## How tracked time works

Each row in `posture_events` represents `SAMPLE_INTERVAL_SECONDS` of tracked
time, written only while the capture loop is running and a pose is visible.
`get_bad_posture_summary(hours)` multiplies sample counts by that interval:

```python
{
  "total_minutes_tracked": 190.0,        # samples_in_window * interval / 60
  "total_minutes_bad_posture": 42.0,
  "issue_breakdown": {"forward_head": 30.0, "slouching": 12.0},
  "percentage_bad": 22.1,                # of TRACKED time
  "camera_coverage_percentage": 52.8     # tracked / (hours * 60)
}
```

Close your laptop for three hours and those hours simply have no rows — they are
never counted as good posture or bad. A sample with both issues contributes to
both `issue_breakdown` entries, so that breakdown can exceed
`total_minutes_bad_posture`.

## Project layout

```
src/posture_detector.py   MediaPipe pose, CVA + torso math, classification, debouncing
src/posture_logger.py     SQLite sample log + trailing-window aggregation
src/notifier.py           ntfy push (primary), desktop toast (fallback), SMTP (optional)
src/corrective_tips.py    issue -> corrective advice
src/scheduler.py          APScheduler job: aggregate every N hours, notify if over threshold
src/camera_stream.py      capture loop + live overlay
src/calibration.py        guided calibration -> calibration.json
src/config.py             .env + calibration.json loading
main.py                   entrypoint (camera loop + background scheduler)
tests/                    pytest suite (no webcam or network needed)
```

## Tests

```bash
pytest
```

The suite covers the angle math against known mock landmark coordinates, the
aggregation logic over a seeded database containing a deliberate camera-off gap,
and the notifier with `requests.post` mocked — real ntfy.sh is never contacted.

## Troubleshooting

- **"Could not open camera index 0"** — another app holds the webcam, or the
  index is wrong. Try `CAMERA_INDEX=1`, `2`, ….
- **"NO POSE DETECTED"** — move back so hip through head is in frame, and
  improve lighting; MediaPipe needs a clear silhouette.
- **Angles look wrong / everything is "bad"** — the camera is probably not
  side-on or is tilted. Re-aim it, then re-run `--calibrate`.
- **The `side:` readout flickers between left and right** — the camera is too
  close to frontal, so both sides score similar visibility. Move it further
  round to your side; the angles are only meaningful from a true profile.
- **No push arriving** — run `python main.py --test-notification`; check the
  topic in `.env` matches the one you subscribed to exactly (case-sensitive).
- **Database growing** — each row is tiny (~50 bytes, ~4 MB per 24h of
  sampling); call `PostureLogger.purge_older_than(days)` or delete
  `posture_data.db` to reset.

## Privacy

Frames are analysed in memory and never stored or uploaded. Only angle numbers
and timestamps go to the local SQLite file, and only the aggregated text summary
leaves your machine (to ntfy.sh, if you use that method).
