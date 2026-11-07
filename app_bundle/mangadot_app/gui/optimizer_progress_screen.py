"""Optimizer progress and summary screen."""
import time

import shiboken6
from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QProgressBar, QAbstractItemView, QMessageBox, QHeaderView,
    QSizePolicy
)

from .. import optimizer
from .. import parser as parser_mod
from .. import config as config_mod
from ..util import fmt_size, fmt_duration
from . import thread_is_running, workers
from .widgets import heading, StatCard, StatusPill, make_flat_link, GlassBox
from .theme import Color

COL_FILENAME = 0
COL_ORIGINAL = 1
COL_OPTIMIZED = 2
COL_SAVED = 3
COL_STATUS = 4

class _OptimizationWorker(workers.AbortableWorker):
    progress = Signal(int, int)  # done, total
    file_done = Signal(dict)
    finished = Signal(str, list, float)  # output_dir, results, elapsed_time

    def __init__(self, directory, mode, pingo, replace, lossy, jpeg_q, webp_q, threads):
        super().__init__()
        self.directory = directory
        self.mode = mode
        self.pingo = pingo
        self.replace = replace
        self.lossy = lossy
        self.jpeg_q = jpeg_q
        self.webp_q = webp_q
        self.threads = threads

    def run(self):
        import concurrent.futures
        start_time = time.time()
        pingo_path = None
        if self.pingo:
            pingo_path, _ = optimizer.ensure_pingo_ready()

        if not pingo_path:
            try:
                optimizer.ensure_optimizer_deps(require_mozjpeg=not self.lossy)
            except optimizer.OptimizerError as e:
                self.finished.emit("", [{"error": str(e), "filename": "Initialization Error"}], 0.0)
                return

        targets = parser_mod.list_archive_targets(self.directory)

        if not targets:
            self.finished.emit(self.directory, [], 0.0)
            return

        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.threads) as pool:
            if pingo_path:
                futures = {pool.submit(optimizer.optimize_cbz_pingo, path, pingo_path, self.replace, self.lossy, self.jpeg_q, self.webp_q): path for path in targets}
            else:
                futures = {pool.submit(optimizer.optimize_cbz, path, self.lossy, self.jpeg_q, 9, self.webp_q, self.replace): path for path in targets}

            done = 0
            for future in concurrent.futures.as_completed(futures):
                if self.abort_event.is_set():
                    # Stop waiting on/reporting further results. Futures
                    # already mid-optimize will still run to completion -
                    # optimizer.py has no interruption point of its own -
                    # but anything not yet started is cancelled instead of
                    # the batch grinding through the rest of the directory.
                    for f in futures:
                        f.cancel()
                    break
                res = future.result()
                results.append(res)
                done += 1
                self.file_done.emit(res)
                self.progress.emit(done, len(targets))

        output_dir = self.directory
        if self.mode == 'chained':
            output_dir = optimizer.handle_chained_unoptimized_files(self.directory, results, self.replace)

        elapsed = time.time() - start_time
        self.finished.emit(output_dir, results, elapsed)


class OptimizerProgressScreen(QWidget):
    optimization_finished = Signal(str)  
    cancelled = Signal()  

    def __init__(self, directory, settings, parent=None):
        super().__init__(parent)
        self.directory = directory
        self.settings = settings

        self._thread = None
        self._worker = None
        self._row_by_filename = {}

        self._build_ui()

        if self.settings.opt_replace and not self._confirm_destructive_replace():
            self._declined = True
            return
        self._declined = False
        self._start_optimization()

    def _confirm_destructive_replace(self):
        targets = parser_mod.list_archive_targets(self.directory)
        count = len(targets)

        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle("Confirm overwrite")
        if count == 0:
            msg.setText("No .cbz/.zip archives were found in this folder, so there is nothing to overwrite.")
            msg.addButton(QMessageBox.Ok)
            msg.exec()
            return False

        msg.setText(
            f"This will permanently overwrite {count} original archive"
            f"{'s' if count != 1 else ''} in-place with optimized versions.\n\n"
            f"This cannot be undone. Continue?"
        )
        yes_btn = msg.addButton("Overwrite originals", QMessageBox.YesRole)
        msg.addButton(QMessageBox.Cancel)
        msg.setDefaultButton(QMessageBox.Cancel)
        msg.exec()
        return msg.clickedButton() == yes_btn

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 20, 28, 24)
        outer.setSpacing(14)

        mode_desc = {
            "standalone": "Optimizing images in place \u2014 no upload will follow.",
            "chained": "Optimizing images before upload continues.",
        }.get(self.settings.opt_mode, "")
        outer.addWidget(heading("Optimizing archives", mode_desc))

        stats_row = QHBoxLayout()
        stats_row.setSpacing(10)
        self.stat_optimized = StatCard("0", "Optimized", kind="success")
        self.stat_skipped = StatCard("0", "Skipped")
        self.stat_errors = StatCard("0", "Errors", kind="danger")
        self.stat_saved = StatCard("0 B", "Saved", kind="accent")
        for card in (self.stat_optimized, self.stat_skipped, self.stat_errors, self.stat_saved):
            stats_row.addWidget(card)
        outer.addLayout(stats_row)

        self.status_label = QLabel("Initializing optimizer\u2026")
        self.status_label.setWordWrap(True)
        self.status_label.setProperty("role", "subheading")
        outer.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%v / %m files")
        self.progress_bar.setFixedHeight(22)
        outer.addWidget(self.progress_bar)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Filename", "Original", "Optimized", "Saved", "Status"])
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setShowGrid(False)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_FILENAME, QHeaderView.Stretch)
        header.setSectionResizeMode(COL_ORIGINAL, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_OPTIMIZED, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_SAVED, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_STATUS, QHeaderView.Fixed)
        header.setSectionsMovable(True)
        header.setHighlightSections(False)
        self.table.setColumnWidth(COL_STATUS, 170)

        self._restore_column_order()

        outer.addWidget(self.table, 1)

        bottom_row = QHBoxLayout()
        bottom_row.addStretch(1)

        btn_text = "Finish" if self.settings.opt_mode == "standalone" else "Continue to Title Review \u2192"
        continue_box = GlassBox(
            tint_rgba="rgba(74, 222, 128, 18)",
            border_color=Color.SUCCESS,
        )
        continue_box_layout = QHBoxLayout(continue_box)
        continue_box_layout.setContentsMargins(14, 6, 14, 6)

        self.done_button = make_flat_link(QPushButton(btn_text), bold=True)
        self.done_button.setEnabled(False)
        self.done_button.clicked.connect(self._on_done_clicked)

        continue_box_layout.addWidget(self.done_button)
        bottom_row.addWidget(continue_box)
        outer.addLayout(bottom_row)

    def _restore_column_order(self):
        cfg = config_mod.load_config()
        order = cfg.get("optimizer_table_column_order")
        if not order or len(order) != self.table.columnCount():
            return
        header = self.table.horizontalHeader()
        for target_visual_index, logical_index in enumerate(order):
            current_visual_index = header.visualIndex(logical_index)
            if current_visual_index != -1 and current_visual_index != target_visual_index:
                header.moveSection(current_visual_index, target_visual_index)

    def _start_optimization(self):
        self._thread = QThread()
        self._worker = _OptimizationWorker(
            self.directory, self.settings.opt_mode, self.settings.opt_pingo,
            self.settings.opt_replace, self.settings.opt_lossy,
            self.settings.opt_jpeg_q, self.settings.opt_webp_q,
            self.settings.opt_threads
        )
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.file_done.connect(self._on_file_done)
        self._worker.finished.connect(self._on_finished)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)

        self._thread.start()

    def _on_progress(self, done, total):
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(done)
        self.status_label.setText(f"Optimizing archives\u2026 ({done}/{total})")

    def _on_file_done(self, result):
        row = self.table.rowCount()
        self.table.insertRow(row)

        filename = result.get("filename", "Unknown")
        self.table.setItem(row, COL_FILENAME, QTableWidgetItem(filename))

        if result.get("error"):
            for col in (COL_ORIGINAL, COL_OPTIMIZED, COL_SAVED):
                self.table.setItem(row, col, QTableWidgetItem("\u2013"))
            self._set_status_pill(row, f"Error: {result['error']}", "danger")
        else:
            orig = result["original_size"]
            opt = result["optimized_size"]
            self.table.setItem(row, COL_ORIGINAL, QTableWidgetItem(fmt_size(orig)))
            self.table.setItem(row, COL_OPTIMIZED, QTableWidgetItem(fmt_size(opt)))

            if result.get("skipped"):
                self.table.setItem(row, COL_SAVED, QTableWidgetItem("\u2013"))
                self._set_status_pill(row, "Skipped (no gain)", "neutral")
            else:
                saved = orig - opt
                pct = (saved / orig * 100) if orig else 0
                self.table.setItem(row, COL_SAVED, QTableWidgetItem(f"-{fmt_size(saved)} ({pct:.1f}%)"))
                self._set_status_pill(row, "Optimized", "success")

        self._refresh_stat_cards()

    def _set_status_pill(self, row, text, kind):
        pill = StatusPill(text, kind)
        pill.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(wrap)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.addWidget(pill, 1, Qt.AlignVCenter)
        wrap._pill = pill
        self.table.setCellWidget(row, COL_STATUS, wrap)

    def _refresh_stat_cards(self):
        optimized = skipped = errors = 0
        for row in range(self.table.rowCount()):
            wrap = self.table.cellWidget(row, COL_STATUS)
            pill = getattr(wrap, "_pill", None) if wrap else None
            text = pill.text() if pill else ""
            if text.startswith("Error"):
                errors += 1
            elif text.startswith("Skipped"):
                skipped += 1
            elif text.startswith("Optimized"):
                optimized += 1

        self.stat_optimized.set_value(optimized)
        self.stat_skipped.set_value(skipped)
        self.stat_errors.set_value(errors)

    def _on_finished(self, output_dir, results, elapsed):
        self.output_dir = output_dir
        self.done_button.setEnabled(True)

        if not results:
            self.status_label.setText("No valid archives found to optimize.")
            return

        total_orig = sum(r.get("original_size", 0) for r in results if not r.get("error"))
        total_opt = sum(r.get("optimized_size", 0) for r in results if not r.get("error"))
        total_saved = total_orig - total_opt
        total_pct = (total_saved / total_orig * 100) if total_orig else 0

        errors = sum(1 for r in results if r.get("error"))
        skipped = sum(1 for r in results if r.get("skipped"))
        optimized = len(results) - errors - skipped

        self.stat_optimized.set_value(optimized)
        self.stat_skipped.set_value(skipped)
        self.stat_errors.set_value(errors)
        self.stat_saved.set_value(fmt_size(max(total_saved, 0)))

        summary = f"Done in {fmt_duration(elapsed)}."
        if total_saved > 0:
            summary += f" Saved {fmt_size(total_saved)} ({total_pct:.1f}% smaller) overall."
        self.status_label.setText(summary)

    def _on_done_clicked(self):
        header = self.table.horizontalHeader()
        order = [header.logicalIndex(visual) for visual in range(self.table.columnCount())]

        cfg = config_mod.load_config()
        cfg["optimizer_table_column_order"] = order
        config_mod.save_config(cfg)

        self.optimization_finished.emit(self.output_dir)

    def stop_background_work(self):
        # self._worker isn't reset to None after it finishes and is
        # deleteLater()'d, so guard with shiboken6.isValid() the same way
        # thread_is_running() does for QThread - stop_background_work()
        # can run well after an optimization already completed.
        if self._worker is not None and shiboken6.isValid(self._worker):
            # Tell the as_completed() loop to stop waiting on/reporting
            # further results and cancel any not-yet-started futures.
            # quit()/wait() below only stop the QThread's event loop -
            # they do nothing on their own to interrupt a worker that's
            # inside one long blocking call.
            self._worker.abort()
        if self._thread is not None and thread_is_running(self._thread):
            self._thread.quit()
            self._thread.wait(3000)