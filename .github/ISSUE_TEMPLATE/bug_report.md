---
name: Bug report
about: Report a problem with the dopa skill or sensor daemon
title: "[Bug]: "
labels: [bug]
assignees: []
---

## Describe the bug

A clear and concise description of what the bug is.

## Which part of dopa?

- [ ] `/dopa` Claude Code skill (diagnosis / check-ins / profile)
- [ ] Sensor daemon (`python -m sensors.daemon`)
- [ ] Camera / vision analysis
- [ ] Git activity sensor
- [ ] Notifications / baseline detection
- [ ] Docs
- [ ] Other

## To reproduce

Steps to reproduce the behavior:

1. Run `...`
2. With config `...` (e.g. `DOPA_CLOUD_VISION`, `--interval`, `--once`)
3. See error

## Expected behavior

What you expected to happen.

## Actual behavior

What actually happened. Include any error output.

## Logs

If applicable, paste relevant lines from `~/.dopa/daemon.log` or terminal output.
Please redact anything personal before posting.

```
<paste logs here>
```

## Environment

- OS / version: <!-- e.g. macOS 14.5 -->
- Python version: <!-- python --version -->
- dopa version / commit: <!-- git rev-parse --short HEAD -->
- Cloud vision enabled? <!-- DOPA_CLOUD_VISION=1 or off (default) -->

## Privacy note

Do **not** attach webcam images, profile YAML, or `~/.dopa/sensor.db` contents.
Share only the minimum needed to reproduce the issue.

## Additional context

Add any other context about the problem here.
