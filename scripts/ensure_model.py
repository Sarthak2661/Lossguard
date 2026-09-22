from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import joblib

from lossguard.model_artifact import validate_bundle, verify_checksum


def artifact_is_valid(path: Path) -> bool:
    try:
        verify_checksum(path)
        validate_bundle(joblib.load(path))
        return True
    except (FileNotFoundError, OSError, ValueError):
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Train only when no valid model artifact exists")
    parser.add_argument("--input", required=True)
    parser.add_argument("--test-input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--metadata-output", required=True)
    parser.add_argument("--max-rows", default="300000")
    parser.add_argument("--max-test-rows", default="0")
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists() and Path(args.metadata_output).exists() and artifact_is_valid(output):
        print(f"Validated existing model artifact: {output}")
        return
    command = [
        sys.executable,
        "-m",
        "ml.train",
        "--input",
        args.input,
        "--test-input",
        args.test_input,
        "--output",
        args.output,
        "--metadata-output",
        args.metadata_output,
        "--max-rows",
        args.max_rows,
        "--max-test-rows",
        args.max_test_rows,
    ]
    subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
