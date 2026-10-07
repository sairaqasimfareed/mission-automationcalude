"""The "choose another frame" picker: a few frames of a character's or place's own
generated clips, each with a button that makes it the reference picture."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.services.recurring_identity_service import ReferenceCandidate

_THUMBNAIL_WIDTH = 220
_COLUMNS = 3


class ReferenceCandidatesDialog(QDialog):
    """Emits `chosen(index)` with the position of the frame the operator picked."""

    chosen = Signal(int)

    def __init__(
        self,
        parent: QWidget | None,
        *,
        identity_name: str,
        candidates: list[ReferenceCandidate],
    ) -> None:
        super().__init__(parent)

        self.setWindowTitle(f"Choose a reference frame - {identity_name}")
        self.setModal(True)
        self.resize(780, 560)

        self._candidates = list(candidates)
        outer = QVBoxLayout(self)
        outer.addWidget(
            QLabel(
                f"Frames from {identity_name}'s generated clips, clearest first. "
                "The one you pick becomes the picture used for every later clip."
            )
        )

        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        self.use_buttons: list[QPushButton] = []

        for index, candidate in enumerate(self._candidates):
            cell = QVBoxLayout()
            picture = QLabel()
            pixmap = QPixmap(candidate.image_path)

            if not pixmap.isNull():
                picture.setPixmap(
                    pixmap.scaledToWidth(
                        _THUMBNAIL_WIDTH, Qt.TransformationMode.SmoothTransformation
                    )
                )
            else:
                picture.setText("(picture not available)")

            caption = QLabel(
                f"Scene {candidate.scene_number}  ·  {candidate.time_seconds:.1f}s"
            )
            use_button = QPushButton("Use this frame")
            use_button.clicked.connect(lambda _checked=False, i=index: self._choose(i))
            self.use_buttons.append(use_button)
            cell.addWidget(picture)
            cell.addWidget(caption)
            cell.addWidget(use_button)
            holder = QWidget()
            holder.setLayout(cell)
            grid.addWidget(holder, index // _COLUMNS, index % _COLUMNS)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(grid_host)
        outer.addWidget(scroll)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        outer.addLayout(buttons)

    def _choose(self, index: int) -> None:
        self.chosen.emit(index)
        self.accept()
