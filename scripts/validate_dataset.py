from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

REQUIRED_COLUMNS = {
    "trans_date_trans_time",
    "cc_num",
    "merchant",
    "category",
    "amt",
    "city_pop",
    "dob",
    "trans_num",
    "lat",
    "long",
    "merch_lat",
    "merch_long",
    "is_fraud",
}


def validate_file(path: Path, expected: dict) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as raw:
        for chunk in iter(lambda: raw.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected["sha256"]:
        raise ValueError(f"{path.name}: SHA-256 does not match the committed manifest")

    rows = 0
    minimum = maximum = None
    with path.open("r", encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path.name}: missing required columns {sorted(missing)}")
        for row in reader:
            timestamp = row["trans_date_trans_time"]
            minimum = timestamp if minimum is None else min(minimum, timestamp)
            maximum = timestamp if maximum is None else max(maximum, timestamp)
            if row["is_fraud"] not in {"0", "1"}:
                raise ValueError(f"{path.name}: is_fraud must contain only 0 or 1")
            if float(row["amt"]) < 0 or not row["trans_num"]:
                raise ValueError(f"{path.name}: invalid amount or transaction identifier")
            rows += 1
    actual = {"rows": rows, "min_timestamp": minimum, "max_timestamp": maximum}
    for key, value in actual.items():
        if value != expected[key]:
            raise ValueError(f"{path.name}: expected {key}={expected[key]!r}, got {value!r}")
    return {"file": path.name, "sha256": digest.hexdigest(), **actual}


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate LossGuard dataset integrity and schema")
    parser.add_argument("--data-dir", default="dataset")
    parser.add_argument("--manifest", default="config/dataset_manifest.json")
    args = parser.parse_args()
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    results = [
        validate_file(Path(args.data_dir) / name, expected) for name, expected in manifest.items()
    ]
    print(json.dumps({"status": "ok", "files": results}, indent=2))


if __name__ == "__main__":
    main()
