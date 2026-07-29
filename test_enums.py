from src.models.enums import (
    ProductionMode,
    Platform,
    JobStatus,
    WorkflowStage,
)

print("Mode:", ProductionMode.PREMIUM)
print("Platform:", Platform.YOUTUBE)
print("Status:", JobStatus.RUNNING)
print("Stage:", WorkflowStage.SCRIPT)