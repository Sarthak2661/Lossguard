from __future__ import annotations

import argparse
import os
import re
import subprocess
from pathlib import Path

try:
    from scripts.bootstrap_env import parse_env
except ModuleNotFoundError:  # Support the documented direct-script invocation.
    from bootstrap_env import parse_env

SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def sync_password(env_path: Path) -> None:
    _, values = parse_env(env_path.read_text(encoding="utf-8"))
    role = values.get("POSTGRES_USER", "lossguard")
    database = values.get("POSTGRES_DB", "lossguard")
    password = values["POSTGRES_PASSWORD"]
    if not SAFE_IDENTIFIER.fullmatch(role) or not SAFE_IDENTIFIER.fullmatch(database):
        raise ValueError("POSTGRES_USER and POSTGRES_DB must be simple PostgreSQL identifiers")

    command_env = os.environ.copy()
    command_env["LOSSGUARD_NEW_POSTGRES_PASSWORD"] = password
    command_env["LOSSGUARD_POSTGRES_ROLE"] = role
    command_env["LOSSGUARD_POSTGRES_DB"] = database
    subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "-e",
            "LOSSGUARD_NEW_POSTGRES_PASSWORD",
            "-e",
            "LOSSGUARD_POSTGRES_ROLE",
            "-e",
            "LOSSGUARD_POSTGRES_DB",
            "postgres",
            "sh",
            "-ec",
            'psql -U "$LOSSGUARD_POSTGRES_ROLE" -d "$LOSSGUARD_POSTGRES_DB" '
            '-v ON_ERROR_STOP=1 -v role_name="$LOSSGUARD_POSTGRES_ROLE" '
            '-v new_password="$LOSSGUARD_NEW_POSTGRES_PASSWORD"',
        ],
        input="ALTER ROLE :\"role_name\" PASSWORD :'new_password';\n",
        text=True,
        check=True,
        env=command_env,
    )
    print(f"Updated the PostgreSQL login for role {role!r} without recreating the volume")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Synchronize an existing PostgreSQL volume with the generated .env password"
    )
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    args = parser.parse_args()
    sync_password(args.env_file)


if __name__ == "__main__":
    main()
