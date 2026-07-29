from src.config.settings import settings


print("Dry-run enabled:", settings.MISSION_AUTOMATION_DRY_RUN)

assert settings.MISSION_AUTOMATION_DRY_RUN is True

print("Dry-run configuration test completed successfully.")