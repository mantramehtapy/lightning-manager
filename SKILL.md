---
name: lightning-manager
description: Lightning Studio, job, and lit:// file management via CLI.
version: 1.1.0
author: Mantra Mehta
license: MIT
compatibility: Requires the lightning CLI (pip install lightning-sdk), network access, and a completed `lightning login`. POSIX-style shell recommended.
metadata:
  spec: https://agentskills.io/specification
  cli-source: https://lightning.ai/docs
---

# Lightning Manager Skill

Manage Lightning Studios — persistent cloud dev environments where files and
environment persist, CPU/GPU can be switched mid-session — plus batch jobs and
`lit://` file transfer.

This skill covers the **full lifecycle**: check for the CLI, install it if
missing, authenticate, then execute commands. Do not assume the CLI is present.

`scripts/lightning_manager.py` is the executable entry point (a
`LightningManagerSkill` class); `scripts/ensure_cli.py` handles check →
install → authenticate. Reference material lives in `references/`.

## When to Use

- User mentions a Lightning Studio, the `lightning` CLI, or `lit://` paths
- Starting, stopping, switching (CPU ↔ GPU), or SSH-ing into a studio
- Copying files to/from a studio, or running a batch training job on one
- User needs to install or authenticate the `lightning` CLI

**Don't use for:** other GPU clouds (Colab, Lambda, RunPod) or general SSH work
unrelated to Lightning studios.

## Prerequisites

None assumed. Run `scripts/ensure_cli.py` first — it is idempotent and reports
what it did.

## How to Run

Always check state before acting:

```bash
python3 scripts/ensure_cli.py --check    # report only, install nothing
python3 scripts/ensure_cli.py            # check → install → authenticate
```

Then drive the class, or call the CLI directly via the `terminal` tool:

```python
from lightning_manager import LightningManagerSkill
skill = LightningManagerSkill()
result = skill.list_studios()
print(result.to_dict())
```

`scripts/lightning_manager.py` is also runnable directly:

```bash
python3 scripts/lightning_manager.py list-studios
python3 scripts/lightning_manager.py start-studio --studio-name my-studio --machine-type H100
python3 scripts/lightning_manager.py run-job --job-name run1 --command "python train.py" \
    --machine-type H100 --image my-registry/my-training-image:latest
```

Every method returns a `LightningResult` with `.to_dict()`. **Never assume
success — check `.success` before reporting to the user.**

## Quick Reference

For broad listings, call `list_studios_across_teamspaces(...)`: query each accessible teamspace alias, use the teamspace returned by the CLI as canonical, and deduplicate by studio ID or canonical teamspace plus studio name.

| Intent | Command |
|---|---|
| List studios | `lightning studio list [--teamspace "owner/teamspace"]` |
| Start studio | `lightning studio start --name "NAME" [--machine H100]` |
| Stop studio | `lightning studio stop --name "NAME"` |
| Switch compute | `lightning studio switch --name "NAME" --machine H100` |
| SSH in | `lightning studio ssh --name "NAME"` |
| Generate SSH config | `lightning generate ssh --name "NAME"` |
| Copy files | `lightning studio cp [-r] SRC DST` |
| List jobs | `lightning list jobs` |
| Run batch job | `lightning run job --name "N" --command "CMD" --machine H100 --image IMG` |
| Show config | `lightning config show` |

## Procedure

1. **Check the CLI exists.** Run `which lightning`. Proceed only if it resolves;
   otherwise go to step 2. *Completion: `which lightning` prints a path.*
2. **Install if absent.** `pip install lightning-sdk -U`, then re-run
   `which lightning`. If the binary landed in `~/.local/bin` and is not on
   PATH, add `export PATH="$HOME/.local/bin:$PATH"` to `~/.bashrc`. *Completion:
   `lightning --version` runs.*
3. **Authenticate.** Run `lightning login` and let the user complete the browser
   flow — never type or request their credentials. Confirm afterwards with
   `lightning config show`. *Completion: config prints without an auth error.*
4. **Identify the target.** If the studio name or machine type was not given,
   ask the user rather than guessing — a wrong machine type burns budget.
   For a broad listing, query every accessible teamspace alias with
   `list_studios_across_teamspaces(...)`; use the teamspace returned by the CLI
   as canonical. Deduplicate by studio ID when available, otherwise by
   canonical teamspace plus studio name. *Completion: each studio appears once
   in the merged result.*
   *Completion: both `--name` and any `--machine` value are explicit.*
5. **Execute.** Call the matching method. *Completion: `.success` is `True` and
   `stdout` is non-empty.*
6. **Report the real output.** Quote `stdout`/`stderr` from the result. If
   `.interactive` is `True`, the method wants a parameter — ask the user the
   question in `.prompt`. *Completion: user sees actual CLI output, not a
   paraphrase.*

## Pitfalls

- **`ssh_into_studio` is not an interactive shell.** It runs with captured
  output, so a live session is unusable through this class. For real
  interactive SSH use the `terminal` tool directly.
- **Missing params return `interactive: True`, not an exception.** Check that
  field and ask the user — do not retry the same call.
- **Non-zero exit codes are returned, not raised.** A rejected machine type
  surfaces as `.error` with a hint. Never report success without checking.
- **`start` defaults to CPU if `--machine` is omitted.** The class asks
  instead of defaulting; do not pass a machine type the user did not name.
- **A stopped studio's files persist.** Stopping does not delete anything —
  confirm with the user before assuming data loss or a clean slate.
- **`studio cp` needs the full `lit://` URI** including user, teamspace,
  `studios/`, studio name, and destination path.

## Verification

Confirm the skill worked by checking the result object, not by exit code alone:

```python
r = skill.list_studios()
assert r.success, r.error          # auth + CLI working
assert r.stdout                     # real data returned
```

For a full lifecycle smoke test: start a CPU studio, `list_studios` to see it,
then `stop_studio`. Two successful calls with non-empty stdout prove install,
auth, and execution all work.