# Toolbox icons

Use a PNG filename without its extension in menu YAML, for example:

```yaml
label: Database Logs
icon: database
```

The additional icons are 128 x 128 RGBA PNGs with transparent backgrounds,
blue gradients, and dark outlines matching the existing palette.

| Icon | Suggested programs or use cases |
| --- | --- |
| learning | Moodle, courses, training materials |
| chat | Zulip, Mattermost, team messaging |
| database | PostgreSQL, MySQL, Redis, database administration |
| terminal | PowerShell, SSH, command line tools |
| network | Interfaces, connectivity, network diagnostics |
| security | Security Onion, security checks, protection |
| backup | Backups, snapshots, restore tasks |
| logs | Service logs, audit trails, event viewers |
| monitoring | Health checks, metrics, Grafana |
| automation | Scheduled jobs, scripts, workflows |
| upload | Import files, upload archives |
| folder | Shared directories, file managers |
| web | Browsers, web services, portals |
| mail | Mail services, notifications |
| key | Credentials, authentication, access |
| replay | PCAP replay, rerun an exercise |

Menus use these icons for learning, chat, backup, replay, security, monitoring,
logs, and credentials. All icons are loaded by filename through `get_icon`;
missing names fall back to `default.png`.

These are generic symbols, not official program logos. Preview the set in
`docs/extra-icons-preview.png`. The PowerShell drawing source is
`scripts/create-extra-icons.ps1`; it refuses to overwrite existing icon files.
