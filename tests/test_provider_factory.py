from src.models.provider_profile import (
    ProviderCategory,
    ProviderHealthStatus,
    ProviderProfile,
)
from src.services.factory.provider_factory import (
    ImageProvider,
    LLMProvider,
    ProviderFactory,
    VideoProvider,
    VoiceProvider,
)
from src.services.registry.provider_registry import (
    ProviderRegistry,
)
from src.services.secrets.provider_secret_manager import (
    InMemorySecretStore,
    ProviderSecretManager,
)

store = InMemorySecretStore()
secret_manager = ProviderSecretManager(store)


llm_secret = secret_manager.create_secret(
    profile_id="openai-main",
    secret_value="sk-openai-123456789",
)

video_secret = secret_manager.create_secret(
    profile_id="veo-main",
    secret_value="veo-secret-123456789",
)

voice_secret = secret_manager.create_secret(
    profile_id="eleven-main",
    secret_value="voice-secret-123456789",
)

image_secret = secret_manager.create_secret(
    profile_id="image-main",
    secret_value="image-secret-123456789",
)


registry = ProviderRegistry(
    profiles=[
        ProviderProfile(
            profile_id="openai-main",
            display_name="OpenAI",
            provider_name="OpenAI",
            category=ProviderCategory.LLM,
            enabled=True,
            secret_reference=llm_secret.secret_reference,
            health_status=ProviderHealthStatus.HEALTHY,
        ),
        ProviderProfile(
            profile_id="veo-main",
            display_name="VEO",
            provider_name="Google",
            category=ProviderCategory.VIDEO,
            enabled=True,
            secret_reference=video_secret.secret_reference,
            health_status=ProviderHealthStatus.HEALTHY,
        ),
        ProviderProfile(
            profile_id="eleven-main",
            display_name="ElevenLabs",
            provider_name="ElevenLabs",
            category=ProviderCategory.VOICE,
            enabled=True,
            secret_reference=voice_secret.secret_reference,
            health_status=ProviderHealthStatus.HEALTHY,
        ),
        ProviderProfile(
            profile_id="image-main",
            display_name="Image",
            provider_name="Image Provider",
            category=ProviderCategory.IMAGE,
            enabled=True,
            secret_reference=image_secret.secret_reference,
            health_status=ProviderHealthStatus.HEALTHY,
        ),
    ]
)

factory = ProviderFactory(
    registry=registry,
    secret_manager=secret_manager,
)


llm = factory.create("openai-main")
video = factory.create("veo-main")
voice = factory.create("eleven-main")
image = factory.create("image-main")


print(type(llm).__name__)
print(type(video).__name__)
print(type(voice).__name__)
print(type(image).__name__)


assert isinstance(llm, LLMProvider)
assert isinstance(video, VideoProvider)
assert isinstance(voice, VoiceProvider)
assert isinstance(image, ImageProvider)

assert llm.instance.profile_id == "openai-main"
assert video.instance.profile_id == "veo-main"
assert voice.instance.profile_id == "eleven-main"
assert image.instance.profile_id == "image-main"

assert llm.api_key == "sk-openai-123456789"
assert video.api_key == "veo-secret-123456789"

try:
    factory.create("missing-provider")
except KeyError:
    print("Missing provider successfully blocked.")
else:
    raise AssertionError("Missing provider should fail.")

print("Provider Factory tests completed successfully.")
