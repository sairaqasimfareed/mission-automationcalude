from src.models.upload_settings import (
    UploadPlatform,
    UploadSettings,
    UploadVisibility,
)

settings = UploadSettings()

print(settings.platform)
print(settings.visibility)

assert settings.platform == UploadPlatform.YOUTUBE
assert settings.visibility == UploadVisibility.PRIVATE

assert settings.auto_upload is False
assert settings.notify_subscribers is True
assert settings.allow_comments is True

scheduled = UploadSettings(
    visibility=UploadVisibility.SCHEDULED,
    scheduled_publish_datetime="2026-08-10T09:00:00Z",
)

assert scheduled.visibility == UploadVisibility.SCHEDULED

assert scheduled.scheduled_publish_datetime == "2026-08-10T09:00:00Z"

serialized = settings.model_dump_json()

restored = UploadSettings.model_validate_json(serialized)

assert restored == settings

print("Upload Settings tests completed successfully.")
