from __future__ import annotations

import shutil
import subprocess

from src.models.ffmpeg_config import (
    FFmpegCapabilities,
    FFmpegConfig,
    FFmpegHardwareAcceleration,
    FFmpegResolvedConfig,
    FFmpegVideoCodec,
)


class FFmpegCapabilityService:
    """Detect and resolve local FFmpeg runtime capabilities."""

    COMMAND_TIMEOUT_SECONDS = 30.0

    def detect(
        self,
        config: FFmpegConfig | None = None,
    ) -> FFmpegCapabilities:
        """Inspect local FFmpeg and ffprobe binaries."""

        resolved_config = config or FFmpegConfig()

        ffmpeg_path = self._resolve_binary(resolved_config.ffmpeg_path)

        ffprobe_path = self._resolve_binary(resolved_config.ffprobe_path)

        ffmpeg_available = ffmpeg_path is not None

        ffprobe_available = ffprobe_path is not None

        ffmpeg_version: str | None = None
        ffprobe_version: str | None = None

        encoders: set[str] = set()
        decoders: set[str] = set()
        filters: set[str] = set()
        hardware_accelerators: set[str] = set()

        if ffmpeg_path is not None:
            ffmpeg_version = self._detect_version(ffmpeg_path)

            encoders = self._parse_component_names(
                self._run(
                    [
                        ffmpeg_path,
                        "-hide_banner",
                        "-encoders",
                    ]
                )
            )

            decoders = self._parse_component_names(
                self._run(
                    [
                        ffmpeg_path,
                        "-hide_banner",
                        "-decoders",
                    ]
                )
            )

            filters = self._parse_component_names(
                self._run(
                    [
                        ffmpeg_path,
                        "-hide_banner",
                        "-filters",
                    ]
                )
            )

            hardware_accelerators = self._parse_hardware_accelerators(
                self._run(
                    [
                        ffmpeg_path,
                        "-hide_banner",
                        "-hwaccels",
                    ]
                )
            )

        if ffprobe_path is not None:
            ffprobe_version = self._detect_version(ffprobe_path)

        return FFmpegCapabilities(
            ffmpeg_available=(ffmpeg_available),
            ffprobe_available=(ffprobe_available),
            ffmpeg_path=ffmpeg_path,
            ffprobe_path=ffprobe_path,
            ffmpeg_version=(ffmpeg_version),
            ffprobe_version=(ffprobe_version),
            encoders=encoders,
            decoders=decoders,
            filters=filters,
            hardware_accelerators=(hardware_accelerators),
            metadata={
                "encoder_count": len(encoders),
                "decoder_count": len(decoders),
                "filter_count": len(filters),
                "hardware_accelerator_count": len(hardware_accelerators),
            },
        )

    def resolve(
        self,
        config: FFmpegConfig | None = None,
    ) -> FFmpegResolvedConfig:
        """Resolve requested preferences against detected capabilities."""

        resolved_config = config or FFmpegConfig()

        capabilities = self.detect(resolved_config)

        if not capabilities.ready:
            raise RuntimeError(
                "FFmpeg runtime is not ready. " "Both ffmpeg and ffprobe are required."
            )

        warnings: list[str] = []

        selected_video_codec = self._select_video_codec(
            config=resolved_config,
            capabilities=capabilities,
            warnings=warnings,
        )

        selected_audio_codec = str(resolved_config.audio_codec.value)

        if not capabilities.has_encoder(selected_audio_codec):
            raise RuntimeError(
                "Requested FFmpeg audio codec is not "
                f"available: {selected_audio_codec}."
            )

        selected_hardware_acceleration = self._select_hardware_acceleration(
            config=resolved_config,
            capabilities=capabilities,
            selected_video_codec=(selected_video_codec),
            warnings=warnings,
        )

        return FFmpegResolvedConfig(
            config=resolved_config,
            capabilities=capabilities,
            selected_video_codec=(selected_video_codec),
            selected_audio_codec=(selected_audio_codec),
            selected_hardware_acceleration=(selected_hardware_acceleration),
            warnings=warnings,
            metadata={
                "resolved_automatically": (
                    resolved_config.video_codec == FFmpegVideoCodec.AUTO
                ),
            },
        )

    @staticmethod
    def _resolve_binary(
        executable: str,
    ) -> str | None:
        """Resolve executable name or explicit path."""

        cleaned = executable.strip()

        if not cleaned:
            return None

        return shutil.which(cleaned)

    def _detect_version(
        self,
        executable: str,
    ) -> str | None:
        """Return first FFmpeg version line."""

        output = self._run(
            [
                executable,
                "-version",
            ]
        )

        if not output:
            return None

        lines = output.splitlines()

        if not lines:
            return None

        first_line = lines[0].strip()

        return first_line or None

    def _run(
        self,
        command: list[str],
    ) -> str:
        """Execute a short FFmpeg capability command."""

        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self.COMMAND_TIMEOUT_SECONDS,
            check=False,
        )

        combined_parts: list[str] = []

        if completed.stdout:
            combined_parts.append(completed.stdout)

        if completed.stderr:
            combined_parts.append(completed.stderr)

        combined = "\n".join(combined_parts)

        if completed.returncode != 0:
            message = "FFmpeg capability command failed: " + " ".join(command)

            if combined.strip():
                message += "\n" + combined.strip()

            raise RuntimeError(message)

        return combined

    @staticmethod
    def _parse_component_names(
        output: str,
    ) -> set[str]:
        """Parse encoder, decoder, or filter table names."""

        names: set[str] = set()

        for raw_line in output.splitlines():
            line = raw_line.strip()

            if not line:
                continue

            if line.startswith("--"):
                continue

            if "=" in line:
                continue

            if (
                line.startswith("Encoders:")
                or line.startswith("Decoders:")
                or line.startswith("Filters:")
            ):
                continue

            parts = line.split()

            if len(parts) < 2:
                continue

            flags = parts[0]

            valid_flags = all(
                character.isalpha() or character in ".|" for character in flags
            )

            if not valid_flags:
                continue

            candidate = parts[1].strip().lower()

            if candidate:
                names.add(candidate)

        return names

    @staticmethod
    def _parse_hardware_accelerators(
        output: str,
    ) -> set[str]:
        """Parse `ffmpeg -hwaccels` output."""

        accelerators: set[str] = set()

        found_heading = False

        for raw_line in output.splitlines():
            line = raw_line.strip()

            if not line:
                continue

            if line.lower() == "hardware acceleration methods:":
                found_heading = True
                continue

            if found_heading:
                accelerators.add(line.lower())

        return accelerators

    @staticmethod
    def _select_video_codec(
        *,
        config: FFmpegConfig,
        capabilities: FFmpegCapabilities,
        warnings: list[str],
    ) -> str:
        """Select requested or safe fallback video encoder."""

        requested = config.video_codec

        if requested != FFmpegVideoCodec.AUTO:
            codec = str(requested.value)

            if not capabilities.has_encoder(codec):
                raise RuntimeError(
                    "Requested FFmpeg video codec is not " f"available: {codec}."
                )

            return codec

        h264_nvenc = str(FFmpegVideoCodec.H264_NVENC.value)

        libx264 = str(FFmpegVideoCodec.LIBX264.value)

        if capabilities.has_encoder(
            h264_nvenc
        ) and capabilities.has_hardware_accelerator("cuda"):
            return h264_nvenc

        if capabilities.has_encoder(libx264):
            warnings.append(
                "Hardware H.264 encoding was not selected; "
                "using libx264 CPU encoding."
            )

            return libx264

        raise RuntimeError("No supported H.264 FFmpeg encoder " "is available.")

    @staticmethod
    def _select_hardware_acceleration(
        *,
        config: FFmpegConfig,
        capabilities: FFmpegCapabilities,
        selected_video_codec: str,
        warnings: list[str],
    ) -> str | None:
        """Resolve hardware acceleration preference."""

        preference = config.hardware_acceleration

        if preference == FFmpegHardwareAcceleration.NONE:
            return None

        if preference != FFmpegHardwareAcceleration.AUTO:
            requested_acceleration = str(preference.value)

            if not capabilities.has_hardware_accelerator(requested_acceleration):
                raise RuntimeError(
                    "Requested FFmpeg hardware "
                    "acceleration is unavailable: "
                    f"{requested_acceleration}."
                )

            return requested_acceleration

        nvenc_codecs = {
            str(FFmpegVideoCodec.H264_NVENC.value),
            str(FFmpegVideoCodec.HEVC_NVENC.value),
        }

        if selected_video_codec in nvenc_codecs:
            if capabilities.has_hardware_accelerator("cuda"):
                return "cuda"

            warnings.append(
                "NVENC encoder is available but CUDA "
                "hardware acceleration was not detected."
            )

        return None
