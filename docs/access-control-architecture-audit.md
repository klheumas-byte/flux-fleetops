# Access Control Center architecture audit

## Existing architecture reused

- Authentication remains the Flask-JWT login in `auth_service`; no alternate identity store or login flow was added.
- `users` remains the canonical account collection. The legacy `role` field is retained and read alongside the additive `role_ids` field.
- Driver data remains embedded in the existing user `driver_profile`; assigning another role does not replace or recreate it.
- Existing route decorators remain the API enforcement boundary. They now resolve current roles and permissions from MongoDB rather than trusting a JWT permission snapshot.
- Existing `branches`, sidebar routing, audit records, portal layouts, and operational services are extended rather than duplicated.

## Compatibility and security model

- Effective permissions are the union of permissions from all active assigned roles, followed by any pre-existing explicit grants and denials.
- `selected_workspace` controls presentation and landing page only. API checks always use total effective permissions.
- Persisted role definitions override safe built-in legacy definitions. Legacy Owner, Administrator, Driver, Fleet Owner, Personal Vehicle Owner, Dispatcher, and Customer Service accounts continue to resolve.
- Role assignment rejects unavailable roles and permissions beyond the actor's authority. `profitability.view` remains a distinct sensitive permission.
- Data scope is resolved separately from permission using `OWN_RECORDS`, `ASSIGNED_RECORDS`, `PRIMARY_BRANCH`, `ALLOWED_BRANCHES`, `ALL_BRANCHES`, or `ALL_RECORDS`. Branch validation is performed against stored user and branch records.
- Branches and roles use deactivation. Protected legacy/system roles cannot be renamed or deactivated, and assigned roles cannot be destructively removed.
- Login, logout, failed login, failed access, user/role/permission/branch changes, password reset, and workspace selection flow into the existing audit collection with request IP/device metadata when available.

## Migration

`backend/scripts/migrate_user_role_ids.py` backfills `[role]` into `role_ids` and initializes `selected_workspace` while retaining the original field. It defaults to a dry run and uses conditional updates when `--apply` is supplied.

## Remaining service-by-service enforcement

The shared branch query/assertion helpers are the required path for new operational queries and writes. Existing delivery, vehicle, maintenance, and task paths already using those helpers receive multi-role scope behavior automatically; older endpoints should continue migrating from legacy role checks to explicit permissions as they are modified.
