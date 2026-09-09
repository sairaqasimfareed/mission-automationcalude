from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402
from unittest.mock import patch  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from src.desktop.views.voice_manager_view import VoiceManagerView  # noqa: E402
from src.services.genre_profile_registry_service import (  # noqa: E402
    GenreProfileRegistryService,
)
from src.services.registry.voice_provider_mapping_repository import (  # noqa: E402
    InMemoryVoiceProviderMappingRepository,
)
from src.services.voice_profile_registry_service import (  # noqa: E402
    VoiceProfileRegistryService,
)
from src.services.voice_provider_mapping_service import (  # noqa: E402
    VoiceProviderMappingService,
)


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])

    yield app  # type: ignore[misc]


def _mapping_service() -> VoiceProviderMappingService:
    service = VoiceProviderMappingService(
        repository=InMemoryVoiceProviderMappingRepository()
    )
    service.load()

    return service


def _view(
    qapp: QApplication,
    *,
    mapping_service: VoiceProviderMappingService | None = None,
) -> VoiceManagerView:
    return VoiceManagerView(
        voice_provider_mapping_service=mapping_service or _mapping_service(),
        voice_profile_registry=VoiceProfileRegistryService.with_default_profiles(),
        genre_profile_registry=GenreProfileRegistryService.with_default_profiles(),
    )


def test_refresh_populates_every_built_in_voice_profile(qapp: QApplication) -> None:
    view = _view(qapp)
    view.refresh()

    registry = VoiceProfileRegistryService.with_default_profiles()
    assert view._list.count() == len(registry.list_all())  # noqa: SLF001


def test_selecting_a_profile_shows_its_real_details(qapp: QApplication) -> None:
    view = _view(qapp)
    view.refresh()
    view._select_profile_id("voice.horror_whisper")  # noqa: SLF001

    assert view._display_name.text() == "Horror Whisper"  # noqa: SLF001
    assert "suspenseful" in view._style_summary.text()  # noqa: SLF001
    assert "genre.horror" not in view._used_by_genres.text()  # noqa: SLF001
    assert "Horror" in view._used_by_genres.text()  # noqa: SLF001


def test_unconfigured_profile_shows_not_configured(qapp: QApplication) -> None:
    view = _view(qapp)
    view.refresh()
    view._select_profile_id("voice.horror_whisper")  # noqa: SLF001

    assert view._status_badge.text() == "Not configured"  # noqa: SLF001
    assert view._voice_id_field.text() == ""  # noqa: SLF001


def test_save_registers_a_real_voice_id(qapp: QApplication) -> None:
    service = _mapping_service()
    view = _view(qapp, mapping_service=service)
    view.refresh()
    view._select_profile_id("voice.horror_whisper")  # noqa: SLF001

    view._voice_id_field.setText("real-voice-abc")  # noqa: SLF001
    view._notes_field.setText("Added from My Voices")  # noqa: SLF001
    view._handle_save_clicked()  # noqa: SLF001

    assert (
        service.get_voice_id(
            voice_profile_id="voice.horror_whisper", provider_name="elevenlabs"
        )
        == "real-voice-abc"
    )
    assert view._status_badge.text() == "Configured: real-voice-abc"  # noqa: SLF001


def test_save_without_a_voice_id_is_rejected(qapp: QApplication) -> None:
    service = _mapping_service()
    view = _view(qapp, mapping_service=service)
    view.refresh()
    view._select_profile_id("voice.horror_whisper")  # noqa: SLF001

    view._voice_id_field.setText("")  # noqa: SLF001

    with patch("src.desktop.views.voice_manager_view.QMessageBox.warning") as warning:
        view._handle_save_clicked()  # noqa: SLF001

    warning.assert_called_once()
    assert "Enter a real voice id" in warning.call_args.args[2]
    assert (
        service.get_voice_id(
            voice_profile_id="voice.horror_whisper", provider_name="elevenlabs"
        )
        is None
    )


def test_remove_clears_a_registered_voice_id(qapp: QApplication) -> None:
    service = _mapping_service()
    service.set_voice_id(
        voice_profile_id="voice.horror_whisper",
        provider_name="elevenlabs",
        voice_id="real-voice-abc",
    )

    view = _view(qapp, mapping_service=service)
    view.refresh()
    view._select_profile_id("voice.horror_whisper")  # noqa: SLF001

    with patch("src.desktop.views.voice_manager_view.QMessageBox.question") as question:
        question.return_value = QMessageBox.StandardButton.Yes
        view._handle_remove_clicked()  # noqa: SLF001

    assert (
        service.get_voice_id(
            voice_profile_id="voice.horror_whisper", provider_name="elevenlabs"
        )
        is None
    )


def test_remove_is_cancelled_when_the_user_declines(qapp: QApplication) -> None:
    service = _mapping_service()
    service.set_voice_id(
        voice_profile_id="voice.horror_whisper",
        provider_name="elevenlabs",
        voice_id="real-voice-abc",
    )

    view = _view(qapp, mapping_service=service)
    view.refresh()
    view._select_profile_id("voice.horror_whisper")  # noqa: SLF001

    with patch("src.desktop.views.voice_manager_view.QMessageBox.question") as question:
        question.return_value = QMessageBox.StandardButton.No
        view._handle_remove_clicked()  # noqa: SLF001

    assert (
        service.get_voice_id(
            voice_profile_id="voice.horror_whisper", provider_name="elevenlabs"
        )
        == "real-voice-abc"
    )


def test_refresh_marks_a_configured_profile_in_the_list(qapp: QApplication) -> None:
    service = _mapping_service()
    service.set_voice_id(
        voice_profile_id="voice.horror_whisper",
        provider_name="elevenlabs",
        voice_id="real-voice-abc",
    )

    view = _view(qapp, mapping_service=service)
    view.refresh()

    labels = [
        view._list.item(i).text() for i in range(view._list.count())
    ]  # noqa: SLF001
    assert any(label.startswith("Horror Whisper") and "✓" in label for label in labels)


def test_genre_overview_table_reflects_real_delivery_mode(qapp: QApplication) -> None:
    view = _view(qapp)
    view.refresh()

    horror_row = None
    for genre_row in range(view._genre_table.rowCount()):  # noqa: SLF001
        genre_cell = view._genre_table.item(genre_row, 0)  # noqa: SLF001
        if genre_cell is not None and genre_cell.text() == "Horror":
            horror_row = genre_row
            break

    assert horror_row is not None

    delivery_cell = view._genre_table.item(horror_row, 2)  # noqa: SLF001
    voice_id_cell = view._genre_table.item(horror_row, 3)  # noqa: SLF001
    assert delivery_cell is not None
    assert voice_id_cell is not None
    assert delivery_cell.text() == "emotion_tags"
    assert voice_id_cell.text() == "not configured"
