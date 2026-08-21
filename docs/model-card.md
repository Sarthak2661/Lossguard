# LossGuard model card

## Current local artifact

- Model version: `xgb-20260811T122124Z`
- Training command: `python -m ml.train --max-rows 300000`
- Data: first 300,000 timestamp-sorted rows of `fraudTrain.csv`
- Split: first 240,000 rows for training; last 60,000 rows for validation
- Validation fraud rate: 0.625%
- ROC AUC: 0.9972
- Average precision: 0.8840
- Best validation F1 threshold: 0.9292
- Cost-optimized global thresholds: verify at 0.3500, decline at 0.9500
- Simulated global validation cost: $18,420.82

The machine-readable details, category thresholds, feature names, and exact timestamp are stored in
`models/model_metadata.json`. The binary model bundle is intentionally ignored by Git and can be
recreated with the documented training command.

## Intended use

This model supports a local portfolio simulation of approve, verify, and decline policies. It is
appropriate for demonstrating cost-sensitive decision design, streaming model serving, explainability,
and analytical reporting. It is not approved for real payment authorization or customer treatment.

## Evaluation caveats

- These figures are held-out validation results from the first 300,000 training rows, not results on
  the untouched `fraudTest.csv` file.
- The source data is synthetic and its fraud behavior may not represent a real merchant.
- Threshold results depend directly on documented margin, reacquisition, verification, and abandonment
  assumptions.
- A high ROC AUC does not establish probability calibration or causal business savings.
- Production use would require delayed-label handling, calibration, fairness/privacy review, drift
  monitoring, authentication, operational capacity constraints, and independent evaluation.
