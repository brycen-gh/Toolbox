"""CTFd deployment and complete SQLite site backups."""
import json
from pathlib import PurePosixPath
import shutil
import tarfile
import tempfile
import uuid
from pathlib import Path

from ..result import ExecutionResult

PARAMETERS = {
    "name": "${CTFD_CONTAINER_NAME}",
    "image": "${CTFD_IMAGE}",
    "recreate": "${CTFD_RECREATE}",
    "restart": "${CTFD_RESTART_POLICY}",
    "ports": ["${CTFD_HOST_PORT}:${CTFD_CONTAINER_PORT}"],
    "volumes": ["${CTFD_DATA_VOLUME}:/var/ctfd-data"],
    "environment": {"SECRET_KEY": "${CTFD_SECRET_KEY}",
                    "DATABASE_URL": "sqlite:////var/ctfd-data/database/ctfd.db",
                    "UPLOAD_FOLDER": "/var/ctfd-data/uploads"},
}


# Deploy ctfd using the resolved service recipe and shared engine.
def deploy(engine, parameters):
    recreate = engine._as_bool(parameters.get('recreate', False), 'recreate')
    names = engine._docker_read(["container", "ls", "-a", "--format", "{{.Names}}"] ).splitlines() if recreate else []
    if parameters['name'] in names:
        info = json.loads(engine._docker_read(['container', 'inspect', parameters['name']]))[0]
        environment = dict(x.split('=', 1) for x in info['Config'].get('Env', []) if '=' in x)
        if environment.get('DATABASE_URL') != PARAMETERS['environment']['DATABASE_URL']:
            return ExecutionResult(['Legacy CTFd storage detected. Create a Manual Backup first, remove the old container through Troubleshooting, load that complete backup, then Install CTFd. Recreation is blocked to preserve the existing database.'], 2)
    root = engine._local_data_directory(parameters['volumes'][0].split(':', 1)[0])
    result = prepare_storage(engine, root, parameters['image'])
    if result.returncode:
        return result
    return engine._run_container(parameters)


def prepare_storage(engine, root, image):
    root.mkdir(parents=True, exist_ok=True)
    result = engine._run_steps([['docker', 'run', '--rm', '--pull', 'never', '--user', '0',
                                '--entrypoint', 'sh', '-v', f'{root}:/var/ctfd-data',
                                image, '-c',
                                'mkdir -p /var/ctfd-data/database /var/ctfd-data/uploads && '
                                'chmod 755 /var/ctfd-data && '
                                'chown -R ctfd:ctfd /var/ctfd-data/database /var/ctfd-data/uploads']])
    return result


def backup(engine, parameters):
    """Snapshot actual container data, including the legacy writable-layer DB."""
    name = engine._container_names(parameters)[0]
    info = json.loads(engine._docker_read(['container', 'inspect', name]))[0]
    environment = dict(x.split('=', 1) for x in info['Config'].get('Env', []) if '=' in x)
    url = environment.get('DATABASE_URL') or 'sqlite:////opt/CTFd/CTFd/ctfd.db'
    if not url.startswith('sqlite:////') or '?' in url:
        return ExecutionResult(['CTFd backup supports the local SQLite preset only; external databases require their own backup.'], 2)
    database = PurePosixPath(url[len('sqlite:///'):])
    uploads = environment.get('UPLOAD_FOLDER') or '/opt/CTFd/CTFd/uploads'
    if not database.is_absolute() or not PurePosixPath(uploads).is_absolute():
        raise ValueError('CTFd data paths must be absolute')
    running = engine._running_containers([name])
    with tempfile.TemporaryDirectory(prefix='ctfd-backup-') as temporary:
        root = Path(temporary)
        snapshot = root / 'snapshot'
        snapshot.mkdir(mode=0o700)
        captured = root / 'captured'
        captured.mkdir()

        def capture():
            result = engine._run_steps([['docker', 'cp', f'{name}:{database.parent}/.', str(captured)]])
            if result.returncode:
                return result
            source = captured / database.name
            if not source.is_file() or source.stat().st_size == 0:
                return ExecutionResult(['CTFd database missing or empty; no complete backup created.'], 2)
            target = snapshot / 'database'
            target.mkdir()
            for suffix in ('', '-wal', '-shm', '-journal'):
                source = captured / (database.name + suffix)
                if source.exists():
                    shutil.copyfile(source, target / ('ctfd.db' + suffix))
            (snapshot / 'uploads').mkdir()
            command = ['docker', 'cp', f'{name}:{uploads}/.', str(snapshot / 'uploads')]
            engine._emit('$ ' + engine._display_command(command))
            copied = engine._run_process(command, capture_output=True)
            if copied.returncode:
                # Docker reports a specific missing-path error for a site that
                # has never uploaded files. Do not suppress daemon/permission
                # failures, or a missing explicitly configured upload path.
                missing = f'Could not find the file {uploads}/. in container {name}'
                if (not environment.get('UPLOAD_FOLDER') and
                        copied.returncode != 130 and missing in copied.stdout):
                    engine._emit('No default CTFd uploads directory exists; backing up the database with empty uploads.')
                else:
                    return ExecutionResult([copied.stdout], copied.returncode)
            (snapshot / 'ctfd-backup.json').write_text(json.dumps({'format': 1, 'image': info['Config']['Image']}))
            args = dict(parameters, data_directory=str(snapshot), containers=[])
            return engine._backup_container_data(args)

        return engine._with_stopped_containers(running, capture)


def restore(engine, parameters):
    """Restore complete archives; never accept the old uploads-only backups."""
    backup_dir = engine._project_directory(parameters['backup_directory'], 'backup directory')
    archive_name = parameters['archive_name']
    if Path(archive_name).name != archive_name:
        raise ValueError('archive_name must be a filename')
    archive = backup_dir / archive_name
    engine._validate_backup_archive(archive)
    with tarfile.open(archive) as contents:
        members = {m.name.removeprefix('./'): m for m in contents.getmembers()}
        db = members.get('database/ctfd.db')
        if db is None or not db.isfile() or db.size == 0 or 'ctfd-backup.json' not in members:
            return ExecutionResult(['Incomplete CTFd backup: database is missing. Create a new Manual Backup from the original container.'], 2)
        if any(m.issym() or m.islnk() or
               (key not in ('.', 'database', 'uploads', 'ctfd-backup.json') and
                not key.startswith(('database/', 'uploads/')))
               for key, m in members.items()):
            raise ValueError('Unexpected content or links in CTFd backup')
        metadata = json.load(contents.extractfile(members['ctfd-backup.json']))
        if metadata.get('format') != 1 or not isinstance(metadata.get('image'), str) or not metadata['image']:
            raise ValueError('Invalid CTFd backup metadata')
    name = engine._container_names(parameters)[0]
    names = engine._docker_read(['container', 'ls', '-a', '--format', '{{.Names}}']).splitlines()
    if name in names:
        info = json.loads(engine._docker_read(['container', 'inspect', name]))[0]
        environment = dict(x.split('=', 1) for x in info['Config'].get('Env', []) if '=' in x)
        if environment.get('DATABASE_URL') != PARAMETERS['environment']['DATABASE_URL']:
            return ExecutionResult(['Legacy CTFd container cannot use this restored database. Preserve a complete backup, remove the old container through Troubleshooting, then Load Backup and Install CTFd.'], 2)
    running = engine._running_containers([name]) if name in names else []
    def load():
        root = engine._local_data_directory(parameters['data_directory'])
        root.parent.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex
        stage = root.with_name(root.name + '.restore-' + token)
        previous = root.with_name(root.name + '.previous-' + token)
        stage.mkdir(mode=0o700)
        sudo = engine._sudo_prefix()
        result = engine._run_steps([sudo + ['tar', '--extract', '--gzip', '--file', str(archive), '--directory', str(stage)]])
        if result.returncode:
            return result
        image = info['Config']['Image'] if name in names else metadata['image']
        result = prepare_storage(engine, stage, image)
        if result.returncode:
            return result
        had_data = root.exists()
        if had_data:
            result = engine._run_steps([sudo + ['mv', '--', str(root), str(previous)]])
            if result.returncode:
                return result
        result = engine._run_steps([sudo + ['mv', '--', str(stage), str(root)]])
        if result.returncode and had_data:
            recovery = engine._run_steps([sudo + ['mv', '--', str(previous), str(root)]])
            result.output.extend(recovery.output)
        if result.returncode == 0:
            result.output.append('CTFd database and uploads restored. Install CTFd if the container does not yet exist.')
            if had_data:
                result.output.append(f'Previous data retained for recovery: {previous}')
        return result
    return engine._with_stopped_containers(running, load)
