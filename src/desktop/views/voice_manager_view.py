from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QHeaderView,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.desktop.widgets import badge, button, card, heading, muted, row, subheading
from src.models.elevenlabs_voice_search import ElevenLabsVoiceSearchResult
from src.models.voice_profile import VoiceProfile
from src.providers.elevenlabs_voice_search_client import ElevenLabsVoiceSearchClient
from src.services.genre_profile_registry_service import GenreProfileRegistryService
from src.services.http.http_provider_executor import HttpProviderExecutionError
from src.services.voice_profile_registry_service import VoiceProfileRegistryService
from src.services.voice_provider_mapping_service import VoiceProviderMappingService
from src.services.voice_search_query_builder import build_voice_search_terms

_LEFT = Qt.AlignmentFlag.AlignLeft

_GENRE_TABLE_COLUMNS = ["Genre", "Voice profile", "Delivery mode", "Real voice"]


class VoiceManagerView(QWidget):
    """
    Desktop Voice Manager: register real ElevenLabs voice ids for this
    app's built-in voice profiles, and see which genre resolves to
    which profile/delivery mode.

    Voice gap #2 (2026-09-09 audit) - the last of 11 voice gaps,
    deliberately built last since it needed the real data the other
    ten gaps produced (a persisted VoiceProviderMappingService, real
    per-genre voice_delivery_mode) to be worth managing. A real
    voice_id registered here becomes usable by real generation
    immediately, through the exact same VoiceProviderMappingService
    VoiceDirectiveResolutionService reads from - see
    src/desktop/services.py.

    Real voice_id values still cannot be entered by guessing:
    ElevenLabs' Free tier blocks API access to library (non-owned)
    voices, so only a voice already added to the target account's own
    "My Voices" will actually work. This screen registers whatever
    real id the account owner supplies; it does not fabricate one.
    """

    def __init__(
        self,
        *,
        voice_provider_mapping_service: VoiceProviderMappingService,
        voice_profile_registry: VoiceProfileRegistryService,
        genre_profile_registry: GenreProfileRegistryService,
        voice_search_client: ElevenLabsVoiceSearchClient | None = None,
        provider_name: str = "elevenlabs",
    ) -> None:
        super().__init__()

        self._mapping_service = voice_provider_mapping_service
        self._voice_profile_registry = voice_profile_registry
        self._genre_profile_registry = genre_profile_registry
        # 2026-09-10 follow-up to voice gap #2: real, auto-suggest-
        # then-confirm voice matching (the user's own explicitly
        # chosen automation level - not fully automatic, not fully
        # manual). None when no real, enabled ElevenLabs voice
        # provider is configured yet - the Suggest button disables
        # itself in that case.
        self._voice_search_client = voice_search_client
        self._provider_name = provider_name

        self._profiles: list[VoiceProfile] = []
        self._selected_profile_id: str | None = None
        self._suggestions: list[ElevenLabsVoiceSearchResult] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(16)

        outer.addWidget(heading("Voice Manager"))
        outer.addWidget(
            muted(
                "Register a real ElevenLabs voice for each built-in voice "
                "profile, and see which genre uses which profile and "
                "delivery mode."
            )
        )

        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter, stretch=1)

        splitter.addWidget(self._build_list_panel())
        splitter.addWidget(self._build_form_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 560])

        outer.addWidget(subheading("Genre overview"))
        outer.addWidget(
            muted(
                "Read-only - which profile and real ElevenLabs delivery "
                "mode each genre resolves to. Edit a genre's voice profile "
                "in source (GenreProfileRegistryService); edit its real "
                "voice id on the left."
            )
        )

        self._genre_table = QTableWidget(0, len(_GENRE_TABLE_COLUMNS))
        self._genre_table.setHorizontalHeaderLabels(_GENRE_TABLE_COLUMNS)
        self._genre_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._genre_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._genre_table.setAlternatingRowColors(True)
        self._genre_table.verticalHeader().setVisible(False)
        self._genre_table.setMaximumHeight(220)
        outer.addWidget(self._genre_table)

    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        layout.addWidget(muted("Built-in voice profiles"))

        self._list = QListWidget()
        self._list.currentItemChanged.connect(self._handle_selection_changed)
        layout.addWidget(self._list, stretch=1)

        return panel

    def _build_form_panel(self) -> QWidget:
        frame, card_layout = card("Voice profile", icon_name="audio")

        self._status_badge = badge("")
        card_layout.addLayout(row(self._status_badge))

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(_LEFT)

        self._display_name = muted("")
        form.addRow("Display name", self._display_name)

        self._description = muted("")
        form.addRow("Description", self._description)

        self._style_summary = muted("")
        form.addRow("Style defaults", self._style_summary)

        self._recommended_tags = muted("")
        form.addRow("Recommended tags", self._recommended_tags)

        self._used_by_genres = muted("")
        form.addRow("Used by genres", self._used_by_genres)

        card_layout.addLayout(form)

        card_layout.addWidget(subheading(f"Real {self._provider_name} voice"))
        card_layout.addWidget(
            muted(
                "Only a voice already added to this account's own "
                '"My Voices" will actually work - ElevenLabs\' Free tier '
                "blocks API access to library (non-owned) voices."
            )
        )

        mapping_form = QFormLayout()
        mapping_form.setSpacing(10)
        mapping_form.setLabelAlignment(_LEFT)

        self._voice_id_field = QLineEdit()
        self._voice_id_field.setPlaceholderText(
            "Real voice id from your ElevenLabs account"
        )
        mapping_form.addRow("Voice id", self._voice_id_field)

        self._notes_field = QLineEdit()
        self._notes_field.setPlaceholderText("Optional")
        mapping_form.addRow("Notes", self._notes_field)

        card_layout.addLayout(mapping_form)

        save_button = button("Save", variant="primary", icon_name="check")
        save_button.clicked.connect(self._handle_save_clicked)

        remove_button = button("Remove mapping", variant="danger")
        remove_button.clicked.connect(self._handle_remove_clicked)

        card_layout.addLayout(row(save_button, remove_button))

        card_layout.addWidget(subheading("Suggest a real voice"))

        self._suggest_note = muted(
            "Searches ElevenLabs' real voice library by this profile's "
            "own style - always review and listen before using one."
        )
        card_layout.addWidget(self._suggest_note)

        self._suggest_button = button("Suggest voices", icon_name="search")
        self._suggest_button.clicked.connect(self._handle_suggest_clicked)
        self._suggest_button.setEnabled(self._voice_search_client is not None)

        if self._voice_search_client is None:
            self._suggest_button.setToolTip(
                "Configure a real, enabled ElevenLabs voice provider in "
                "Provider Manager first."
            )

        card_layout.addLayout(row(self._suggest_button))

        self._suggestions_list = QListWidget()
        self._suggestions_list.setMaximumHeight(140)
        card_layout.addWidget(self._suggestions_list)

        use_suggestion_button = button("Use selected suggestion")
        use_suggestion_button.clicked.connect(self._handle_use_suggestion_clicked)
        card_layout.addLayout(row(use_suggestion_button))

        card_layout.addStretch()

        return frame

    def refresh(self) -> None:
        """Reload voice profiles, their registered mappings, and the
        genre overview table."""

        self._profiles = self._voice_profile_registry.list_all()

        self._list.blockSignals(True)
        self._list.clear()

        for profile in self._profiles:
            configured = self._mapping_service.get_voice_id(
                voice_profile_id=profile.profile_id,
                provider_name=self._provider_name,
            )
            marker = " ✓" if configured else ""
            item = QListWidgetItem(f"{profile.display_name}{marker}")
            item.setData(Qt.ItemDataRole.UserRole, profile.profile_id)
            self._list.addItem(item)

        self._list.blockSignals(False)

        if self._selected_profile_id and any(
            profile.profile_id == self._selected_profile_id
            for profile in self._profiles
        ):
            self._select_profile_id(self._selected_profile_id)
        elif self._profiles:
            self._select_profile_id(self._profiles[0].profile_id)

        self._refresh_genre_table()

    def _refresh_genre_table(self) -> None:
        genres = self._genre_profile_registry.list_all()

        self._genre_table.setRowCount(len(genres))

        for genre_row, genre in enumerate(genres):
            voice_profile_id = genre.voice.voice_profile_id
            configured = self._mapping_service.get_voice_id(
                voice_profile_id=voice_profile_id,
                provider_name=self._provider_name,
            )

            self._genre_table.setItem(
                genre_row, 0, QTableWidgetItem(genre.display_name)
            )
            self._genre_table.setItem(genre_row, 1, QTableWidgetItem(voice_profile_id))
            self._genre_table.setItem(
                genre_row,
                2,
                QTableWidgetItem(genre.voice.voice_delivery_mode.value),
            )
            self._genre_table.setItem(
                genre_row,
                3,
                QTableWidgetItem(configured if configured else "not configured"),
            )

    def _select_profile_id(self, profile_id: str) -> None:
        for index in range(self._list.count()):
            item = self._list.item(index)

            if item.data(Qt.ItemDataRole.UserRole) == profile_id:
                self._list.setCurrentItem(item)
                return

    def _handle_selection_changed(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        if current is None:
            self._selected_profile_id = None
            self._reset_form()
            return

        profile_id = current.data(Qt.ItemDataRole.UserRole)
        self._selected_profile_id = profile_id

        profile = next(
            (
                candidate
                for candidate in self._profiles
                if candidate.profile_id == profile_id
            ),
            None,
        )

        if profile is not None:
            self._load_profile_into_form(profile)

    def _load_profile_into_form(self, profile: VoiceProfile) -> None:
        self._display_name.setText(profile.display_name)
        self._description.setText(profile.description or "—")

        self._style_summary.setText(
            f"{profile.emotion.value} · {profile.pace.value} · "
            f"{profile.energy.value} energy · {profile.pitch_style.value} pitch"
        )

        provider_mapping = profile.provider_mappings.get(self._provider_name, {})
        recommended_tags = provider_mapping.get("recommended_voice_tags", [])
        self._recommended_tags.setText(
            ", ".join(recommended_tags) if recommended_tags else "—"
        )

        using_genres = [
            genre.display_name
            for genre in self._genre_profile_registry.list_all()
            if genre.voice.voice_profile_id == profile.profile_id
        ]
        self._used_by_genres.setText(", ".join(using_genres) if using_genres else "—")

        registered_voice_id = self._mapping_service.get_voice_id(
            voice_profile_id=profile.profile_id,
            provider_name=self._provider_name,
        )
        self._voice_id_field.setText(registered_voice_id or "")
        self._notes_field.clear()

        self._status_badge.setText(
            f"Configured: {registered_voice_id}"
            if registered_voice_id
            else "Not configured"
        )

        self._clear_suggestions()

    def _reset_form(self) -> None:
        self._display_name.setText("")
        self._description.setText("")
        self._style_summary.setText("")
        self._recommended_tags.setText("")
        self._used_by_genres.setText("")
        self._voice_id_field.clear()
        self._notes_field.clear()
        self._status_badge.setText("")

        self._clear_suggestions()

    def _clear_suggestions(self) -> None:
        self._suggestions = []
        self._suggestions_list.clear()

    def _handle_save_clicked(self) -> None:
        if self._selected_profile_id is None:
            return

        voice_id = self._voice_id_field.text().strip()

        if not voice_id:
            QMessageBox.warning(
                self,
                "Could not save voice mapping",
                "Enter a real voice id before saving.",
            )

            return

        try:
            self._mapping_service.set_voice_id(
                voice_profile_id=self._selected_profile_id,
                provider_name=self._provider_name,
                voice_id=voice_id,
                notes=self._notes_field.text(),
            )
        except ValueError as error:
            QMessageBox.warning(self, "Could not save voice mapping", str(error))

            return

        self.refresh()

    def _handle_remove_clicked(self) -> None:
        if self._selected_profile_id is None:
            return

        confirmation = QMessageBox.question(
            self,
            "Remove voice mapping",
            (
                "Remove the registered real voice id for "
                f"'{self._selected_profile_id}'? Real generation for this "
                "profile will fall back to an error until a new one is "
                "registered."
            ),
        )

        if confirmation != QMessageBox.StandardButton.Yes:
            return

        self._mapping_service.remove(
            voice_profile_id=self._selected_profile_id,
            provider_name=self._provider_name,
        )
        self.refresh()

    def _handle_suggest_clicked(self) -> None:
        if self._voice_search_client is None or self._selected_profile_id is None:
            return

        profile = next(
            (
                candidate
                for candidate in self._profiles
                if candidate.profile_id == self._selected_profile_id
            ),
            None,
        )

        if profile is None:
            return

        terms = build_voice_search_terms(profile)

        if not terms:
            QMessageBox.information(
                self,
                "Suggest voices",
                "This profile has no real style information to search on.",
            )

            return

        try:
            results = self._voice_search_client.suggest(terms=terms)
        except (HttpProviderExecutionError, ValueError) as error:
            QMessageBox.warning(self, "Could not suggest voices", str(error))

            return

        self._suggestions = results
        self._suggestions_list.clear()

        if not results:
            self._suggestions_list.addItem(
                f"No real ElevenLabs voices matched {', '.join(terms)}."
            )

            return

        for result in results:
            label_text = ", ".join(
                f"{key}: {value}" for key, value in result.labels.items()
            )
            summary = f"{result.name or result.voice_id}"

            if label_text:
                summary += f" ({label_text})"

            if result.preview_url:
                summary += f" — preview: {result.preview_url}"

            self._suggestions_list.addItem(summary)

    def _handle_use_suggestion_clicked(self) -> None:
        selected_row = self._suggestions_list.currentRow()

        if selected_row < 0 or selected_row >= len(self._suggestions):
            QMessageBox.information(
                self,
                "Use selected suggestion",
                "Select a suggestion first, then click this to fill in "
                "its real voice id - you'll still need to click Save to "
                "register it.",
            )

            return

        self._voice_id_field.setText(self._suggestions[selected_row].voice_id)
