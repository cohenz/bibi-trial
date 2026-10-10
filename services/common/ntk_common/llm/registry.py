"""ModelRegistry: which model plays which role, and the policy around it.

Policy (spec §23.5, §23.6, §30.1, build brief "שימוש במודלים"):
* no model name is hard-coded; every role is configured;
* a Lite / Flash-Lite class model may only be used for high-recall candidate
  extraction (role ``extractor``) — never for the final judicial
  classification or the final verification;
* the verifier should come from a different model family; when it does not
  (pilot with Gemini only) the registry reports ``single_family=True`` and
  the gates route every sensitive item and every judicial classification to
  human review instead of auto-publishing.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from ..config import Settings

ROLES = ("extractor", "mapper", "judicial_classifier", "verifier", "writer", "qa_relation", "embedder")
FINAL_ROLES = {"judicial_classifier", "verifier"}
_LITE_RE = re.compile(r"(?:^|[-_.])(?:lite|nano|mini|tiny|small)(?:$|[-_.])", re.I)


class ModelPolicyError(ValueError):
    pass


@dataclass(frozen=True)
class ModelSpec:
    role: str
    provider: str
    model_family: str
    model_id: str
    model_version: str | None = None
    temperature: float = 0.0
    is_lite: bool = False
    allowed_for_final: bool = False
    context_limit: int | None = None

    @property
    def registry_id(self) -> str:
        return f"{self.role}:{self.provider}:{self.model_id}"

    def to_row(self) -> dict:
        d = asdict(self)
        d["id"] = self.registry_id
        d["active"] = True
        return d


def family_of(provider: str, model_id: str) -> str:
    p = provider.lower()
    if p == "gemini" or model_id.lower().startswith("gemini"):
        return "google-gemini"
    if p in {"anthropic", "claude"} or model_id.lower().startswith("claude"):
        return "anthropic-claude"
    if p in {"openai"}:
        return "openai-gpt"
    if p == "mock":
        return "mock"
    return p


def is_lite_model(model_id: str) -> bool:
    return bool(_LITE_RE.search(model_id or ""))


class ModelRegistry:
    def __init__(self, specs: dict[str, ModelSpec]):
        self._specs = specs
        self.validate()

    @classmethod
    def from_settings(cls, s: Settings) -> ModelRegistry:
        provider = s.model_provider.lower()
        verifier_provider = (s.verifier_provider or provider).lower()

        def spec(role: str, model_id: str, prov: str) -> ModelSpec:
            if prov == "mock":
                model_id = model_id or f"mock-{role}"
            if not model_id:
                raise ModelPolicyError(f"no model configured for role {role!r} (set NTK_MODEL_{role.upper()})")
            lite = is_lite_model(model_id)
            return ModelSpec(
                role=role,
                provider=prov,
                model_family=family_of(prov, model_id),
                model_id=model_id,
                temperature=s.model_temperature,
                is_lite=lite,
                allowed_for_final=(role in FINAL_ROLES and not lite),
            )

        specs = {
            "extractor": spec("extractor", s.model_extractor, provider),
            "mapper": spec("mapper", s.model_mapper or s.model_writer, provider),
            "judicial_classifier": spec("judicial_classifier", s.model_judicial_classifier or s.model_mapper, provider),
            "writer": spec("writer", s.model_writer or s.model_mapper, provider),
            "qa_relation": spec("qa_relation", s.model_qa_relation or s.model_extractor, provider),
            "verifier": spec("verifier", s.model_verifier, verifier_provider),
            "embedder": spec("embedder", s.embedding_model, s.embedding_provider.lower()),
        }
        return cls(specs)

    def validate(self) -> None:
        for role in ROLES:
            if role not in self._specs:
                raise ModelPolicyError(f"role {role!r} missing from registry")
        for role in FINAL_ROLES:
            sp = self._specs[role]
            if sp.is_lite:
                raise ModelPolicyError(
                    f"{sp.model_id!r} is a Lite-class model and may not be used as the final {role} (spec §23.6)"
                )
        for role in ("mapper", "writer"):
            if self._specs[role].is_lite:
                raise ModelPolicyError(f"{self._specs[role].model_id!r} is Lite-class; role {role} requires a stronger model")

    def get(self, role: str) -> ModelSpec:
        return self._specs[role]

    @property
    def single_family(self) -> bool:
        return self._specs["verifier"].model_family == self._specs["writer"].model_family

    @property
    def uses_mock(self) -> bool:
        return any(sp.provider == "mock" for r, sp in self._specs.items() if r != "embedder")

    def rows(self) -> list[dict]:
        return [sp.to_row() for sp in self._specs.values()]

    def describe(self) -> dict:
        return {
            "roles": {r: {"provider": s.provider, "model_id": s.model_id, "family": s.model_family, "is_lite": s.is_lite}
                      for r, s in self._specs.items()},
            "single_family": self.single_family,
            "uses_mock": self.uses_mock,
        }
