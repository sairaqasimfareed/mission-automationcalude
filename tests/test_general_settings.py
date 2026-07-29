from pydantic import ValidationError

from src.models.general_settings import (
    GeneralSettings,
)

settings = GeneralSettings(
    project_name="Hidden Cities Project",
    channel_name="History Vault",
    topic="Hidden underground cities",
    video_type="Documentary",
    tags=[
        "history",
        " underground ",
        "history",
        "",
    ],
)

print(settings.project_name)
print(settings.channel_name)
print(settings.topic)

assert settings.tag_count == 2
assert settings.tags == [
    "history",
    "underground",
]

serialized = settings.model_dump_json()

restored = GeneralSettings.model_validate_json(serialized)

assert restored == settings

try:
    GeneralSettings(
        project_name="",
        channel_name="History",
        topic="Topic",
        video_type="Story",
    )
except ValidationError:
    print("Empty project name blocked.")
else:
    raise AssertionError("Validation failed.")

try:
    GeneralSettings(
        project_name="Project",
        channel_name="",
        topic="Topic",
        video_type="Story",
    )
except ValidationError:
    print("Empty channel blocked.")
else:
    raise AssertionError("Validation failed.")

print("General Settings tests completed successfully.")
