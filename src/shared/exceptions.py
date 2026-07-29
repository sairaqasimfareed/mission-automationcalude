class MissionAutomationError(Exception):
    """Base exception for Mission Automation."""
    pass


class ConfigurationError(MissionAutomationError):
    """Configuration related errors."""
    pass


class ScriptGenerationError(MissionAutomationError):
    """Raised when script generation fails."""
    pass


class VoiceGenerationError(MissionAutomationError):
    """Raised when voice generation fails."""
    pass


class VideoGenerationError(MissionAutomationError):
    """Raised when video generation fails."""
    pass


class RenderError(MissionAutomationError):
    """Raised when rendering fails."""
    pass


class PolicyViolationError(MissionAutomationError):
    """Raised when originality or policy checks fail."""
    pass


class BudgetExceededError(MissionAutomationError):
    """Raised when budget limits are exceeded."""
    pass