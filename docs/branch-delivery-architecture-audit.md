# Branch-Aware Delivery Architecture Audit

## Reused architecture

- Authentication remains the single JWT flow in `routes/auth.py` and `services/auth_service.py`. Mutable account status and permissions are evaluated from MongoDB on every protected request.
- Users remain in `users`; branch tenancy uses `primary_branch_id` and `allowed_branch_ids` ObjectId references.
- RBAC remains action-based through `permission_required` and the centralized definitions in `rbac_service.py`.
- Navigation continues through the existing `App`, `AdminLayout`, `DriverLayout`, and permission-filtered sidebars.
- Planning stays in the shared operations area. Smart Living deliveries are exposed beside Dispatch Planner, not as another application.
- Driver execution stays in Driver Portal. Smart Living batches are added to the existing operational-task aggregation and link to the shared delivery workspace.
- Vehicle availability follows existing `vehicles`, assignments, reservations, and maintenance status conventions. Delivery batches additionally reject unavailable vehicles and same-day driver/vehicle overlap.
- Notifications reuse `notification_service.create_notification` and the existing notification bell/work queue.
- Exceptions reuse `delivery_exceptions`; damaged, missing, wrong, or exceptional returns create an open delivery exception.
- Auditing reuses `audit_logs`, extended with branch, old/new values, and reason.

## New collections

- `branches`: branch master data with soft active/inactive status.
- `delivery_orders`: certified Smart Living customer deliveries and embedded product lines.
- `delivery_batches`: planner grouping, assignments, route sequence, status, and reconciliation result.
- `item_issues`: immutable custody issue plus driver acknowledgement.
- `item_returns`: receiving records and condition/variance evidence.

These are new domain records, not duplicates of sales, installments, Smart Living certification, dispatch jobs, inventory, or vehicle assignments.

## Branch enforcement

`branch_access_service.py` derives allowed branch ObjectIds from the authenticated database user. Read filters and write validation use those IDs; frontend branch input is never trusted. System and Operations Administrators have global branch scope. Driver and field-agent schedules add ownership predicates in addition to branch scope.

## Lifecycle invariants

- `(external_source, external_reference)` is unique.
- Only active branches accept new operations.
- Scheduled batches require branch-compatible active users and an available vehicle.
- Active same-day batches cannot share a driver or vehicle.
- Issue records are unique per batch; acknowledgement is driver-owned and idempotent.
- Driver quantity writes are limited to the driver's active batch.
- Reconciliation requires `issued = delivered + returned + approved exception` on every order and is idempotent.
- Reconciliation locks order quantities and preserves audit history.

## Migration notes

Run `python backend/scripts/backfill_branch_relationships.py --branch-code HEAD --apply` after creating the initial active branch. Without `--apply`, the script reports proposed changes only. Existing historical records remain readable; backfilling assigns references without copying branch names into operational records.
