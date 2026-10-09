# my-tailscale-playground

A fork of [tailscale/tailscale](https://github.com/tailscale/tailscale) used as a monorepo for tools built around a personal tailnet. Against the point where it forked, the additions are new directories and files, plus one change to `.gitignore`; no Tailscale source file was modified or deleted.

| Path | What it is |
|---|---|
| `tailtop/` | Terminal UI for a tailnet (Python 3.13, Textual). Modes: Comfort, Cockpit, Observatory. `tailtop fleet` prints a one-shot hardware vitals table for the Pi fleet. |
| `tailsnap/` | CLI snapshot of the tailnet from `tailscale status --json`: `status`, `health`, `map`, `traffic`, and `--demo` with a built-in fixture. |
| `cmd/tailprobe/` | Go agent that serves one device's vitals (`/healthz`, `/vitals`, `/metrics`) on its Tailscale address. Install scripts for systemd and OpenSSH hosts are under `deploy/`. |
| `tailhub/` | Python collector (FastAPI, SQLite) that discovers devices from `tailscale status`, scrapes each `tailprobe`, and serves `/fleet`, `/device/{host}` and `/history`. |
| `lifelog/` | WiFi-sensing time-tracker that runs end to end on simulated data. |
| `docs/superpowers/` | Design specs and implementation plans for the tools above. |
| `notes/`, `scripts/` | Research notes, a fleet capability probe, and `extract-subprojects.sh` for splitting `lifelog/` and `tailtop/` into their own repos. |

Each tool has its own README with build and run steps. The rest of this file is the upstream Tailscale README, unchanged.

---

# Tailscale

https://tailscale.com

Private WireGuard® networks made easy

## Overview

This repository contains the majority of Tailscale's open source code.
Notably, it includes the `tailscaled` daemon and
the `tailscale` CLI tool. The `tailscaled` daemon runs on Linux, Windows,
[macOS](https://tailscale.com/kb/1065/macos-variants/), and to varying degrees
on FreeBSD and OpenBSD. The Tailscale iOS and Android apps use this repo's
code, but this repo doesn't contain the mobile GUI code.

Other [Tailscale repos](https://github.com/orgs/tailscale/repositories) of note:

* the Android app is at https://github.com/tailscale/tailscale-android
* the Synology package is at https://github.com/tailscale/tailscale-synology
* the QNAP package is at https://github.com/tailscale/tailscale-qpkg
* the Chocolatey packaging is at https://github.com/tailscale/tailscale-chocolatey

For background on which parts of Tailscale are open source and why,
see [https://tailscale.com/opensource/](https://tailscale.com/opensource/).

## Using

We serve packages for a variety of distros and platforms at
[https://pkgs.tailscale.com](https://pkgs.tailscale.com/).

## Other clients

The [macOS, iOS, and Windows clients](https://tailscale.com/download)
use the code in this repository but additionally include small GUI
wrappers. The GUI wrappers on non-open source platforms are themselves
not open source.

## Building

We always require the latest Go release, currently Go 1.26. (While we build
releases with our [Go fork](https://github.com/tailscale/go/), its use is not
required.)

```
go install tailscale.com/cmd/tailscale{,d}
```

If you're packaging Tailscale for distribution, use `build_dist.sh`
instead, to burn commit IDs and version info into the binaries:

```
./build_dist.sh tailscale.com/cmd/tailscale
./build_dist.sh tailscale.com/cmd/tailscaled
```

If your distro has conventions that preclude the use of
`build_dist.sh`, please do the equivalent of what it does in your
distro's way, so that bug reports contain useful version information.

## Bugs

Please file any issues about this code or the hosted service on
[the issue tracker](https://github.com/tailscale/tailscale/issues).

## Contributing

PRs welcome! But please file bugs. Commit messages should [reference
bugs](https://docs.github.com/en/github/writing-on-github/autolinked-references-and-urls).

We require [Developer Certificate of
Origin](https://en.wikipedia.org/wiki/Developer_Certificate_of_Origin)
`Signed-off-by` lines in commits.

See [commit-messages.md](docs/commit-messages.md) (or skim `git log`) for our commit message style.

## About Us

[Tailscale](https://tailscale.com/) is primarily developed by the
people at https://github.com/orgs/tailscale/people. For other contributors,
see:

* https://github.com/tailscale/tailscale/graphs/contributors
* https://github.com/tailscale/tailscale-android/graphs/contributors

## Legal

WireGuard is a registered trademark of Jason A. Donenfeld.
