import io
import json
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from archmon import fand, mangohud as mh, system


class ProcessTests(unittest.TestCase):
    def test_pid_reuse_is_rejected(self):
        process = Mock()
        process.create_time.return_value = 20
        with patch.object(system.psutil, 'Process', return_value=process):
            self.assertIn('changed', system.send_signal(111, signal.SIGTERM, 10))
        process.send_signal.assert_not_called()

    def test_matching_identity_receives_signal(self):
        process = Mock()
        process.create_time.return_value = 10
        with patch.object(system.psutil, 'Process', return_value=process):
            self.assertIn('Sent', system.send_signal(111, signal.SIGTERM, 10))
        process.send_signal.assert_called_once_with(signal.SIGTERM)

    def test_unknown_identity_does_not_receive_signal(self):
        with patch.object(system.psutil, 'Process') as process:
            system.send_signal(111, signal.SIGTERM, 0)
        process.return_value.send_signal.assert_not_called()


class FanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.hw = self.root / 'hwmon' / 'hwmon0'
        self.hw.mkdir(parents=True)
        (self.hw / 'name').write_text('it8689')
        for n in (1, 2):
            (self.hw / f'pwm{n}_enable').write_text('2')
            (self.hw / f'pwm{n}').write_text('100')
        self.state = self.root / 'state'
        self.state_file = self.state / 'original.json'
        for name, value in [('HWMON', str(self.hw.parent)), ('STATE_DIR', str(self.state)),
                            ('CONFIG', str(self.root / 'config.json'))]:
            p = patch.object(fand, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.cfg = {'chip': 'it8689', 'fans': [{'index': 1, 'mode': 'fixed', 'fixed': 30}],
                    'curves': dict(fand.PRESETS)}
        self.ctl = fand.Controller(self.cfg, log=Mock())
        self.ctl.attach(wait=0)
        p = patch.object(fand, 'read_temps', return_value={'cpu': 40, 'gpu': 40, 'hottest': 40})
        self.temps = p.start()
        self.addCleanup(p.stop)

    def test_fixed_control_and_clean_stop(self):
        self.ctl.step()
        self.assertEqual((self.hw / 'pwm1').read_text(), '76')
        self.assertEqual((self.hw / 'pwm1_enable').read_text(), '1')
        self.assertEqual(json.loads(self.state_file.read_text())['pending'], [1])
        self.assertTrue(self.ctl.restore_all())
        self.assertEqual((self.hw / 'pwm1_enable').read_text(), '2')
        self.assertFalse(self.state_file.exists())

    def test_write_and_restore_failure_is_retried(self):
        write = fand._write
        def failing(path, value):
            if Path(path).name == 'pwm1' or str(value) == '2':
                raise OSError('temporary fault')
            write(path, value)
        with patch.object(fand, '_write', side_effect=failing):
            self.ctl.step()
        self.assertEqual(self.ctl.pending, {1})
        self.assertEqual((self.hw / 'pwm1_enable').read_text(), '1')
        self.temps.return_value = {'cpu': 95, 'gpu': 40, 'hottest': 95}
        self.ctl.step()
        self.assertEqual((self.hw / 'pwm1_enable').read_text(), '2')
        self.assertEqual(self.ctl.pending, set())

    def test_persistent_fault_retains_state_for_separate_recovery(self):
        self.ctl.step()
        with patch.object(fand, '_write', side_effect=OSError('fault')), patch.object(fand.time, 'sleep'):
            self.assertFalse(self.ctl.restore_all())
        self.assertTrue(self.state_file.exists())
        self.assertEqual(self.ctl.pending, {1})
        self.assertTrue(fand.restore_saved())
        self.assertEqual((self.hw / 'pwm1_enable').read_text(), '2')
        self.assertFalse(self.state_file.exists())

    def test_other_channels_restore_when_one_fails(self):
        self.cfg['fans'].append({'index': 2, 'mode': 'fixed', 'fixed': 50})
        self.ctl.step()
        write = fand._write
        def failing(path, value):
            if Path(path).name == 'pwm1_enable':
                raise OSError('fault')
            write(path, value)
        with patch.object(fand, '_write', side_effect=failing):
            self.assertFalse(self.ctl.restore_all(attempts=1))
        self.assertEqual(self.ctl.pending, {1})
        self.assertEqual((self.hw / 'pwm2_enable').read_text(), '2')

    def test_emergency_speed_when_mode_restore_still_fails(self):
        self.ctl.step()
        self.ctl.broken.add(1)
        self.temps.return_value = {'cpu': 95, 'gpu': 40, 'hottest': 95}
        write = fand._write
        def failing(path, value):
            if Path(path).name == 'pwm1_enable':
                raise OSError('mode switch failed')
            write(path, value)
        with patch.object(fand, '_write', side_effect=failing):
            self.ctl.step()
        self.assertEqual((self.hw / 'pwm1').read_text(), '255')
        self.assertEqual(self.ctl.pending, {1})

    def test_unknown_original_mode_never_enters_manual_control(self):
        self.ctl.original[1] = None
        with patch.object(fand, '_write') as write:
            self.ctl.step()
        write.assert_not_called()

    def test_mode_readback_failure_is_not_success(self):
        self.ctl.step()
        with patch.object(fand, '_write'):
            self.assertFalse(self.ctl.restore_all(attempts=1))
        self.assertEqual(self.ctl.pending, {1})

    def test_thermal_emergency_and_gradual_slowdown(self):
        self.temps.return_value = {'cpu': 95, 'gpu': 40, 'hottest': 95}
        self.ctl.step()
        self.assertEqual((self.hw / 'pwm1').read_text(), '255')
        self.temps.return_value = {'cpu': 40, 'gpu': 40, 'hottest': 40}
        self.ctl.step()
        self.assertEqual(self.ctl.last[1], 92)

    def test_missing_curve_temperature_uses_full_speed(self):
        self.cfg['fans'][0].update(mode='curve', source='cpu')
        self.temps.return_value = {'cpu': None, 'gpu': 40, 'hottest': 40}
        self.ctl.step()
        self.assertEqual((self.hw / 'pwm1').read_text(), '255')

    def test_bios_mode_releases_channel(self):
        self.ctl.step()
        self.cfg['fans'][0]['mode'] = 'bios'
        self.ctl.step()
        self.assertEqual((self.hw / 'pwm1_enable').read_text(), '2')

    def test_legacy_service_state_is_recovered(self):
        self.state.mkdir()
        self.state_file.write_text(json.dumps({'hw': str(self.hw), 'enable': {'1': '2'}}))
        Path(fand.CONFIG).write_text(json.dumps(self.cfg))
        (self.hw / 'pwm1_enable').write_text('1')
        self.assertTrue(fand.restore_saved())
        self.assertEqual((self.hw / 'pwm1_enable').read_text(), '2')

    def test_changed_device_does_not_receive_writes(self):
        self.ctl.step()
        (self.hw / 'name').write_text('different-chip')
        with patch.object(fand, '_write') as write:
            self.assertFalse(fand.restore_saved())
        write.assert_not_called()
        self.assertTrue(self.state_file.exists())

    def test_absent_or_invalid_state(self):
        self.assertTrue(fand.restore_saved())
        self.state.mkdir()
        self.state_file.write_text('{invalid')
        self.assertFalse(fand.restore_saved())
        self.assertTrue(self.state_file.exists())


class FanHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        previous = list(sys.path)
        with patch.dict(sys.modules, {'fand': fand}):
            from archmon import fanctl
        sys.path[:] = previous
        cls.helper = fanctl

    def test_failed_recovery_blocks_apply(self):
        raw = {'chip': 'it8689', 'fans': [{'index': 1, 'mode': 'fixed'}]}
        with patch.object(self.helper.os, 'geteuid', return_value=0), \
             patch.object(self.helper, 'systemctl') as ctl, \
             patch.object(fand, 'restore_saved', return_value=False), \
             patch.object(self.helper, 'write_config') as write:
            self.assertEqual(self.helper.main(['apply'], io.StringIO(json.dumps(raw))), 1)
        ctl.assert_called_once_with('stop', self.helper.SERVICE)
        write.assert_not_called()

    def test_stop_reports_failure_when_modes_not_restored(self):
        with patch.object(self.helper.os, 'geteuid', return_value=0), \
             patch.object(self.helper, 'systemctl') as ctl, \
             patch.object(fand, 'restore_saved', return_value=False):
            self.assertEqual(self.helper.main(['stop']), 1)
        self.assertEqual([c.args[0] for c in ctl.call_args_list], ['disable', 'stop'])

    def test_failed_service_exit_still_allows_recovery(self):
        with patch.object(self.helper, 'systemctl', side_effect=subprocess.CalledProcessError(1, 'systemctl')), \
             patch.object(self.helper.subprocess, 'run', return_value=Mock(stdout='failed\n')):
            self.helper.stop_service()

    def test_running_service_blocks_recovery(self):
        with patch.object(self.helper, 'systemctl', side_effect=subprocess.CalledProcessError(1, 'systemctl')), \
             patch.object(self.helper.subprocess, 'run', return_value=Mock(stdout='active\n')):
            with self.assertRaises(subprocess.CalledProcessError):
                self.helper.stop_service()

    def test_invalid_input_cannot_stop_or_write(self):
        with patch.object(self.helper.os, 'geteuid', return_value=0), \
             patch.object(self.helper, 'systemctl') as ctl, \
             patch.object(self.helper, 'write_config') as write:
            self.assertEqual(self.helper.main(['apply'], io.StringIO('{}')), 1)
        ctl.assert_not_called()
        write.assert_not_called()


class MangoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'MangoHud.conf'

    def test_disabled_flags_survive_round_trip(self):
        text = '# custom\nfps\ncpu_stats=0\ngpu_stats=0\nframe_timing=0\ncustom_text=test\n'
        self.path.write_text(text)
        cfg = mh.load_config(str(self.path))
        mh.save_config(cfg, str(self.path))
        self.assertEqual(mh.load_config(str(self.path)).flags, {'fps'})
        self.assertIn('cpu_stats=0', self.path.read_text())
        self.assertIn('custom_text=test', self.path.read_text())
        self.assertEqual(Path(str(self.path) + '.bak').read_text(), text)

    def test_defaults_and_last_flag_assignment(self):
        self.assertEqual(mh.load_config(str(self.path)).flags, mh.DEFAULT_FLAGS)
        self.path.write_text('fps=0\nfps\ngpu_stats=0\n')
        flags = mh.load_config(str(self.path)).flags
        self.assertIn('fps', flags)
        self.assertNotIn('gpu_stats', flags)

    def test_all_flags_can_be_disabled(self):
        mh.save_config(mh.HudConfig(flags=set()), str(self.path))
        self.assertEqual(mh.load_config(str(self.path)).flags, set())

    def test_periodic_log_has_ten_second_span_and_samples(self):
        self.path.write_text('fps,frametime,elapsed\n' +
                            ''.join(f'100,10,{i * 100000000}\n' for i in range(101)))
        summary = mh.summarize_log(str(self.path))
        self.assertEqual(summary.samples, 101)
        self.assertEqual(summary.seconds, 10)
        self.assertEqual(summary.avg_fps, 100)
        self.assertFalse(hasattr(summary, 'frames'))

    def test_missing_or_invalid_timestamps_do_not_invent_duration(self):
        for text in ('fps,frametime\n60,16.7\n60,16.7\n',
                     'fps,elapsed\n60,10\n60,5\n', 'fps,elapsed\n60,nan\n60,5\n',
                     'fps,elapsed\n60,10\n'):
            with self.subTest(text=text):
                self.path.write_text(text)
                self.assertIsNone(mh.summarize_log(str(self.path)).seconds)

    def test_sample_fps_mean_and_nonfinite_filtering(self):
        self.path.write_text('fps,frametime\n30,33.3\n90,11.1\nnan,10\n60,inf\n0,0\n')
        summary = mh.summarize_log(str(self.path))
        self.assertEqual(summary.samples, 2)
        self.assertEqual(summary.avg_fps, 60)
        self.assertEqual(summary.min_fps, 30)
        self.assertEqual(summary.max_fps, 90)


if __name__ == '__main__':
    unittest.main()
