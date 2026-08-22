from __future__ import annotations

import pytest
from pydantic import ValidationError

from lossguard.config import Settings
from scripts.bootstrap_env import GENERATED_KEYS, bootstrap, parse_env
from scripts.sync_postgres_password import sync_password

VALID_SETTINGS = {
    "postgres_password": "postgres-secret-with-24-characters",
    "database_url": "postgresql://lossguard:secret@localhost:55432/lossguard",
    "pii_hash_salt": "pii-salt-secret-with-24-characters",
    "scoring_api_key": "scoring-secret-with-24-characters",
    "admin_api_key": "admin-secret-different-24-characters",
}


def test_settings_accept_generated_distinct_secrets() -> None:
    settings = Settings(_env_file=None, **VALID_SETTINGS)

    assert settings.scoring_api_key != settings.admin_api_key


@pytest.mark.parametrize(
    "field",
    ["postgres_password", "pii_hash_salt", "scoring_api_key", "admin_api_key"],
)
def test_settings_reject_weak_secrets(field: str) -> None:
    values = {**VALID_SETTINGS, field: "change-this"}

    with pytest.raises(ValidationError, match=field):
        Settings(_env_file=None, **values)


def test_settings_reject_reused_api_keys() -> None:
    values = {**VALID_SETTINGS, "admin_api_key": VALID_SETTINGS["scoring_api_key"]}

    with pytest.raises(ValidationError, match="must be different"):
        Settings(_env_file=None, **values)


def test_bootstrap_generates_distinct_secrets_and_preserves_optional_values(tmp_path) -> None:
    env_path = tmp_path / ".env"
    bootstrap(env_path)
    lines, generated = parse_env(env_path.read_text(encoding="utf-8"))

    assert len({generated[key] for key in GENERATED_KEYS}) == len(GENERATED_KEYS)
    assert all(len(generated[key]) >= 24 for key in GENERATED_KEYS)
    env_path.write_text("\n".join(lines + ["OPENAI_API_KEY=keep-private-value"]) + "\n")

    bootstrap(env_path, rotate=True)
    _, rotated = parse_env(env_path.read_text(encoding="utf-8"))

    assert rotated["OPENAI_API_KEY"] == "keep-private-value"
    assert rotated["SCORING_API_KEY"] != generated["SCORING_API_KEY"]


def test_postgres_password_sync_keeps_secret_out_of_host_command_args(
    tmp_path, monkeypatch
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "POSTGRES_USER=lossguard\n"
        "POSTGRES_DB=lossguard\n"
        "POSTGRES_PASSWORD=private-generated-database-password\n",
        encoding="utf-8",
    )
    captured = {}

    def fake_run(command, **kwargs) -> None:
        captured["command"] = command
        captured.update(kwargs)

    monkeypatch.setattr("scripts.sync_postgres_password.subprocess.run", fake_run)
    sync_password(env_path)

    assert "private-generated-database-password" not in " ".join(captured["command"])
    assert (
        captured["env"]["LOSSGUARD_NEW_POSTGRES_PASSWORD"] == "private-generated-database-password"
    )
    assert captured["check"] is True
