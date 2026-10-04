# lightning-manager

A [Hermes Agent](https://hermes-agent.nousresearch.com/docs) skill for managing
[Lightning AI](https://lightning.ai/docs) Studios — persistent cloud dev
environments — from the terminal.

Start and stop studios, switch CPU ↔ GPU, copy files in and out, run batch
training jobs, and open SSH sessions. The skill handles the entire first-run
path for people who have never installed a command-line tool: it checks whether
the `lightning` CLI exists, installs it if missing, and walks you through
logging in before it manages anything.

Built to the [Agent Skills specification](https://agentskills.io/specification) —
a plain `SKILL.md` with YAML frontmatter, plus `scripts/` and `references/`.

## Install

```bash
git clone https://github.com/mantramehtapy/lightning-manager.git
mkdir -p ~/.hermes/skills
cp -r lightning-manager ~/.hermes/skills/
```

<details>
<summary>No Git? Download the zip instead.</summary>

Grab `lightning-manager.zip` from the repo page, unzip it, then:

```bash
mkdir -p ~/.hermes/skills
cp -r lightning-manager ~/.hermes/skills/
```

</details>

Hermes discovers skills automatically from `~/.hermes/skills/` — no config to
edit, no restart needed.

Verify:

```bash
ls -R ~/.hermes/skills/lightning-manager
```

## Quickstart

Check whether the CLI is installed (report-only, installs nothing):

```bash
cd ~/.hermes/skills/lightning-manager
python3 scripts/ensure_cli.py --check
```

Then install and authenticate in one step:

```bash
python3 scripts/ensure_cli.py
```

Log in when prompted — `lightning login` opens a browser and you complete the
flow yourself. Never paste a password or API key into a chat or a script.

Confirm it worked:

```bash
lightning config show
```

## Usage

Ask Hermes in plain language — "list my studios", "start a studio called
`my-studio` on an H100", "copy `./train.py` into `my-studio`" — or drive the
Python class yourself:

```python
import sys
sys.path.insert(0, "scripts")
from lightning_manager import LightningManagerSkill

skill = LightningManagerSkill()
result = skill.list_studios()
print(result.success, result.stdout, result.error)
```

Or call the CLI directly:

```bash
python3 scripts/lightning_manager.py list-studios
python3 scripts/lightning_manager.py start-studio --studio-name my-studio --machine-type H100
python3 scripts/lightning_manager.py copy-files \
    --source-path ./train.py \
    --destination-path lit://user/teamspace/studios/my-studio/train.py
```

### Operations

| What you want | Python method | Direct CLI command |
|---|---|---|
| List studios | `list_studios(teamspace=None)` | `lightning studio list [--teamspace "owner/teamspace"]` |
| Broad studio listing | `list_studios_across_teamspaces([...])` | Repeats `--teamspace`, uses CLI canonical teamspace, deduplicates by studio ID or canonical teamspace + name |
| Start a studio | `start_studio(studio_name, machine_type)` | `lightning studio start --name "NAME" [--machine H100]` |
| Stop a studio | `stop_studio(studio_name)` | `lightning studio stop --name "NAME"` |
| Switch CPU ↔ GPU | `switch_studio(studio_name, machine_type)` | `lightning studio switch --name "NAME" --machine H100` |
| SSH into a studio | `ssh_into_studio(studio_name)` | `lightning studio ssh --name "NAME"` |
| Set up an SSH alias | `generate_ssh_config(studio_name)` | `lightning generate ssh --name "NAME"` |
| Copy files | `copy_files(source_path, dest_path, recursive=False)` | `lightning studio cp [-r] SRC DEST` |
| List jobs | `list_jobs()` | `lightning list jobs` |
| Run a batch job | `run_job(job_name, command, machine_type, image)` | `lightning run job --name "N" --command "CMD" --machine H100 --image IMG` |
| Show config | `show_config()` | `lightning config show` |

### Results, not exceptions

Every method returns a `LightningResult`. Failures are **returned, never
raised** — check `.success` first.

| Field | Meaning |
|---|---|
| `success` | Did it work? |
| `stdout` / `stderr` | CLI output |
| `returncode` | Exit code (`0` ok, `124` timeout) |
| `error` | Plain-English failure explanation |
| `interactive` | `True` means a parameter is missing — ask the user |
| `missing_params` | Which parameters were missing |
| `prompt` | The exact question to ask |

If you omit a required parameter, the skill deliberately does *not* run the
command, because the real CLI would open an interactive prompt and hang. It
hands back the question in `prompt` instead. Never guess a machine type —
GPUs cost real money.

## Requirements

- WSL2 (Linux) or a POSIX shell. Windows-native PowerShell and `cmd.exe` are
  not supported.
- Python 3.8+
- Network access to PyPI and Lightning AI
- A Lightning AI account (<https://lightning.ai>)

## Troubleshooting

| Symptom | Fix |
|---|---|
| `command not found: lightning` | Run `python3 scripts/ensure_cli.py`; if a `PATH` hint appears, add the `export PATH=…` line to `~/.bashrc` and reopen the terminal |
| Auth errors | `lightning login`, then confirm with `lightning config show` |
| Machine type rejected | `lightning studio list` to see what your account supports |
| Studio not found | `lightning studio list` for exact names |
| Copy fails on a path | Use the full `lit://user/teamspace/studios/studio/path` form |

`ssh_into_studio()` is **not** an interactive shell — output is captured, so a
live session cannot survive the call. For a real interactive SSH session, run
`lightning studio ssh --name "NAME"` in a real terminal.

## Verification status

Both scripts compile cleanly and all ten operations were exercised against a
local stub CLI inside WSL2 — argument forwarding, recursive copy, shell quoting
of values containing spaces, invalid machine type handling, missing-parameter
prompts, and missing-binary detection.

**This skill has never been run against the real Lightning AI service or a live
Lightning account.** No studio has been created and no GPU has been requested.
Flag names and output formats come from Lightning's published documentation,
not live testing, so expect minor drift on first real use.

## Documentation

- [`INSTALL.md`](INSTALL.md) — full step-by-step installation and usage guide
- `references/cli-reference.md` — command reference and `lit://` URI format

## License

MIT — see [LICENSE](LICENSE).