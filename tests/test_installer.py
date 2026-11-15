"""Установщик запускается только после перенаправления путей и подмены системных команд."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


INSTALLER = os.environ.get('ARCHMON_INSTALLER')


@unittest.skipUnless(INSTALLER, 'Set ARCHMON_INSTALLER to test the built installer in isolation')
class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / 'user'
        self.fake_root = self.root / 'system'
        self.bin = self.root / 'commands'
        self.bin.mkdir()
        self.log = self.root / 'commands.log'
        self.app = self.home / '.local/share/archmon'
        self.app.mkdir(parents=True)
        (self.app / 'old-marker').write_text('previous installation')
        self.env = dict(os.environ, PATH=f'{self.bin}:{os.environ["PATH"]}',
                        ARCHMON_TEST_HOME=str(self.home), ARCHMON_TEST_ROOT=str(self.fake_root),
                        ARCHMON_TEST_LOG=str(self.log), ARCHMON_TEST_RECOVERY_FAIL='0',
                        ARCHMON_TEST_UNIT_STATE='loaded', ARCHMON_TEST_STOP_FAIL='0', ARCHMON_TEST_ACTIVE='inactive')
        def command(name, body):
            p = self.bin / name
            p.write_text('#!/bin/sh\nprintf "%s\\n" "' + name + ' $*" >> "$ARCHMON_TEST_LOG"\n' + body + '\n')
            p.chmod(0o755)
        command('sudo', 'exec "$@"')
        command('systemctl', 'case "$*" in\n*LoadState*) echo "$ARCHMON_TEST_UNIT_STATE" ;;\n'
                '*ActiveState*) echo "$ARCHMON_TEST_ACTIVE" ;;\nstop*) exit "$ARCHMON_TEST_STOP_FAIL" ;;\nesac\nexit 0')
        command('recover', 'if [ "$ARCHMON_TEST_RECOVERY_FAIL" = 1 ]; then exit 1; fi\n'
                'rm -f "$ARCHMON_TEST_ROOT/run/archmon-fans/original.json"\nexit 0')
        for name in ('pacman', 'pkill', 'update-desktop-database', 'kbuildsycoca6'):
            command(name, 'exit 0')
        text = Path(INSTALLER).read_text()
        header, payload = text.split('\n#__PAYLOAD__\n', 1)
        header = header.replace('$HOME', '$ARCHMON_TEST_HOME')
        for path in ('/usr/local/lib/archmon', '/etc/systemd/system/archmon-fans.service',
                     '/etc/polkit-1/rules.d/50-archmon-fans.rules', '/run/archmon-fans', '/etc/archmon'):
            header = header.replace(path, str(self.fake_root) + path)
        header = header.replace('/usr/bin/python3', str(self.bin / 'recover'))
        self.installer = self.root / 'install.sh'
        self.installer.write_text(header + '\n#__PAYLOAD__\n' + payload)

    def run_installer(self, *args):
        return subprocess.run(['bash', str(self.installer), *args], env=self.env, cwd=self.root,
                              capture_output=True, text=True, timeout=15)

    def install_service_files(self):
        self.service_files = []
        for relative in ('etc/systemd/system/archmon-fans.service', 'usr/local/lib/archmon/fand.py',
                         'usr/local/lib/archmon/fanctl', 'usr/local/lib/archmon/installed.stamp',
                         'etc/polkit-1/rules.d/50-archmon-fans.rules', 'etc/archmon/fans.json',
                         'run/archmon-fans/original.json'):
            path = self.fake_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('test fixture')
            self.service_files.append(path)

    def test_install_and_update_unpack_fixed_code(self):
        for _ in range(2):
            result = self.run_installer()
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.app / 'archmon/gpu_poll.py').exists())
        self.assertIn('self.selected_started', (self.app / 'archmon/window.py').read_text())
        self.assertTrue((self.home / '.local/bin/archmon').exists())

    def test_remove_without_service_and_repeat(self):
        for _ in range(2):
            result = self.run_installer('--remove')
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.app.exists())
        self.assertNotIn('sudo', self.log.read_text())

    def test_remove_service_restores_before_deleting_files(self):
        self.install_service_files()
        result = self.run_installer('--remove')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.app.exists())
        self.assertTrue(all(not p.exists() for p in self.service_files))
        log = self.log.read_text()
        self.assertLess(log.index('systemctl disable'), log.index('systemctl stop'))
        self.assertLess(log.index('systemctl stop'), log.index('recover -I'))
        self.assertLess(log.index('recover -I'), log.index('systemctl daemon-reload'))

    def test_failed_restore_preserves_files_and_allows_retry(self):
        self.install_service_files()
        self.env['ARCHMON_TEST_RECOVERY_FAIL'] = '1'
        result = self.run_installer('--remove')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Removal stopped', result.stderr)
        self.assertTrue((self.app / 'old-marker').exists())
        self.assertTrue(all(p.exists() for p in self.service_files))
        self.assertNotIn('daemon-reload', self.log.read_text())
        self.env['ARCHMON_TEST_RECOVERY_FAIL'] = '0'
        self.assertEqual(self.run_installer('--remove').returncode, 0)

    def test_missing_unit_still_recovers_leftover_state(self):
        self.install_service_files()
        self.env['ARCHMON_TEST_UNIT_STATE'] = 'not-found'
        result = self.run_installer('--remove')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('systemctl disable', self.log.read_text())
        self.assertIn('recover -I', self.log.read_text())

    def test_failed_service_exit_can_be_recovered_after_stop(self):
        self.install_service_files()
        self.env['ARCHMON_TEST_STOP_FAIL'] = '1'
        self.env['ARCHMON_TEST_ACTIVE'] = 'failed'
        result = self.run_installer('--remove')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('recover -I', self.log.read_text())

    def test_service_still_running_blocks_recovery_and_deletion(self):
        self.install_service_files()
        self.env['ARCHMON_TEST_STOP_FAIL'] = '1'
        self.env['ARCHMON_TEST_ACTIVE'] = 'active'
        result = self.run_installer('--remove')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('recover -I', self.log.read_text())
        self.assertTrue(all(p.exists() for p in self.service_files))

    def test_corrupt_archive_keeps_previous_installation(self):
        text = self.installer.read_text()
        header, payload = text.split('\n#__PAYLOAD__\n', 1)
        corrupted = ('A' if payload[0] != 'A' else 'B') + payload[1:]
        self.installer.write_text(header + '\n#__PAYLOAD__\n' + corrupted)
        result = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.app / 'old-marker').exists())
        self.assertFalse(self.log.exists())


if __name__ == '__main__':
    unittest.main()
