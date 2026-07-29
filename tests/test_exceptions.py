from src.shared.exceptions import (
    BudgetExceededError,
    ScriptGenerationError,
    VideoGenerationError,
)

try:
    raise ScriptGenerationError("Script generation failed.")
except ScriptGenerationError as e:
    print(e)

try:
    raise VideoGenerationError("Video generation failed.")
except VideoGenerationError as e:
    print(e)

try:
    raise BudgetExceededError("Daily budget exceeded.")
except BudgetExceededError as e:
    print(e)

print("Exception tests completed successfully.")
