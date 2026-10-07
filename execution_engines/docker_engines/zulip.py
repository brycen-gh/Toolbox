"""Local Zulip Compose deployment with persistent dependency credentials."""
import os
from pathlib import Path
import re
import secrets
import tarfile
import uuid

import yaml

from ..result import ExecutionResult


PARAMETERS = {
    "name": "${ZULIP_CONTAINER_NAME}",
    "zulip_image": "${ZULIP_IMAGE}",
    "database_image": "${ZULIP_DATABASE_IMAGE}",
    "memcached_image": "${ZULIP_MEMCACHED_IMAGE}",
    "rabbitmq_image": "${ZULIP_RABBITMQ_IMAGE}",
    "redis_image": "${ZULIP_REDIS_IMAGE}",
    "recreate": "${ZULIP_RECREATE}",
    "restart": "${ZULIP_RESTART_POLICY}",
    "https_port": "${ZULIP_HTTPS_HOST_PORT}",
    "bind_address": "${ZULIP_BIND_ADDRESS}",
    "external_host": "${ZULIP_EXTERNAL_HOST}",
    "organization_id": "${ZULIP_ORGANIZATION_ID}",
    "administrator": "${ZULIP_ADMINISTRATOR}",
    "data_directory": "${ZULIP_DATA_VOLUME}",
}


# Deploy zulip using the resolved service recipe and shared engine.
def deploy(engine, parameters):
    return engine._deploy_zulip(parameters)


class ZulipActions:
    # Extract before touching live data; retain the previous directory for recovery.
    def _restore_zulip(self, parameters):
        root = self._local_data_directory(parameters['data_directory'])
        backup_dir = self._project_directory(parameters['backup_directory'], 'backup directory')
        archive_name = str(parameters.get('archive_name', ''))
        if not archive_name or Path(archive_name).name != archive_name:
            raise ValueError('Zulip restore requires a backup filename')
        archive = backup_dir / archive_name
        if not archive.is_file():
            raise ValueError(f'Backup not found: {archive}')
        self._validate_backup_archive(archive)
        with tarfile.open(archive) as stream:
            members = {entry.name.removeprefix('./'): entry for entry in stream.getmembers()}
            required = ['compose.yaml', 'database/PG_VERSION'] + [
                'secrets/' + key for key in ('postgres_password', 'memcached_password',
                                             'rabbitmq_password', 'redis_password', 'secret_key')]
            if any(key not in members or not members[key].isfile() for key in required):
                raise ValueError('This archive is not a complete Zulip stack backup')
            saved = yaml.safe_load(stream.extractfile(members['compose.yaml']).read())
        if not root.is_dir():
            raise ValueError('Install the matching Zulip stack before restoring its backup')
        current = yaml.safe_load((root / 'compose.yaml').read_text(encoding='utf-8'))
        def identities(document):
            return {key: (value['image'], value['container_name'])
                    for key, value in document['services'].items()}
        if identities(saved) != identities(current):
            raise ValueError('Restore requires matching Zulip image versions and container names')
        running = self._running_containers(self._container_names(parameters))
        suffix = uuid.uuid4().hex[:12]
        staging = root.with_name(root.name + '-restore-' + suffix)
        previous = root.with_name(root.name + '-previous-' + suffix)
        staging.mkdir(mode=0o700)
        sudo = self._sudo_prefix()
        extracted = self._run_steps([sudo + ['tar', '--extract', '--gzip', '--file', str(archive),
                                            '--directory', str(staging)]])
        if extracted.returncode:
            extracted.output.append(f'Live data is unchanged. Incomplete restore files remain at {staging}.')
            return extracted

        def replace():
            if self.cancel_requested.is_set():
                return ExecutionResult(['Restore cancelled; live data is unchanged.'], 130)
            # Do not honor cancellation between the two renames or during rollback.
            self._protect_cleanup = True
            try:
                moved = self._run_steps([sudo + ['mv', '--', str(root), str(previous)]])
                if moved.returncode:
                    return moved
                installed = self._run_steps([sudo + ['mv', '--', str(staging), str(root)]])
                if installed.returncode:
                    recovered = self._run_steps([sudo + ['mv', '--', str(previous), str(root)]])
                    installed.output.extend(recovered.output)
                    if recovered.returncode:
                        installed.output.append(f'Manual recovery required: original data is at {previous}.')
                    return installed
                return ExecutionResult([f'Zulip backup restored. Previous data retained at {previous}.'])
            finally:
                self._protect_cleanup = False

        return self._with_stopped_containers(running, replace)

    # Generate persistent stack configuration, initialize Zulip, and start its services.
    def _deploy_zulip(self, parameters):
        name = str(parameters.get('name', ''))
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', name):
            raise ValueError('Zulip container name must use lowercase letters, digits, _ or -')
        host = str(parameters.get('external_host', '')).strip()
        administrator = str(parameters.get('administrator', '')).strip()
        if not host or '://' in host or '/' in host or any(c.isspace() for c in host):
            raise ValueError('Set ZULIP_EXTERNAL_HOST to the hostname and optional port, without a URL scheme')
        if '@' not in administrator:
            raise ValueError('Set ZULIP_ADMINISTRATOR to an email address')
        port = int(parameters.get('https_port', 8443))
        if not 1 <= port <= 65535:
            raise ValueError('Zulip HTTPS port must be between 1 and 65535')
        root = self._local_data_directory(parameters['data_directory'])
        compose_path = root / 'compose.yaml'
        names = [name] + [name + '-' + service for service in ('database', 'memcached', 'rabbitmq', 'redis')]
        existing = set(self._docker_read(['container', 'ls', '-a', '--format', '{{.Names}}']).splitlines())
        occupied = existing.intersection(names)
        recreate = self._as_bool(parameters.get('recreate', False), 'recreate')
        if occupied and not recreate:
            return ExecutionResult(['Zulip containers already exist. Back up the stack, then enable ZULIP_RECREATE to apply changes.'], 1)
        # Never adopt containers belonging to another Compose project.
        for container in occupied:
            owner = self._docker_read(['container', 'inspect', '--format',
                                       '{{index .Config.Labels "com.docker.compose.project"}}', container]).strip()
            if owner != 'toolbox-' + name:
                raise ValueError(f'Container {container!r} belongs to another deployment')
        check = self._run_steps([['docker', 'compose', 'version']])
        if check.returncode:
            return check
        for service in ('database', 'memcached', 'rabbitmq', 'redis', 'zulip'):
            image = str(parameters[service + '_image']).strip()
            if not image or image.startswith('-'):
                raise ValueError(f'Invalid Zulip {service} image')
            try:
                self._docker_read(['image', 'inspect', image])
            except RuntimeError as exc:
                raise ValueError(f'Zulip image {image!r} is unavailable. Use Save/Update Images or Load Saved Images first.') from exc
        secret_dir = root / 'secrets'
        # Missing secrets on an existing installation must not silently rotate credentials.
        initialized = occupied or compose_path.exists() or (root / 'database').exists()
        keys = ('postgres_password', 'memcached_password', 'rabbitmq_password', 'redis_password', 'secret_key')
        if initialized and any(not (secret_dir / key).is_file() for key in keys):
            raise ValueError('Zulip secrets are missing. Restore the original secrets directory from backup.')
        secret_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(secret_dir, 0o700)
        for key in keys:
            path = secret_dir / key
            if not path.exists():
                with path.open('x', encoding='utf-8') as stream:
                    os.chmod(path, 0o600)
                    stream.write(secrets.token_hex(32))
            # Memcached runs as a non-root UID. Compose bind-mounts these files;
            # the private parent directory protects them on the host.
            os.chmod(path, 0o444)
            value = path.read_text(encoding='utf-8')
            if not value.strip():
                raise ValueError(f'Empty Zulip secret file: {path}')
            self._sensitive_values.add(value)

        def secret(key):
            return 'zulip__' + key

        def mount(folder, target):
            return {'type': 'bind', 'source': './' + folder, 'target': target}

        restart = str(parameters.get('restart', 'unless-stopped'))
        services = {}
        for service in ('database', 'memcached', 'rabbitmq', 'redis', 'zulip'):
            image = str(parameters[service + '_image']).strip()
            if not image or image.startswith('-'):
                raise ValueError(f'Invalid Zulip {service} image')
            services[service] = {
                'image': image,
                'container_name': name if service == 'zulip' else name + '-' + service,
                'restart': restart,
                'pull_policy': 'never',
            }
        services['database'].update({
            'environment': {'POSTGRES_DB': 'zulip', 'POSTGRES_USER': 'zulip',
                            'POSTGRES_PASSWORD_FILE': '/run/secrets/zulip__postgres_password'},
            'secrets': [secret('postgres_password')],
            'volumes': [mount('database', '/var/lib/postgresql/data')],
        })
        services['memcached'].update({
            'environment': {'SASL_CONF_PATH': '/home/memcache/memcached.conf',
                            'MEMCACHED_SASL_PWDB': '/home/memcache/memcached-sasl-db'},
            'secrets': [secret('memcached_password')],
            'command': ['sh', '-ec',
                        'printf "mech_list: plain\\n" > "$$SASL_CONF_PATH"; '
                        'p=$$(cat /run/secrets/zulip__memcached_password); '
                        'printf "zulip@%s:%s\\nzulip@localhost:%s\\n" "$$HOSTNAME" "$$p" "$$p" '
                        '> "$$MEMCACHED_SASL_PWDB"; exec memcached -S'],
        })
        services['rabbitmq'].update({
            'hostname': 'rabbitmq',
            'environment': {'RABBITMQ_DEFAULT_USER': 'zulip'},
            'secrets': [secret('rabbitmq_password')],
            'command': ['sh', '-ec', 'export RABBITMQ_DEFAULT_PASS=$$(cat /run/secrets/zulip__rabbitmq_password); '
                        'exec docker-entrypoint.sh rabbitmq-server'],
            'volumes': [mount('rabbitmq', '/var/lib/rabbitmq')],
        })
        services['redis'].update({
            'secrets': [secret('redis_password')],
            'command': ['sh', '-ec', 'exec /usr/local/bin/docker-entrypoint.sh redis-server '
                        '--requirepass "$$(cat /run/secrets/zulip__redis_password)"'],
            'volumes': [mount('redis', '/data')],
        })
        services['zulip'].update({
            'environment': {'SETTING_EXTERNAL_HOST': host, 'SETTING_ZULIP_ADMINISTRATOR': administrator,
                            'CERTIFICATES': 'self-signed', 'SETTING_REMOTE_POSTGRES_HOST': 'database',
                            'SETTING_MEMCACHED_LOCATION': 'memcached:11211',
                            'SETTING_RABBITMQ_HOST': 'rabbitmq', 'SETTING_REDIS_HOST': 'redis'},
            'secrets': [secret(key) for key in keys],
            'ports': [f'{parameters.get("bind_address", "127.0.0.1")}:{port}:443'],
            'volumes': [mount('zulip', '/data')],
            'depends_on': ['database', 'memcached', 'rabbitmq', 'redis'],
            'ulimits': {'nofile': {'soft': 1000000, 'hard': 1048576}},
        })
        document = {'services': services,
                    'secrets': {secret(key): {'file': './secrets/' + key} for key in keys}}
        # A named organization supports localhost routing; the root realm ignores overrides.
        if host.split(':', 1)[0] == 'localhost':
            import json
            services['zulip']['environment']['SETTING_EXTERNAL_HOST'] = host.replace('localhost', 'localhost.localdomain', 1)
            organization_id = str(parameters.get('organization_id', 'ggsec'))
            if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', organization_id):
                raise ValueError('ZULIP_ORGANIZATION_ID must be a lowercase slug')
            services['zulip']['environment']['SETTING_REALM_HOSTS'] = json.dumps({organization_id: host})
        # Escape user-controlled dollar signs so Compose does not interpolate them.
        for service in services.values():
            for field in ('image', 'container_name', 'restart'):
                service[field] = service[field].replace('$', '$$')
        for key, value in services['zulip']['environment'].items():
            services['zulip']['environment'][key] = value.replace('$', '$$')
        temporary = root / 'compose.yaml.new'
        temporary.write_text(yaml.safe_dump(document, sort_keys=False), encoding='utf-8')
        os.replace(temporary, compose_path)
        command = ['docker', 'compose', '--project-name', 'toolbox-' + name, '-f', str(compose_path)]
        commands = [command + ['config', '--quiet']]
        if occupied:
            commands.append(command + ['stop', 'zulip'])
        commands.extend([
            command + ['run', '--rm', '--pull', 'never', 'zulip', 'app:init'],
            command + ['up', '-d', '--wait', '--wait-timeout', '600', '--pull', 'never'],
        ])
        result = self._run_steps(commands)
        if result.returncode:
            result.output.append('Zulip setup did not complete. Inspect the stack logs before retrying; data and containers were retained.')
        else:
            result.output.append(f'Zulip is available at https://{host}. Use Create Organization Link to finish setup. The training certificate is self-signed.')
        return result

    # Create the local organization and owner, sending the password over stdin.
    def _zulip_create_organization(self, parameters):
        name = str(parameters.get('name', ''))
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', name):
            raise ValueError('Invalid Zulip container name')
        organization = str(parameters.get('organization', '')).strip()
        email = str(parameters.get('email', '')).strip()
        full_name = str(parameters.get('full_name', '')).strip()
        password = str(parameters.get('initial_password', ''))
        if password != password.strip():
            raise ValueError('The initial password cannot begin or end with whitespace')
        if not organization or not full_name or '@' not in email or not password.strip() or '\n' in password or '\r' in password:
            raise ValueError('Provide an organization name, owner name, email and a single-line password')
        if any(value.startswith('-') for value in (organization, email, full_name)):
            raise ValueError('Organization name, owner email and owner name cannot start with a dash')
        self._sensitive_values.add(password)
        organization_id = str(parameters.get('organization_id', 'ggsec'))
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', organization_id):
            raise ValueError('ZULIP_ORGANIZATION_ID must be a lowercase slug')
        command = ['docker', 'exec', '-i', '-u', 'zulip', name,
                   '/home/zulip/deployments/current/manage.py', 'create_realm',
                   '--string-id=' + organization_id, '--password-file=/dev/stdin', '--no-color',
                   organization, email, full_name]
        result = self._run_process(command, input_text=password + '\n')
        return ExecutionResult([result.stdout, 'Organization and owner created.' if result.returncode == 0
                                else 'Organization creation failed; review the output above.'], result.returncode)

    # Generate a private organization-creation link in the running Zulip container.
    def _zulip_organization_link(self, parameters):
        name = str(parameters.get('name', ''))
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', name):
            raise ValueError('Invalid Zulip container name')
        return self._run_steps([['docker', 'exec', '-u', 'zulip', name,
                                 '/home/zulip/deployments/current/manage.py', 'generate_realm_creation_link', '--no-color']])
