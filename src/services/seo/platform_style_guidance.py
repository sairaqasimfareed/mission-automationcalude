from __future__ import annotations

from src.models.enums import Platform

# Real-world finding, 2026-09-14: SEOContext.platform already carried a
# real Platform value into every SEO/thumbnail generation prompt, but
# none of the three LLM-calling generation services (title,
# description, thumbnail concept) ever read it - each one's system
# prompt was hardcoded to "You are an expert YouTube ... writer"
# regardless of what context.platform actually was, and the human
# prompt text below it said "YouTube titles"/"YouTube video
# description" unconditionally too. SEOPlatformMetadataService's
# PlatformConstraints and ThumbnailLayoutService's platform dimensions
# were already real and platform-aware - only the GENERATED CONTENT
# itself never varied, so a TikTok-targeted package still got written
# in YouTube's voice and just happened to pass TikTok's length limit.
#
# One small shared table, not three separate copies, so all three
# generation services describe each platform's real conventions
# identically rather than risking drift between them.
_PLATFORM_DISPLAY_NAME: dict[Platform, str] = {
    Platform.YOUTUBE: "YouTube",
    Platform.FACEBOOK: "Facebook",
    Platform.TIKTOK: "TikTok",
}

_PLATFORM_STYLE_GUIDANCE: dict[Platform, str] = {
    Platform.YOUTUBE: (
        "Write in a keyword-rich, search-oriented style suited to "
        "YouTube's search and recommendation systems - longer, "
        "detailed descriptions are normal and rewarded there."
    ),
    Platform.FACEBOOK: (
        "Write in a conversational, share-friendly style, the way one "
        "person would describe the video to a friend - not "
        "search-engine-optimized copy."
    ),
    Platform.TIKTOK: (
        "Write in a short, punchy, hashtag-forward style with a "
        "casual, high-energy voice suited to a fast-scrolling feed - "
        "keep it brief."
    ),
}


def platform_display_name(platform: Platform) -> str:
    """The platform's real, human-facing name for prompt text."""

    return _PLATFORM_DISPLAY_NAME[platform]


def platform_style_guidance(platform: Platform) -> str:
    """
    One sentence of real, platform-specific writing guidance for an
    LLM system prompt - see this module's own real-world-finding
    comment for why this exists.
    """

    return _PLATFORM_STYLE_GUIDANCE[platform]
