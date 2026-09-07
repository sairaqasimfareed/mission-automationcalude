from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.desktop.theme import ThemeMode  # noqa: E402
from src.desktop.views.settings_view import SettingsView  # noqa: E402
from src.models.advanced_settings import AdvancedSettings  # noqa: E402
from src.models.provider_profile import (  # noqa: E402
    ProviderCategory,
    ProviderProfile,
)
from src.models.voice_profile import VoiceProfile  # noqa: E402
from src.providers.dry_run_voice_provider import DryRunVoiceProvider  # noqa: E402
from src.services.genre_profile_registry_service import (  # noqa: E402
    GenreProfileRegistryService,
)
from src.services.runtime_configuration_loader import RuntimeConfiguration  # noqa: E402
from src.services.secrets.provider_secret_manager import (
    InMemorySecretStore,
)  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])

    yield app  # type: ignore[misc]


def _configuration() -> RuntimeConfiguration:
    return RuntimeConfiguration(
        secret_store=InMemorySecretStore(),
        provider_profiles=[
            ProviderProfile(
                profile_id="provider.llm.openai",
                display_name="OpenAI",
                provider_name="openai",
                category=ProviderCategory.LLM,
                enabled=True,
                secret_reference="secret://providers/provider.llm.openai/test",
            ),
        ],
        voice_profiles=[
            VoiceProfile(
                profile_id="voice.neutral_narrator",
                display_name="Neutral Narrator",
                fallback_profile_id=None,
            ),
        ],
        voice_providers=[DryRunVoiceProvider()],
        genre_registry=GenreProfileRegistryService.with_default_profiles(),
        advanced_settings=AdvancedSettings(dry_run=True),
        checkpoint_storage_root=None,
    )


def test_theme_combo_offers_system_light_and_dark_in_order(
    qapp: QApplication,
) -> None:
    view = SettingsView(get_configuration=_configuration)

    labels = [view._theme_combo.itemText(i) for i in range(view._theme_combo.count())]

    assert labels == ["Match system", "Light", "Dark"]


def test_theme_combo_preselects_the_current_preference(qapp: QApplication) -> None:
    view = SettingsView(
        get_configuration=_configuration,
        get_theme_mode=lambda: ThemeMode.LIGHT,
    )

    assert ThemeMode(view._theme_combo.currentData()) == ThemeMode.LIGHT


def test_theme_combo_defaults_to_first_item_when_no_getter_is_supplied(
    qapp: QApplication,
) -> None:
    view = SettingsView(get_configuration=_configuration)

    assert view._theme_combo.currentIndex() == 0


def test_selecting_a_theme_calls_the_change_callback(qapp: QApplication) -> None:
    received: list[ThemeMode] = []

    view = SettingsView(
        get_configuration=_configuration,
        get_theme_mode=lambda: ThemeMode.SYSTEM,
        on_theme_mode_changed=received.append,
    )

    dark_index = view._theme_combo.findData(ThemeMode.DARK.value)
    view._theme_combo.setCurrentIndex(dark_index)

    assert received == [ThemeMode.DARK]


def test_refresh_still_populates_the_provider_table(qapp: QApplication) -> None:
    view = SettingsView(get_configuration=_configuration)

    view.refresh()

    assert view._table.rowCount() == 1

    first_item = view._table.item(0, 0)
    assert first_item is not None
    assert first_item.text() == "provider.llm.openai"

    assert view._dry_run_label.text() == "Dry run: True"
