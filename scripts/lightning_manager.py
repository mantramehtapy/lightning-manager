"""
LightningManagerSkill — a Hermes tool definition wrapping the Lightning CLI.

A Lightning Studio is a persistent cloud dev environment: files and environment
persist, it can start on CPU, switch to GPU for training, and be shut down when
done. This class exposes one typed method per documented `lightning` command and
returns a structured result dict instead of raising on CLI failure.

This module does not install or authenticate anything. Run
`scripts/ensure_cli.py` first — it checks whether the `lightning` CLI exists,
installs `lightning-sdk` if it is missing, and runs `lightning login`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

# ---------------------------------------------------------------------------
# Structured result object
# ---------------------------------------------------------------------------


@dataclass
class LightningResult:
    """Outcome of a single `lightning` CLI invocation."""

    success: bool
    command: List[str]
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    # Set when the call could not run at all (missing binary, bad params).
    error: Optional[str] = None
    # Set when a required parameter is missing and the CLI would prompt instead.
    interactive: bool = False
    missing_params: List[str] = field(default_factory=list)
    # Hint for the agent on what to ask the user next.
    prompt: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "command": " ".join(self.command),
            "stdout": self.stdout,
            "stderr": self.stderr,
            "returncode": self.returncode,
            "error": self.error,
            "interactive": self.interactive,
            "missing_params": list(self.missing_params),
            "prompt": self.prompt,
        }


def _interactive(
    command: List[str], missing: List[str], prompt: str
) -> LightningResult:
    """Mirror the CLI: a missing required option means 'ask the user first'."""
    return LightningResult(
        success=False,
        command=command,
        interactive=True,
        missing_params=missing,
        prompt=prompt,
        error=f"Missing required parameter(s): {', '.join(missing)}",
    )


def _clean_teamspace(value: str) -> str:
    """Normalize a teamspace for stable comparison without changing display text."""
    return re.sub(r"\s+", " ", value.strip().strip("/\\")).casefold()


def _json_records(value: Any) -> Iterable[Dict[str, Any]]:
    """Yield nested JSON mappings that may represent studio records."""
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _json_records(child)
    elif isinstance(value, list):
        for child in value:
            yield from _json_records(child)


def _canonical_teamspace(text: str, requested: str) -> str:
    """Prefer the teamspace returned by the CLI over the requested alias."""
    try:
        payload = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        payload = None
    if payload is not None:
        for record in _json_records(payload):
            for key in ("canonical_teamspace", "teamspace", "team_space", "teamspace_name"):
                value = record.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

    match = re.search(
        r"(?im)^\s*(?:canonical\s+)?team\s*space\s*[:|]\s*([^|\n]+?)\s*$",
        text,
    )
    return match.group(1).strip() if match else requested


def _studio_key(line: str, canonical_teamspace: str) -> Tuple[str, ...]:
    """Build a dedupe key: studio ID first, then teamspace/name, then row."""
    id_match = re.search(
        r"(?i)\b(?:studio[_ -]?id|studio[- ]?id|id)\s*[:=]\s*[\"']?([A-Za-z0-9._:-]+)",
        line,
    )
    if id_match:
        return ("id", id_match.group(1).casefold())

    name_match = re.search(
        r"(?i)\b(?:studio[_ -]?name|studio|name)\s*[:=]\s*[\"']?([^,|]+?)['\"]?\s*(?:,|\||$)",
        line,
    )
    if name_match:
        return ("name", _clean_teamspace(canonical_teamspace), name_match.group(1).strip().casefold())
    return ("row", _clean_teamspace(canonical_teamspace), re.sub(r"\s+", " ", line.strip()).casefold())


def _dedupe_listing(outputs: Sequence[Tuple[str, str]]) -> str:
    """Merge teamspace listings while preserving first-seen rows."""
    seen: set[Tuple[str, ...]] = set()
    merged: List[str] = []
    for requested, output in outputs:
        canonical = _canonical_teamspace(output, requested)
        for line in output.splitlines():
            if not line.strip():
                continue
            key = _studio_key(line, canonical)
            if key not in seen:
                seen.add(key)
                merged.append(line)
    return "\n".join(merged)


class LightningManagerSkill:
    """Manage Lightning Studios, jobs, and GPU switching from the terminal.

    Usage:
        skill = LightningManagerSkill()
        skill.list_studios()
        skill.start_studio("my-studio", machine_type="H100")
    """

    name = "lightning_manager"
    description = "Manage Lightning Studios, jobs, file transfer, and GPU switching via the lightning CLI."

    def __init__(
        self,
        binary: str = "lightning",
        shell: bool = True,
        default_teamspace: Optional[str] = None,
        timeout: Optional[int] = 900,
    ) -> None:
        self.binary = binary
        # shell=True so the command runs inside the WSL2 bash environment.
        self.shell = shell
        self.default_teamspace = default_teamspace
        self.timeout = timeout

    # -- internals ---------------------------------------------------------

    def _require(self, value: Optional[str], name: str) -> bool:
        return bool(value) and bool(str(value).strip())

    def _resolve_binary(self) -> Optional[str]:
        """Locate the CLI. `which` alone misses extensionless POSIX scripts."""
        if os.path.isfile(self.binary) and os.access(self.binary, os.X_OK):
            return self.binary
        found = shutil.which(self.binary)
        if found:
            return found
        if shutil.which(f"{self.binary}.exe") or shutil.which(f"{self.binary}.cmd"):
            return f"{self.binary}.cmd"
        return None

    def _run(self, command: List[str]) -> LightningResult:
        """Execute a `lightning` command and capture stdout/stderr."""
        if self._resolve_binary() is None:
            return LightningResult(
                success=False,
                command=command,
                error=(
                    f"`{self.binary}` not found on PATH. Verify inside WSL2 with "
                    f"`which {self.binary}`."
                ),
            )
        try:
            # shell=True takes a single string, so args must be pre-quoted.
            # shlex.quote is POSIX-correct (the WSL2 target) but emits single
            # quotes that cmd.exe on Windows misparses — use list2cmdline there.
            if not self.shell:
                argv: Any = command
            elif os.name == "nt":
                argv = subprocess.list2cmdline(command)
            else:
                argv = " ".join(shlex.quote(a) for a in command)
            proc = subprocess.run(
                argv,
                shell=self.shell,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            return LightningResult(
                success=False,
                command=command,
                error=f"`{' '.join(command)}` timed out after {self.timeout}s.",
                returncode=124,
            )
        except OSError as exc:  # permission denied, exec format, etc.
            return LightningResult(
                success=False, command=command, error=f"Failed to run CLI: {exc}"
            )
        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            hint = ""
            low = stderr.lower()
            if "machine" in low and ("invalid" in low or "not found" in low):
                hint = " Machine type was rejected — check `lightning studio list` for valid options."
            elif "not found" in low and "studio" in low:
                hint = " No such studio — list studios first with `list_studios()`."
            elif "unauthorized" in low or "login" in low:
                hint = " Not authenticated — run `lightning login` in the WSL2 terminal."
            return LightningResult(
                success=False,
                command=command,
                stdout=(proc.stdout or "").strip(),
                stderr=stderr,
                returncode=proc.returncode,
                error=f"Exit code {proc.returncode}.{hint}",
            )

        return LightningResult(
            success=True,
            command=command,
            stdout=(proc.stdout or "").strip(),
            stderr=(proc.stderr or "").strip(),
            returncode=0,
        )

    # -- studios -----------------------------------------------------------

    def list_studios(
        self,
        teamspace: Optional[Union[str, Sequence[str]]] = None,
    ) -> LightningResult:
        """List studios, optionally across multiple teamspace aliases.

        For broad discovery, pass a sequence of accessible teamspaces. Each
        alias is queried separately; the CLI's returned teamspace is treated
        as canonical and duplicate studios are removed from the merged output.
        """
        if isinstance(teamspace, (list, tuple, set)):
            return self.list_studios_across_teamspaces(teamspace)
        cmd = [self.binary, "studio", "list"]
        tspace = teamspace or self.default_teamspace
        if self._require(tspace, "teamspace"):
            cmd += ["--teamspace", str(tspace)]
        return self._run(cmd)

    def list_studios_across_teamspaces(
        self, teamspaces: Optional[Iterable[str]] = None
    ) -> LightningResult:
        """Query each accessible teamspace and return a deduplicated listing."""
        requested = []
        for value in teamspaces or []:
            if self._require(value, "teamspace") and value not in requested:
                requested.append(str(value))
        if not requested:
            return _interactive(
                [self.binary, "studio", "list"],
                ["teamspaces"],
                "Which accessible teamspaces should I query for a broad studio listing?",
            )

        results: List[Tuple[str, str]] = []
        failures: List[str] = []
        for value in requested:
            result = self._run([self.binary, "studio", "list", "--teamspace", value])
            if result.success:
                results.append((value, result.stdout))
            else:
                failures.append(f"{value}: {result.error or result.stderr or 'list failed'}")

        if not results:
            return LightningResult(
                success=False,
                command=[self.binary, "studio", "list"],
                stderr="\n".join(failures),
                returncode=1,
                error="Every teamspace listing failed.",
            )
        merged = _dedupe_listing(results)
        warning = "\n".join(failures)
        return LightningResult(
            success=True,
            command=[self.binary, "studio", "list", "--teamspace", "<each accessible teamspace>"],
            stdout=merged,
            stderr=warning,
            returncode=0,
        )

    def start_studio(
        self, studio_name: Optional[str] = None, machine_type: Optional[str] = None
    ) -> LightningResult:
        """`lightning studio start --name "my-studio" [--machine H100]`

        `machine_type` is optional in the CLI: without it the studio starts on
        CPU. This method flags it as interactive so the agent can offer the
        choice rather than silently defaulting.
        """
        cmd = [self.binary, "studio", "start", "--name", str(studio_name or "")]
        if not self._require(studio_name, "studio_name"):
            return _interactive(
                cmd,
                ["studio_name"],
                "Which studio should I start? (pass studio_name)",
            )
        if not self._require(machine_type, "machine_type"):
            return _interactive(
                cmd,
                ["machine_type"],
                "Which machine should I start it on? e.g. H100 — or say 'CPU' to start without a GPU.",
            )
        cmd += ["--machine", str(machine_type)]
        return self._run(cmd)

    def stop_studio(self, studio_name: Optional[str] = None) -> LightningResult:
        """`lightning studio stop --name "my-studio"`"""
        cmd = [self.binary, "studio", "stop", "--name", str(studio_name or "")]
        if not self._require(studio_name, "studio_name"):
            return _interactive(
                cmd, ["studio_name"], "Which studio should I stop? (pass studio_name)"
            )
        return self._run(cmd)

    def switch_studio(
        self, studio_name: Optional[str] = None, machine_type: Optional[str] = None
    ) -> LightningResult:
        """`lightning studio switch --name "my-studio" --machine H100`"""
        cmd = [self.binary, "studio", "switch", "--name", str(studio_name or "")]
        if not self._require(studio_name, "studio_name"):
            return _interactive(
                cmd, ["studio_name"], "Which studio should I switch? (pass studio_name)"
            )
        if not self._require(machine_type, "machine_type"):
            return _interactive(
                cmd, ["machine_type"], "Which machine should I switch to? e.g. H100"
            )
        cmd += ["--machine", str(machine_type)]
        return self._run(cmd)

    def ssh_into_studio(
        self, studio_name: Optional[str] = None
    ) -> LightningResult:
        """`lightning studio ssh --name "my-studio"` (interactive session)"""
        cmd = [self.binary, "studio", "ssh", "--name", str(studio_name or "")]
        if not self._require(studio_name, "studio_name"):
            return _interactive(
                cmd, ["studio_name"], "Which studio should I SSH into? (pass studio_name)"
            )
        return self._run(cmd)

    def generate_ssh_config(self, studio_name: Optional[str] = None) -> LightningResult:
        """`lightning generate ssh --name "my-studio"`"""
        cmd = [self.binary, "generate", "ssh", "--name", str(studio_name or "")]
        if not self._require(studio_name, "studio_name"):
            return _interactive(
                cmd, ["studio_name"], "Which studio's SSH config should I generate?"
            )
        return self._run(cmd)

    # -- files -------------------------------------------------------------

    def copy_files(
        self,
        source_path: Optional[str] = None,
        destination_path: Optional[str] = None,
        recursive: bool = False,
    ) -> LightningResult:
        """`lightning studio cp [-r] <source> <destination>`

        Paths are `lit://` URIs, e.g.
        lit://user-123/my-teamspace/studios/my-studio/main.py
        """
        cmd = [self.binary, "studio", "cp"]
        if recursive:
            cmd.append("-r")
        cmd += [str(source_path or ""), str(destination_path or "")]
        missing = []
        if not self._require(source_path, "source_path"):
            missing.append("source_path")
        if not self._require(destination_path, "destination_path"):
            missing.append("destination_path")
        if missing:
            return _interactive(
                cmd, missing, "I need both a source and a destination (lit:// URI)."
            )
        return self._run(cmd)

    # -- jobs --------------------------------------------------------------

    def list_jobs(self) -> LightningResult:
        """`lightning list jobs`"""
        return self._run([self.binary, "list", "jobs"])

    def run_job(
        self,
        job_name: Optional[str] = None,
        command: Optional[str] = None,
        machine_type: Optional[str] = None,
        image: Optional[str] = None,
    ) -> LightningResult:
        """`lightning run job --name ... --command ... --machine H100 --image ...`

        `image` is optional per the article; when omitted the CLI uses the
        default training image, so we prompt rather than guess a registry path.
        """
        cmd = [self.binary, "run", "job", "--name", str(job_name or "")]
        if not self._require(job_name, "job_name"):
            return _interactive(cmd, ["job_name"], "What should I name the job?")
        if not self._require(command, "command"):
            return _interactive(
                cmd, ["command"], "What command should the job run? e.g. \"python train.py\""
            )
        cmd += ["--command", str(command)]
        if not self._require(machine_type, "machine_type"):
            return _interactive(
                cmd, ["machine_type"], "Which machine should run the job? e.g. H100"
            )
        cmd += ["--machine", str(machine_type)]
        if not self._require(image, "image"):
            return _interactive(
                cmd,
                ["image"],
                "Which container image? e.g. my-registry/my-training-image:latest — or say 'default'.",
            )
        cmd += ["--image", str(image)]
        return self._run(cmd)

    # -- config ------------------------------------------------------------

    def show_config(self) -> LightningResult:
        """`lightning config show`"""
        return self._run([self.binary, "config", "show"])


def _build_parser() -> "argparse.ArgumentParser":
    ap = argparse.ArgumentParser(
        prog="lightning_manager.py",
        description="Manage Lightning Studios, jobs, and file transfer via the lightning CLI.",
    )
    ap.add_argument("--binary", default="lightning", help="path to the lightning CLI")
    ap.add_argument("--timeout", type=int, default=900)
    sub = ap.add_subparsers(dest="op", metavar="OPERATION")

    p = sub.add_parser("list-studios", help="lightning studio list")
    p.add_argument(
        "--teamspace",
        action="append",
        help="teamspace to query; repeat for broad listing across aliases",
    )

    p = sub.add_parser("start-studio", help="lightning studio start")
    p.add_argument("--studio-name")
    p.add_argument("--machine-type")

    p = sub.add_parser("stop-studio", help="lightning studio stop")
    p.add_argument("--studio-name")

    p = sub.add_parser("switch-studio", help="lightning studio switch")
    p.add_argument("--studio-name")
    p.add_argument("--machine-type")

    p = sub.add_parser("ssh-into-studio", help="lightning studio ssh")
    p.add_argument("--studio-name")

    p = sub.add_parser("generate-ssh-config", help="lightning generate ssh")
    p.add_argument("--studio-name")

    p = sub.add_parser("copy-files", help="lightning studio cp")
    p.add_argument("--source-path")
    p.add_argument("--destination-path")
    p.add_argument("-r", "--recursive", action="store_true")

    sub.add_parser("list-jobs", help="lightning list jobs")

    p = sub.add_parser("run-job", help="lightning run job")
    p.add_argument("--job-name")
    p.add_argument("--command")
    p.add_argument("--machine-type")
    p.add_argument("--image")

    sub.add_parser("show-config", help="lightning config show")
    return ap


def _dispatch(skill: "LightningManagerSkill", a: "argparse.Namespace") -> LightningResult:
    ops = {
        "list-studios": lambda: skill.list_studios(a.teamspace),
        "start-studio": lambda: skill.start_studio(a.studio_name, a.machine_type),
        "stop-studio": lambda: skill.stop_studio(a.studio_name),
        "switch-studio": lambda: skill.switch_studio(a.studio_name, a.machine_type),
        "ssh-into-studio": lambda: skill.ssh_into_studio(a.studio_name),
        "generate-ssh-config": lambda: skill.generate_ssh_config(a.studio_name),
        "copy-files": lambda: skill.copy_files(a.source_path, a.destination_path, a.recursive),
        "list-jobs": lambda: skill.list_jobs(),
        "run-job": lambda: skill.run_job(a.job_name, a.command, a.machine_type, a.image),
        "show-config": lambda: skill.show_config(),
    }
    if not a.op:
        raise SystemExit(_build_parser().format_help())
    return ops[a.op]()


if __name__ == "__main__":
    import json

    _args = _build_parser().parse_args()
    _skill = LightningManagerSkill(binary=_args.binary, timeout=_args.timeout)
    _res = _dispatch(_skill, _args)
    print(json.dumps(_res.to_dict(), indent=2))
    raise SystemExit(0 if _res.success else 1)
