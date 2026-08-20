from src.models.enums import (
    JobStatus,
    Platform,
    ProductionMode,
    WorkflowStage,
)

print("Mode:", ProductionMode.PREMIUM)
print("Platform:", Platform.YOUTUBE)
print("Status:", JobStatus.RUNNING)
print("Stage:", WorkflowStage.SCRIPT)
