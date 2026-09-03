# Legion

Linux-first, open-source, CLI-first command-and-control for a fleet of autonomous **Sentinel** nodes.

The executable is `legionctl`. Fleet configuration documents are **SOI profiles**.

## Purpose

Legion is the Sentinel **management plane**. An operator can:

- Discover and inventory Sentinel nodes
- Inspect status and health
- Create, validate, version, and deploy SOI profiles
- Issue safe operational commands (test Discord alert, bounded diagnostic scan, reboot)
- Retrieve recent event metadata
- Store per-node API credentials securely

Sentinel nodes remain autonomous. Local SOI detection, cooldown enforcement, alert queueing, and Discord webhook delivery continue if Legion is offline.

## Non-goals (version 1)

- Graphical desktop UI or web dashboard
- MQTT, OTA firmware, SSH/serial management
- Cloud accounts or a required database server
- Raw packet capture / PCAP
- Discord bot command parsing
- Docker or Kubernetes as a runtime requirement

## Security model

- Discord is the Sentinel **notification plane**. Legion never issues commands through Discord.
- Bearer tokens are stored in the OS keyring (`service=legionctl`, `account=<sentinel_id>`), with an encrypted local fallback when no keyring backend is available.
- Tokens are never accepted as shell arguments, never written to inventory/profile/audit files, and never printed.
- TLS certificate verification is on by default.
- Write and disruptive operations require an explicit target, confirmation (or `--yes`), and support `--dry-run`.

**Use Sentinel nodes only with authorized SOIs and authorized deployments.**

## Requirements

- Linux (primary target)
- Python 3.11 or newer

## Install

With [pipx](https://pipx.pypa.io/) from a local checkout:

```bash
pipx install .
```

Editable developer install:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Bootstrap flow

```bash
legionctl discover
legionctl discover --add
legionctl node list
legionctl credential set sentinel-north-door-01 --token-stdin
legionctl status --all
```

## Profile validation and deployment

```bash
legionctl profile validate docs/examples/event-alpha.json
legionctl profile import docs/examples/event-alpha.json
legionctl profile push event-alpha --group event-alpha
```

Milestone 1 supports local validation and inventory listing without a network:

```bash
legionctl profile validate docs/examples/event-alpha.json
legionctl node list
legionctl group list
```

## Data locations (XDG)

```text
$XDG_CONFIG_HOME/legion/   # config.json, inventory.json, profiles/
$XDG_DATA_HOME/legion/     # schema/
$XDG_STATE_HOME/legion/    # audit.jsonl, discovery cache
```

Defaults: `~/.config/legion`, `~/.local/share/legion`, `~/.local/state/legion`.

## Development

```bash
pytest
ruff check src tests
mypy src tests
```
