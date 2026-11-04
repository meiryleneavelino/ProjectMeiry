import json
import os
from dataclasses import dataclass
from pathlib import Path

CHANNEL_LABEL = "Fabric fhir-channel"
POLICY_ID = "ConsentRequiredPolicy"


def _read(path: str) -> str:
    value = Path(path).read_text().strip()
    if len(value) < 24:
        raise RuntimeError(f"{path} must hold a token of at least 24 characters")
    return value


@dataclass(frozen=True)
class Settings:
    fhir_base: str
    gateway_url: str
    gateway_token: str
    api_token: str
    personas: dict
    exams: dict
    notice: str

    @classmethod
    def load(cls):
        config = json.loads(Path(os.environ.get("PERSONAS_FILE", Path(__file__).parent.parent / "config/personas.json")).read_text())
        return cls(fhir_base=os.environ.get("FHIR_BASE", "http://fhir-hapi:8080/fhir"),
                   gateway_url=os.environ.get("GATEWAY_URL", "http://fhir-gateway:8080"),
                   gateway_token=_read(os.environ.get("GATEWAY_TOKEN_FILE", "/run/secrets/fhir_gateway_token")),
                   api_token=_read(os.environ.get("API_TOKEN_FILE", "/run/secrets/fhir_api_token")),
                   personas=config["personas"], exams=config["exams"], notice=config["notice"])

    def persona(self, persona_id: str) -> dict:
        if persona_id not in self.personas:
            raise KeyError(persona_id)
        return {"id": persona_id, **self.personas[persona_id]}

    def pseudonym_of(self, reference: str):
        for persona_id, persona in self.personas.items():
            if persona["fhir"] == reference:
                return persona_id
        return None
