from __future__ import annotations

from diskdoctor.providers.docker import DockerProvider
from diskdoctor.providers.huggingface import HuggingFaceProvider
from diskdoctor.providers.large_files import LargeFilesProvider
from diskdoctor.providers.lm_studio import LMStudioProvider
from diskdoctor.providers.ollama import OllamaProvider
from diskdoctor.providers.venv import VenvProvider

CLASS_PROVIDERS = [
    DockerProvider,
    HuggingFaceProvider,
    LargeFilesProvider,
    LMStudioProvider,
    OllamaProvider,
    VenvProvider,
]


def test_every_class_provider_has_details_under_300_chars():
    for cls in CLASS_PROVIDERS:
        assert cls.details is not None, f"{cls.__name__} missing details"
        assert isinstance(cls.details, str)
        assert 0 < len(cls.details) <= 300, (
            f"{cls.__name__}.details length {len(cls.details)} not in (0, 300]"
        )
