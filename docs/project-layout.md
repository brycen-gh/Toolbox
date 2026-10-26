# Project layout

- `main.py` starts the desktop app and coordinates action execution.
- `ui/` contains Home, collection pages, preferences and client setup dialogs.
- `execution_engines/` contains action execution, domain validation and shared proxy helpers.
- `execution_engines/docker_engines/` keeps each service recipe independent.
- `menus/` describes navigation; `variables/` stores editable settings.
- `assets/` contains icons and the public browser portal.
- `scripts/` contains packaging, LAN forwarding and maintenance helpers.
- `run-once/` prepares a development environment on Windows or Linux.
- `tests/` contains regression coverage and optional desktop checks.
- `docs/` contains operating guides and design notes.

`repos/`, `backups/`, `share/` and `data/` are local working data. They are
excluded from Git and are never included automatically in a portable release.
The offline repositories and backups are deliberately preserved during cleanup.
Personal workspace notes are under `docs/notes/` and remain untracked.

`build/`, `dist/`, `__pycache__/` and `.setup-complete` are generated. A portable
build creates a new output folder; retain the release you use and discard old
unconfigured builds. Keep a configured release's settings and data before
removing it. Local launchers and `.venv/` remain available for development.

The optional copy-to-local Linux helper is `scripts/copy-local.sh`.
