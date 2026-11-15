import os
from pathlib import Path
import signal
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
_config = tempfile.TemporaryDirectory(prefix='archmon-test-settings-')
os.environ['XDG_CONFIG_HOME'] = _config.name

from PyQt6.QtCore import QEvent, QTimer
from PyQt6.QtWidgets import QApplication
from archmon import fan_service, fans, gpu_poll, mangohud, mangohud_dialog, reflector, system, window
from archmon.gpu import Gpu


APP = QApplication.instance() or QApplication([])
APP.setQuitOnLastWindowClosed(False)
GPU = Gpu('nv0', 'NVIDIA GeForce RTX 5070', 2, '2%', vram_used=1.2e9, vram_total=12e9,
          temp=34, pci='0000:01:00.0')


def pump_until(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        APP.processEvents()
        time.sleep(0.005)
    if not predicate():
        raise AssertionError('Timed out waiting for Qt callback')


class WindowTests(unittest.TestCase):
    def setUp(self):
        with patch.object(window.QTimer, 'singleShot'), \
             patch.object(gpu_poll.GpuPoller, 'request'), \
             patch.object(fans, 'read_fans', return_value=[]), \
             patch.object(window, 'read_fans', return_value=[]), \
             patch.object(fan_service, 'load_config', return_value=None), \
             patch.object(reflector, '_run', return_value=None), \
             patch.object(system, 'prime_counters'), \
             patch.object(mangohud, 'load_config', return_value=mangohud.HudConfig()), \
             patch.object(gpu_poll, 'read_gpus', side_effect=AssertionError('Synchronous GPU query')):
            self.w = window.MainWindow()
        self.w.timer.stop()
        self.w.freeze_timer.stop()
        self.w.apps_first = False
        self.w.tree_mode = False
        self.a = system.Proc(111, 'me', 20, 1, 1024, 'app-A', started=1)
        self.b = system.Proc(222, 'me', 10, 1, 1024, 'app-B', started=2)

    def tearDown(self):
        self.w.gpu_poller.shutdown()
        self.w.table.viewport().removeEventFilter(self.w)
        self.w.hide()
        self.w.deleteLater()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def rows(self, procs):
        with patch.object(system, 'list_processes', return_value=system.ProcessList(procs, 2, 2)):
            self.w.refresh_table()

    def test_filter_clears_target_and_new_selection_works(self):
        self.rows([self.a, self.b])
        self.w.table.selectRow(0)
        with patch.object(system, 'list_processes', return_value=system.ProcessList([self.b], 2, 2)):
            self.w.filter_box.setText('app-B')
        self.assertIsNone(self.w.selected_pid)
        self.assertFalse(self.w.table.selectionModel().selectedRows())
        with patch.object(system, 'send_signal', return_value='sent') as send:
            self.w.end_process(signal.SIGTERM)
            send.assert_not_called()
            self.w.table.selectRow(0)
            self.w.end_process(signal.SIGTERM)
            send.assert_called_once_with(222, signal.SIGTERM, 2)

    def test_sorting_preserves_identity(self):
        self.rows([self.a, self.b])
        self.w.table.selectRow(0)
        self.b.cpu = 30
        self.rows([self.a, self.b])
        self.assertEqual(self.w.table.selectionModel().selectedRows()[0].row(), 1)
        self.assertEqual(self.w.selected_pid, 111)

    def test_reused_pid_clears_selection(self):
        self.rows([self.a])
        self.w.table.selectRow(0)
        replacement = system.Proc(111, 'me', 20, 1, 1024, 'replacement', started=3)
        self.rows([replacement])
        self.assertIsNone(self.w.selected_pid)
        with patch.object(system, 'send_signal') as send:
            self.w.end_process(signal.SIGKILL)
        send.assert_not_called()

    def test_explicit_deselection_clears_target(self):
        self.rows([self.a])
        self.w.table.selectRow(0)
        self.w.table.clearSelection()
        self.assertIsNone(self.w.selected_pid)

    def test_gpu_appears_after_empty_start_and_recovers_again(self):
        self.w._receive_gpus([])
        self.assertFalse(self.w.gpu_cards)
        self.assertTrue(self.w.gpu_ring.isHidden())
        self.w._receive_gpus([GPU])
        self.assertIn('nv0', self.w.gpu_cards)
        self.assertFalse(self.w.gpu_ring.isHidden())
        gpu_button = dict(self.w.nav_buttons)[window.NAV_INDEX['GPU']]
        self.assertFalse(gpu_button.isHidden())
        card = self.w.gpu_cards['nv0']
        self.w._receive_gpus([])
        self.assertIn('Retrying', card.toolTip())
        self.w._receive_gpus([GPU])
        self.assertIs(card, self.w.gpu_cards['nv0'])
        self.assertEqual(card.toolTip(), '')
        self.assertEqual(self.w.gpu_name.text(), GPU.name)

    def test_missing_vram_value_does_not_crash(self):
        missing = Gpu('nv0', GPU.name, 2, '2%', vram_total=12e9, vram_used=None)
        self.w._receive_gpus([missing])
        self.assertIn('nv0', self.w.gpu_cards)
        self.assertFalse(self.w.vram_ring.isHidden())

    def test_freeze_defers_render_until_unfrozen(self):
        self.w._frozen = True
        self.w._receive_gpus([GPU])
        self.assertFalse(self.w.gpu_cards)
        self.w._frozen = False
        with patch.object(self.w.gpu_poller, 'request'):
            self.w.update_gpus()
        self.assertIn('nv0', self.w.gpu_cards)

    def test_bad_mangohud_values_do_not_crash_window(self):
        self.w.mango.cfg.values.update(font_size='bad', alpha='nan', background_alpha='inf', log_interval='-10')
        with patch.object(mangohud, 'save_config') as save:
            self.w.mango._config_to_widgets()
        save.assert_not_called()
        self.assertEqual(self.w.mango.font_size.value(), 24)
        self.assertEqual(self.w.mango.log_interval.value(), 0)
        self.assertIn('font_size', self.w.mango.status.text())

    def test_gpu_choices_preserve_custom_and_existing_pci(self):
        self.w.mango.cfg.values['pci_dev'] = '0000:02:00.0'
        self.w.mango._config_to_widgets()
        self.w._receive_gpus([GPU])
        self.assertEqual(self.w.mango.gpu_choice.currentData(), '0000:02:00.0')
        self.w.mango.gpu_choice.setCurrentIndex(self.w.mango.gpu_choice.findData(GPU.pci))
        self.w.mango.set_gpus([GPU])
        self.assertEqual(self.w.mango.gpu_choice.currentData(), GPU.pci)

    def test_log_display_calls_rows_samples(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'sample.csv'
            log.write_text('fps,frametime,elapsed\n100,10,0\n100,10,10000000000\n')
            self.w.mango._log_files = [str(log)]
            self.w.mango._show_log(0)
        self.assertIn('Samples', self.w.mango.summary.text())
        self.assertIn('10.00 s', self.w.mango.summary.text())


class PollerTests(unittest.TestCase):
    def test_gui_remains_responsive_and_requests_do_not_overlap(self):
        release = threading.Event()
        entered = threading.Event()
        worker = gpu_poll.GpuPoller()
        received, fired, threads = [], [], []
        def query():
            threads.append(threading.get_ident())
            entered.set()
            release.wait(2)
            return [GPU]
        worker.ready.connect(received.append)
        try:
            with patch.object(gpu_poll, 'read_gpus', side_effect=query) as read:
                worker.request()
                self.assertTrue(entered.wait(1))
                for _ in range(30):
                    worker.request()
                QTimer.singleShot(10, lambda: fired.append(True))
                pump_until(lambda: fired)
                self.assertFalse(received)
                read.assert_called_once()
                self.assertNotEqual(threads[0], threading.get_ident())
                release.set()
                pump_until(lambda: received)
                self.assertEqual(received, [[GPU]])
        finally:
            release.set()
            worker.shutdown()
        worker.request()
        self.assertFalse(worker.isRunning())

    def test_query_exception_allows_next_poll(self):
        worker = gpu_poll.GpuPoller()
        received = []
        worker.ready.connect(received.append)
        try:
            with patch.object(gpu_poll, 'read_gpus', side_effect=[RuntimeError('test fault'), [GPU]]):
                with self.assertLogs(level='ERROR'):
                    worker.request()
                    pump_until(lambda: len(received) == 1)
                worker.request()
                pump_until(lambda: len(received) == 2)
            self.assertEqual(received, [[], [GPU]])
        finally:
            worker.shutdown()


if __name__ == '__main__':
    unittest.main()
