#!/usr/bin/env bash
# Copy Toolbox off a shared folder and prepare a fresh Linux environment.
set -Eeuo pipefail

if [[ ${1:-} == --help || ${1:-} == -h ]]; then
    printf 'Usage: bash copy_local.sh [destination]\nDefault destination: ~/Toolbox\n'
    exit 0
fi
if (( $# > 1 )); then
    printf 'Usage: bash copy_local.sh [destination]\n' >&2
    exit 1
fi
if (( EUID == 0 )); then
    printf 'Run this script without sudo. Setup requests elevated access when needed.\n' >&2
    exit 1
fi

SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
DESTINATION="${1:-${HOME}/Toolbox}"
for command_name in tar realpath; do
    command -v "$command_name" >/dev/null || {
        printf 'Required command is missing: %s\n' "$command_name" >&2
        exit 1
    }
done
DESTINATION="$(realpath -m -- "$DESTINATION")"
case "$DESTINATION/" in
    "$SOURCE_DIR/"*)
        printf 'Choose a destination outside the source directory.\n' >&2
        exit 1
        ;;
    /mnt/hgfs/*)
        printf 'Choose a destination on the VM local disk, outside /mnt/hgfs.\n' >&2
        exit 1
        ;;
esac
if [[ -e "$DESTINATION" ]]; then
    if [[ ! -d "$DESTINATION" ]]; then
        printf 'Destination is not a directory: %s\n' "$DESTINATION" >&2
        exit 1
    fi
    shopt -s nullglob dotglob
    existing_files=("$DESTINATION"/*)
    if (( ${#existing_files[@]} )); then
        printf 'Destination must be empty. Choose another directory: %s\n' "$DESTINATION" >&2
        exit 1
    fi
fi

mkdir -p -- "$DESTINATION"
printf 'Copying Toolbox to %s (excluding the old virtual environment)…\n' "$DESTINATION"
tar -C "$SOURCE_DIR" --exclude='./.venv' --exclude='./.setup-complete' -cf - . |
    tar -C "$DESTINATION" -xf -

cd -- "$DESTINATION"
printf 'Starting setup. Choose online or offline preparation as appropriate.\n'
bash ./run-once/run-once
printf '\nToolbox is ready. Launch it without sudo:\n  cd %q\n  bash ./run_toolbox.sh\n' "$DESTINATION"
