# Delivery Phases 2–4: Reuse and Gap Audit

## Reused canonical records

- `delivery_orders` remains the certified customer/product source.
- `delivery_batches` remains both the daily run and route plan record. Route stops, versions, assignments, execution state, and status history are embedded here.
- `item_issues` remains the single custody manifest per run; corrections are recorded as authorized reissues.
- `item_returns` remains the downstream return/reconciliation record.
- Existing branch-scope, RBAC, notifications, and audit-log services are used for every new operation.

No duplicate account, trip, route, custody, permission, or login model was added.

## Gap found

The scheduler foundation ended at uppercase `PUBLISHED`/`LOCKED`. The pre-existing custody and driver workflow only accepted legacy lowercase batch statuses (`scheduled`, `awaiting_issue`, `issued`, `accepted`, `in_progress`). Published scheduler runs therefore had no valid path into issue, custody, or driver execution.

## Canonical lifecycle added

`DRAFT → PUBLISHED/LOCKED → ACCEPTED → ITEMS_ISSUED → IN_PROGRESS → EXECUTION_COMPLETED → AWAITING_RECONCILIATION`

`LOCKED` is retained as a backward-compatible operational-plan state before driver acceptance. Final returns and reconciliation remain deliberately outside this delivery.

## Product and route rules

- Product lines normalize to `READY_FOR_DELIVERY`, `CLOSED_PRODUCT`, `ON_HOLD`, `DELIVERED`, `CANCELLED`, or `SUBSTITUTED`.
- Closed lines remain visible with `DO NOT LOAD OR DELIVER` and are excluded from issue and outcome controls.
- Conversion lines remain ordinary deliverable lines; conversion is not treated as closure.
- Customer and non-customer stop types share the same ordered stop model.
- Completed stops cannot be removed; in-progress execution is sequential.
- Each outcome requires `delivered + undelivered = issued` per eligible line.
- When the final stop receives an outcome, the service records both execution-completed and awaiting-reconciliation transitions atomically; it does not close the batch.

## Security and traceability

- Branch scope is resolved through the existing branch-access service.
- Driver mutations require the assigned driver, not merely a driver role.
- Custody disputes block start unless a separately authorized override includes a reason.
- Status history, immutable published route snapshots, notification dedupe keys, and audit entries retain actor and timestamp context.
- Issue, custody acknowledgement, and delivery-outcome writes use MongoDB transactions when the connected deployment supports sessions.
