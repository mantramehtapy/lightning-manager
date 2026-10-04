#!/usr/bin/env python3
"""Check for the `lightning` CLI, install it if missing, then authenticate.

Idempotent: safe to run repeatedly. Reports exactly what it did.

Usage:
    python3 ensure_cli.py --check    # report only, change nothing
    python3 ensure_cli.py            # check -> install -> authenticate
    python3 ensure_cli.py --yes      # skip the confirmation prompt
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from typing import List, Optional, Tuple

PACKAGE = "lightning-sdk"
BINARY = "lightning"


def _run(cmd: List[str], timeout: Optional[int] = 300) -> Tuple[int, str]:
    """Run a command, returning (returncode, combined output). Never raises."""
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"
    except OSError as exc:
        return 127, str(exc)
    return proc.returncode, ((proc.stdout or "") + (proc.stderr or "")).strip()


def find_cli() -> Optional[str]:
    """Return the path to the lightning binary, or None if absent.

    shutil.which alone misses extensionless POSIX scripts, so check directly
    too — the console script can land in ~/.local/bin without a suffix.
    """
    found = shutil.which(BINARY)
    if found:
        return found
    for candidate in (
        os.path.expanduser(f"~/.local/bin/{BINARY}"),
        os.path.expanduser(f"~/.local/bin/{BINARY}.cmd"),
        os.path.expanduser(f"~/.local/bin/{BINARY}.exe"),
    ):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def check() -> dict:
    """Report CLI + auth state without changing anything."""
    path = find_cli()
    if path is None:
        return {"installed": False, "path": None, "authenticated": None,
                "version": None}
    rc, out = _run([path, "--version"], timeout=60)
    authed: Optional[bool] = None
    rc2, cfg = _run([path, "config", "show"], timeout=60)
    if rc2 == 0:
        low = cfg.lower()
        authed = not any(
            m in low for m in ("not logged in", "unauthorized", "please login",
                               "no api key", "not authenticated")
        )
    return {"installed": True, "path": path, "authenticated": authed,
            "version": out or None}


def install() -> bool:
    """Install the SDK. Returns True on success."""
    print(f"[install] pip install {PACKAGE} -U")
    for cmd in ([sys.executable, "-m", "pip", "install", PACKAGE, "-U"],
      [sys.executable, "-m", "pip", "install", "--user", PACKAGE, "-U"]):
        rc, out = _run(cmd, timeout=900)
        if rc == 0:
            print("[install] done")
            return True
        print(f"[install] attempt failed (exit {rc}): {out[:400]}")
    return False


def authenticate(assume_yes: bool = False) -> bool:
    """Run `lightning login`. The USER completes the browser flow themselves.

    This function never asks for, reads, or types a password or API key.
    """
    path = find_cli()
    if path is None:
        print("[auth] cannot authenticate: lightning CLI not found")
        return False
    if not assume_yes:
        answer = input("[auth] Run `lightning login` now? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("[auth] skipped")
            return False
    print("[auth] opening the Lightning login flow —")
    print("[auth] complete it in your browser. Do not paste credentials here.")
    rc, out = _run([path, "login"], timeout=600)
    if out:
        print(out[:2000])
    if rc != 0:
        print(f"[auth] `lightning login` exited {rc}")
        return False
    return True


def ensure_path_hint() -> None:
    """Advise on PATH when the binary exists but isn't resolvable."""
    if find_cli() is not None:
        return
    local_bin = os.path.expanduser("~/.local/bin")
    if os.path.isdir(local_bin):
        print(f"[path] If the CLI lands in {local_bin}, add it to your shell:")
        print(f'[path]   echo \'export PATH="$HOME/.local/bin:$PATH"\' >> ~/.bashrc')


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
               help="report state only; install nothing")
    ap.add_argument("--yes", action="store_true",
          help="skip the login confirmation prompt")
    args = ap.parse_args()

    state = check()
    if state["installed"]:
        print(f"[check] lightning found at {state['path']}")
        print(f"[check] version: {state['version']}")
        print(f"[check] authenticated: {state['authenticated']}")
        if args.check:
            return 0
        if state["authenticated"]:
            print("[done] already installed and authenticated — nothing to do")
            return 0
        authenticate(assume_yes=args.yes)
        post = check()
        print(f"[done] authenticated: {post['authenticated']}")
        return 0 if post["authenticated"] else 1

    print("[check] lightning CLI NOT found")
    ensure_path_hint()
    if args.check:
        return 1

    if not install():
        print("[done] install failed")
        return 1
    state = check()
    if not state["installed"]:
        ensure_path_hint()
        print("[done] installed but binary still not resolvable — check PATH")
        return 1
    print(f"[check] installed at {state['path']}")
    authenticate(assume_yes=args.yes)
    post = check()
    print(f"[done] authenticated: {post['authenticated']}")
    return 0 if post["authenticated"] else 1


if __name__ == "__main__":
    sys.exit(main())