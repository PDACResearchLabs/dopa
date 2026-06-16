# dopa

Personalized dopamine-aware ADHD assistant for founders.

Two-layer system: a Claude Code skill for interactive diagnosis and check-ins, plus a passive sensor daemon that learns your patterns and pushes interventions without you having to do anything.

> **Why this exists.** It was built after noticing ADHD symptoms intensify under heavy AI‑coding‑agent use — long hyperfocus locks, skipped breaks, blurred work/rest boundaries. dopa is meant to help people in the same situation notice and interrupt those patterns. Because the audience is vulnerable, **dopa is local‑first and privacy‑first by default** (see [Privacy](#privacy)).

## Claude Code Skill — `/dopa`

1. **Diagnose** — behavioral fingerprinting conversation (8 dimensions: energy, task initiation, focus, crash, avoidance, dopamine sources, recovery, emotional landscape)
2. **Profile** — saved to `profiles/<name>.yaml` (schema at `profile-schema.yaml`)
3. **Adapt** — tailored interventions: task breakdown, hyperfocus interrupts, micro-win tracking, energy-aware scheduling, emotional regulation

## Sensor Daemon — continuous passive sensing

```bash
# Install
pip install -r sensors/requirements.txt

# Run daemon — LOCAL-ONLY by default (no data ever leaves your machine)
python -m sensors.daemon

# One-shot capture + analysis (no daemon)
python -m sensors.daemon --once

# Faster cadence for debugging
python -m sensors.daemon --interval 60 --deep-every 2 --verbose
```

**Optional cloud vision (opt-in).** Deep facial-affect analysis uses Google Gemini and
**sends webcam frames off your machine**. It is **off by default**. Enable it explicitly
only if you accept that trade-off:

```bash
export DOPA_CLOUD_VISION=1
export GEMINI_API_KEY=...          # https://aistudio.google.com/apikey
python -m sensors.daemon
```

For persistent background running:

```bash
nohup python -m sensors.daemon --interval 300 --deep-every 3 > ~/.dopa/daemon.log 2>&1 &
```

### Architecture

```
sensors/
├── daemon.py       # Main loop — sync, 10s sleep chunks, graceful shutdown
├── camera.py       # Webcam capture (OpenCV) + Haar cascade face detection
├── analyzer.py     # Gemini 2.5 Flash vision analysis (thinking disabled)
├── git_sensor.py   # Workspace git activity: commits, bursts, repo switching
├── store.py        # SQLite at ~/.dopa/sensor.db — features only, never images
├── baseline.py     # 14-day rolling baseline, 2σ deviation detection (16 markers)
├── notifier.py     # macOS native notifications (throttled, 1 per 30 min)
└── config.py       # All knobs (interval, model, thresholds)
```

### What it measures

**Camera + Vision (16 trendable markers)**:
- Presence, head pose, gaze direction, eye openness, squinting
- Primary affect (focused/neutral/frustrated/anxious/sad/flat/tired), expressivity range, intensity
- Posture (upright/slumped/head-in-hands), engagement quality, attention
- Fatigue signs (eye rubbing, yawning, head propping, overall level)

**Git activity (6 markers)**:
- Ship rate, burst detection, hyperfocus patterns
- Repo fragmentation, late-night commit ratio
- Scans the git repos you point it at (`DOPA_GIT_ROOT` / `DOPA_GIT_SCAN_DIRS`; defaults to the current directory)

**Two-tier analysis**:
- **Local** (every 5 min, default): OpenCV face detection, brightness, face ratio — free, on-device, nothing leaves your machine
- **Cloud (opt-in)** (every 15 min): Gemini — facial affect, gaze, posture, fatigue, engagement. **Off by default; sends webcam frames to Google when enabled.**

### Resilience

Camera unavailable (no macOS permission)? Git sensor still collects. API down? Observations still stored with error markers. Daemon runs until explicitly killed. Logs to `~/.dopa/daemon.log` with automatic flush (no buffered output).

### Model

Defaults to `gemini-2.5-flash`. Override with `--model gemini-2.5-pro` or any Gemini vision model.

## Privacy

dopa is **local-first**. By default nothing leaves your machine.

| Data | Where it goes |
|---|---|
| Webcam frames | Held in memory only; **never written to disk**. Sent to Google Gemini **only if** you set `DOPA_CLOUD_VISION=1` (off by default). |
| Derived features/metrics | Local SQLite at `~/.dopa/sensor.db`. Never transmitted. |
| Git activity | Commit hash/time/subject from the repos you choose (`DOPA_GIT_ROOT`/`DOPA_GIT_SCAN_DIRS`), stored locally only. Point it at your own projects; don't scan others' confidential work. |
| Your profile | `profiles/<name>.yaml` — gitignored, never committed. |

**Config knobs:** `DOPA_CLOUD_VISION` (opt-in cloud vision, default off) · `GEMINI_API_KEY` (only if cloud vision on) · `GEMINI_MODEL` · `DOPA_GIT_ROOT` (default: cwd) · `DOPA_GIT_SCAN_DIRS` (default: `.`).

### Data locations
- SQLite: `~/.dopa/sensor.db` (observations, events, baselines)
- Log: `~/.dopa/daemon.log`
- Profiles: `profiles/<name>.yaml`

### Behavior
- Baselines start after 50 deep observations
- Notifications fire on 2σ deviation from your personal baseline

## License & citation

MIT — see `LICENSE`. If dopa helps your work or research, please cite it (see `CITATION.cff` — GitHub's "Cite this repository").
