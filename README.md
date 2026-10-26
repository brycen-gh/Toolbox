# The lazy way to run this.

If Git isn't installed, install it using your preferred package manager before running these commands.

git clone https://github.com/brycen-gh/Toolbox.git
cd Toolbox


# Toolbox


Toolbox is a YAML-driven desktop application for deploying training containers, replaying PCAP captures, running local Windows host exercises, and troubleshooting Docker and Security Onion systems. It's gotten a little out of scope and was mostly vibe coded. But yeah, I also want this tool for me and accessible so here it is. 

## Desktop workspace

Source is organized by responsibility; see the [project layout](docs/project-layout.md).

Optional hostname routing is available through **Home → Options → Optional domain**.
Set `ggsec.org`, then install **Deployment → Nginx Reverse Proxy → Install nginx-proxy**
and recreate the desired services. Clients can map your LAN IP to
`openproject.ggsec.org`, `etherpad.ggsec.org` and the other service names in their
own hosts file. **Client hosts-file entries** prepares a copyable block.
See the [complete hostname setup guide](docs/hostname-routing.md), including the
`172.16.10.250` example, WSL forwarding and the HTTPS requirements for Zulip.

Home brings together the five collections: **Deployment**, **Training**,
**Troubleshooting**, **Capture** and **Tools**. Each collection and its sections
have a card overview, with descriptions and shortcuts to the tools inside.
Overview cards respect **Show / Hide Items** preferences. Selecting an action
opens its details; use **Run Action** when you are ready to run it.

Home's **HOST IPv4** card shows the detected address with **Copy IP** and
**Refresh** controls. It refreshes when you return Home; use Refresh after
switching networks. In WSL it attempts to find the Windows host's LAN address
and labels the detected source. If no usable address is detected, Home shows
**No IPv4 detected** and disables copying. The address is useful for service
links, but access still depends on the service's ports, firewall and network
configuration.

## Run from a USB drive

The portable release is a complete application folder. Copy the **whole folder**
to a writable USB drive and open `Toolbox.exe` on Windows or `./Toolbox` on Linux.
No Python installation or application setup is required on the destination
computer. Keep `_internal` and `portable.mode` beside the executable. Settings,
menus, assets and helper scripts remain editable beside it; changing the drive
letter does not change project-relative paths.

```text
Toolbox/
  Toolbox.exe           # Linux: Toolbox
  _internal/            # bundled Python, Tk and libraries
  portable.mode
  assets/  menus/  scripts/  variables/
  data/containers/
  backups/  repos/containers/  repos/pcap/  share/
  README-USB.txt
  build-info.json
```

Fresh releases use `./data/containers` for container data and have blank stored
credentials, a reset appearance profile, and no personal captures, archives or
backups. Configure your own remote credentials and a new **Portainer setup token**
before deploying that service. Your private working settings are never copied
by the build script. Treat a configured drive as sensitive data.

Docker, WSL, PowerShell, `tcpreplay`, `tcpdump`, drivers and administrator access
remain host requirements for the actions that use them. Check **Home → On this computer**
after connecting to another machine. Containers and system changes remain on
that machine. Docker bind mounts must be accessible to the selected daemon: a
remote daemon cannot read files on your USB, and Docker Desktop/WSL path sharing
must allow the chosen folder.

A USB SSD is recommended for large image archives and container databases.
exFAT works for exchanging files across Windows and Linux, but it does not supply
all Linux permissions and links required by some container databases. For those
services use compatible host-local container storage and save backups to the
USB. FAT32 limits individual files to 4 GiB. Stop jobs and containers that use the
drive before safely ejecting it.

### Build a portable release

Build from a Git checkout on the target operating system and architecture.
Windows and Linux releases are separate; this is not a universal binary.
The build bundles the active Python interpreter, Tkinter, CustomTkinter theme
data and application dependencies using [PyInstaller's folder mode](https://pyinstaller.org/en/stable/operating-mode.html).
CustomTkinter requires its [theme and font assets](https://customtkinter.tomschimansky.com/documentation/packaging/).
For Linux, build on the oldest compatible Linux distribution you intend to
support; the target still needs a graphical session and compatible system
libraries.

On Windows, after creating `.venv` and installing runtime requirements:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe scripts/build_portable.py
```

On Linux, install the runtime requirements and Tk development/runtime support in
the build environment, then run:

```bash
.venv/bin/python -m pip install -r requirements-build.txt
.venv/bin/python scripts/build_portable.py
```

Each run creates a new `dist/Toolbox-<os>-<architecture>-<UTC timestamp>/`
directory. The script refuses existing output directories and retains its work
files under `build/portable/`. Build tooling is pinned separately from runtime
dependencies in `requirements-build.txt`. To choose a new destination, pass
`--output <new-folder>`.

Python source and tracked assets, helper scripts and menus come from the current
checkout. Existing configuration defaults come from **committed HEAD**; the new
proxy schema is included explicitly. Working private settings are excluded, and
fresh releases leave the optional domain blank. Credential values are cleared,
declarative `${GENERATED_SECRET}` placeholders are preserved, local UI state is
reset and portable data paths are applied. Hidden files, service-secret stores,
untracked configuration, working credentials and existing data are excluded.
`build-info.json` records the defaults revision and resource hashes.

The build launches the frozen application's offline `--self-check --report`
before publishing the folder. This verifies imports and editable resources
without opening a window or contacting Docker or SSH. Test the completed release
on a clean computer without Python and after changing the drive letter before
relying on it for a class. To inspect sanitized resources without PyInstaller:

```powershell
.\.venv\Scripts\python.exe scripts/build_portable.py --prepare-only
```

That command produces resources only, without an executable.

### Update an existing USB copy

Close Toolbox and stop sharing, capture and replay jobs. Back up the drive, then
extract the new release beside the old folder. Review changed defaults and copy
your `variables`, custom `menus`, `data`, `backups`, `repos` and `share` into the
new folder; also copy any custom background. Keep the new executable, `_internal`,
marker and helper scripts together. Avoid installing over an active release or
replacing its data directories with the fresh empty ones. Retain the old folder
until the new copy works on your host.

## Share WSL containers on your LAN

In Toolbox, open **Deployment → WSL LAN Forwarding**. Set the distribution and
optional comma-separated port selection in **Variable Settings**, then use
**Preview Forwarding** and **Apply / Refresh Forwarding**. `auto` detects the
current distribution when Toolbox runs inside WSL; on Windows, enter the name
from `wsl --list --quiet`. Leave ports blank for all published TCP ports, or
select `80,443` for Nginx. Apply and removal open the Windows administrator
approval prompt for the helper and report its output back in Toolbox.
**Remove Managed Forwarding** removes all helper-managed rules for that
distribution. This works from Windows or WSL with Windows interop enabled.

For Docker Engine running inside WSL's default NAT network, run this from
Windows PowerShell in the project root. Replace `Ubuntu` with the distribution
name shown by `wsl --list --quiet`:

```powershell
.\scripts\share-wsl-containers.ps1 -Distro Ubuntu
```

This previews forwarding for all running containers' published IPv4 TCP ports.
To configure Windows port forwarding and firewall rules, open PowerShell as
Administrator and run:

```powershell
.\scripts\share-wsl-containers.ps1 -Distro Ubuntu -Apply
```

Visitors use your Windows Ethernet/Wi-Fi IPv4 address (see `ipconfig`) and the
existing service ports, for example `http://192.168.1.20:8088`. Firewall access
is limited to `LocalSubnet`. All published TCP services are included, including
administration interfaces; use `-Ports 8088,8082` to select specific ports.
Loopback-only ports, IPv6-only ports, UDP and unpublished database ports are excluded.
Application public URLs and trusted hosts must also allow the Windows LAN address.

Rerun after WSL restarts or containers change: the script rediscovers WSL's IP
and refreshes forwarding. Old rules remain until explicitly removed. Preview
removal with `-Remove`; apply removal with `-Remove -Apply`. Removal deletes all
rules managed by this script for that distribution, regardless of `-Ports`.
Existing unrelated forwarding rules are preserved; conflicting ports stop setup.
Preview still queries Windows Firewall and WSL and may require an elevated shell
on systems restricting those queries. This script targets WSL NAT with Docker
Engine inside the chosen distribution; Docker Desktop and mirrored networking
use different networking paths.

This automates the existing port-based URLs without adding a reverse proxy or
local DNS. See [Microsoft's WSL networking guide](https://learn.microsoft.com/windows/wsl/networking).

## Nginx reverse proxy

Use **Deployment → Prep Install → Save/Update Images** to select Nginx,
then **Deployment → Nginx Reverse Proxy → Install Nginx Proxy Manager**.
Settings are in `variables/docker_variables/nginx.yaml`. The defaults expose
HTTP on 80, HTTPS on 443 and the administration interface on 81, following the
[Nginx Proxy Manager setup](https://nginxproxymanager.com/setup/).
Configuration, its SQLite database and certificates persist under
`${CONTAINER_DATA_ROOT}/nginx`. Backups → Nginx saves and restores that directory.
Enable `NGINX_RECREATE` to replace an existing instance with updated settings;
back up first because image upgrades can migrate the database.

Open `http://<Windows-LAN-IP>:81` (or `http://localhost:81` on Windows with WSL
localhost forwarding) and complete the image's initial administrator setup.
Add a Proxy Host for each application: choose its hostname, use
`host.docker.internal` as Forward Hostname, and enter the application's existing
published host port. Choose HTTP or HTTPS to match the backend. Enable Websockets
Support for chat and collaborative applications. Docker's `host-gateway` mapping
lets this Linux container reach published ports without attaching to each stack's
private network. Backends bound only to `127.0.0.1` are unreachable through this
gateway: configure their bind address to a reachable host interface and recreate
them first (for example, Zulip's `ZULIP_BIND_ADDRESS`).

Point LAN DNS names to the Windows LAN IP. Update each application's public URL,
allowed hosts and trusted proxies to match; configure Home's service links for
the new URLs if needed. Proxy deployment does not rewrite existing application
settings, create DNS records or automatically create proxy hosts. For LAN-only
HTTPS, use a certificate you supply or a DNS challenge for a domain you control;
HTTP certificate validation requires public reachability.

In Administrator PowerShell, forward only the public proxy ports:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\share-wsl-containers.ps1 -Distro Ubuntu -Ports 80,443 -Apply
```

To administer from another LAN device, temporarily include 81 in `-Ports`.
Existing forwarding rules remain: use `-Remove -Apply` before selecting only
80 and 443 if you previously shared every container. Reserve these ports for
Nginx or change its settings to unused ports. This supports Docker Engine in
Linux/WSL; Windows NAT forwarding remains a separate Administrator operation.

## Linux and WSL setup

Run the following commands from the project root in a Linux or WSL terminal. The desktop interface requires a graphical display. For Windows host exercises, use the PowerShell instructions under [Starting the toolbox](#starting-the-toolbox).

If the project was downloaded or edited on Windows and you are running it on Linux or WSL, convert the setup script's Windows line endings before running it:

```bash
sed -i 's/\r$//' run-once/run-once
```

Make the setup script executable, then start the interactive setup:

```bash
chmod +x run-once/run-once
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

The setup is safe to rerun. Preparation modes update the virtual environment and dependencies, check that every menu YAML file parses into a mapping, validate dependency and execution-engine imports, recreate the launcher, and refresh `.setup-complete`. Download-only mode refreshes the portable repositories without preparing the application. Repository-download modes stage a complete replacement before removing obsolete wheels or OS packages.

Setup loads `execution_engines/main.py`, its shared action modules, and the service modules in `execution_engines/docker_engines/`, then verifies that the dispatcher has callable action handlers. This check does not execute actions or contact Docker or SSH targets. It works even when setup is launched from outside the project directory. Both setup scripts also validate variable YAML files and their Includes, catching missing includes and duplicate keys. Full validation of menu action IDs, required parameters, and variable references is not yet implemented.

The setup creates `repos/containers` but does not download Docker images. Images are downloaded later from **Deployment → Prep Install → Save/Update Images**.

## What `run-once/run-once` installs

The system package set includes the tools used by setup and Linux actions:

- Python 3
- pip
- Python virtual-environment support
- Tkinter
- `tcpreplay`
- `tcpdump` for packet capture
- `sg`, `groupadd`, and `usermod` for Docker access (`login`, `passwd`, and, where available, `util-linux-extra` on Ubuntu/Debian; `shadow-utils` on RPM systems)
- sudo, curl, and CA certificates
- Shell, file, archive, process, and systemd utilities

Setup checks these commands even when Python is already configured and installs missing dependencies. Online installation and offline downloads share the same package lists. Rebuild older offline repositories with `--download-repos` to include the added packages. Docker Engine and Compose remain installed through **Install Docker**.

If `sg` remains unavailable, setup continues and Toolbox uses sudo for Docker access until login groups refresh.

On Debian/Ubuntu, optional recommended packages and unnecessary font-provider families are skipped. DejaVu Core and Mono are retained for basic GUI and symbol coverage.

The Python environment installs:

- CustomTkinter
- PyYAML
- Pillow
- cryptography
- Paramiko

After a successful run, `.setup-complete` records the completion time, setup mode, host, operating system, architecture, Python and library versions, validated YAML count, execution-engine location and validation status, virtual-environment path, and launcher path.

## Starting the toolbox

For background packet replay, set **Training → Settings → Variable Settings → REPLAY_BACKGROUND** to `true`, then select a PCAP replay action. Replay uses `tcpreplay` and runs once at the capture's recorded timing. **Training → PCAP Replay → Replay Status** shows progress or final output; **Stop Background Replay** stops it. Other actions remain available while replay runs. Closing Toolbox stops background replay. Set `REPLAY_BACKGROUND` to `false` for foreground replay.

On Linux or WSL, use the launcher generated by setup:

```bash
./run_toolbox.sh
```

The launcher uses `.venv/bin/python`. Running `python3 main.py` without activating the virtual environment can use the system Python and produce `ModuleNotFoundError` even though setup completed successfully.

For local Windows Host Actions, install Python 3 with Tkinter support, copy the project to the Windows training VM, and open PowerShell in the project root as the intended exercise account:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\run-once\run-once.ps1
.\.venv\Scripts\python.exe .\main.py
```

Windows setup generates `run_toolbox.ps1`; use `.\run_toolbox.ps1` after setup, or run the virtual-environment Python command above directly. The generated launcher is excluded from Git. Virtual-environment activation and separate manual package installation are unnecessary when using these commands.

The Windows setup creates `.venv\Scripts\python.exe`, installs the Python requirements, validates menu parsing and engine registration, and writes `.setup-complete`. It is an online setup and does not install or configure Sysmon, Windows audit policy, or PowerShell logging. Run the toolbox as Administrator only for exercises that say elevation is required.

Actions requiring local sudo access prompt for the password inside the application and keep it in memory for the session.

## Interface basics

### Share a folder over HTTP

Select **Tools** from the menu dropdown, then **Share Folder → Start Sharing**.
Toolbox creates `./share` in the project folder and serves its contents in the
background with Python's built-in HTTP server. Put files there and open
`http://localhost:8000/`, or share `http://<this-computer-IP>:8000/` with other
computers that can reach the port through your firewall.

**Sharing Status** shows the folder and address. **Stop Sharing** stops the
server. **Open Share Folder** displays its path and contents. Press **Open Folder**
to open it in your system file manager, creating it if needed. While sharing is running, it opens
the active shared folder.
Closing or restarting Toolbox also stops the
server. **Variable Settings** lets
you change the folder, address, and port; stop and start to apply changes.
The default address `0.0.0.0` accepts network connections; use `127.0.0.1` for
access only from this computer. HTTP provides directory listings and downloads
without login or encryption, so share only files intended for those users.


In Deployment, Training, or Troubleshooting, open **Settings → Show / Hide Items** above **About** to choose which sidebar actions and sections appear. Unchecking a section hides its children too, including from search. Settings and its Show / Hide Items control remain visible so you can restore hidden items. Choices are saved per menu in `variables/ui.yaml`; hiding an item does not remove its configuration or disable its underlying action.

Deployment settings are grouped under **Prep Install → Variable Settings** for image downloads and **Containers → Variable Settings** for shared data and backup paths. Each service has its own subsection under **Containers**, containing **Variable Settings** and its **Install** action. Service values remain in their matching files under `variables/docker_variables/`.

- **Home** clears the sidebar selection and displays informational content.
- **Select YAML...** switches between Deployment, Training, and Troubleshooting.
- Categories expand and collapse in the sidebar.
- Selecting an action displays its description and enables **Run Action**.
- **Variable Settings** edits values for its section. Training keeps replay settings under **Settings** and Security Onion settings under **SecOnion**. Troubleshooting also provides a scoped editor under **SecOnion**; shared target settings apply to both its Docker and SecOnion actions.
- The search field is case-insensitive and supports shell-style wildcards such as `*docker*`, `install*`, `?tfd`, and `[NU]*cloud*`.
- Action output, standard output, standard error, and exit status are displayed inside the application.
- Actions run in a background worker. Local command output appears while they run; **Cancel Action** requests cancellation. Remote diagnostics finish their current command before stopping. Container stop/restart recovery finishes before cancellation completes. Menu selection is held while an action is running.
- Output is preserved while an action runs and when it finishes. Selecting another action or category clears the panel. The red eraser beside **Run Action**, labeled **Clear output** on hover, clears displayed text without stopping the action; new output continues appearing.

### Appearance options

The Home page **Options** button supports:

- Blue, Green, and Dark Blue themes.
- Light, Dark, and System appearance modes.
- An optional Home background image.

UI choices are stored in `variables/ui.yaml`. A selected background outside the project is copied into `assets/backgrounds`, preserving portability. Appearance and background changes apply immediately; a color-theme change applies on the next launch.

Menu icons are transparent PNGs in `assets/icons/`. Set `icon` to the filename without `.png`; missing icons use `default.png`. Service icons now distinguish Moodle, Zulip, and the other applications, while task icons identify backups, replay, logs, monitoring, security, and credentials. See [the icon catalog](assets/icons/README.md) for available additions and suggested uses.

## YAML and variable design

Menus and settings are deliberately separated:

- `menus/*.yaml` defines labels, descriptions, hierarchy, confirmation prompts, action IDs, and parameter mappings.
- `variables/*-variables.yaml` contains values expected to change between systems or exercises.
- `variables/deployment-variables.yaml` holds shared storage and image-download settings and an `Includes` list. Container settings live in `variables/docker_variables/home.yaml`, `zulip.yaml`, `open_project.yaml`, `etherpad.yaml`, `nextcloud.yaml`, `moodle.yaml`, `ctfd.yaml`, and `portainer.yaml`. The Deployment variable editor loads them together and saves each setting back to its own file. References such as `${CONTAINER_DATA_ROOT}` can use values from any included file.
- `execution_engines/main.py` registers allowed actions and provides shared command execution, credentials, and variable expansion.
- `execution_engines/deployment.py`, `training.py`, `capture.py`, and `troubleshooting.py` implement the menu-specific actions. `result.py` defines their shared result type, and `settings.py` loads shared container names and persists application secrets.
- `execution_engines/docker_engines/` contains a deployment module for each service: `home.py`, `open_project.py`, `etherpad.py`, `nextcloud.py`, `moodle.py`, `ctfd.py`, `portainer.py`, and `zulip.py`. Each module owns its deployment parameter mappings and handler; `registry.py` connects them to menu action IDs. Shared container execution, image downloads, and backups remain in `deployment.py`.

Variable references use `${VARIABLE_NAME}`. Nested references are expanded before an action runs. For example:

```yaml
OPENPROJECT_DATA_VOLUME: "${CONTAINER_DATA_ROOT}/openproject"
```

Unknown `action_id` values are rejected. Only registered actions are supported; legacy inline Python and Python-file `action` entries are no longer executed.

## Deployment workflow

### Mattermost chat

Open **Deployment → Containers → Mattermost → Variable Settings** and set
`MATTERMOST_SITE_URL` to the address users will visit (for example,
`http://lab-server:8065`). Use **Prep Install → Save/Update Images** online, or
**Load Saved Images** offline, then run **Install Mattermost**. Open the site to
create the first administrator account on a fresh installation.

The stack uses Mattermost Enterprise Edition (free features work without a
license) and PostgreSQL 18. Image versions, container names, port, and storage
are configurable in `variables/docker_variables/mattermost.yaml`. Database
credentials are generated once and retained under the stack's `secrets` folder.
PostgreSQL stays inside the Docker network. This chat deployment exposes HTTP;
configure an HTTPS reverse proxy for access outside your training network.

**Deployment → Backups → Mattermost** backs up and restores both services and
their data, including credentials. Restore with matching image versions and
container names. **Troubleshooting → Container Actions → Mattermost** provides
logs, restart, and removal for each container. Reinstall Home with `HOME_RECREATE`
enabled to add the Mattermost portal link. PostgreSQL major upgrades require a
database migration; changing its image tag alone does not migrate existing data.


### 1. Check the system

Open **Deployment → System Readiness**:

- **Show Network Address** detects a default-route IPv4 address and displays a
  homepage link to share with other computers. In WSL it prefers the Windows
  host's LAN address; NAT may still require port forwarding and firewall rules.
  With `HOME_PUBLIC_HOST: auto`, homepage links follow the visitor's hostname,
  using the detected address when the portal is opened through localhost.
  Service URLs configured as localhost also use that host in portal links.
  This does not change services' canonical site URLs; configure Mattermost and
  Moodle with the address users will visit. Enable `HOME_RECREATE` and run
  **Install Home** to refresh an existing portal after these changes.

- **Show System Info** displays the Linux distribution, Docker command path, and project directory.
- **Check Docker Status** displays the Docker server version and running containers.

### 2. Install Docker when online

Use **Deployment → Prep Install → Install Docker**. The action supports Rocky/RHEL-family and Debian/Ubuntu-family systems and enables the Docker service.

The current offline repository builder captures toolbox runtime dependencies, not Docker Engine packages. For an isolated target, install Docker before disconnecting or separately provide Docker packages for that exact distribution.

### 3. Save portable images

Selecting **Save/Update Images** opens a service checklist with image sizes.
Select the services you need, then press **Download Selected**. Dependencies are
included and shared images are downloaded once. Nothing is selected initially.
Docker Hub compressed sizes are estimates for the Docker host architecture;
cached layers may reduce transferred bytes. Offline or unsupported registries
show a local disk size when available, or “Size unavailable.” Unselected saved
archives are retained. Size lookups run in the background without pulling images.

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

Open **Deployment → Containers**, expand the service, review its **Variable Settings**, then select **Install <service>**. OpenProject, Etherpad, Nextcloud, CTFd, and Portainer use a controlled `docker run` with the saved image, port, volume, environment, restart-policy, and container-name variables. Moodle and Zulip use the Compose workflows below.

For single-container deployments, if a container with the configured name already exists, deployment stops unless that service's `*_RECREATE` value is set to `true`. Recreation first creates a candidate container, then stops and renames the previous container. It starts the replacement and checks its health (up to 180 seconds), or requires three running-state observations when no Docker health check exists. Only after those checks succeed is the previous container removed. Startup failures and cancellation trigger cleanup and an attempt to restore the previous name and running state. Recovery errors identify containers requiring manual attention.

This recovers container configuration, not changes made to shared data by the new application. Back up persistent data before upgrading; an application may migrate its database before failing. Running-state checks without a health check do not guarantee the application is ready to serve requests.

OpenProject and CTFd's `${GENERATED_SECRET}` values are generated once per container name and environment key, then reused from `variables/.service-secrets.json`. On first recreation, the tool adopts the existing container's corresponding key if available. This private file is excluded from Git and created with owner-only permissions. Preserve it when moving or backing up the toolbox. To deliberately use a different key, set an explicit value in the service's secret setting; ordinary recreation does not rotate keys.

Container removal is available under **Troubleshooting → Container Actions → <service> → Remove Container**. It uses the selected local or remote target and requires typing `REMOVE CONTAINER`. Removal discards the selected container's writable-layer data; images, volumes, and bind-mounted files remain. Deployment contains installation and configuration actions; backups have their own top-level section.

### Home browser portal

**Deployment → Containers → Home** deploys a browser landing page with links to all seven lab services and built-in help. Set its variables, save/load the configured images, then select **Install Home**. Open `http://<lab-server>:8088`. The default avoids OpenProject's port 8080.

`variables/docker_variables/home.yaml` controls the image, published port, container name, storage and public hostname. `HOME_PUBLIC_HOST: auto` uses the hostname in the visitor's browser; set it to the lab server's hostname or IP if service links need a different host. Ports come from each service's saved variables. All linked services are assumed to run on that host. Configure OpenProject's hostname, Nextcloud's trusted domains and Zulip's external hostname consistently, with DNS available to students.

The portal is static HTML/CSS/JavaScript served by `nginx:stable-alpine`, with no external fonts, scripts, database, Docker socket or live status claims. Only public service names, descriptions, schemes, ports and the chosen host are exported. Passwords, tokens and private setup links are excluded. The help covers first login, service access, capture/replay and instructor maintenance. Source content lives in `assets/home/`.

Install generates a separate `site-<id>` snapshot under `HOME_DATA_VOLUME` and mounts it read-only into the container. To update links or documentation, set `HOME_RECREATE: true` and rerun **Install Home**. Previous snapshots remain for recovery; do not remove a snapshot referenced by a container mount. Troubleshooting → Container Actions → Home provides settings, logs, restart and removal. Home is served over HTTP by default; it links directly to each service's configured HTTP/HTTPS port. It does not proxy services or manage authentication.

### Guacamole deployment

**Troubleshooting → Container Actions → Guacamole** provides shared container settings and logs, restart and removal actions for the web container, PostgreSQL and guacd. These actions use the selected local or SSH target and the container names saved in the deployment settings.

**Deployment → Containers → Guacamole → Install Guacamole** deploys Apache Guacamole, PostgreSQL and guacd using Docker Compose v2. Review `variables/docker_variables/guacamole.yaml`, then use **Save/Update Images** online or **Load Saved Images** offline. Installation uses local images only.

Open `http://<lab-server>:8085/guacamole/` (or the configured port). Initial login is `guacadmin` / `guacadmin`; change the password after first sign-in. Only the web port is published. Database initialization SQL is generated automatically from the Guacamole image on first installation, and the database password is generated once and retained.

Preserve the entire `GUACAMOLE_DATA_VOLUME` directory, including database, initialization SQL, private credentials and Compose configuration. Enable `GUACAMOLE_RECREATE` to update existing containers. Back up before upgrades and apply required database schema migrations manually; Compose updates do not roll back database changes. Startup checks confirm container state and database health; verify the login page after deployment. See the [Apache Docker deployment guide](https://guacamole.apache.org/doc/1.6.0/gug/guacamole-docker.html).

### Moodle deployment

**Deployment → Containers → Moodle** deploys Moodle plus PostgreSQL using Docker Compose v2. The preset uses the community-maintained [Alpine Moodle image](https://github.com/erseco/alpine-moodle) and `postgres:17-alpine`. Both images are included in **Save/Update Images**; use that action online or **Load Saved Images** offline before installation. Install uses only local images.

Set `MOODLE_SITE_URL` to the address students will use, such as `http://lab-server:8082`, and set the initial admin username and email under **Variable Settings**. The default is `http://localhost:8082`. Moodle requires a canonical URL; Home links to this exact address. An HTTPS URL requires an externally configured TLS reverse proxy forwarding to the Moodle HTTP port. Regenerate Home with `HOME_RECREATE` after changing the URL.

Select **Install Moodle** and allow up to 15 minutes for initialization. The database password is generated once; the initial administrator password is initialized once to the training default `GGpassword1!`. Change it after first sign-in. Use **Deployment → Containers → Moodle → Read Admin Password** to view the saved initial password in a local dialog, or read `MOODLE_DATA_VOLUME/secrets/admin_password` (default `~/.local/share/yaml-toolbox/containers/moodle-stack/secrets/admin_password`); it is not written to execution output or published by Home. Administrator settings apply to initial installation and do not reset existing accounts. SMTP is not configured by this preset.

The data directory contains `database`, `moodledata`, private `secrets`, and the generated private `compose.yaml`. Preserve all of them when moving the installation. Missing existing secrets stop deployment instead of rotating credentials. The PostgreSQL port is not published. Moodle application code comes from the selected image; manually installed plugins and themes in the container must be reinstalled after recreation, or supplied through a custom image. **Troubleshooting → Container Actions → Moodle** provides settings, web-container logs/restart/removal, and database logs. Removing the web container retains the database and persistent data.

Enable `MOODLE_RECREATE` and run **Install Moodle** to apply settings or image changes. Keep the existing container names and data path. Upgrades may migrate the database; Compose does not automatically roll back these changes. Keep PostgreSQL on the configured major version unless performing an explicit database migration. Follow the image maintainer's [persistence and backup instructions](https://erseco.github.io/alpine-moodle/persistence/) before upgrades. Use **Deployment → Backups → Moodle → Manual Backup** before upgrades. This pauses both Moodle and PostgreSQL and archives the full stack directory, including credentials. Backups are manual; Toolbox does not schedule them automatically.

### Portainer setup token

**Deployment → Containers → Portainer → Variable Settings** includes `PORTAINER_SETUP_TOKEN`, defaulting to `ggtoolbox` in `variables/docker_variables/portainer.yaml`. Install passes this as `--setup-token`. Enter it on Portainer's first-time setup screen, then choose your administrator password. The token does not reset an existing administrator account. This preset is stored in the repository, so it is a shared default rather than a private secret; change it for installations requiring a private token. Requires a Portainer version supporting `--setup-token` (2.43 / 2.39.4 or later).

### Zulip deployment

For preset local setup, edit `ZULIP_ORGANIZATION_NAME` (default `ggsec`), `ZULIP_OWNER_EMAIL` (default `ggsec@ggsec.org`) and `ZULIP_OWNER_NAME` under Zulip's Variable Settings. After installing, run **Create Organization and Admin**. Enter and confirm the initial password in Toolbox; it is sent over stdin and is not saved in YAML or published by Home. This creates the organization identified by `ZULIP_ORGANIZATION_ID` (default `ggsec`) and its owner; changing these variables later does not rename existing organizations or accounts. The organization-link action remains available for browser-based setup.

Zulip defaults to local-only access: `ZULIP_EXTERNAL_HOST` is `localhost:8443` and `ZULIP_BIND_ADDRESS` is `127.0.0.1`. For localhost, Toolbox uses a valid internal server domain and maps the configured organization ID to localhost. Existing installations need recreation to apply these settings; older root-domain organizations also need a one-time address migration using Zulip's change_realm_subdomain command. For access from other computers, change the bind address and external hostname together. `ZULIP_ADMINISTRATOR` is the server contact email; it does not create a login account.

**Deployment → Containers → Zulip → Install Zulip** manages a five-service Docker Compose stack: Zulip, PostgreSQL, Memcached, RabbitMQ, and Redis. It requires Docker Compose v2 or later. **Save/Update Images** includes all five images; use that action online or **Load Saved Images** offline before installing. The Install action uses local images and does not pull missing images.

In Variable Settings, set `ZULIP_EXTERNAL_HOST` to a hostname clients can resolve (including the port when it is not 443) and `ZULIP_ADMINISTRATOR` to the server administrator's email address. The training defaults use `https://localhost:8443` and a self-signed certificate. For other computers, configure DNS or hosts-file entries and replace `localhost` with the training server's hostname. After installation, select **Zulip Create Organization Link** and open the private link to create the organization and administrator account.

The stack stores its generated Compose configuration, uploads, database, queue data, and credentials under `ZULIP_DATA_VOLUME`, defaulting to `~/.local/share/yaml-toolbox/containers/zulip-stack`. Passwords are generated once and stored in the private `secrets` directory. Preserve that directory with the data; missing credentials on an existing installation cause setup to stop instead of silently generating replacements. SMTP delivery and incoming email are not configured by this training preset. For production email, trusted TLS, and other customization, follow the [official Zulip Docker documentation](https://zulip.readthedocs.io/projects/docker/en/latest/).

To apply saved settings or image changes, first create a backup, enable `ZULIP_RECREATE`, and rerun **Install Zulip**. Compose updates can change the database and do not have the automatic container rollback described for single-container deployments above. The generated `compose.yaml` is rewritten by Install; keep Toolbox-managed settings in Variable Settings. Avoid changing the stack name or data directory on an existing installation.

**Troubleshooting → Container Actions → Zulip** provides settings, web-container logs and restart, and separate logs for each dependency. **Deployment → Backups → Zulip** stops all five containers for a full backup and restarts those that were running. Backups include private credentials. Restore requires the same data path, matching image versions, and all five containers already created. It extracts into a separate directory, replaces the stack data directory while the containers are stopped, and keeps the previous directory beside it for recovery. Unlike other services' overlay restores, this avoids mixing old and new PostgreSQL files.

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

CTFd backups now capture the actual SQLite database and uploads from the stopped container, including the database kept inside legacy containers. New deployments persist both under `CTFD_DATA_VOLUME`, in `database/` and `uploads/`. Old uploads-only archives cannot restore the site and are rejected. External CTFd databases require a separate database backup.

For an existing legacy CTFd installation: create a new **Deployment → Backups → CTFd → Manual Backup**, verify it contains `database/ctfd.db`, then remove the old container through Troubleshooting. Use **Load Backup** and **Install CTFd** in that order. Legacy recreation is blocked until migration to avoid losing the original database. For a fresh device, load the original image archive before restoring; the restore uses the recorded image to prepare file ownership. Restore stages a separate directory and retains previous host data for recovery.

All eight managed services (Home, OpenProject, Etherpad, Nextcloud, Moodle, CTFd, Zulip, and Portainer) have two actions under **Deployment → Backups**:

- **Manual Backup** creates a timestamped `.tar.gz` archive.
- **Load Backup** expands into every compatible archive found in that service's backup folder. The newest file is labeled **Newest**, but older manually placed versions remain selectable.

During backup or restore, the service's running managed containers are stopped and restarted afterward. Moodle includes both its web and database containers; Zulip includes all five stack containers. If a stop fails, recovery is attempted for every container whose stop was attempted. A restart failure does not prevent attempts to restart the others. Docker inspection errors abort the operation. Backup archives are created through a temporary file and renamed into place only after success. Before restore, archives are checked for absolute paths, directory traversal, device entries, and unsafe links.

For services other than Zulip, a restore extracts into the existing service-data directory. Matching files can be overwritten; files that are absent from the archive are not automatically deleted. Zulip uses the directory replacement procedure described above. Keep an additional manual backup before loading an older CTF state.

## PCAP training workflow

### Capture Ethernet or Wi-Fi traffic

Select **Capture** from the menu dropdown, then **Capture Traffic**. Choose a local interface and a new `.pcap` filename, click **Start Capture**, and supply your sudo password if prompted. **Stop Capture** finishes the file and displays capture statistics and the saved path. Existing files are never overwritten. Capture continues until stopped, so allow enough disk space for the session.

Capture currently requires Linux and `tcpdump`; rerun `./run-once/run-once --prepare` to install the dependency, or refresh offline repositories before offline setup. Native Windows capture is not implemented. WSL lists only interfaces visible inside WSL.

Ethernet and Wi-Fi capture save traffic visible to the selected adapter. The tool does not enable Wi-Fi monitor mode or change adapter settings. See the [tcpdump manual](https://www.tcpdump.org/manpages/tcpdump.1.html) for capture behavior. Save captures under `repos/pcap` to use them with Training, then add the filename to the training menu as described below.

### Replay saved captures

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

Open **Training → Settings → Variable Settings** to set `PCAP_DIRECTORY` and `TARGET_DEVICE`. These values are saved in `variables/training-variables.yaml`. The engine verifies that the selected interface exists before invoking `tcpreplay`; this check does not establish whether it is a physical adapter.

### Replay through a physical Ethernet port

Yes: on Linux with access to the physical Ethernet adapter, Toolbox sends the capture through the interface selected by `TARGET_DEVICE`. List interfaces with:

```bash
ip link
```

Choose the interface connected to your training network, for example `enp3s0`, and save it as `TARGET_DEVICE`. Interface names vary between computers; the default `eth0` is not necessarily a physical port. The replay action runs the equivalent of:

```bash
sudo tcpreplay --intf1=enp3s0 path/to/capture.pcap
```

**WSL:** its default NAT networking uses a virtual Ethernet adapter. Selecting WSL's `eth0` does not guarantee that captured Ethernet frames will leave the Windows host's physical port unchanged. See [Microsoft's WSL networking documentation](https://learn.microsoft.com/windows/wsl/networking). For physical-port replay, run Toolbox on native Linux or in a Linux VM with the Ethernet adapter passed through to the guest, then verify traffic at the receiving sensor.

Replay runs on the computer running Toolbox, even when the SecOnion target is remote. The current replay action requires Linux interface discovery and `tcpreplay`; the native Windows launcher supports the Windows host exercises but does not provide native Windows PCAP replay. Toolbox does not rewrite captured IP or MAC addresses, so prepare captures and the receiving network accordingly.

### Capture menu entries

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

- **Variable Settings** edits the Security Onion target and SSH connection settings.
- **Check SecOnion Status** runs `so-status` and lists SecOnion containers.
- **Config Remote Creds** encrypts the remote SSH username and SSH/sudo password.
- **Lock Session Creds** removes decrypted remote credentials and the local sudo password from memory.
- **Clear SecOnion Data** runs `so-elastic-clear` after both a confirmation dialog and the required phrase `CLEAR SECURITY ONION DATA`.

Clearing SecOnion data permanently deletes Elasticsearch documents and indices, including alerts and searchable event data. It does not delete PCAPs in the toolbox.

Configure these values through **Training → SecOnion → Variable Settings**. They are stored in `variables/training-variables.yaml`; the replay settings are edited separately under **Training → Settings**.

| Variable | Meaning |
| --- | --- |
| `SECURITY_ONION_REMOTE_HOST` | Target hostname or IP address; localhost and loopback IPs run locally. |
| `SECURITY_ONION_REMOTE_PORT` | SSH port, normally 22. |
| `SECURITY_ONION_ACCEPT_NEW_HOST_KEY` | Whether the first unseen SSH host key may be accepted automatically. |

## Troubleshooting workflow

Select **Troubleshooting → Tool Update** to pull the latest version from the current Git branch's upstream and restart Toolbox using the same Python environment. Install Git with your preferred package manager if needed. Commit or stash tracked local changes first; failed pulls or diverged branches keep the current instance open. A successful restart stops background replay and clears session credentials. If an update changes dependencies, rerun the setup script before launching again.

Set `REMOTE_HOST` in Variable Settings to `localhost` or `127.0.0.1` for local diagnostics, or a hostname/IP address for SSH diagnostics. `::1` is also local; an empty host defaults to local.

### Docker diagnostics

**Troubleshooting → Docker → Stop All Containers** stops every running container on the selected local or remote host. **Remove All Containers** force-removes running and stopped containers, including services outside Toolbox. Removal discards writable-layer data but retains images, Docker volumes, and bind-mounted host files. Both actions display the target and require a typed confirmation phrase.

The Docker section provides:

- Engine version, daemon information, storage driver, and disk usage.
- Image inventory, dangling-image discovery, optional image inspection, and image history.
- Full container status and recent Docker events.

The **Container Actions** section contains OpenProject, Etherpad, Nextcloud, CTFd, Portainer, and Zulip. Each container expands to:

- **Read Logs**: inspects the container and reads the latest timestamped entries.
- **Remove Container**: asks for confirmation and force-removes only the configured container. Images, volumes, and bind-mounted files remain; writable-layer data is discarded. For Zulip, only its web container is removed.
- **Restart Container**: asks for confirmation, restarts the selected container, and displays its resulting state.
- **Edit Container Settings**: opens an editor for that service's saved deployment image, ports, paths, and other settings, with the logs still visible behind the dialog.

The editor saves to the selected service's file under `variables/docker_variables/`; it does not modify a running container. To apply changes locally, check **Recreate existing container**, save, then select the service's **Install** action under **Deployment → Containers**. Review persistent data paths before recreating. **Restart Container** alone does not apply changed deployment settings.

The editor is available only when the target host is local; it does not edit or redeploy remote containers. Troubleshooting reads managed container names from the included files in `variables/docker_variables/` at execution time, so saved name changes apply to subsequent diagnostics automatically. For remote diagnostics, those names refer to containers on the explicitly selected remote host. **Read Logs** shows actual state, image, ports, and mounts; the editor shows saved deployment settings, which may differ from the running container.

Edit the service's deployment `*_CONTAINER_NAME` value if its actual name differs. `LOG_LINES` controls how many recent lines are requested. Set `DOCKER_USE_SUDO` when the selected account cannot access the Docker daemon directly.

### SecOnion diagnostics

Use **Troubleshooting → SecOnion → Variable Settings** for the target, SSH connection, log length, and selected Security Onion service. Target and SSH values are shared with Docker troubleshooting. Manage encrypted credentials through **Settings → Config Remote Creds**.

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

Remote diagnostics automatically accept and save the first SSH host key by default. Subsequent connections check the saved key and reject changes. This trusts the first connection to the selected target. Set the relevant `*_ACCEPT_NEW_HOST_KEY` value to `false` to require a previously trusted key. Local diagnostics run directly without SSH.

Credential variables are stored separately for Training and Troubleshooting. Unlocked SSH credentials are bound to the host, port, variable file, and encrypted credential values. Switching menus clears session credentials; changing the remote target or saved credentials requires unlocking again. Configure or unlock credentials while the intended YAML menu is selected.

Command displays redact Docker environment values, and output masks known application secrets and session passwords. Container inspection displays selected operational fields rather than the complete environment. Application logs may still contain other sensitive information unknown to the toolbox.

## Offline preparation

On an online staging computer that matches the target distribution, release, architecture, and Python compatibility, run this from the project root:

```bash
./run-once/run-once --download-repos
```

Then copy the complete project, including `repos`, to the offline computer and run this from its project root:

```bash
./run-once/run-once --offline
```

Setup resolves the offline `repos` directory relative to the terminal's current working directory. Running these commands from the project root keeps the downloaded files in the locations used by the toolbox.

The OS package folder is named from the detected platform, for example:

```text
repos/libraries/rocky-9-x86_64/
repos/libraries/ubuntu-24.04-amd64/
repos/libraries/debian-13-amd64/
```

RPM and DEB repositories are not interchangeable. A repository downloaded on one release or architecture should not be assumed to work on another.

To prepare Docker images for offline use, use **Save/Update Images** on an online Docker host, then use **Load Saved Images** on the offline target.

## Editing or extending the toolbox

### Publish as a new initial commit

From WSL or Git Bash, preview the destination and pending files:

```bash
bash scripts/push-initial.sh --dry-run
```

Then publish with:

```bash
bash scripts/push-initial.sh
```

The script asks you to type `PUSH INITIAL`, stages tracked changes and unignored new files, and replaces `origin/main` with one root commit named `Initial commit`. It requires the local `main` branch and refuses remotes with other branches or tags. An explicit force-with-lease prevents overwriting remote changes made after its check. On push failure, local history is retained, though files remain staged. GitHub releases and cached or unreferenced commits are not deleted. Use `--yes` only when you intend to skip the confirmation.

### Add a menu item

Add a child to the appropriate file in `menus/` and reference an existing allow-listed `action_id`. Keep machine-specific values in the matching variables file.

### Add a PCAP

1. Copy the capture to `repos/pcap`.
2. Add or copy an entry under the desired kill-chain phase in `menus/training.yaml`.
3. Set `pcap_name` to the filename or basename.
4. Keep `interface: "${TARGET_DEVICE}"` unless the item intentionally uses another configured interface.

### Add a managed container

At minimum, define its container name, image, host/container ports, restart policy, and local data paths in a new `variables/docker_variables/<service>.yaml` file. Add that file to `Includes` in `variables/deployment-variables.yaml` and its service-to-filename mapping to `CONTAINER_VARIABLE_FILES` in `execution_engines/settings.py`. Add its service module under `execution_engines/docker_engines/` with a `PARAMETERS` mapping and a `deploy(engine, parameters)` function, then register its action ID in `docker_engines/registry.py` and add that action to `menus/deployment.yaml`. Simple services can delegate to the shared `engine._run_container(parameters)` handler. If it needs backup and troubleshooting controls, add matching backup paths and log/restart entries as well.

Implement new operations in the appropriate module under `execution_engines/` and register their action IDs in `execution_engines/main.py`.

## Common problems

### `python: command not found` or missing Python modules

On Linux or WSL, use `./run_toolbox.sh` to select the prepared virtual environment. On Windows, use `.\.venv\Scripts\python.exe .\main.py` from the project root. If the virtual environment is missing, rerun the setup script for that operating system.

### `env: 'bash\r': No such file or directory`

The script has Windows CRLF line endings. Convert it with `sed -i 's/\r$//' run-once/run-once` and rerun `chmod +x run-once/run-once`.

### `sudo: a password is required`

Local SecOnion, sudo-enabled Docker troubleshooting, Docker installation, backup/restore, and PCAP replay actions prompt for the password inside the application. Use **Lock Session Creds** to clear a saved password and enter it again. Run setup from a terminal where sudo can prompt.

### Docker pull TLS handshake timeouts

**Save/Update Images** retries each pull using a short backoff. If all configured attempts fail, check DNS, proxy, firewall, VPN, Docker daemon connectivity, and system time, then rerun the action. Successfully pulled local images do not need to download their layers again.

### Offline Pillow or another wheel is missing

Option 1 is always online and ignores `repos/python`. Use it when connected. To repair offline content, run `./run-once/run-once --download-repos` on a compatible online system before choosing the offline setup option.

### Emoji or icons do not display in WSL

In WSL, Toolbox automatically remaps its window after resizing a normal window
to keep mouse input aligned with the controls. Maximized and fullscreen windows
skip this remap to avoid a second position or size change. **Ctrl+Shift+R** also
requests a manual refresh.
This preserves application state and background services. If the
problem persists, run `TOOLBOX_UI_DEBUG=1 ./run_toolbox.sh` and capture the
terminal output. A continuing heartbeat with misaligned clicks indicates an
input/display problem rather than a blocked application event loop.

The interface uses PNG icons where available. Text emoji rendering depends on the Linux font set and WSL display stack. The setup intentionally avoids large optional font collections; install an emoji-capable font separately only if text emoji are required.

### A PCAP cannot be found

Confirm the file is under `repos/pcap`, and that its basename matches the `pcap_name` in `menus/training.yaml`.

### Replay runs in WSL but no traffic reaches the physical port

Check whether `TARGET_DEVICE` identifies a virtual adapter. Follow [Replay through a physical Ethernet port](#replay-through-a-physical-ethernet-port) and verify packets at the receiving sensor before starting an exercise.

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
6. Verify shared paths under **Deployment → Containers → Variable Settings**, then ports and service paths in each service's **Variable Settings**.
7. Deploy the required training services.
8. Confirm backups exist for any state that must be restored during the exercise.
9. Set the correct PCAP replay interface and verify packets reach the training sensor.
10. Configure the local or remote SecOnion target.
11. Run status checks before students begin.
12. Use container logs, restart controls, and SecOnion diagnostics during the event.
13. Lock session credentials and create final backups when the exercise ends.
