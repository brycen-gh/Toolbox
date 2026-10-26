"""Locate a native POSIX shell without selecting the Windows WSL launcher."""
import os
from pathlib import Path
import shutil
import unittest


def shell(name='sh'):
    if os.name == 'nt':
        for directory in (os.environ.get('ProgramFiles', 'C:/Program Files'),
                          os.environ.get('LOCALAPPDATA', '') + '/Programs'):
            candidate = Path(directory) / 'Git' / 'bin' / (name + '.exe')
            if candidate.is_file():
                return str(candidate)
        raise unittest.SkipTest('Git for Windows is required for POSIX shell integration tests')
    command = shutil.which(name)
    if not command:
        raise unittest.SkipTest(name + ' is required for POSIX shell integration tests')
    return command
