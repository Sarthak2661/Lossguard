from __future__ import annotations

import argparse
import secrets
from pathlib import Path

GENERATED_KEYS = (
    "POSTGRES_PASSWORD",
    "PII_HASH_SALT",
    "SCORING_API_KEY",
    "ADMIN_API_KEY",
    "GRAFANA_ADMIN_PASSWORD",
    "GRAFANA_READER_PASSWORD",
)


def parse_env(text: str) -> tuple[list[str], dict[str, str]]:
    lines = text.splitlines()
    values: dict[str, str] = {}
    for line in lines:
        if line and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return lines, values


def replace_values(lines: list[str], replacements: dict[str, str]) -> str:
    output: list[str] = []
    seen: set[str] = set()
    for line in lines:
        key = line.split("=", 1)[0] if "=" in line else ""
        if key in replacements:
            output.append(f"{key}={replacements[key]}")
            seen.add(key)
        else:
            output.append(line)
    output.extend(f"{key}={value}" for key, value in replacements.items() if key not in seen)
    return "\n".join(output) + "\n"


def bootstrap(output_path: Path, rotate: bool = False) -> None:
    example_path = Path(__file__).resolve().parents[1] / ".env.example"
    if output_path.exists():
        if not rotate:
            raise FileExistsError(
                f"{output_path} already exists; use --rotate-core-secrets to preserve other values"
            )
        source_text = output_path.read_text(encoding="utf-8")
    else:
        source_text = example_path.read_text(encoding="utf-8")

    lines, values = parse_env(source_text)
    replacements = {key: secrets.token_urlsafe(32) for key in GENERATED_KEYS}
    postgres_user = values.get("POSTGRES_USER", "lossguard")
    postgres_db = values.get("POSTGRES_DB", "lossguard")
    postgres_port = values.get("POSTGRES_HOST_PORT", "55432")
    replacements["DATABASE_URL"] = (
        f"postgresql://{postgres_user}:{replacements['POSTGRES_PASSWORD']}"
        f"@localhost:{postgres_port}/{postgres_db}"
    )
    output_path.write_text(replace_values(lines, replacements), encoding="utf-8")
    output_path.chmod(0o600)
    print(f"Generated protected local configuration at {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate LossGuard local development secrets")
    parser.add_argument("--output", type=Path, default=Path(".env"))
    parser.add_argument(
        "--rotate-core-secrets",
        action="store_true",
        help="Rotate only LossGuard core secrets while preserving other .env values",
    )
    args = parser.parse_args()
    bootstrap(args.output, args.rotate_core_secrets)


if __name__ == "__main__":
    main()
