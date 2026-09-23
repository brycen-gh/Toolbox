# Toolbox


# Might need to run the following command in PowerShell to allow scripts to run:
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned

# Activate the venv (relative path – works)
.\.venv\Scripts\Activate.ps1

# Make sure the packages are installed
python -m pip install customtkinter pyyaml

# If downloaded from Windows and being ran on a 
dos2unix run-once/run-once
./run-once/run-once
```

The interactive setup provides five choices:

| Choice | Purpose |
| --- | --- |
| 1. Prepare this computer (online) | Installs missing system requirements, creates `.venv`, and downloads current Python dependencies from online sources. Local wheels are ignored. |
| 2. Prepare from `./repos` (offline) | Installs system packages and Python wheels only from the portable repositories. |
| 3. Download/update `./repos` | Refreshes offline Python wheels and matching OS packages without installing the application. |
| 4. Download, then prepare | Refreshes the portable repositories and installs from that downloaded set. |
| 5. Exit | Leaves the project unchanged. |

The same operations can be selected non-interactively:

```bash
./run-once/run-once --prepare
./run-once/run-once --offline
./run-once/run-once --download-repos
./run-once/run-once --download-and-prepare
```

The setup is safe to rerun. It updates the virtual environment and dependencies, checks that every menu YAML file parses into a mapping, validates dependency and execution-engine imports, recreates the launcher, and refreshes `.setup-complete`. Repository-download modes stage a complete replacement before removing obsolete wheels or OS packages.

Setup loads `execution_engines/main.py` and its deployment, training, troubleshooting, and result modules, then verifies that the dispatcher has callable action handlers. This check does not execute actions or contact Docker or SSH targets. It works even when setup is launched from outside the project directory. Full validation of menu action IDs, required parameters, and variable references is not yet implemented.

The setup creates `repos/containers` but does not download Docker images. Images are downloaded later from **Deployment → Prep Install → Save/Update Images**.

## What `run-once/run-once` installs

The system package set is intentionally small:

- Python 3
- pip
- Python virtual-environment support
- Tkinter
- `tcpreplay`

On Debian/Ubuntu, optional recommended packages and unnecessary font-provider families are skipped. DejaVu Core and Mono are retained for basic GUI and symbol coverage.

The Python environment installs:

- CustomTkinter
- PyYAML
- Pillow
- cryptography
- Paramiko

After a successful run, `.setup-complete` records the completion time, setup mode, host, operating system, architecture, Python and library versions, validated YAML count, execution-engine location and validation status, virtual-environment path, and launcher path.

## Starting the toolbox

Always use the generated launcher:

```bash
./run_toolbox.sh
```

The launcher uses `.venv/bin/python`. Running `python3 main.py` uses the system Python and can produce `ModuleNotFoundError` even though setup completed successfully.

For local Windows Host Actions, copy the project to the Windows training VM and run PowerShell as the intended exercise account:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\run-once\run-once.ps1
.\run_toolbox.ps1
```

The Windows setup creates `.venv\Scripts\python.exe`, installs the Python requirements, validates menu parsing and engine registration, and writes `.setup-complete`. It is an online setup and does not install or configure Sysmon, Windows audit policy, or PowerShell logging. Run the toolbox as Administrator only for exercises that say elevation is required.

Actions requiring local sudo access prompt for the password inside the application and keep it in memory for the session.

## Interface basics

- **Home** clears the sidebar selection and displays informational content.
- **Select YAML...** switches between Deployment, Training, and Troubleshooting.
- Categories expand and collapse in the sidebar.
- Selecting an action displays its description and enables **Run Script**.
- **Settings → Variable Settings** edits the variable file belonging to the selected menu.
- The search field is case-insensitive and supports shell-style wildcards such as `*docker*`, `install*`, `?tfd`, and `[NU]*cloud*`.
- Action output, standard output, standard error, and exit status are displayed inside the application.
- Actions run in a background worker. Local command output appears while they run; **Cancel Action** requests cancellation. Remote diagnostics finish their current command before stopping. Container stop/restart recovery finishes before cancellation completes. Menu selection is held while an action is running.
- Output is preserved while an action runs and when it finishes. Selecting another action or category clears the panel. The red eraser beside **Run Script**, labeled **Clear output** on hover, clears displayed text without stopping the action; new output continues appearing.

### Appearance options

The Home page **Options** button supports:

- Blue, Green, and Dark Blue themes.
- Light, Dark, and System appearance modes.
- An optional Home background image.

UI choices are stored in `variables/ui.yaml`. A selected background outside the project is copied into `assets/backgrounds`, preserving portability. Appearance and background changes apply immediately; a color-theme change applies on the next launch.

## YAML and variable design

Menus and settings are deliberately separated:

- `menus/*.yaml` defines labels, descriptions, hierarchy, confirmation prompts, action IDs, and parameter mappings.
- `variables/*-variables.yaml` contains values expected to change between systems or exercises.
- `execution_engines/main.py` registers allowed actions and provides shared command execution, credentials, and variable expansion.
- `execution_engines/deployment.py`, `training.py`, and `troubleshooting.py` implement the menu-specific actions. `result.py` defines their shared result type, and `settings.py` loads shared container names and persists application secrets.

Variable references use `${VARIABLE_NAME}`. Nested references are expanded before an action runs. For example:

```yaml
OPENPROJECT_DATA_VOLUME: "${CONTAINER_DATA_ROOT}/openproject"
```

Unknown `action_id` values are rejected. Only registered actions are supported; legacy inline Python and Python-file `action` entries are no longer executed.

## Deployment workflow

### 1. Check the system

Open **Deployment → System Readiness**:

- **Show System Info** displays the Linux distribution, Docker command path, and project directory.
- **Check Docker Status** displays the Docker server version and running containers.

### 2. Install Docker when online

Use **Deployment → Prep Install → Install Docker**. The action supports Rocky/RHEL-family and Debian/Ubuntu-family systems and enables the Docker service.

The current offline repository builder captures toolbox runtime dependencies, not Docker Engine packages. For an isolated target, install Docker before disconnecting or separately provide Docker packages for that exact distribution.

### 3. Save portable images

On an internet-connected Docker host, select **Save/Update Images**. The toolbox:

1. Pulls every configured image.
2. Retries transient pull failures up to `CONTAINER_IMAGE_PULL_ATTEMPTS` times.
3. Saves each image as a TAR archive in `repos/containers`.
4. Replaces archives only after the new set is successfully staged.
5. Deletes old TAR files that are no longer in the configured image list.
6. Writes `repos/containers/images.txt` as the current image manifest.

Temporary `.images-*` folders and `images.txt.new` are staging artifacts and are removed or atomically replaced when the operation completes normally.

### 4. Load images offline

Move the project to the offline system, prepare it, verify Docker is installed, then select **Load Saved Images**. Every `.tar` file in `repos/containers` is loaded into that computer's Docker image store.

Docker does not run images directly from the flash drive. The TAR files are portable copies; Docker imports their layers into the local Docker engine.

### 5. Deploy containers

Open **Deployment → Containers** and choose the service. The engine runs a controlled `docker run` using the current image, port, volume, environment, restart-policy, and container-name variables.

If a container with the configured name already exists, deployment stops unless that service's `*_RECREATE` value is set to `true`. Recreation first creates a candidate container, then stops and renames the previous container. It starts the replacement and checks its health (up to 180 seconds), or requires three running-state observations when no Docker health check exists. Only after those checks succeed is the previous container removed. Startup failures and cancellation trigger cleanup and an attempt to restore the previous name and running state. Recovery errors identify containers requiring manual attention.

This recovers container configuration, not changes made to shared data by the new application. Back up persistent data before upgrading; an application may migrate its database before failing. Running-state checks without a health check do not guarantee the application is ready to serve requests.

OpenProject and CTFd's `${GENERATED_SECRET}` values are generated once per container name and environment key, then reused from `variables/.service-secrets.json`. On first recreation, the tool adopts the existing container's corresponding key if available. This private file is excluded from Git and created with owner-only permissions. Preserve it when moving or backing up the toolbox. To deliberately use a different key, set an explicit value in the service's secret setting; ordinary recreation does not rotate keys.

## Portable and local storage model

The default layout separates portable artifacts from active workloads:

| Data | Default location | Intended storage |
| --- | --- | --- |
| Active container data | `~/.local/share/yaml-toolbox/containers` | Local computer disk |
| Docker image archives | `./repos/containers` | Project or flash drive |
| Service backups | `./backups/<service>` | Project or flash drive |
| PCAP files | `./repos/pcap` | Project or flash drive |
| Python wheels | `./repos/python` | Project or flash drive |
| OS packages | `./repos/libraries/<os-version-arch>` | Project or flash drive |

This prevents application databases and active container writes from running against removable media while keeping installation assets and recovery points portable.

## Backups and restores

Each managed service has two actions under **Deployment → Containers → Backups**:

- **Manual Backup** creates a timestamped `.tar.gz` archive.
- **Load Backup** expands into every compatible archive found in that service's backup folder. The newest file is labeled **Newest**, but older manually placed versions remain selectable.

During backup or restore, a running managed container is stopped and restarted afterward. If a stop fails, recovery is attempted for every container whose stop was attempted. A restart failure does not prevent attempts to restart the others. Docker inspection errors abort the operation. Backup archives are created through a temporary file and renamed into place only after success. Before restore, archives are checked for absolute paths, directory traversal, device entries, and unsafe links.

A restore extracts into the existing service-data directory. Matching files can be overwritten; files that are absent from the archive are not automatically deleted. Keep an additional manual backup before loading an older CTF state.

## PCAP training workflow

Training captures belong in:

```text
repos/pcap/
```

The engine accepts a configured name with no suffix or with `.pcap`/`.pcapng`. For example, the `ssh_scan_01` menu item checks:

```text
repos/pcap/ssh_scan_01
repos/pcap/ssh_scan_01.pcap
repos/pcap/ssh_scan_01.pcapng
```

Set `TARGET_DEVICE` in `variables/training-variables.yaml` to the replay interface, such as `eth1`. The engine verifies that the interface exists before invoking `tcpreplay`.

The current examples provide three placeholders for each phase:

- Recon
- Weaponization
- Delivery
- Exploitation
- Installation
- Command & Control
- Actions on Objectives

The labels and filenames are templates. Add the corresponding PCAP files or edit `menus/training.yaml` to match your capture library.

Only replay captures on an isolated, authorized training network. Recorded packets retain their original addresses and behavior and can affect reachable systems.

## Local Windows host exercises

**Training → Host Actions** provides eleven local Windows exercises: successful and failed login, process creation, parent/child process, file activity, PowerShell activity, service activity, scheduled task, registry activity, account activity, and a process chain.

The toolbox and exercises run on the same Windows VM; SSH and a SIEM are not required. Each scenario provides:

- **Run Exercise**, which generates a unique run ID and writes an instructor record under `%LOCALAPPDATA%\ToolboxTraining\Runs`.
- **Analyze Local Logs**, which searches the local Security, System, Sysmon, and PowerShell logs for the latest run and saves candidate events to `evidence.json`.
- **Show Instructor Record**, which reports what the exercise actually attempted and whether execution completed.
- **Clean Up Latest Run**, which removes only artifacts whose names and ownership markers match that run. Run records, evidence exports, and Windows event logs remain.

Use **Check Local Readiness** before a class. It reports elevation, available logs, record counts, and audit-policy output without changing the VM. Availability is not proof of collection: validate every exercise against the VM's actual audit policy, Sysmon configuration, PowerShell Script Block Logging, and event retention before scoring analysts.

Log analysis returns time-window candidates and flags records containing the run ID or temporary account. Candidate counts are not an analyst score and do not prove correlation. The analyst should still establish the account, host, process ancestry, paths, timestamps, and resulting artifacts. Exercise execution, telemetry collection, and analyst performance are three separate outcomes.

Login, service, scheduled-task, and account exercises require an elevated toolbox. Successful and failed login exercises create a temporary local account and use a single authentication attempt; cleanup removes the account. Other exercises use isolated run folders, a dedicated registry path, or uniquely named services/tasks. Use only on an isolated training VM and take a snapshot before class exercises.

## SecOnion training controls

The Training menu contains a separate **SecOnion** section:

- **Check SecOnion Status** runs `so-status` and lists SecOnion containers.
- **Config Remote Creds** encrypts the remote SSH username and SSH/sudo password.
- **Lock Session Creds** removes decrypted remote credentials and the local sudo password from memory.
- **Clear SecOnion Data** runs `so-elastic-clear` after both a confirmation dialog and the required phrase `CLEAR SECURITY ONION DATA`.

Clearing SecOnion data permanently deletes Elasticsearch documents and indices, including alerts and searchable event data. It does not delete PCAPs in the toolbox.

Configure these values in `variables/training-variables.yaml`:

| Variable | Meaning |
| --- | --- |
| `PCAP_DIRECTORY` | Project-relative capture folder. |
| `TARGET_DEVICE` | Linux interface used by `tcpreplay`. |
| `SECURITY_ONION_TARGET_MODE` | `local` or `remote`. |
| `SECURITY_ONION_REMOTE_HOST` | Remote hostname or IP address. |
| `SECURITY_ONION_REMOTE_PORT` | SSH port, normally 22. |
| `SECURITY_ONION_ACCEPT_NEW_HOST_KEY` | Whether the first unseen SSH host key may be accepted automatically. |

## Troubleshooting workflow

Set `TARGET_MODE` in `variables/troubleshooting-variables.yaml` to `local` or `remote`.

### Docker diagnostics

The Docker section provides:

- Engine version, daemon information, storage driver, and disk usage.
- Image inventory, dangling-image discovery, optional image inspection, and image history.
- Full container status and recent Docker events.

The **Container Logs** section contains OpenProject, Etherpad, Nextcloud, CTFd, and Portainer. Each container expands to:

- **Read Logs**: inspects the container and reads the latest timestamped entries.
- **Restart Container**: asks for confirmation, restarts the selected container, and displays its resulting state.
- **Edit Container Settings**: opens an editor for that service's saved deployment image, ports, paths, and other settings, with the logs still visible behind the dialog.

The editor saves to `variables/deployment-variables.yaml`; it does not modify a running container. To apply changes locally, check **Recreate existing container**, save, then select the service's **Install** action under **Deployment → Containers**. Review persistent data paths before recreating. **Restart Container** alone does not apply changed deployment settings.

The editor is available only when `TARGET_MODE` is `local`; it does not edit or redeploy remote containers. Troubleshooting reads managed container names from `variables/deployment-variables.yaml` at execution time, so saved name changes apply to subsequent diagnostics automatically. For remote diagnostics, those names refer to containers on the explicitly selected remote host. **Read Logs** shows actual state, image, ports, and mounts; the editor shows saved deployment settings, which may differ from the running container.

Edit the service's deployment `*_CONTAINER_NAME` value if its actual name differs. `LOG_LINES` controls how many recent lines are requested. Set `DOCKER_USE_SUDO` when the selected account cannot access the Docker daemon directly.

### SecOnion diagnostics

The troubleshooting SecOnion section provides:

- `so-status` and SecOnion container inventory.
- Load, memory, filesystem, Docker-service, and failed-systemd-unit checks.
- Docker, Salt, Suricata, and Kibana logs.
- Logs for a selected `so-*` container.
- `so-checkin` to apply Salt states.

`so-checkin` can change services and configuration and therefore requires confirmation.

## Local and remote credentials

Remote troubleshooting uses password-based SSH through Paramiko. SSH-agent and key-file discovery are disabled for this workflow.

When **Config Remote Creds** is used:

1. The application prompts for the remote SSH username.
2. It prompts for the SSH/sudo password.
3. It prompts for a separate vault passphrase.
4. The username and password are encrypted with a PBKDF2-derived Fernet key.
5. Only the salt and encrypted values are written to the active variable YAML.

The vault passphrase is never written to disk. Decrypted credentials remain only in application memory and are requested once per session. Local SecOnion or sudo-enabled Docker diagnostics prompt once for the local sudo password and also keep it only in memory.

Use **Lock Session Creds** before leaving the workstation. Closing the application also discards in-memory credentials.

By default, unknown SSH host keys are rejected. Set the relevant `*_ACCEPT_NEW_HOST_KEY` value to `true` only when you have verified the target and intend to trust its first presented key. Return it to `false` afterward if strict checking is required.

Credential variables are stored separately for Training and Troubleshooting. Unlocked SSH credentials are bound to the host, port, variable file, and encrypted credential values. Switching menus clears session credentials; changing the remote target or saved credentials requires unlocking again. Configure or unlock credentials while the intended YAML menu is selected.

Command displays redact Docker environment values, and output masks known application secrets and session passwords. Container inspection displays selected operational fields rather than the complete environment. Application logs may still contain other sensitive information unknown to the toolbox.

## Offline preparation

On an online staging computer that matches the target distribution, release, architecture, and Python compatibility:

```bash
./run-once/run-once --download-repos
```

Then copy the complete project to the offline computer and run:

```bash
./run-once/run-once --offline
```

The OS package folder is named from the detected platform, for example:

```text
repos/libraries/rocky-9-x86_64/
repos/libraries/ubuntu-24.04-amd64/
repos/libraries/debian-13-amd64/
```

RPM and DEB repositories are not interchangeable. A repository downloaded on one release or architecture should not be assumed to work on another.

To prepare Docker images for offline use, use **Save/Update Images** on an online Docker host, then use **Load Saved Images** on the offline target.

## Editing or extending the toolbox

### Add a menu item

Add a child to the appropriate file in `menus/` and reference an existing allow-listed `action_id`. Keep machine-specific values in the matching variables file.

### Add a PCAP

1. Copy the capture to `repos/pcap`.
2. Add or copy an entry under the desired kill-chain phase in `menus/training.yaml`.
3. Set `pcap_name` to the filename or basename.
4. Keep `interface: "${TARGET_DEVICE}"` unless the item intentionally uses another configured interface.

### Add a managed container

At minimum, define its container name, image, host/container ports, restart policy, and local data paths in `variables/deployment-variables.yaml`, then add its deployment action to `menus/deployment.yaml`. If it needs backup and troubleshooting controls, add matching backup paths and log/restart entries as well.

Implement new operations in the appropriate module under `execution_engines/` and register their action IDs in `execution_engines/main.py`.

## Common problems

### `python: command not found` or missing Python modules

Use `./run_toolbox.sh`, not `python main.py` or `python3 main.py`. The launcher selects the prepared virtual environment.

### `env: 'bash\r': No such file or directory`

The script has Windows CRLF line endings. Convert it with `sed -i 's/\r$//' run-once/run-once` and rerun `chmod +x run-once/run-once`.

### `sudo: a password is required`

Local SecOnion, sudo-enabled Docker troubleshooting, Docker installation, backup/restore, and PCAP replay actions prompt for the password inside the application. Use **Lock Session Creds** to clear a saved password and enter it again. Run setup from a terminal where sudo can prompt.

### Docker pull TLS handshake timeouts

**Save/Update Images** retries each pull using a short backoff. If all configured attempts fail, check DNS, proxy, firewall, VPN, Docker daemon connectivity, and system time, then rerun the action. Successfully pulled local images do not need to download their layers again.

### Offline Pillow or another wheel is missing

Option 1 is always online and ignores `repos/python`. Use it when connected. To repair offline content, run `./run-once/run-once --download-repos` on a compatible online system before choosing the offline setup option.

### Emoji or icons do not display in WSL

The interface uses PNG icons where available. Text emoji rendering depends on the Linux font set and WSL display stack. The setup intentionally avoids large optional font collections; install an emoji-capable font separately only if text emoji are required.

### A PCAP cannot be found

Confirm the file is under `repos/pcap`, and that its basename matches the `pcap_name` in `menus/training.yaml`.

### Remote SSH connection is rejected

Verify the host, port, username, password, and remote SSH service. If the host is new, verify its fingerprint before temporarily enabling the accept-new-host-key variable.

### Docker permission denied

Set `DOCKER_USE_SUDO: true` for troubleshooting actions, or configure the account's Docker access according to local policy. Group changes normally require a new login session.

## Operational safety

- Review variable settings before every class or exercise.
- Keep PCAP replay on an isolated authorized network.
- Treat backup archives and encrypted credential YAML files as sensitive training data.
- Verify remote host identity before accepting a new SSH host key.
- Take a manual service backup before loading an older CTF state.
- Use the guarded SecOnion clear action only when resetting the training SIEM is intentional.
- Do not unplug the portable drive while creating image archives or backups.
- Remember that encrypted credentials are only as strong as the selected vault passphrase.

## Quick classroom checklist

1. Connect or copy the toolbox project.
2. Run `./run-once/run-once` and choose the correct online or offline preparation mode.
3. Start with `./run_toolbox.sh`.
4. Verify Docker under **Deployment → System Readiness**.
5. Load saved images or update them while online.
6. Verify deployment ports and local data paths in Variable Settings.
7. Deploy the required training services.
8. Confirm backups exist for any state that must be restored during the exercise.
9. Set the correct PCAP replay interface.
10. Configure the local or remote SecOnion target.
11. Run status checks before students begin.
12. Use container logs, restart controls, and SecOnion diagnostics during the event.
13. Lock session credentials and create final backups when the exercise ends.
