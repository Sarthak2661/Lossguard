# Dependency locks

Each image installs one fully resolved Linux `*.lock` file with `--require-hashes`, then installs the
local LossGuard package with `pip install --no-build-isolation --no-deps -e .`. The editable install makes `lossguard`,
`apps`, `ml`, and `monitoring` importable without modifying `sys.path`, while `--no-deps` prevents
the package metadata from bypassing the lock.

Docker and CI target CPython 3.12 on x86-64 Linux. `test.windows.lock` is the equivalent Windows
developer lock; it avoids installing Linux-only XGBoost/NVIDIA packages on the host.

Regenerate all locks with Python 3.12 and uv 0.12.5:

```powershell
python -m pip install "uv==0.12.5"
Get-ChildItem requirements/*.in | ForEach-Object {
    uv pip compile --python-platform x86_64-unknown-linux-gnu --python-version 3.12 `
        --generate-hashes `
        --custom-compile-command "uv pip compile --python-platform x86_64-unknown-linux-gnu --python-version 3.12 --generate-hashes" `
        --output-file ($_.FullName -replace '\.in$', '.lock') $_.FullName
}
uv pip compile requirements/test.in --python-platform windows --python-version 3.12 `
    --generate-hashes `
    --custom-compile-command "uv pip compile --python-platform windows --python-version 3.12 --generate-hashes" `
    --output-file requirements/test.windows.lock
```

```bash
python -m pip install "uv==0.12.5"
for input in requirements/*.in; do
  uv pip compile --python-platform x86_64-unknown-linux-gnu --python-version 3.12 \
    --generate-hashes \
    --custom-compile-command "uv pip compile --python-platform x86_64-unknown-linux-gnu --python-version 3.12 --generate-hashes" \
    --output-file "${input%.in}.lock" "$input"
done
```

Review and test the resulting version changes before committing them. The input files remain the
human-maintained dependency policy; the lockfiles are generated artifacts and must not be edited.
