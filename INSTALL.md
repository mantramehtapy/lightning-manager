# `lightning-manager` — Hermes Agent Skill

Manage [Lightning AI](https://lightning.ai/docs) Studios — persistent cloud dev
environments — from the terminal: start and stop studios, switch CPU ↔ GPU,
copy files in and out, run batch training jobs, and open SSH sessions.

This skill is for anyone who wants an assistant to drive their Lightning
Studios for them, and for people who have never installed a command-line tool
before. It handles the whole first-run path: it checks whether the `lightning`
CLI exists, installs it if it does not, walks you through logging in, and only
then starts managing studios.

It is authored to the [Agent Skills specification](https://agentskills.io/specification),
so it is a plain `SKILL.md` file plus a `scripts/` folder — no proprietary
packaging.

---

## 1. Requirements

Check off each of these before you start.

- [ ] **WSL2 (Linux) or a POSIX shell.** The commands in this guide are Linux
      commands. Windows-native PowerShell and `cmd.exe` are **not** a supported
      path. If you are on Windows, use WSL2.
- [ ] **Python 3.8 or newer.** Check with `python3 --version`.
- [ ] **Network access** to PyPI (to install) and to Lightning AI (to log in
      and run studios).
- [ ] **A Lightning AI account.** You need one to create studios. Free tiers
      exist; you can sign up at https://lightning.ai.

---

## 2. Installation

The skill is a folder. Copy it into your Hermes skills directory.

```bash
mkdir -p ~/.hermes/skills
cp -r lightning-manager ~/.hermes/skills/
```

Verify it landed. You should see four files:

```bash
ls -R ~/.hermes/skills/lightning-manager
```

Expected layout:

```
lightning-manager/
├── SKILL.md
├── scripts/
│   ├── ensure_cli.py
│   └── lightning_manager.py
└── references/
    └── cli-reference.md
```

Hermes discovers skills automatically from this directory — no config file to
edit, no restart needed.

---

## 3. Bootstrap: check, install, authenticate

This is the part that makes the skill usable by a first-timer. Do these steps
in order.

### Step 1 — Check whether the CLI is already there

Report-only. Installs nothing, changes nothing.

```bash
cd ~/.hermes/skills/lightning-manager
python3 scripts/ensure_cli.py --check
```

| What you see | What it means |
|---|---|
| `[check] lightning found at /…/lightning` | Already installed — skip to Step 4 |
| `[check] authenticated: True` | Installed and logged in — you're done |
| `[check] lightning CLI NOT found` | Not installed — go to Step 2 |
| `[check] authenticated: False` | Installed but not logged in — go to Step 4 |

Exit code `0` means the CLI is present. Exit code `1` means it isn't.

### Step 2 — Install it

```bash
python3 scripts/ensure_cli.py
```

This does three things in order:

1. **Checks** again whether `lightning` exists.
2. **Installs** it, if missing:
   ```bash
   pip install lightning-sdk -U
   ```
   (It retries with `--user` if the first attempt is refused.) This can take a
   minute or two.
3. **Authenticates** — see Step 4.

### Step 3 — If the binary isn't found after installing

Sometimes the CLI installs into `~/.local/bin`, which may not be on your
`PATH`. You'll see a hint like this:

```
[path]   echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
```

Run exactly that command, then open a new terminal (or run `source ~/.bashrc`)
so the change takes effect. Then re-run the check:

```bash
python3 scripts/ensure_cli.py --check
```

### Step 4 — Log in

`lightning login` opens a browser window and starts a login flow.

```bash
lightning login
```

**You complete this step yourself, in your browser.** The skill will never ask
you for a password, an API key, or any other credential, and neither should
any assistant using this skill.

> **Never paste a password or API key into a chat window, a script, or a
> command.** If any tool ever asks you to, stop and don't. Legitimate login
> happens in Lightning's own browser page, never in a chat.

Confirm it worked:

```bash
lightning config show
```

It should print your configuration without an authentication error.

---

## 4. Usage

### Option A — let Hermes do it

Just ask in plain language:

> "List my Lightning studios."
> "Start a studio called `my-studio` on an H100."
> "Copy `./train.py` into the `my-studio` studio."
> "Show me my jobs."

Hermes reads `SKILL.md`, runs the bootstrap check, and calls the matching
method.

### Option B — drive the Python class yourself

```python
import sys
sys.path.insert(0, "scripts")
from lightning_manager import LightningManagerSkill

skill = LightningManagerSkill()

result = skill.list_studios()
if not result.success:
    print("FAILED:", result.error)
else:
    print(result.stdout)
```

**Always check `.success`.** The class never raises on a CLI failure — it hands
you a result object describing what went wrong.

### Option C — call the CLI directly

The script is runnable on its own:

```bash
python3 scripts/lightning_manager.py list-studios
python3 scripts/lightning_manager.py start-studio --studio-name my-studio --machine-type H100
python3 scripts/lightning_manager.py run-job --job-name run1 \
    --command "python train.py" --machine-type H100 \
    --image my-registry/my-training-image:latest
```

### The ten operations

| What you want | Python method | Direct CLI command |
|---|---|---|
| List studios | `list_studios(teamspace=None)` | `lightning studio list [--teamspace "owner/teamspace"]` |
| Start a studio | `start_studio(studio_name, machine_type)` | `lightning studio start --name "NAME" [--machine H100]` |
| Stop a studio | `stop_studio(studio_name)` | `lightning studio stop --name "NAME"` |
| Switch CPU ↔ GPU | `switch_studio(studio_name, machine_type)` | `lightning studio switch --name "NAME" --machine H100` |
| SSH into a studio | `ssh_into_studio(studio_name)` | `lightning studio ssh --name "NAME"` |
| Set up an SSH alias | `generate_ssh_config(studio_name)` | `lightning generate ssh --name "NAME"` |
| Copy files | `copy_files(source_path, dest_path, recursive=False)` | `lightning studio cp [-r] SRC DEST` |
| List jobs | `list_jobs()` | `lightning list jobs` |
| Run a batch job | `run_job(job_name, command, machine_type, image)` | `lightning run job --name "N" --command "CMD" --machine H100 --image IMG` |
| Show config | `show_config()` | `lightning config show` |

**About `lit://` paths.** To copy files into a studio you need its full URI,
which looks like this:

```
lit://<your-username>/<teamspace>/studios/<studio-name>/<path-inside>
```

For example:

```bash
python3 scripts/lightning_manager.py copy-files \
    --source-path ./main.py \
    --dest-path lit://user-123/my-teamspace/studios/my-studio/main.py
```

Directories need the recursive flag:

```python
skill.copy_files("./my-dataset/", "lit://user-123/my-teamspace/studios/my-studio/data/", recursive=True)
```

---

## 5. The result object

Every method returns a `LightningResult`. Call `.to_dict()` for a
JSON-serialisable version.

| Field | Type | What it tells you |
|---|---|---|
| `success` | bool | Did the command succeed? **Check this first.** |
| `command` | list of str | The exact command that was run |
| `stdout` | str | Normal output from the CLI |
| `stderr` | str | Error output from the CLI |
| `returncode` | int | Exit code; `0` is success, `124` is a timeout |
| `error` | str or None | A plain-English explanation when something failed |
| `interactive` | bool | `True` means a parameter is missing and you should be asked |
| `missing_params` | list of str | Which parameters were missing |
| `prompt` | str or None | The exact question to ask the user |

Two behaviours worth knowing:

- **Failures are returned, never raised.** A rejected machine type comes back
  as `success: False` with an `error` message, not a Python exception. Check
  the result — don't assume.
- **`interactive: True` means "ask the user."** If you leave out a required
  parameter, the class deliberately does *not* run the command, because the
  real CLI would open an interactive prompt and hang. Instead it hands back the
  question in `prompt` so it can be asked properly. Example:

  ```python
  r = skill.start_studio("my-studio")          # no machine given
  print(r.interactive)                          # True
  print(r.prompt)   # Which machine should I start it on? e.g. H100 — or say 'CPU'…
  ```

---

## 6. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `command not found: lightning` | Not installed, or `~/.local/bin` isn't on `PATH` | Run `python3 scripts/ensure_cli.py`; if Step 3's hint appears, add the `export PATH=…` line to `~/.bashrc` and reopen the terminal |
| Any command returns an auth error | Not logged in | `lightning login`, then confirm with `lightning config show` |
| `Machine type was rejected` | Invalid or unsupported machine value | Run `lightning studio list` to see what your account supports. **Never guess a machine type — GPUs cost real money.** |
| Studio not found | Wrong name, or wrong teamspace | `lightning studio list` to see exact names |
| `… not found on PATH` from the Python class | Binary resolution failed | Same fix as the first row. The class also looks in `~/.local/bin` directly, so this usually means it genuinely isn't installed. |
| Copy fails with a path error | Incomplete `lit://` URI | Use the full form: `lit://user/teamspace/studios/studio/path` |

### One important caveat about SSH

`ssh_into_studio()` is **not** an interactive shell. It runs the command with
its output captured, so a live terminal session cannot survive the call — you
will get a truncated result rather than a usable prompt.

If you need a real interactive SSH session, run the command yourself in a
terminal instead of through the skill:

```bash
lightning studio ssh --name "my-studio"
```

The `ssh_into_studio` method is still useful for scripted checks (confirming
the studio is reachable); it is just not a substitute for sitting in the
session.

---

## 7. Verification status

Being straight with you about what has and hasn't been tested:

- **Verified:** both Python scripts compile cleanly (`py_compile`). All ten
  operations were exercised against a local stub CLI inside WSL2 — recursive
  directory copy forwards the `-r` flag correctly, command arguments
  containing spaces survive shell quoting intact, an invalid machine type
  returns exit code 2 with the correct hint, missing parameters return
  `interactive: True` with a prompt, and a missing binary is detected and
  reported rather than crashing.
- **Verified:** the "CLI not installed" detection path works — on this
  machine `lightning` is genuinely not installed, and `ensure_cli.py --check`
  correctly reported it and exited 1.

- **Not verified:** this skill has **never been run against the real Lightning
  AI service** or a live Lightning account. No studio has been created, no job
  has been submitted, and no real GPU has been requested. The exact flag names
  and output formats come from Lightning's published CLI documentation, not
  from live testing.

- **Not verified:** `ssh_into_studio` and `generate_ssh_config` have only been
  exercised against the stub. Interactive SSH behaviour is untested in
  practice.

Expect to need small adjustments on first real use — most likely in the
machine-type names or the exact wording of `lit://` URIs in your account.

---

## 8. Where to go next

- `references/cli-reference.md` in the skill folder — the command reference,
  the `lit://` URI format, the typical start → copy → switch → train → stop
  workflow, and a troubleshooting table.
- <https://lightning.ai/docs> — official Lightning documentation.
- <https://agentskills.io/specification> — the Agent Skills specification this
  skill follows.

## License

MIT. Contributed by Mantra Mehta.
