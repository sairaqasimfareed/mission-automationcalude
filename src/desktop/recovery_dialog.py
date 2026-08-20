from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QMessageBox, QWidget


def show_recoverable_error(
    parent: QWidget,
    title: str,
    message: str,
    *,
    on_retry: Callable[[], None] | None = None,
) -> None:
    """
    Show a step-failure dialog, offering a real Retry action instead of
    dismiss-only when the failed step is safe to simply run again.

    Every call site wiring on_retry re-reads current job state fresh
    from the job store on each run, so retrying just re-attempts the
    same operation with nothing stale carried over - no new recovery
    classification is invented here beyond what that already makes
    true (unlike AssetModuleFailure's per-reason recovery_options,
    which reflects real classified failure causes from the asset
    acquisition backend; these callers only ever have a raw exception
    message, so "try again" is the one honest recovery action to
    offer).
    """

    if on_retry is None:
        QMessageBox.warning(parent, title, message)

        return

    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(title)
    box.setText(message)
    retry_button = box.addButton("Retry", QMessageBox.ButtonRole.ActionRole)
    box.addButton(QMessageBox.StandardButton.Ok)
    box.exec()

    if box.clickedButton() is retry_button:
        on_retry()
