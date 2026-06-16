# dopa — Privacy & Data Flow

dopa is **local-first**. The default configuration transmits **nothing** off your machine.
This document states exactly what is collected, where it goes, and how to control it.

## Default mode (local-only)

With no extra configuration:

- **Webcam** — frames are captured into memory, run through on-device OpenCV (face
  detection, brightness, face ratio), and **discarded**. Frames are **never written to
  disk** and **never transmitted**.
- **Git activity** — for the repos you point it at, dopa reads `git log` metadata
  (commit hash, timestamp, subject) to detect ship-rate / hyperfocus / avoidance
  patterns. Stored **only** in the local SQLite database. Never transmitted.
- **Derived signals & baselines** — stored in local SQLite at `~/.dopa/sensor.db`.
- **Your profile** — `profiles/<name>.yaml`. Gitignored; never committed, never sent.

## Opt-in cloud vision (off by default)

Setting `DOPA_CLOUD_VISION=1` (plus a `GEMINI_API_KEY`) enables deep facial-affect
analysis via **Google Gemini**. In this mode, **raw webcam JPEG frames are sent to
Google** for the configured cadence (default ~every 15 min). Only enable this if you
accept sending biometric/affect data to a third party. Unset the variable to return to
fully local operation. The daemon logs, at startup, whether cloud vision is on or off.

## Controlling scope

| Variable | Default | Effect |
|---|---|---|
| `DOPA_CLOUD_VISION` | unset (off) | `1`/`true` to enable cloud webcam-affect analysis |
| `GEMINI_API_KEY` | unset | required only when cloud vision is on |
| `GEMINI_MODEL` | `gemini-2.5-flash` | cloud vision model |
| `DOPA_GIT_ROOT` | current working directory | root dir the git sensor scans |
| `DOPA_GIT_SCAN_DIRS` | `.` | comma-separated sub-dirs to scan |

**Git-scope guidance:** commit subjects can contain confidential detail. Point
`DOPA_GIT_ROOT`/`DOPA_GIT_SCAN_DIRS` at your own project directories only; do not scan
directories holding other people's or clients' confidential work.

## What dopa never does

- Never writes webcam images to disk.
- Never transmits anything in default (local-only) mode.
- Never commits your personal profile.
- Camera or API unavailable? It degrades gracefully and keeps working locally.
