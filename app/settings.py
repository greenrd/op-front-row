import json
import os
from pathlib import Path

from pydantic import BaseModel

DATA_DIR = Path(os.environ.get("FRONT_ROW_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
SETTINGS_PATH = DATA_DIR / "settings.json"


class Settings(BaseModel):
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"

    ig_app_id: str = ""
    ig_app_secret: str = ""
    ig_access_token: str = ""
    ig_username: str = ""
    ig_user_id: str = ""

    public_base_url: str = ""
    demo_mode: bool = False
    import_mode: bool = False

    def llm_configured(self) -> bool:
        return bool(self.llm_base_url.strip() and self.llm_api_key.strip())

    def instagram_configured(self) -> bool:
        return bool(self.ig_access_token.strip())

    def public(self) -> dict:
        d = self.model_dump()
        d["llm_api_key"] = _mask(self.llm_api_key)
        d["ig_app_secret"] = _mask(self.ig_app_secret)
        d["ig_access_token"] = _mask(self.ig_access_token)
        d["llm_configured"] = self.llm_configured()
        d["instagram_configured"] = self.instagram_configured()
        return d


class SettingsUpdate(BaseModel):
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    ig_app_id: str | None = None
    ig_app_secret: str | None = None
    ig_access_token: str | None = None
    public_base_url: str | None = None
    demo_mode: bool | None = None
    import_mode: bool | None = None


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return value[:4] + "*" * 8 + value[-4:]


def load_settings() -> Settings:
    if SETTINGS_PATH.exists():
        return Settings.model_validate(json.loads(SETTINGS_PATH.read_text()))
    return Settings()


def save_settings(settings: Settings) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings.model_dump(), indent=2))


def apply_update(settings: Settings, update: SettingsUpdate) -> Settings:
    data = settings.model_dump()
    for key, value in update.model_dump(exclude_none=True).items():
        if key in ("llm_api_key", "ig_app_secret", "ig_access_token"):
            value = value.strip()
            if not value or "*" in value:
                continue  # left blank or masked value echoed back from the UI; keep the stored secret
        data[key] = value
    return Settings.model_validate(data)
