import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    state_root: Path
    name: str = "Meirylene Avelino"
    organization: str = "TUDELFT"
    pseudonym: str = "researcher-local-001"
    training_url: str = "http://127.0.0.1:8096/api/v1/ml"
    training_token_file: Path = ROOT.parent / "configuration/federated-training/.local/api-token"
    ledger_url: str = "http://127.0.0.1:8098"
    ledger_token_file: Path = ROOT / ".local/ledger/gateway-token"

    @classmethod
    def load(cls):
        source = Path(os.environ.get("HORUS_SETTINGS", ROOT / "config/settings.example.json"))
        config = json.loads(source.read_bytes())
        researcher = config["researcher"]
        return cls(Path(os.environ.get("HORUS_STATE_ROOT", ROOT / ".local")),
                   researcher["name"], researcher["organization"], researcher["pseudonym"],
                   os.environ.get("HORUS_TRAINING_URL", config["training_url"]),
                   Path(os.environ.get("HORUS_TRAINING_TOKEN_FILE", cls.training_token_file)),
                   os.environ.get("HORUS_LEDGER_URL", config.get("ledger_url", cls.ledger_url)),
                   Path(os.environ.get("HORUS_LEDGER_TOKEN_FILE", cls.ledger_token_file)))

    def token(self):
        self.state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self.state_root / "api-token"
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as target:
                target.write(secrets.token_urlsafe(32))
        except FileExistsError:
            pass
        return path.read_text().strip()
