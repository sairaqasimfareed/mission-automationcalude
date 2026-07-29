# Mission Automation Provider Center

## Version

Version: 1.0  
Status: Architecture Freeze Candidate  
Scope: Mission Automation v1.0

---

## 1. Purpose

The Provider Center manages every external service used by Mission
Automation.

It allows users to connect, configure, test, prioritize, disable, and
replace external providers without changing the core application code.

Examples of external providers include:

- LLM services
- Video-generation services
- Voice-generation services
- Image-generation services
- Stock-media services
- Music services
- Sound-effect services
- Upload platforms

No external provider may be hardcoded into a workflow.

---

## 2. Core Principle

The rest of the application must use provider interfaces instead of calling
external SDKs directly.

```text
Pipeline Stage
        ↓
Manager or Router
        ↓
Provider Registry
        ↓
Provider Selection Service
        ↓
Configured Provider Profile
        ↓
Provider Adapter
        ↓
External API
```

This separation allows providers to be replaced without rewriting the
Pipeline.

---

## 3. Provider Categories

Mission Automation v1.0 supports these provider categories:

```text
LLM
Video
Voice
Image
Stock Video
Stock Image
Music
Sound Effects
Translation
Speech Recognition
Upload
```

Additional categories may be added later through the same architecture.

---

## 4. LLM Providers

LLM providers may be used for:

- Research
- Script writing
- Originality review
- SEO planning
- Title generation
- Description generation
- Keyword generation
- Chapter generation
- Policy assistance
- Packaging analysis

Possible providers include:

```text
OpenAI
Anthropic
Google Gemini
Other compatible LLM providers
```

The system must not assume that one LLM provider is always available.

---

## 5. Video Providers

Video providers may eventually be used for automatic visual generation.

Possible providers include:

```text
Google Veo
Kling
Runway
Luma
Pika
Future providers
```

Automatic AI video generation remains disabled in the first active visual
workflow until a suitable provider is configured and enabled.

The existing active visual sources remain:

- Manual Upload
- Local Library
- Stock Footage
- Image-to-Video

---

## 6. Voice Providers

Voice providers may generate the complete video voiceover.

Possible providers include:

```text
ElevenLabs
OpenAI TTS
Google Text-to-Speech
Azure Speech
Other compatible providers
```

Mission Automation v1.0 supports two whole-video voice strategies:

```text
AUTO_GENERATE
MANUAL_UPLOAD
```

Scene-level mixed voice providers are not supported in v1.0.

---

## 7. Image Providers

Image providers may be used for:

- Thumbnail generation
- Scene images
- Image-to-video source images
- Backgrounds
- Illustrations
- Packaging assets

Possible providers include:

```text
OpenAI Images
Google image-generation services
Ideogram
Stable Diffusion-compatible providers
Future providers
```

Manual upload, local images, stock images, and extracted video frames must
remain available even when no image API is configured.

---

## 8. Stock Providers

Stock providers may supply:

- Stock video
- Stock images
- Music
- Sound effects

Possible providers include:

```text
Pexels
Pixabay
Storyblocks
Envato
Other licensed media services
```

In Hybrid visual mode, the system must search the Local Library first.

Stock search begins only after explicit user approval.

---

## 9. Music Providers

Music providers may supply:

- Background music
- Intro music
- Outro music
- Mood-specific tracks
- AI-generated music

The system must support:

```text
Manual Upload
Local Music Library
Stock Music
AI Music Provider
No Music
```

Every music asset should include licensing information where available.

---

## 10. Sound-Effect Providers

Sound-effect providers may supply:

- Ambience
- Impacts
- Footsteps
- Weather sounds
- Transitions
- Mechanical sounds
- Environmental effects

Supported source strategies:

```text
Manual Upload
Local SFX Library
Stock SFX
AI-generated SFX
None
```

Sound effects remain separate from background music.

---

## 11. Upload Providers

Upload providers publish completed projects.

Supported platform targets:

```text
YouTube
Facebook
TikTok
Instagram
```

Every upload provider must validate:

- Final video path
- Packaging approval
- Upload metadata
- Thumbnail path where required
- Policy approval
- Upload readiness
- Authentication state

Prototype or Quick Mode output must never be uploaded automatically.

---

## 12. Provider Profiles

One provider may have multiple profiles.

Example:

```text
Google Veo
├── Personal Account
├── Business Account
└── Backup Account
```

Another example:

```text
ElevenLabs
├── Main Profile
├── Client Profile
└── Backup Profile
```

Each profile has its own:

- Credentials
- Model
- Priority
- Budget
- Quota
- Region
- Health state
- Enabled state

---

## 13. Provider Profile Fields

Every provider profile may store:

```text
Profile ID
Provider Category
Provider Name
Profile Name
Enabled
Priority
Default Model
Base URL
Region
Organization ID
Project ID
Secret Reference
Daily Budget
Monthly Budget
Per-Request Limit
Per-Video Limit
Rate Limit
Timeout
Maximum Retries
Fallback Order
Health Status
Last Health Check
Last Successful Request
Last Failure
Usage Statistics
Metadata
```

Not every provider requires every field.

Provider-specific fields may be stored in validated configuration metadata.

---

## 14. Multiple API Keys

A provider profile may support one or more credentials where the provider's
terms and technical design permit it.

Example:

```text
Provider Profile
├── Primary Credential
├── Secondary Credential
└── Backup Credential
```

Credential switching must not be used to evade provider restrictions,
billing requirements, quotas, or terms of service.

Credential selection may be based on:

- Enabled state
- Validity
- Approved fallback order
- Remaining configured quota
- Health status

---

## 15. Secret Storage

API keys must never be stored as plain text in normal configuration tables.

Required flow:

```text
Provider Settings UI
        ↓
Backend Validation
        ↓
Encryption Service
        ↓
Encrypted Secret Store
        ↓
Secret Reference
        ↓
Provider Execution
```

Provider profiles store only a secret reference.

---

## 16. Secret Display Rules

The User Interface must never show the complete saved secret.

Example:

```text
sk-proj-••••••••••••7K4P
```

Available actions:

```text
Test Connection
Replace Credential
Disable Credential
Delete Credential
```

The complete existing secret must not be returned to the frontend.

---

## 17. Security Rules

1. API secrets must not appear in logs.
2. API secrets must not be committed to Git.
3. API secrets must not be included in error messages.
4. API secrets must not be stored in plain text.
5. Secret access must be limited to provider execution.
6. Provider configuration and credentials must be stored separately.
7. Sensitive values must be masked in the User Interface.
8. Credential changes should be auditable.
9. Deleted credentials must no longer be available to provider execution.
10. Exported project settings must not contain secrets.

---

## 18. Provider Registry

The Provider Registry contains available provider implementations.

Example:

```text
Provider Registry
├── OpenAIProvider
├── AnthropicProvider
├── ManualUploadProvider
├── StockFootageProvider
├── ImageToVideoProvider
├── ElevenLabsProvider
└── YouTubeUploadProvider
```

Registration identifies which implementation supports which provider
category and capabilities.

---

## 19. Provider Factory

The Provider Factory creates configured provider instances.

```text
Provider Profile
        ↓
Provider Factory
        ↓
Provider Adapter
        ↓
Configured Provider Instance
```

The Factory may inject:

- Secret
- Model
- Base URL
- Region
- Timeout
- Retry policy
- Provider-specific settings

Workflows must not construct external SDK clients directly.

---

## 20. Provider Selection Service

The Provider Selection Service chooses a provider profile for one operation.

Possible selection inputs:

```text
Provider Category
Required Capability
Explicit User Choice
Preferred Provider
Priority
Health State
Budget
Quota
Quality Mode
Production Mode
Fallback Policy
```

The selection result must be recorded.

---

## 21. Manual Provider Selection

The user may explicitly select a provider.

Example:

```text
Voice Provider:
ElevenLabs Main
```

When a provider is explicitly selected and locked, automatic selection must
not silently replace it.

If the selected provider is unavailable, the system should:

- Pause for user action
- Or use an approved fallback policy

The behavior must be visible to the user.

---

## 22. Automatic Provider Selection

When Auto Select is enabled, the system checks:

```text
Enabled?
    ↓
Healthy?
    ↓
Supports Required Capability?
    ↓
Within Budget?
    ↓
Quota Available?
    ↓
Highest Valid Priority
```

The system must record why a provider was selected.

---

## 23. Provider Priority

Lower numeric values represent higher priority.

Example:

```text
Priority 1 — Primary
Priority 2 — Secondary
Priority 3 — Backup
```

Two profiles may not share the same effective priority within one strict
fallback chain unless a tie-breaking rule exists.

---

## 24. Fallback Behavior

Fallback may occur when:

- Provider is unhealthy
- Provider times out
- Provider returns a retryable error
- Configured budget is insufficient
- Configured quota is unavailable
- Required capability is unsupported

Example:

```text
Veo Main
    ↓ failure
Kling Backup
    ↓ failure
Manual Upload Required
```

Fallback must not happen silently.

The Stage Result must record:

- Original provider
- Failure reason
- Fallback provider
- Retry count
- Final provider
- Additional cost

---

## 25. Retry Policy

Each provider profile may define:

```text
Maximum Retries
Initial Delay
Maximum Delay
Backoff Strategy
Retryable Errors
Non-Retryable Errors
```

Authentication errors and invalid requests should normally not be retried
without correction.

Retries must respect the configured budget.

---

## 26. Health Checks

Provider profiles may support connection tests.

Health states:

```text
Unknown
Healthy
Degraded
Unhealthy
Disabled
Misconfigured
```

Health checks may validate:

- Credential presence
- Authentication
- API availability
- Model availability
- Basic request capability
- Account or quota status when supported

A health check must avoid expensive generation whenever a lightweight
provider endpoint is available.

---

## 27. Test Connection

The Provider Center User Interface must provide:

```text
Test Connection
```

The result may show:

```text
Connected
Authentication Failed
Model Not Available
Quota Unavailable
Timeout
Configuration Invalid
Provider Unreachable
```

The test must not expose secrets.

---

## 28. Budget Controls

Provider profiles may define:

```text
Daily Budget
Monthly Budget
Per-Video Budget
Per-Request Budget
Maximum Retry Cost
```

Budget limits may apply at:

```text
Global Level
Provider Category
Provider Profile
Project
Video Job
Pipeline Stage
Scene
```

The system must stop or ask for approval before exceeding a hard budget.

---

## 29. Usage Tracking

The Provider Center may track:

```text
Requests
Successful Requests
Failed Requests
Retries
Input Usage
Output Usage
Credits Consumed
Estimated Cost
Confirmed Cost
Average Latency
Last Used
```

Usage data must clearly distinguish estimates from provider-confirmed
billing data.

---

## 30. Provider Capabilities

Provider adapters should declare supported capabilities.

Examples:

```text
Text Generation
Structured JSON
Voice Generation
Voice Cloning
Image Generation
Image Editing
Text-to-Video
Image-to-Video
Stock Search
Media Download
Upload
Scheduling
```

Provider selection must verify capability compatibility.

---

## 31. Provider Models

A provider profile may expose multiple models.

Example:

```text
Provider
├── Fast Model
├── Standard Model
└── Premium Model
```

The user may select:

```text
Default Model
Operation-Specific Model
Auto Model Selection
```

Model selection must be stored with execution results.

---

## 32. Quality Modes

Provider selection may respond to Project quality settings.

Example:

```text
Draft
    ↓
Fast or low-cost provider

Premium
    ↓
Higher-quality provider

Ultra
    ↓
Highest approved quality profile
```

Quality mode does not override hard budget or user-locked provider choices
without approval.

---

## 33. Dry-Run Providers

Every external provider category should support a Dry-Run implementation
where practical.

Dry-Run providers allow:

- Development without API keys
- Automated tests
- Pipeline validation
- Cost-free demonstrations
- Failure simulation

Dry-Run output must be clearly marked as non-production output.

---

## 34. Provider User Interface

Suggested navigation:

```text
Settings
    ↓
Provider Center
        ├── LLM
        ├── Video
        ├── Voice
        ├── Images
        ├── Stock
        ├── Music
        ├── Sound Effects
        └── Upload
```

Each category page may display:

```text
Profile Name
Provider
Enabled
Priority
Model
Health
Budget
Usage
Last Used
Actions
```

---

## 35. Add Provider Flow

```text
Open Provider Center
        ↓
Choose Category
        ↓
Choose Provider Type
        ↓
Enter Profile Name
        ↓
Enter Required Configuration
        ↓
Add Credential
        ↓
Test Connection
        ↓
Set Priority and Budget
        ↓
Enable Profile
```

A profile should not become active until required validation passes, unless
the user explicitly saves it as disabled or incomplete.

---

## 36. Edit Provider Flow

The user may change:

- Profile name
- Enabled state
- Priority
- Model
- Limits
- Timeout
- Retry policy
- Fallback behavior
- Non-secret provider settings

Replacing a credential must create or update the encrypted secret without
displaying the previous full secret.

---

## 37. Delete Provider Flow

Before deletion, the system should check:

- Whether the profile is used as a default
- Whether projects reference it
- Whether it belongs to a fallback chain
- Whether active jobs are using it

Deletion may be blocked or require explicit confirmation.

Historical Stage Results should retain the deleted provider's identifying
metadata without retaining its secret.

---

## 38. Project-Level Provider Preferences

A Project Specification may define preferred profiles.

Example:

```text
LLM:
OpenAI Main

Voice:
ElevenLabs Main

Stock:
Pexels

Image:
Image Provider A
```

It may also use:

```text
Auto Select
```

Project preferences override global defaults but remain subject to health,
budget, capability, and enabled-state validation.

---

## 39. Stage-Level Provider Selection

A Pipeline Stage may request a provider category and capability.

Example:

```text
Title Generation Stage
Category: LLM
Capability: Structured Text Generation
```

Another example:

```text
Thumbnail Generation Stage
Category: Image
Capability: Image Generation
```

The Stage must receive the selected provider through the Stage Context or a
Provider Resolver service.

---

## 40. Scene-Level Provider Override

Scene-level provider selection may be supported for video and image
generation.

Example:

```text
Scene 1 — Manual Upload
Scene 2 — Stock Provider
Scene 3 — Image-to-Video Provider
Scene 4 — Future AI Video Provider
```

Automatic AI video providers remain disabled in the initial active visual
workflow.

---

## 41. Packaging Provider Integration

Packaging-related operations may use:

```text
LLM Providers
Image Providers
Stock Image Providers
SEO Data Providers
```

The Provider Center must support separate preferences for:

- Title generation
- Description generation
- Keyword generation
- Thumbnail generation
- Thumbnail analysis
- Future SEO data

Generated estimates must not be presented as verified external SEO data.

---

## 42. Upload Provider Authentication

Upload providers may use OAuth or other provider-supported authentication.

Upload credentials and refresh tokens must use secure secret storage.

The system must support:

```text
Connect Account
Reconnect Account
Test Account
Disable Account
Disconnect Account
```

The User Interface must show the connected account identity without
displaying sensitive tokens.

---

## 43. Persistence

Provider configuration persistence should separate:

```text
Provider Profile
Provider Settings
Secret Reference
Health History
Usage Records
Budget Records
```

Initial database target:

```text
SQLite
```

Future target:

```text
PostgreSQL or managed cloud database
```

---

## 44. Suggested Domain Models

Future backend models may include:

```text
ProviderCategory
ProviderProfile
ProviderCredentialReference
ProviderCapability
ProviderHealthResult
ProviderSelectionRequest
ProviderSelectionResult
ProviderUsageRecord
ProviderBudgetConfig
ProviderRetryPolicy
ProviderFallbackRule
```

Exact implementation may be split into multiple files.

---

## 45. Suggested Services

Future backend services may include:

```text
ProviderConfigService
ProviderRegistry
ProviderFactory
ProviderSelectionService
ProviderHealthService
ProviderUsageService
ProviderBudgetService
SecretEncryptionService
SecretStore
```

Each service must have one primary responsibility.

---

## 46. Audit Events

Important provider events should be auditable:

```text
Profile Created
Profile Updated
Credential Replaced
Profile Enabled
Profile Disabled
Connection Tested
Provider Selected
Fallback Used
Budget Blocked
Profile Deleted
```

Audit records must not contain secrets.

---

## 47. Error Handling

Provider errors should be normalized into internal error categories.

Suggested categories:

```text
Authentication Error
Authorization Error
Configuration Error
Rate Limit
Quota Exhausted
Budget Exceeded
Timeout
Provider Unavailable
Capability Unsupported
Invalid Request
Provider Response Error
Unknown Provider Error
```

Pipeline Stages should not depend on provider-specific exception classes.

---

## 48. Logging Rules

Provider logs may include:

- Provider name
- Profile ID
- Operation
- Model
- Status
- Latency
- Retry count
- Estimated cost
- Error category

Provider logs must not include:

- API keys
- Access tokens
- Refresh tokens
- Secret payloads
- Full sensitive headers

---

## 49. Completion Criteria

The Provider Center is considered production-ready when:

- Multiple profiles can be stored per category
- Secrets are encrypted
- Profiles can be tested
- Profiles can be enabled and disabled
- Priority and fallback work
- Health is visible
- Budget limits are enforced
- Usage is recorded
- Provider selection is auditable
- No workflow hardcodes an external provider
- Manual and Dry-Run workflows remain available

---

## 50. Architecture Rules

1. No API is hardcoded.
2. Multiple providers may exist in every category.
3. Multiple profiles may exist for one provider.
4. Provider configuration and secrets remain separate.
5. Secrets are encrypted and masked.
6. Providers are resolved through Registry and Factory layers.
7. User-locked choices are not silently replaced.
8. Fallback actions are recorded.
9. Budget limits are checked before expensive calls.
10. Provider errors are normalized.
11. Manual workflows remain available without APIs.
12. Dry-Run providers remain available for development and testing.
13. Provider-specific SDKs must not be called directly by Pipeline Stages.
14. Provider selection results must be recorded in Stage Results.
15. Deleted providers must not remove historical execution metadata.