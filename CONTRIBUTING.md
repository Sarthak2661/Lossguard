# Contributing to LossGuard

## Code review guide

Before reviewing model behavior or dollar claims, read:

- [`docs/model-card.md`](docs/model-card.md) for training windows, calibration, final-test results,
  limitations, and artifact trust assumptions.
- [`docs/business-assumptions.md`](docs/business-assumptions.md) for every simulated cost and margin
  input used by the policy and dashboard.

Then review `src/lossguard/costs.py`, `ml/train.py`, and `apps/scoring_api/model_service.py` before
the UI. LossGuard is a retrospective decision simulator, not a payment authorization system.

## Development setup

Use Python 3.12. Install the hash-locked test environment first, then install the repository as an
editable package without re-resolving dependencies:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --require-hashes --no-deps -r requirements/test.windows.lock
python -m pip install --no-build-isolation --no-deps -e .
```

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes --no-deps -r requirements/test.lock
python -m pip install --no-build-isolation --no-deps -e .
```

Run `python -m ruff check .`, `python -m ruff format --check .`, and
`python -m pytest --cov --cov-report=term-missing --cov-fail-under=75` before opening a pull request.
Integration tests additionally require the Redpanda and PostgreSQL services described in the README.

## Container security

LossGuard-owned images run as numeric UID/GID `10001:10001`. On Linux, make `models/`, `reports/`,
and `analytics/dbt/` writable by that identity when running the trainer, monitor, or dbt tools.
The optional cAdvisor service is the sole intentional privileged-container exception because it
collects host container metrics; do not enable the observability profile on an untrusted host.

## Dependency changes

Edit the appropriate `requirements/*.in` policy file, regenerate all affected hash locks using
`requirements/README.md`, and include both input and lock changes in the pull request. Docker base
images and GitHub Actions are pinned by digest or commit SHA; version tags remain beside pins for
human readability and Dependabot discovery.
