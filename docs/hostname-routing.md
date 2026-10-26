# Lab hostnames with nginx-proxy

The automatic proxy uses [nginx-proxy/nginx-proxy](https://github.com/nginx-proxy/nginx-proxy).
It discovers application frontends through `VIRTUAL_HOST`, `VIRTUAL_PORT` and
their shared Docker network. Databases and caches keep their private stack network.
Nginx Proxy Manager remains available as a separate, manually configured option.

1. Open **Home → Options**, set **Optional domain** to `ggsec.org`, and save.
   Leave it blank to use the original IP-and-port deployment settings.
2. In **Deployment → Prep Install → Save/Update Images**, download nginx-proxy
   and the applications you need, or load their saved images.
3. Open **Deployment → Nginx Reverse Proxy → Install nginx-proxy**.
   Host TCP port **80** must be available. Stop or reconfigure another proxy
   using that port first; Toolbox does not stop it automatically.
4. Install each application. For existing services, enable its **Recreate**
   setting and install again. Restarting a container does not apply new
   environment variables, application URLs or networks.
5. Recreate **Home** to regenerate the browser portal's service links.
6. Use **Home → Options → Client hosts-file entries**. Enter the server's
   reachable LAN IP, copy the block, and add it on every client computer.

For server `172.16.10.250`, these are example entries:

```text
172.16.10.250  ggsec.org
172.16.10.250  home.ggsec.org
172.16.10.250  openproject.ggsec.org
172.16.10.250  etherpad.ggsec.org
172.16.10.250  nextcloud.ggsec.org
172.16.10.250  moodle.ggsec.org
172.16.10.250  mattermost.ggsec.org
172.16.10.250  ctfd.ggsec.org
172.16.10.250  portainer.ggsec.org
172.16.10.250  guacamole.ggsec.org
```

Client hosts files are `C:\Windows\System32\drivers\etc\hosts` on Windows and
`/etc/hosts` on Linux/macOS. Each name needs an explicit mapping; entering only
`ggsec.org` does not map its subdomains. LAN DNS can provide the same mappings.
Toolbox prepares the text and does not edit a client's hosts file.

Browse to **http://openproject.ggsec.org/** or **http://etherpad.ggsec.org/**.
Home is at **http://ggsec.org/** or **http://home.ggsec.org/**. Guacamole retains
its application path: **http://guacamole.ggsec.org/guacamole/**.

The shared domain controls frontend URLs at deployment time. Application data,
credentials and saved direct-port settings are retained. Clearing or changing
the domain requires recreating the services and proxy again. Back up existing
services before recreation. Nextcloud can persist canonical URL settings in its
own configuration; review those if switching an established instance back to
direct-port access.

The automatic lab profile serves **HTTP**. Hosts-file mappings do not provide
TLS certificates. Zulip requires public HTTPS and keeps its existing direct
HTTPS endpoint; use a separately configured TLS proxy for a Zulip hostname.
The existing Nginx Proxy Manager option can manage a manual HTTPS setup.
Portainer uses its internal HTTP listener through this profile while retaining
its direct published HTTPS port.

For Docker inside WSL NAT, clients must reach the Windows LAN IP. Forward port
80 into the Docker distribution with **WSL LAN Forwarding**; the network and
firewall must allow it. Docker Desktop uses its own host networking path.
All routed containers and the proxy must run on the same Docker daemon.

Proxy settings live in `variables/docker_variables/nginx_proxy.yaml`; the
optional `LAB_DOMAIN` lives in `variables/deployment-variables.yaml`. The proxy
uses a read-only Docker socket mount to discover containers. That socket still
provides Docker API access, so this deployment is intended for a trusted lab
host. Configuration snapshots stay separate from live mounts so a failed
replacement can preserve the previous working proxy.
