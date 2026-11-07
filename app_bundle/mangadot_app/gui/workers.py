"""Shared QThread worker helpers used across screens.

Every screen that needs to run a backend call off the GUI thread was
independently re-implementing the same ~9-line "create a QThread, move a
QObject worker onto it, wire up the started/finished/quit/deleteLater
signal chain, start it" pattern - group_config_dialog.py had a module-
level version, picker_screen.py's _CreateFromMangaBakaDialog had its own
bound-method version (plus separately duplicated pruning logic), and
upload_progress_screen.py / optimizer_progress_screen.py / login_screen.py
/ main.py all inlined it again with no shared helper at all.

This module is the single place that pattern lives now:

- CallableWorker: a generic QObject worker for the common case of "call
  one backend function, emit its return value as a signal" - replaces
  the ~7 near-identical one-line worker classes that used to live in
  picker_screen.py alone (_SearchWorker, _DetailsWorker, etc).
- run_worker(): creates the QThread, wires the standard lifecycle chain,
  starts it, and returns (thread, worker) so the caller can track it.
- prune_finished(): drops dead (finished + deleted) entries from a
  screen's tracked thread/worker lists, using gui.thread_is_running so a
  QThread whose C++ object has already been deferred-deleted is treated
  as not-running instead of raising.
- AbortableWorker: a QObject worker base for long-running batch jobs
  (uploads, optimization passes) that need to be interruptible from the
  GUI thread, not just "fire and forget". Owns a threading.Event that
  stop_background_work() can set before calling QThread.quit()/wait() -
  without this, quit() only stops a worker's *event loop*, which does
  nothing to a worker stuck inside one long blocking call.
"""
import threading

from PySide6.QtCore import QObject, QThread, Signal

from . import thread_is_running


class CallableWorker(QObject):
    """Generic one-shot worker: calls fn(*args, **kwargs) on a background
    thread and emits its return value.

    Replaces single-purpose worker classes that only ever did
    `self.finished.emit(some_backend_call(...))`. For workers that need
    to emit more than one value, or emit *during* the call (progress
    signals), keep or write a dedicated QObject subclass instead - this
    is only for the "one call in, one result out" shape.
    """
    finished = Signal(object)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self):
        result = self._fn(*self._args, **self._kwargs)
        self.finished.emit(result)


class _MainThreadRelay(QObject):
    """Forwards a signal to an arbitrary callable, guaranteed to run on
    whatever thread this relay object itself lives on.

    run_worker() creates this on the calling thread (which is always the
    GUI/main thread for every call site in this app) and never moves it,
    so it keeps that thread's affinity. Qt's signal/slot AutoConnection
    then correctly recognizes "the emitting worker thread differs from
    this receiver's thread" and queues the delivery - which only works
    because the receiver is a genuine QObject Qt can inspect. Connecting
    a signal directly to a plain function or lambda does NOT get this
    protection: a bare callable has no thread affinity of its own, so
    Qt's AutoConnection can't tell it needs queuing, and testing showed
    it firing on the wrong (worker) thread - or, with QueuedConnection
    forced, inconsistently not firing at all. Routing every on_finished
    callback through this relay avoids both failure modes regardless of
    whether the caller passed a bound QObject method, a lambda, or a
    plain function.
    """

    def __init__(self, callback):
        super().__init__()
        self._callback = callback

    def _relay(self, *args):
        self._callback(*args)


def run_worker(worker, on_finished=None):
    """Starts `worker` (any QObject with a no-arg .run() and a .finished
    signal) on a new QThread, wiring the standard lifecycle chain:
    started -> run, finished -> thread.quit, finished -> worker.deleteLater,
    thread.finished -> thread.deleteLater.

    If on_finished is given, it's connected to worker.finished (via an
    internal relay - see _MainThreadRelay) before the thread starts, so
    it fires on this call's thread (the GUI thread) whether
    worker.finished carries zero, one, or several arguments - the
    caller's callback signature decides that, this helper doesn't care.

    Returns (thread, worker) so the caller can append both to its own
    tracked lists (see prune_finished) if it needs to keep more than one
    of these alive/cancellable at once. If on_finished was given, the
    relay is kept alive as worker._on_finished_relay for the worker's
    lifetime - callers don't need to hold a separate reference to it.
    """
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    if on_finished is not None:
        relay = _MainThreadRelay(on_finished)
        worker._on_finished_relay = relay  # keep it alive alongside the worker
        worker.finished.connect(relay._relay)
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.start()
    return thread, worker


def run_callable(fn, *args, on_finished=None, **kwargs):
    """Convenience wrapper: run_worker() around a fresh CallableWorker(fn,
    *args, **kwargs). Covers the common "just call this backend function
    off-thread and hand me the result" case without a dedicated worker
    class. Returns (thread, worker) exactly like run_worker()."""
    worker = CallableWorker(fn, *args, **kwargs)
    return run_worker(worker, on_finished=on_finished)


def prune_finished(threads, workers):
    """Drops entries from `threads`/`workers` (parallel lists, same
    order) whose QThread is no longer running - either it finished
    normally, or its underlying C++ object has already been deferred-
    deleted by Qt. Mutates both lists in place (same convention as the
    call sites that used this before centralizing it), so callers keep
    using the same list objects they already track on self.

    Call this before appending a newly-started (thread, worker) pair,
    not after - pruning after adding the new one would immediately
    re-check the thread you just started for no reason.
    """
    alive = [(t, w) for t, w in zip(threads, workers) if thread_is_running(t)]
    threads[:] = [t for t, _ in alive]
    workers[:] = [w for _, w in alive]


class AbortableWorker(QObject):
    """Base class for a worker that runs one long blocking call which
    itself accepts an `abort_event` (a threading.Event) it checks
    periodically - e.g. uploader.process_uploads() or a batch of
    optimizer.optimize_cbz() calls guarded between iterations.

    QThread.quit() only stops a worker's event loop; it does nothing to
    interrupt a worker that's inside a single long Python call, which is
    exactly the shape every batch job in this app has. Subclasses (or
    the QThread owner) should pass self.abort_event into whatever
    backend call is being made, and the owning screen's
    stop_background_work() should call self.abort_event.set() *before*
    thread.quit()/thread.wait() - quit()/wait() alone is not enough to
    actually stop the work, only to stop waiting for it.

    Usage:
        class _UploadWorker(AbortableWorker):
            def __init__(self, files, ...):
                super().__init__()
                self.files = files
                ...

            def run(self):
                failed, session_expired, reasons = uploader.process_uploads(
                    ..., abort_event=self.abort_event,
                )
                self.finished.emit(failed, session_expired, reasons)
    """

    def __init__(self):
        super().__init__()
        self.abort_event = threading.Event()

    def abort(self):
        """Signal this worker's blocking call to stop at its next
        interruption checkpoint. Safe to call from any thread."""
        self.abort_event.set()