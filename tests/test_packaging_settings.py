from pydantic import ValidationError

from src.models.packaging_settings import (
    PackagingSettings,
)


settings = PackagingSettings()

print("Packaging enabled:", settings.enabled)
print("Title variants:", settings.title_variant_count)
print(
    "Thumbnail variants:",
    settings.thumbnail_variant_count,
)
print("Requires review:", settings.requires_user_review)

assert settings.enabled is True
assert settings.title_variant_count == 5
assert settings.thumbnail_variant_count == 3
assert settings.generate_description is True
assert settings.generate_keywords is True
assert settings.generate_tags is True
assert settings.generate_hashtags is True
assert settings.generate_chapters is True
assert settings.requires_user_review is True


automatic_settings = PackagingSettings(
    require_title_approval=False,
    require_thumbnail_approval=False,
    require_final_packaging_approval=False,
)

assert automatic_settings.requires_user_review is False


disabled_settings = PackagingSettings(
    enabled=False,
    require_title_approval=False,
    require_thumbnail_approval=False,
    require_final_packaging_approval=False,
)

assert disabled_settings.requires_user_review is False


try:
    PackagingSettings(
        enabled=False,
    )
except ValidationError:
    print(
        "Disabled packaging with approval requirements "
        "successfully blocked."
    )
else:
    raise AssertionError(
        "Disabled packaging should not require approval."
    )


try:
    PackagingSettings(
        thumbnail_variant_count=0,
        require_thumbnail_approval=True,
    )
except ValidationError:
    print(
        "Thumbnail approval without variants "
        "successfully blocked."
    )
else:
    raise AssertionError(
        "Thumbnail approval requires a thumbnail variant."
    )


serialized = settings.model_dump_json()
restored = PackagingSettings.model_validate_json(
    serialized
)

assert restored == settings
assert restored.schema_version == "1.0"

print("Packaging Settings tests completed successfully.")