"""Image sizes for the download selector; metadata only, never pulls images."""
import json
import platform
import subprocess
from urllib.parse import quote
from urllib.request import urlopen


def image_size(image, architecture=None):
    architecture = architecture or {"x86_64": "amd64", "aarch64": "arm64", "AMD64": "amd64"}.get(platform.machine(), platform.machine())
    size = None
    source = "Size unavailable"
    reference = image.removeprefix("docker.io/").removeprefix("index.docker.io/")
    repository, separator, tag = reference.rpartition(":")
    if not separator:
        repository, tag = reference, "latest"
    if "@" not in reference and not ("/" in repository and ("." in repository.split('/')[0] or ':' in repository.split('/')[0])):
        if '/' not in repository:
            repository = 'library/' + repository
        try:
            namespace, name = repository.split('/', 1)
            url = f'https://hub.docker.com/v2/namespaces/{quote(namespace, safe="")}/repositories/{quote(name, safe="")}/tags/{quote(tag, safe="")}'
            with urlopen(url, timeout=6) as response:
                data = json.load(response)
            candidates = [item for item in data.get('images', []) if item.get('architecture') == architecture and item.get('os') == 'linux']
            if candidates:
                size = candidates[0].get('size')
                source = f'Compressed, linux/{architecture}'
        except Exception:
            pass
    if size is None:
        try:
            result = subprocess.run(['docker', 'image', 'inspect', image, '--format', '{{.Size}}'], capture_output=True, text=True, timeout=3)
            if result.returncode == 0:
                size = int(result.stdout.strip())
                source = 'Local disk size; download size unavailable'
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    return size, source
