"""Authoritative container names and persistent, private application secrets."""
import json
import os
from pathlib import Path
import secrets
import tempfile

import yaml


CONTAINER_VARIABLE_FILES = {
    'HOME': 'home.yaml',
    'OPENPROJECT': 'open_project.yaml',
    'ETHERPAD': 'etherpad.yaml',
    'NEXTCLOUD': 'nextcloud.yaml',
    'MOODLE': 'moodle.yaml',
    'CTFD': 'ctfd.yaml',
    'PORTAINER': 'portainer.yaml',
    'ZULIP': 'zulip.yaml',
}


# Locate the YAML file belonging to a registered container service.
def container_variables_path(base_dir, service):
    return Path(base_dir) / 'variables' / 'docker_variables' / CONTAINER_VARIABLE_FILES[service]


# Read a variable file and its explicit, relative Includes without flattening it.
def _variable_documents(path):
    path = Path(path).resolve()
    document = yaml.safe_load(path.read_text(encoding='utf-8')) if path.exists() else {'Variables': {}}
    if not isinstance(document, dict):
        raise ValueError(f'Variable file must contain a mapping: {path}')
    if 'Variables' not in document and 'Includes' not in document:
        document = {'Variables': document}
    documents = {path: document}
    includes = document.get('Includes', [])
    if not isinstance(includes, list):
        raise ValueError(f'Includes must be a list: {path}')
    for filename in includes:
        included = (path.parent / str(filename)).resolve()
        if Path(str(filename)).is_absolute() or not included.is_relative_to(path.parent):
            raise ValueError(f'Variable include escapes its directory: {filename}')
        if included in documents:
            raise ValueError(f'Duplicate variable include: {filename}')
        child = yaml.safe_load(included.read_text(encoding='utf-8'))
        if not isinstance(child, dict) or 'Includes' in child:
            raise ValueError(f'Included variable files must be mappings without nested Includes: {included}')
        documents[included] = child if 'Variables' in child else {'Variables': child}
    owners = {}
    for filename, data in documents.items():
        values = data.get('Variables', {})
        if not isinstance(values, dict):
            raise ValueError(f'Variables must be a mapping: {filename}')
        for key in values:
            if key in owners:
                raise ValueError(f'Duplicate variable {key!r} in {filename} and {owners[key]}')
            owners[key] = filename
    return documents, owners


# Merge shared settings and included service files into one variable mapping.
def load_variables(path):
    documents, _ = _variable_documents(path)
    return {key: value for document in documents.values()
            for key, value in document.get('Variables', {}).items()}


# Save each value back to its owning file, retaining the include list.
def save_variables(path, values):
    path = Path(path).resolve()
    documents, owners = _variable_documents(path)
    grouped = {filename: {} for filename in documents}
    for key, value in values.items():
        owner = owners.get(key)
        if owner is None:
            service = str(key).split('_', 1)[0]
            filename = CONTAINER_VARIABLE_FILES.get(service)
            candidate = path.parent / 'docker_variables' / filename if filename else None
            owner = candidate if candidate in documents else path
        grouped[owner][key] = value
    staged = []
    try:
        for filename, document in documents.items():
            if filename.exists() and document.get('Variables', {}) == grouped[filename]:
                continue
            document['Variables'] = grouped[filename]
            filename.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=filename.parent,
                                             suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                staged.append((temporary, filename))
                yaml.safe_dump(document, stream, sort_keys=False, allow_unicode=True)
            if filename.exists():
                os.chmod(temporary, filename.stat().st_mode & 0o777)
        for temporary, filename in staged:
            os.replace(temporary, filename)
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)


# Read authoritative container names for troubleshooting actions.
def shared_container_variables(base_dir):
    path = Path(base_dir) / 'variables' / 'deployment-variables.yaml'
    if not path.exists():
        return {}
    values = load_variables(path)
    return {key: value for key, value in values.items() if key.endswith('_CONTAINER_NAME')}


# Reuse or securely persist a secret for a container and environment key.
def persistent_secret(base_dir, container, key, existing=None):
    path = Path(base_dir) / 'variables' / '.service-secrets.json'
    values = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    identity = container + ':' + key
    if identity in values:
        return values[identity]
    values[identity] = existing or secrets.token_hex(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         delete=False) as stream:
            temporary = Path(stream.name)
            os.chmod(temporary, 0o600)
            json.dump(values, stream)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return values[identity]


# Load saved application secrets so command output can redact them.
def stored_secret_values(base_dir):
    path = Path(base_dir) / 'variables' / '.service-secrets.json'
    if not path.exists():
        return set()
    return set(json.loads(path.read_text(encoding='utf-8')).values())
