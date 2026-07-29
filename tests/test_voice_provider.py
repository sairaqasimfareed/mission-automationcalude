from src.providers.voice_provider import VoiceProvider


class DummyVoiceProvider(VoiceProvider):

    @property
    def provider_name(self) -> str:
        return "Dummy Voice"

    def health_check(self) -> bool:
        return True

    def generate_voice(
        self,
        text: str,
        voice: str,
    ) -> str:
        return "outputs/audio/test.wav"


provider = DummyVoiceProvider()

audio = provider.generate_voice(
    text="Hello world",
    voice="Narrator",
)

print("Provider:", provider.provider_name)
print("Healthy:", provider.health_check())
print("Audio:", audio)

assert provider.health_check() is True
assert audio.endswith(".wav")

print("Voice Provider tests completed successfully.")
