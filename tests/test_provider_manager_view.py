from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.desktop.views.provider_manager_view import (  # noqa: E402
    ProviderManagerView,
)
from src.models.provider_profile import ProviderCategory  # noqa: E402
from src.services.provider_profile_management_service import (  # noqa: E402
    ProviderProfileManagementService,
)
from src.services.registry.provider_profile_repository import (  # noqa: E402
    InMemoryProviderProfileRepository,
)
from src.services.registry.provider_registry import ProviderRegistry  # noqa: E402
from src.services.secrets.provider_secret_manager import (  # noqa: E402
    InMemorySecretStore,
    ProviderSecretManager,
)

# Real-world finding: "Provider name" used to be a plain free-text
# field, so a typo (e.g. "opena" instead of "openai") could silently
# produce a profile this app has no coded adapter for. These tests
# cover the fix - an editable combo box suggesting the known, real
# provider names per category, while staying free-text for categories
# with no coded adapter (or a deliberate generic-HTTP-adapter name).


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])

    yield app  # type: ignore[misc]


def _management_service() -> ProviderProfileManagementService:
    return ProviderProfileManagementService(
        registry=ProviderRegistry(),
        repository=InMemoryProviderProfileRepository(),
        secret_manager=ProviderSecretManager(InMemorySecretStore()),
    )


def _view(
    qapp: QApplication,
    *,
    service: ProviderProfileManagementService | None = None,
) -> ProviderManagerView:
    return ProviderManagerView(management_service=service or _management_service())


def test_provider_name_is_an_editable_combo_box(qapp: QApplication) -> None:
    view = _view(qapp)

    assert view._provider_name.isEditable() is True  # noqa: SLF001


def test_llm_category_suggests_the_known_llm_providers(qapp: QApplication) -> None:
    view = _view(qapp)

    llm_index = view._category.findData(ProviderCategory.LLM)  # noqa: SLF001
    view._category.setCurrentIndex(llm_index)  # noqa: SLF001

    items = [
        view._provider_name.itemText(i)  # noqa: SLF001
        for i in range(view._provider_name.count())  # noqa: SLF001
    ]
    assert items == ["openai", "anthropic", "gemini"]


def test_voice_category_suggests_elevenlabs_only(qapp: QApplication) -> None:
    view = _view(qapp)

    voice_index = view._category.findData(ProviderCategory.VOICE)  # noqa: SLF001
    view._category.setCurrentIndex(voice_index)  # noqa: SLF001

    items = [
        view._provider_name.itemText(i)  # noqa: SLF001
        for i in range(view._provider_name.count())  # noqa: SLF001
    ]
    assert items == ["elevenlabs"]


def test_a_category_with_no_coded_adapter_has_no_forced_suggestions(
    qapp: QApplication,
) -> None:
    """
    VIDEO/IMAGE/UPLOAD have no coded provider_name dispatch at all
    (src/services/factory/provider_factory.py only branches on
    category for these, never provider_name) - the combo must stay
    free-text, not force a fabricated list of "known" names that
    don't actually exist.
    """

    view = _view(qapp)

    video_index = view._category.findData(ProviderCategory.VIDEO)  # noqa: SLF001
    view._category.setCurrentIndex(video_index)  # noqa: SLF001

    assert view._provider_name.count() == 0  # noqa: SLF001
    assert view._provider_name.isEditable() is True  # noqa: SLF001


def test_a_custom_provider_name_is_still_accepted_and_saved(
    qapp: QApplication,
) -> None:
    """The combo stays editable - a deliberate custom name for the
    generic HTTP adapter path (not one of the coded suggestions) must
    still work, never rejected."""

    service = _management_service()
    view = _view(qapp, service=service)

    llm_index = view._category.findData(ProviderCategory.LLM)  # noqa: SLF001
    view._category.setCurrentIndex(llm_index)  # noqa: SLF001

    view._profile_id.setText("provider.custom")  # noqa: SLF001
    view._display_name.setText("Custom Provider")  # noqa: SLF001
    view._provider_name.setCurrentText("my-custom-llm")  # noqa: SLF001

    view._handle_save_clicked()  # noqa: SLF001

    saved = service.get_profile("provider.custom")
    assert saved.provider_name == "my-custom-llm"


def test_loading_a_profile_shows_its_saved_provider_name(
    qapp: QApplication,
) -> None:
    service = _management_service()
    from src.models.provider_profile_management import ProviderProfileUpsertCommand

    service.upsert_profile(
        ProviderProfileUpsertCommand(
            profile_id="provider.llm.main",
            display_name="Main LLM",
            provider_name="anthropic",
            category=ProviderCategory.LLM,
            enabled=True,
            secret_value="sk-test-secret",
        )
    )

    view = _view(qapp, service=service)
    view.refresh()
    view._list.setCurrentRow(0)  # noqa: SLF001

    assert view._provider_name.currentText() == "anthropic"  # noqa: SLF001


def test_reset_form_clears_provider_name_and_repopulates_for_llm(
    qapp: QApplication,
) -> None:
    """
    Regression guard: setCurrentIndex(0) on the category combo is a
    no-op (fires no signal) when it was already at index 0 - New
    provider must still end up with real LLM suggestions, not an
    empty combo left over from a previous .clear().
    """

    service = _management_service()
    from src.models.provider_profile_management import ProviderProfileUpsertCommand

    service.upsert_profile(
        ProviderProfileUpsertCommand(
            profile_id="provider.llm.main",
            display_name="Main LLM",
            provider_name="anthropic",
            category=ProviderCategory.LLM,
            enabled=True,
            secret_value="sk-test-secret",
        )
    )

    view = _view(qapp, service=service)
    view.refresh()
    view._list.setCurrentRow(0)  # noqa: SLF001
    assert view._category.currentIndex() == 0  # noqa: SLF001

    view._handle_new_clicked()  # noqa: SLF001

    assert view._provider_name.currentText() == ""  # noqa: SLF001
    items = [
        view._provider_name.itemText(i)  # noqa: SLF001
        for i in range(view._provider_name.count())  # noqa: SLF001
    ]
    assert items == ["openai", "anthropic", "gemini"]


# --- 2026-09-11 real fix ("can we add an option to choose Claude
# model in the GUI where we add the API key"): "Default model" used to
# be a plain free-text field with no hint at all about what a valid
# value looks like - an empty value silently sent the literal
# placeholder string "provider-default-model" to the real API (a real
# 404, found live). Same editable-combo-with-real-suggestions pattern
# as Provider name above. ---


def test_default_model_is_an_editable_combo_box(qapp: QApplication) -> None:
    view = _view(qapp)

    assert view._default_model.isEditable() is True  # noqa: SLF001


def test_selecting_anthropic_suggests_real_claude_models(qapp: QApplication) -> None:
    view = _view(qapp)

    llm_index = view._category.findData(ProviderCategory.LLM)  # noqa: SLF001
    view._category.setCurrentIndex(llm_index)  # noqa: SLF001
    view._provider_name.setCurrentText("anthropic")  # noqa: SLF001

    items = [
        view._default_model.itemText(i)  # noqa: SLF001
        for i in range(view._default_model.count())  # noqa: SLF001
    ]
    assert "claude-sonnet-5" in items
    assert "claude-opus-5" in items


def test_selecting_gemini_suggests_real_gemini_models(qapp: QApplication) -> None:
    view = _view(qapp)

    llm_index = view._category.findData(ProviderCategory.LLM)  # noqa: SLF001
    view._category.setCurrentIndex(llm_index)  # noqa: SLF001
    view._provider_name.setCurrentText("gemini")  # noqa: SLF001

    items = [
        view._default_model.itemText(i)  # noqa: SLF001
        for i in range(view._default_model.count())  # noqa: SLF001
    ]
    assert "gemini-2.5-flash" in items


def test_a_provider_with_no_known_models_has_no_forced_suggestions(
    qapp: QApplication,
) -> None:
    """
    OpenAI is deliberately left without suggestions this session (no
    live-verified current model id) - the combo must stay free-text,
    not force a fabricated/possibly-stale list.
    """

    view = _view(qapp)

    llm_index = view._category.findData(ProviderCategory.LLM)  # noqa: SLF001
    view._category.setCurrentIndex(llm_index)  # noqa: SLF001
    view._provider_name.setCurrentText("openai")  # noqa: SLF001

    assert view._default_model.count() == 0  # noqa: SLF001
    assert view._default_model.isEditable() is True  # noqa: SLF001


def test_a_custom_default_model_is_still_accepted_and_saved(
    qapp: QApplication,
) -> None:
    """The combo stays editable - picking a suggestion is optional,
    never a hard restriction."""

    service = _management_service()
    view = _view(qapp, service=service)

    llm_index = view._category.findData(ProviderCategory.LLM)  # noqa: SLF001
    view._category.setCurrentIndex(llm_index)  # noqa: SLF001

    view._profile_id.setText("provider.custom")  # noqa: SLF001
    view._display_name.setText("Custom Provider")  # noqa: SLF001
    view._provider_name.setCurrentText("anthropic")  # noqa: SLF001
    view._default_model.setCurrentText("claude-some-future-model")  # noqa: SLF001

    view._handle_save_clicked()  # noqa: SLF001

    saved = service.get_profile("provider.custom")
    assert saved.default_model == "claude-some-future-model"


def test_loading_a_profile_shows_its_saved_default_model(qapp: QApplication) -> None:
    service = _management_service()
    from src.models.provider_profile_management import ProviderProfileUpsertCommand

    service.upsert_profile(
        ProviderProfileUpsertCommand(
            profile_id="provider.llm.main",
            display_name="Main LLM",
            provider_name="anthropic",
            category=ProviderCategory.LLM,
            enabled=True,
            secret_value="sk-test-secret",
            default_model="claude-sonnet-5",
        )
    )

    view = _view(qapp, service=service)
    view.refresh()
    view._list.setCurrentRow(0)  # noqa: SLF001

    assert view._default_model.currentText() == "claude-sonnet-5"  # noqa: SLF001
