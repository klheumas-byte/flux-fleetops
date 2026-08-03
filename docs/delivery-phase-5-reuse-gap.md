# Delivery Phase 5: Reuse and Gap Audit

## Audit result

### Already implemented

- Route completion already handed scheduler runs to `AWAITING_RECONCILIATION` only after every stop had a terminal outcome.
- Item issue, custody, delivery outcome, batch/branch scope, audit writing, attachment validation, and notification infrastructure were reusable.
- Product-line reconciliation already derived issued, delivered, returned, and approved-exception quantities from source records.
- Exception transitions, critical-exception reconciliation blocking, batch close/reopen actions, and record locking already existed.
- The existing Delivery Scheduler Accountability tab already provided a mobile-compatible Phase 5 surface.

### Partially implemented or broken

- Return receiving was a one-shot record: the first partial receipt prevented a later receipt for the remaining quantity.
- Duplicate return protection existed only at batch level and could not distinguish a retry from a legitimate second receipt.
- Closure permissions used non-canonical `batch.close` / `batch.reopen` names.
- Exception and investigation records did not capture all requested responsibility, quantity, resolution, and audit fields.
- Any exception could enter investigation, while required investigations could be bypassed by resolving the exception directly.
- Reconciliation returned a difference but no explicit product-line status.
- Phase 5 state changes did not emit the required deduplicated operational notifications.
- The UI hid return receiving after the first receipt and did not show the requested Returns summary or complete product-line reconciliation badges.

### Gaps completed

- Partial receipts now accumulate into the existing `item_returns` document with immutable `receiving_events`, per-request idempotency keys, cumulative received totals, and outstanding quantities.
- Return validation prevents negative or excess receipts while preserving full retry idempotency.
- Canonical permissions are `delivery_batches.close` and `delivery_batches.reopen`.
- Exceptions now capture quantity, responsible department/person, evidence, notes, and whether investigation is required.
- Investigations now capture investigator, findings, responsible party, approved quantity, resolution, corrective action, notes, and resolved/closed attribution.
- Critical, theft, safety, or explicitly flagged exceptions require a closed investigation before resolution and closure.
- Every reconciliation line now reports `BALANCED`, `OUTSTANDING_RETURN`, `EXCEPTION_PENDING`, `MISMATCH`, or `RECONCILED`.
- Deduplicated notifications cover outstanding/partial/damaged returns, investigation assignment, exception resolution, mismatch, ready-for-closure, closed, and reopened events.
- The Accountability UI remains available for subsequent receipts, shows the requested five summary cards, and displays compact source-derived product-line reconciliation rows.

## Reused architecture

- `delivery_batches` remains the accountability aggregate and lifecycle record.
- `delivery_orders` and their product lines remain the source of delivered quantities.
- `item_issues` remains the issued/custody source.
- `item_returns` remains the return-receiving record; a batch source key prevents duplicate receiving.
- `delivery_exceptions` and `delivery_exception_investigations` reuse the established Stock Transfer exception and evidence pattern.
- Existing branch scoping, RBAC, notifications, attachment validation, audit logging, and Mongo transaction support are reused.
- The Delivery Scheduler now exposes an Accountability tab rather than introducing another operations application.

## Gaps closed

- Phase 4 previously stopped at `AWAITING_RECONCILIATION`; uppercase scheduler batches could not use the legacy lowercase reconciliation function.
- Legacy returns allowed multiple receiving documents and lacked the Phase 5 condition vocabulary, expected-return manifest, investigation gate, separate reconciliation/closure states, and authorized reopening.
- The new workflow calculates every line as:

  `outstanding = issued - delivered - returned - approved exception quantity`

- Critical open exceptions block reconciliation. All exceptions and required investigations block closure until completed.
- Closure atomically locks the batch, issue, orders, return, exception, and investigation records. Reopening requires `delivery_batches.reopen` and an audit reason.

## Terminal lifecycle

`AWAITING_RECONCILIATION → RECONCILED → CLOSED`

Authorized reopening produces `REOPENED` while retaining the prior reconciliation and closure audit history.
