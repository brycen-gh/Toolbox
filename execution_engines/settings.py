"""Authoritative container names and persistent, private application secrets."""
import json
import os
from pathlib import Path
import secrets
import tempfile

import yaml


def shared_container_variables(base_dir):
    path = Path(base_dir) / 'variables' / 'deployment-variables.yaml'
    if not path.exists():
        return {}
    values = yaml.safe_load(path.read_text(encoding='utf-8'))['Variables']
    return {key: value for key, value in values.items() if key.endswith('_CONTAINER_NAME')}


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


def stored_secret_values(base_dir):
    path = Path(base_dir) / 'variables' / '.service-secrets.json'
    if not path.exists():
        return set()
    return set(json.loads(path.read_text(encoding='utf-8')).values())
