from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from shell_support import shell


class SetupPublishTests(unittest.TestCase):
    def test_setup_validation_blocks(self):
        root = Path.cwd()
        linux = (root / 'run-once/run-once').read_text()
        windows = (root / 'run-once/run-once.ps1').read_text()
        blocks = [linux.split("<<'PY'\n", 1)[1].split('\nPY\n', 1)[0],
                  windows.split("@'\n", 1)[1].split("\n'@", 1)[0]]
        for block in blocks:
            result = subprocess.run([sys.executable, '-c', block],
                env=dict(os.environ, TOOLBOX_PROJECT_DIR=str(root)), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_initial_publish_against_temporary_local_remote(self):
        if not Path('scripts/push-initial.sh').is_file():
            self.skipTest('Optional local publishing script is not installed')
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repo = base / 'project'
            remote = base / 'remote.git'
            def run(*args, ok=True):
                result = subprocess.run(args, cwd=repo if repo.exists() else base,
                    capture_output=True, text=True)
                if ok:
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result
            run('git', 'init', '--bare', str(remote))
            run('git', 'init', '-b', 'main', str(repo))
            run('git', 'config', 'user.name', 'Script Test')
            run('git', 'config', 'user.email', 'test@example.invalid')
            (repo / 'scripts').mkdir()
            shutil.copyfile('scripts/push-initial.sh', repo / 'scripts/push-initial.sh')
            (repo / '.gitignore').write_text('private.txt\n')
            (repo / 'app.txt').write_text('old')
            run('git', 'add', '--all')
            run('git', 'commit', '-m', 'old version')
            run('git', 'remote', 'add', 'origin', str(remote))
            run('git', 'push', 'origin', 'main')
            old = run('git', 'rev-parse', 'HEAD').stdout.strip()
            (repo / 'app.txt').write_text('new')
            (repo / 'extra.txt').write_text('included')
            (repo / 'private.txt').write_text('excluded')
            run(shell('bash'), 'scripts/push-initial.sh', '--dry-run')
            self.assertEqual(run('git', 'rev-parse', 'HEAD').stdout.strip(), old)
            run(shell('bash'), 'scripts/push-initial.sh', '--yes')
            self.assertEqual(run('git', 'rev-list', '--count', 'HEAD').stdout.strip(), '1')
            new = run('git', 'rev-parse', 'HEAD').stdout.strip()
            self.assertNotEqual(old, new)
            self.assertIn(new, run('git', 'ls-remote', 'origin', 'refs/heads/main').stdout)
            files = run('git', 'ls-tree', '-r', '--name-only', 'HEAD').stdout
            self.assertIn('extra.txt', files)
            self.assertNotIn('private.txt', files)
            self.assertEqual(run('git', 'status', '--porcelain').stdout, '')
            run('git', 'push', 'origin', 'HEAD:refs/heads/backup')
            refused = run(shell('bash'), 'scripts/push-initial.sh', '--yes', ok=False)
            self.assertNotEqual(refused.returncode, 0)
            self.assertEqual(run('git', 'rev-parse', 'HEAD').stdout.strip(), new)
