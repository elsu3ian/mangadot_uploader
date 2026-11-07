"""Shared GUI-layer helpers used by more than one screen."""
import shiboken6


def thread_is_running(thread):
    """True if `thread` (a QThread) still has a live C++ object AND is
    currently running. Every screen in this app tracks its background
    QThreads in a Python list and later calls .isRunning() on them - to
    decide whether to prune a finished thread from the list, or whether
    stop_background_work() needs to wait on one before the widget holding
    it is destroyed. But each thread also has
    `thread.finished.connect(thread.deleteLater)` wired up, and Qt can
    process that deferred deletion (destroying the underlying C++ object)
    at any point the event loop runs - including between one call site
    appending a thread to a list and a later call site checking it, or
    between a screen's constructor and the main window's closeEvent.
    Once that happens, `thread.isRunning()` doesn't return False - it
    raises `RuntimeError: Internal C++ object already deleted`, since
    there's no C++ object left to ask. That exception, uncaught, aborts
    whatever call was in progress (e.g. starting a new search) partway
    through, which is why "Searching..." can get stuck forever: the
    thread that would have emitted the finishing signal never actually
    starts.
    shiboken6.isValid() checks whether the C++ object is still alive
    without raising, so this can be used everywhere `thread.isRunning()`
    would otherwise be unsafe."""
    return shiboken6.isValid(thread) and thread.isRunning()
