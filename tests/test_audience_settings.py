from pydantic import ValidationError

from src.models.audience_settings import (
    AudienceAgeGroup,
    AudienceSettings,
)


settings = AudienceSettings(
    language=" English ",
    target_country=" United States ",
    target_audience=(
        "Adults interested in history and mystery"
    ),
    age_group=AudienceAgeGroup.ADULTS,
    localization_enabled=True,
    localization_notes=(
        "Use natural American English and familiar references."
    ),
    cultural_requirements=[
        "American English",
        "Respectful historical context",
        "American English",
        "",
    ],
    excluded_topics=[
        "Graphic violence",
        "Hate speech",
        "",
    ],
)

print("Language:", settings.language)
print("Country:", settings.target_country)
print("Audience:", settings.target_audience)
print("Age group:", settings.age_group)
print("Localization:", settings.localization_enabled)

assert settings.language == "English"
assert settings.target_country == "United States"
assert settings.age_group == AudienceAgeGroup.ADULTS
assert settings.localization_enabled is True

assert settings.cultural_requirements == [
    "American English",
    "Respectful historical context",
]

assert settings.excluded_topics == [
    "Graphic violence",
    "Hate speech",
]


default_settings = AudienceSettings()

assert default_settings.language == "English"
assert default_settings.target_country == "United States"
assert default_settings.age_group == AudienceAgeGroup.GENERAL


try:
    AudienceSettings(
        language="",
        target_country="United States",
        target_audience="General audience",
    )
except ValidationError:
    print("Empty language successfully blocked.")
else:
    raise AssertionError(
        "An empty language should not be accepted."
    )


try:
    AudienceSettings(
        language="English",
        target_country="",
        target_audience="General audience",
    )
except ValidationError:
    print("Empty target country successfully blocked.")
else:
    raise AssertionError(
        "An empty target country should not be accepted."
    )


serialized = settings.model_dump_json()
restored = AudienceSettings.model_validate_json(
    serialized
)

assert restored == settings
assert restored.schema_version == "1.0"

print("Audience Settings tests completed successfully.")