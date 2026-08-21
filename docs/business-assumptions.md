# Business and simulation assumptions

The Sparkov labels and transaction attributes are simulated. LossGuard adds the following transparent
business assumptions so decisions can be expressed in dollars. These values are configurable and are
not presented as merchant-specific facts.

## Category gross-margin assumptions

| Category group | Margin |
|---|---:|
| grocery, gas | 8–12% |
| shopping, misc, home | 22–32% |
| food, entertainment, personal care, health, kids/pets | 28–38% |
| travel | 18% |

Exact mappings live in `src/lossguard/constants.py` and are versioned with the model.

## Customer lifetime-value bands

The source has no LTV. A stable salted hash of the source card identifier assigns a synthetic band:
50% `low`, 35% `medium`, and 15% `high`. Only the hash-derived customer ID and band leave the
producer. Reacquisition costs are assumed to be $15, $45, and $120 respectively.

## Decision costs

- `approve`: if fraudulent, simulated cost is transaction amount; otherwise zero.
- `verify`: $3 operational cost, 85% assumed fraud detection, and 8% legitimate abandonment.
- `decline`: zero immediate fraud loss; a legitimate decline loses gross margin plus the assumed
  reacquisition cost.

The training job searches category-specific verification and decline thresholds that minimize these
realized costs on a time-ordered validation set. Dashboard values are retrospective simulations and
must not be described as causal or realized savings.

## Privacy boundary

Names, street addresses, raw card numbers, and date of birth are read only inside the producer.
Card numbers become salted SHA-256 customer IDs. Age is derived from date of birth; the date itself
is discarded. Logs must identify events by transaction ID only.
