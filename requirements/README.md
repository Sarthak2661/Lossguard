# Dependency locks

Each image installs one fully resolved `*.lock` file with `--require-hashes`, then installs the
local LossGuard package with `pip install --no-build-isolation --no-deps -e .`. The editable install makes `lossguard`,
`apps`, `ml`, and `monitoring` importable without modifying `sys.path`, while `--no-deps` prevents
the package metadata from bypassing the lock.

Regenerate all locks with Python 3.12 and uv 0.12.5:

```powershell
python -m pip install "uv==0.12.5"
Get-ChildItem requirements/*.in | ForEach-Object {
    uv pip compile --universal --python-version 3.12 --generate-hashes `
        --custom-compile-command "uv pip compile --universal --python-version 3.12 --generate-hashes" `
        --output-file ($_.FullName -replace '\.in$', '.lock') $_.FullName
}
```

```bash
python -m pip install "uv==0.12.5"
for input in requirements/*.in; do
  uv pip compile --universal --python-version 3.12 --generate-hashes \
    --custom-compile-command "uv pip compile --universal --python-version 3.12 --generate-hashes" \
    --output-file "${input%.in}.lock" "$input"
done
```

Review and test the resulting version changes before committing them. The input files remain the
human-maintained dependency policy; the lockfiles are generated artifacts and must not be edited.
