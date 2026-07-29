Provider-based Design
Multiple API Support
No Hardcoded Providers
UI-driven Configuration
Pipeline-based Execution
Resume & Retry Support
Enterprise-grade Testing
# Mission Automation Project Principles

## Version

Version: 1.0  
Status: Architecture Freeze Candidate  
Scope: Mission Automation v1.0

---

## 1. Purpose

This document defines the permanent engineering and product principles of
Mission Automation.

These principles guide:

- Architecture decisions
- Feature design
- Backend development
- User interface development
- Provider integrations
- Testing
- Security
- Documentation
- Git workflow
- Future expansion

When two implementation options are available, the option that follows these
principles should normally be selected.

---

## 2. Product Identity

Mission Automation v1.0 is an AI-assisted video production platform.

Its purpose is to create complete, publish-ready video projects for:

- YouTube
- Facebook
- TikTok
- Instagram

A successful project contains more than a rendered video.

A completed project may include:

- Final video
- Voiceover
- Background music
- Sound effects
- Titles
- Thumbnails
- Description
- Keywords
- Tags
- Hashtags
- Chapters
- Platform captions
- Upload metadata
- Production records

Mission Automation v1.0 remains focused on video production.

General blog, podcast, newsletter, LinkedIn, and X/Twitter automation remain
outside the active v1.0 scope.

---

## 3. Core Architecture Layers

Mission Automation uses the following primary layers:

```text
Project Wizard
        ↓
Project Specification
        ↓
VideoJob
        ↓
Pipeline Engine
        ↓
Managers and Routers
        ↓
Provider Center
        ↓
Execution Providers
        ↓
Assets and Timelines
        ↓
Render Engine
        ↓
Packaging Engine
        ↓
Upload Center
```

Each layer has a separate responsibility.

A layer must not absorb unrelated responsibilities from another layer.

---

## 4. Project Specification Principle

The Project Specification defines what the user wants.

It may contain:

- Platform
- Video type
- Duration
- Language
- Audience
- Resolution
- Aspect ratio
- Quality
- Visual strategy
- Voice strategy
- Music strategy
- Sound-effect strategy
- Budget
- Provider preferences
- Packaging preferences
- Upload settings

The Pipeline determines how to produce the requested project.

Providers perform external operations.

The Project Specification must not contain API secrets.

---

## 5. VideoJob Principle

VideoJob is the central state object for one video production project.

It contains:

- User requirements
- Workflow state
- Research
- Script
- Originality review
- Scenes
- Asset states
- Video clips
- Voice assets
- Audio timeline
- Video timeline
- Render result
- Packaging result
- Policy result
- Upload state
- Errors
- Warnings

Every major production component works with the same VideoJob.

VideoJob should remain serializable and suitable for persistence.

---

## 6. Pipeline Principle

Every production workflow is executed through the Pipeline Engine.

Each Pipeline Stage must have one primary responsibility.

Examples:

```text
Research Stage
Script Stage
Originality Stage
Scene Planning Stage
Asset Selection Stage
Voice Stage
Music Stage
Sound Effects Stage
Render Stage
Packaging Stage
Upload Stage
```

A Pipeline Stage must not silently perform unrelated work.

For example:

```text
Research Stage
```

must not also generate the final script.

Stages communicate through:

```text
StageContext
StageResult
VideoJob
PipelineState
```

---

## 7. Pipeline State Principle

Pipeline execution must be observable and resumable.

Every stage may use these statuses:

```text
Pending
Running
Completed
Failed
Skipped
Waiting for User
```

Pipeline State should eventually be saved after meaningful stage changes.

Completed work must not be destroyed when a later stage fails.

Resume should continue from the first incomplete or invalid stage.

---

## 8. Provider Principle

No external API may be hardcoded into core workflows.

All external operations use provider interfaces.

Correct flow:

```text
Pipeline Stage
        ↓
Manager or Router
        ↓
Provider Selection
        ↓
Provider Interface
        ↓
Provider Adapter
        ↓
External Service
```

Incorrect flow:

```text
Pipeline Stage
        ↓
External SDK directly
```

Provider-specific implementation details must remain outside core business
logic.

---

## 9. Multiple Provider Principle

Every relevant provider category may support multiple profiles.

Categories may include:

- LLM
- Video
- Voice
- Images
- Stock video
- Stock images
- Music
- Sound effects
- Upload platforms

One category may contain:

```text
Primary Profile
Secondary Profile
Backup Profile
Disabled Profiles
```

Provider selection may consider:

- Explicit user choice
- Priority
- Health
- Capability
- Budget
- Quota
- Quality mode
- Fallback policy

A user-locked provider must not be replaced silently.

---

## 10. API Configuration Principle

API configuration should be managed through the Provider Center.

The future User Interface must allow users to:

- Add a provider profile
- Enter credentials
- Select a model
- Test the connection
- Enable or disable the profile
- Set priority
- Configure budget
- Configure retry
- Configure fallback
- Replace credentials
- Delete profiles

Core source code must not require editing when a provider profile changes.

---

## 11. Secret Security Principle

API keys, tokens, and credentials are secrets.

Secrets must:

- Never be committed to Git
- Never appear in normal logs
- Never appear in user-facing error messages
- Never be stored in plain text
- Never be returned fully to the frontend
- Never be embedded in Project Specifications
- Never be exported with ordinary project data

Provider profiles store secret references, not raw secrets.

Required flow:

```text
Provider Settings
        ↓
Backend Validation
        ↓
Encryption Service
        ↓
Encrypted Secret Store
        ↓
Secret Reference
```

---

## 12. Manual Workflow Principle

Mission Automation must remain useful without paid APIs.

Manual options must exist where practical.

Examples:

```text
Manual Video Upload
Manual Voiceover Upload
Manual Thumbnail Upload
Manual Titles
Manual Description
Manual Chapters
Manual Upload Metadata
```

Automatic generation is an enhancement, not a requirement for basic system
operation.

---

## 13. Dry-Run Principle

External provider categories should support Dry-Run implementations where
practical.

Dry-Run mode supports:

- Development without API keys
- Automated testing
- Pipeline testing
- Demonstrations
- Failure simulation
- Architecture validation

Dry-Run output must be clearly marked as non-production output.

Dry-Run output must not become upload-ready automatically.

---

## 14. Local-First Asset Principle

In Hybrid visual mode, the system searches the Local Library first.

Workflow:

```text
Scene
    ↓
Search Local Library
    ↓
Show Results
    ↓
Wait for User Decision
```

If local results are found, the user may:

- Use a local asset
- Search stock
- Upload manually
- Use image-to-video

If local results are not found, the system asks the user to choose:

- Search stock
- Manual upload
- Image-to-video

Stock search must not begin automatically without user approval.

---

## 15. Visual Source Principle

Mission Automation v1.0 supports scene-level visual source selection.

Active visual sources:

```text
Manual Upload
Local Library
Stock Footage
Image-to-Video
```

Reserved future source:

```text
Automatic AI Video Generation
```

Automatic AI video generation remains disabled and hidden until an approved
provider is configured and enabled.

Different scenes may use different visual sources.

---

## 16. Voice Strategy Principle

Voice strategy applies to the complete video.

Supported v1.0 strategies:

```text
AUTO_GENERATE
MANUAL_UPLOAD
```

Scene-by-scene mixed voiceover is not supported in v1.0.

This rule protects:

- Voice consistency
- Accent consistency
- Tone consistency
- Timing
- Audio quality
- Workflow simplicity

---

## 17. Duration Principle

Every project must define its requested duration.

Supported modes:

```text
Exact Duration
Duration Range
```

All durations are stored internally in seconds.

Duration affects:

- Script word count
- Scene count
- Scene timing
- Voiceover length
- Video timeline
- Audio timeline
- Final render validation

The system must distinguish:

- Requested duration
- Estimated duration
- Actual duration

A duration difference should produce a warning or failure according to the
configured tolerance.

---

## 18. Asset Reuse Principle

Existing assets should be reused when suitable.

Reusable assets may include:

- Videos
- Images
- Music
- Sound effects
- Thumbnails
- Logos
- Overlays

Asset metadata may include:

- File path
- Source
- Provider
- License
- Keywords
- Tags
- Duration
- Resolution
- Aspect ratio
- Content hash
- Usage count
- Last-used time

Asset reuse improves:

- Speed
- Cost
- Consistency
- Offline capability

Duplicate detection should use content hashes where practical.

---

## 19. Standard Internal Model Principle

All providers performing the same type of operation must return standard
internal models.

Examples:

```text
Every visual provider returns VideoClip.
Every voice provider returns a standard voice asset or AudioTrack.
Every image provider returns a standard image asset.
Every upload provider returns a standard upload result.
```

The Render Engine must not need to know whether a clip came from:

- Manual upload
- Stock
- Local Library
- Image-to-video
- Future AI generation

---

## 20. Manager and Router Principle

Managers coordinate workflows.

Routers select the correct provider.

Examples:

```text
AssetManager
VisualAssetRouter
VoiceAssetRouter
ProviderSelectionService
UploadRouter
```

Managers should not contain provider-specific SDK code.

Routers should not perform unrelated business logic.

---

## 21. Dependency Injection Principle

Services and providers should be passed into components instead of created
inside core workflow logic.

Preferred:

```python
manager = AssetManager(local_search_service)
```

Avoid:

```python
class AssetManager:
    def __init__(self):
        self.local_search_service = LocalAssetSearchService(...)
```

Dependency injection improves:

- Testing
- Replacement
- Configuration
- Plugin support
- Separation of responsibilities

---

## 22. Single Responsibility Principle

Every class, service, provider, and stage should have one clear primary
responsibility.

Examples:

```text
LocalAssetScanner
```

scans local files.

```text
LocalAssetSearchService
```

searches an existing index.

```text
AssetDecisionService
```

applies user decisions.

```text
VisualAssetRouter
```

routes scenes to providers.

One large service must not replace several clearly separate responsibilities.

---

## 23. Packaging Principle

A rendered video alone is not considered a complete project.

A complete project must also contain required publish-ready packaging.

Packaging may include:

- Selected title
- Selected thumbnail
- Description
- Keywords
- Tags
- Hashtags
- Chapters
- Platform captions
- Upload metadata

The Packaging Engine remains separate from the Render Engine.

---

## 24. Platform-Aware Packaging Principle

Packaging must be generated separately for each selected platform.

Examples:

```text
YouTube Package
Facebook Package
TikTok Package
Instagram Package
```

The same title, description, caption, tags, and hashtags must not be copied
to every platform without platform-specific validation.

---

## 25. SEO Accuracy Principle

Mission Automation may generate SEO recommendations.

It must clearly distinguish:

- AI-generated suggestions
- Internal estimates
- External provider data
- Verified platform data

The system must not present estimated search volume, competition, trend, or
CTR predictions as verified facts unless they come from a configured,
identified data provider.

---

## 26. Thumbnail Principle

Thumbnail generation and selection remain independent from video rendering.

Supported thumbnail sources may include:

- Manual upload
- Local image assets
- Stock images
- Frame extraction
- AI image generation
- Hybrid composition

Users should be able to:

- Review multiple variants
- Select one variant
- Upload a replacement
- Regenerate variants
- Edit thumbnail text
- Lock an approved thumbnail

---

## 27. User Control Principle

The system may recommend actions, but important decisions must remain visible
to the user.

Examples requiring user control may include:

- Stock search approval
- Manual upload selection
- Provider lock
- Budget override
- Title selection
- Thumbnail selection
- Packaging approval
- Upload approval

The system must not silently perform expensive or irreversible actions.

---

## 28. Waiting for User Principle

The Pipeline may pause safely when user input is required.

Examples:

- Manual video upload
- Manual voice upload
- Stock selection
- Local asset approval
- Title selection
- Thumbnail selection
- Policy confirmation
- Upload confirmation

Waiting states must be persistable and visible in the future User Interface.

---

## 29. Budget Principle

Expensive operations must respect configured budgets.

Budget levels may include:

- Global
- Project
- Provider category
- Provider profile
- Pipeline stage
- Scene
- Daily
- Monthly

Before an expensive operation, the system should validate:

- Remaining project budget
- Provider budget
- Estimated cost
- Retry cost
- Fallback cost

Hard budget limits must not be exceeded silently.

---

## 30. Cost Transparency Principle

The system should record costs when available.

Cost records must distinguish:

```text
Estimated Cost
Confirmed Provider Cost
Subscription Allocation Estimate
Unknown Cost
```

The system must not claim exact billing when the provider does not supply
exact billing data.

---

## 31. Error Normalization Principle

Provider-specific errors should be translated into internal error categories.

Suggested categories:

- Authentication
- Authorization
- Configuration
- Rate limit
- Quota exhausted
- Budget exceeded
- Timeout
- Provider unavailable
- Unsupported capability
- Invalid request
- Invalid response
- File missing
- Validation failure
- Unknown error

Core Pipeline code must not depend on external SDK exception types.

---

## 32. Retry Principle

Retries should occur only for retryable errors.

Retry configuration may include:

- Maximum retries
- Initial delay
- Maximum delay
- Backoff strategy
- Maximum retry cost

Authentication and invalid-request errors normally require correction, not
automatic retries.

Every retry must be recorded.

---

## 33. Fallback Principle

Fallback providers may be used only according to an approved fallback policy.

Fallback events must record:

- Original provider
- Failure reason
- Retry count
- Fallback provider
- Final provider
- Additional cost
- Result

Fallback must not happen invisibly.

---

## 34. Persistence Principle

Important workflow data must eventually be persistable.

Initial persistence target:

```text
SQLite
```

Persistable data includes:

- VideoJob
- Project Specification
- Pipeline State
- Stage Results
- Asset Index
- Provider profiles
- Secret references
- Usage records
- Cost records
- Packaging data
- Upload records
- Audit events

Future databases may include PostgreSQL or managed cloud storage.

---

## 35. Idempotency Principle

Repeated execution of the same stage should not create unnecessary duplicate
work.

Examples:

- Do not download the same selected asset repeatedly.
- Do not generate duplicate voice files without a regeneration request.
- Do not upload the same final project twice accidentally.
- Do not recreate completed packaging without a reason.

Stages should record stable identifiers and execution results where practical.

---

## 36. Audit Principle

Important system changes and decisions should be auditable.

Examples:

- Provider profile created
- Credential replaced
- Provider selected
- Fallback used
- Budget override approved
- User selected title
- User selected thumbnail
- Pipeline resumed
- Stage retried
- Upload started
- Upload completed
- Upload failed

Audit data must never contain API secrets.

---

## 37. Logging Principle

Logs should include enough information to diagnose problems.

Logs may include:

- Job ID
- Stage name
- Provider
- Profile ID
- Model
- Status
- Duration
- Retry count
- Error category
- Estimated cost

Logs must exclude:

- API keys
- Access tokens
- Refresh tokens
- Secret headers
- Full sensitive payloads

---

## 38. Validation Principle

Domain validation belongs in domain models where practical.

Examples:

- Exact duration requires a target duration.
- Range duration requires minimum and maximum.
- Minimum duration cannot exceed maximum.
- Manual-ready media requires a file path.
- Stock scenes require a query.
- Image-to-video scenes require an image prompt.
- Ready voiceover requires an audio file.
- Upload requires packaging approval.

Invalid states should be blocked early.

---

## 39. Backward Compatibility Principle

Existing working functionality should be upgraded incrementally.

Before modifying an established model:

1. Review the current implementation.
2. Preserve required fields.
3. Add new fields with safe defaults where possible.
4. Run old tests.
5. Add new tests.
6. Create a stable Git commit.

Large files should not be replaced blindly without reviewing their current
content.

---

## 40. Testing Principle

Every important component requires tests.

Test levels include:

```text
Model Tests
Service Tests
Provider Tests
Failure Tests
Integration Tests
Sprint Regression Tests
End-to-End Tests
```

Every Sprint must finish with:

- Relevant component tests
- At least one integration or regression test
- Git commit
- Git push

Dry-Run providers should make external workflows testable without API keys.

---

## 41. Documentation-First Principle

Important architecture and product decisions should be documented before
large implementation changes.

Recommended order:

```text
Idea
    ↓
Discussion
    ↓
Architecture Decision
    ↓
Documentation
    ↓
Domain Model
    ↓
Service or Provider
    ↓
Tests
    ↓
Integration Test
    ↓
Commit
```

Documentation and code should remain synchronized.

---

## 42. Architecture Decision Principle

Major decisions should be recorded in:

```text
docs/DECISIONS.md
```

Each decision should contain:

- Decision number
- Title
- Status
- Context
- Decision
- Reason
- Consequences
- Date

Accepted decisions should not be changed casually.

A replacement decision should explain what it supersedes.

---

## 43. Scope Control Principle

Mission Automation v1.0 remains focused on video production.

New ideas outside the active scope should be recorded in:

```text
docs/FUTURE_IDEAS.md
```

They should not interrupt the current Sprint unless they are necessary for
the current architecture.

One Sprint must be completed before the next Sprint begins.

---

## 44. Naming Principle

Naming must remain consistent.

General rules:

```text
Classes: PascalCase
Functions: snake_case
Variables: snake_case
Files: snake_case
Packages: lowercase snake_case
Constants: UPPER_SNAKE_CASE
Enums: PascalCase
Enum Members: UPPER_SNAKE_CASE
```

The same concept must use the same field name throughout the project.

Examples:

```text
manual_file_path
image_prompt
stock_query
selected_asset_path
voice_file
```

Different names for the same concept should be avoided.

---

## 45. Package Naming Principle

Python package and folder names must use lowercase.

Correct:

```text
src/pipeline
src/providers
src/services
src/models
```

Incorrect:

```text
src/Pipeline
src/Providers
src/Services
```

This rule avoids import failures and cross-platform inconsistencies.

---

## 46. Type Hint Principle

Public Python functions and methods should use type hints.

Type hints improve:

- Readability
- Static analysis
- Editor support
- Refactoring
- Testing
- Documentation

Unstructured dictionaries should be replaced by validated models when the
data becomes part of the stable domain.

---

## 47. Standard Output Principle

Generated files should follow a predictable structure.

Example:

```text
project_output/
├── video/
├── audio/
├── images/
├── thumbnails/
├── packaging/
├── metadata/
├── logs/
└── reports/
```

File names should contain stable identifiers where appropriate.

User-facing files should not overwrite previous outputs without an explicit
replacement policy.

---

## 48. Upload Safety Principle

Automatic upload is allowed only when:

- Final render exists
- Packaging is approved
- Required metadata is valid
- Policy review passes
- Upload readiness is true
- Platform account is connected
- User settings permit automatic upload

Quick Mode, prototype, or Dry-Run outputs must not upload automatically.

---

## 49. UI-Friendly Backend Principle

Backend models should support future User Interfaces.

The future interface may include:

- Project Wizard
- Pipeline progress
- Scene Manager
- Asset Manager
- Provider Center
- Voice Manager
- Audio Manager
- Timeline Editor
- Render Center
- Packaging Center
- Upload Center
- Analytics

Backend state should expose explicit statuses instead of relying on hidden
side effects.

---

## 50. Analytics Principle

Future analytics may include:

- Jobs created
- Jobs completed
- Stage duration
- Provider success rate
- Provider latency
- Estimated cost
- Confirmed cost
- Asset reuse
- Render duration
- Upload success
- Packaging approval
- Failure reasons

Analytics must distinguish estimates from verified provider or platform data.

---

## 51. Plugin Readiness Principle

Core interfaces should permit future plugins.

Potential plugin areas:

- Pipeline stages
- Providers
- Render engines
- Upload platforms
- Packaging analyzers
- Asset scanners
- Storage backends

Plugin readiness does not mean building a full plugin marketplace in v1.0.

The architecture should remain extensible without unnecessary early
complexity.

---

## 52. Performance Principle

Performance optimizations should preserve correctness and observability.

Examples:

- Reuse the Asset Index instead of scanning folders repeatedly.
- Cache stable provider metadata.
- Avoid duplicate downloads.
- Avoid duplicate hashes.
- Use parallel execution only when dependencies allow it.
- Record background task states.
- Do not hide failures for apparent speed.

Correctness and resumability are more important than premature optimization.

---

## 53. Quality Principle

Mission Automation must optimize for reliable production quality.

Quality includes:

- Original content
- Human value
- Accurate timing
- Appropriate visuals
- Clear voiceover
- Balanced audio
- Valid packaging
- Platform compliance
- Reproducible results

A successful test does not automatically mean production quality is verified.

Real provider integrations require separate production validation.

---

## 54. Truthfulness Principle

The system must not misrepresent:

- Provider costs
- Search volume
- Trend data
- CTR predictions
- Licensing
- Platform approval
- Quota availability
- Upload success
- AI originality

Unknown or estimated information must be labeled clearly.

---

## 55. Licensing Principle

Assets should carry licensing metadata where available.

The system should preserve:

- Source
- Provider
- License type
- Attribution requirement
- Download reference
- Usage notes

The system must not assume that every downloaded asset is royalty-free or
commercially usable.

User approval may be required when licensing information is incomplete.

---

## 56. Platform Compliance Principle

Publishing workflows must respect platform requirements.

The system should validate:

- File format
- Duration
- Resolution
- Aspect ratio
- Caption limits
- Metadata limits
- Thumbnail requirements
- Audience settings
- Authentication
- Policy readiness

Platform-specific rules should remain isolated from general workflow logic.

---

## 57. Versioning Principle

Mission Automation should use clear milestone versioning.

Suggested progression:

```text
v0.1 — Foundation
v0.2 — Pipeline
v0.3 — Voice
v0.4 — Music and Sound Effects
v0.5 — Render
v0.6 — Packaging
v0.7 — Provider Center
v0.8 — User Interface
v0.9 — Beta
v1.0 — Stable Video Production Release
```

Git tags should identify important stable milestones.

---

## 58. Git Principle

Before major development changes:

```text
Run Tests
Check Git Status
Commit Stable Work
Push
Begin New Work
```

Commit messages should describe the completed architectural or functional
milestone.

Examples:

```text
Sprint 10 - Complete visual asset management system
Sprint 11 - Add pipeline engine foundation
```

Temporary files, caches, credentials, and generated secrets must not be
committed.

---

## 59. Definition of Done

A feature is complete when:

- Architecture is documented
- Domain models are validated
- Service or provider implementation exists
- Unit tests pass
- Failure behavior is tested where relevant
- Integration behavior is tested
- Naming is consistent
- Documentation matches code
- Git commit is created
- Changes are pushed

A Sprint is not complete merely because one happy-path test passes.

---

## 60. Final Principle

Mission Automation should remain:

```text
Modular
Testable
Secure
Provider-independent
User-controlled
Resumable
Budget-aware
Platform-aware
Publish-ready
Extensible
```

The project should prefer a clear, maintainable solution over unnecessary
complexity.

Architecture exists to support reliable production, not to create complexity
for its own sake.