# Lightning CLI Reference

Source: Joe Mannix, "Working with the Lightning CLI to Manage Lightning
Studios" (Lightning AI, February 24, 2026). The `lit://` URI shape and studio
lifecycle semantics below come from that article.

## Studio lifecycle

| Command | Notes |
|---|---|
| `lightning studio list` | Add `--teamspace "owner/teamspace-name"` to scope; repeat it for broad listings and deduplicate by the CLI canonical teamspace plus studio identity |
| `lightning studio start --name "my-studio"` | `--machine H100` optional; CPU if omitted |
| `lightning studio stop --name "my-studio"` | Files persist — stopping is not deleting |
| `lightning studio switch --name "my-studio" --machine H100` | Change compute on a running studio |
| `lightning studio ssh --name "my-studio"` | Interactive session; not scriptable |
| `lightning generate ssh --name "my-studio"` | Writes an SSH alias you can use directly |

## File transfer

```
lightning studio cp ./main.py lit://user-123/my-teamspace/studios/my-studio/main.py
lightning studio cp -r ./my-dataset/ lit://user-123/my-teamspace/studios/my-studio/data/
```

The `lit://` URI is: `lit://<user>/<teamspace>/studios/<studio>/<path>`.
`-r` is required for directories.

## Jobs

```
lightning list jobs
lightning run job --name "training-run" --command "python train.py" \
    --machine H100 --image "my-registry/my-training-image:latest"
```

## Config

```
lightning config show
```

## Typical workflow

1. `studio start` on CPU to write and debug code
2. `studio cp` code and data into the studio
3. `studio switch --machine H100` when ready to train
4. `run job` for the training run, or `studio ssh` to drive it interactively
5. `studio stop` when finished

## Machine types

`H100` is the example throughout the source article. Treat the set of valid
values as whatever `lightning studio list` reports — do not hardcode a list,
and never pass a machine type the user did not name, since GPU cost is real.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `command not found: lightning` | Not installed, or `~/.local/bin` off PATH | Run `scripts/ensure_cli.py` |
| Auth error on any command | Not logged in | `lightning login`, then `lightning config show` |
| Machine type rejected | Invalid/unsupported value | Check `lightning studio list` |
| Studio not found | Wrong name or teamspace | `lightning studio list` |