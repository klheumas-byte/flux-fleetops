# Multi-role access and workspace audit

## Finding

The user records already used one account and one `users` collection. The affected
Driver records retained every assigned code in `role_ids`; no duplicate account or
parallel role model was needed.

Additional roles were lost or ignored at four boundaries:

1. `user_role_codes` only normalized string values in `role_ids`. It ignored
   `user_type`, role objects, and persisted role ObjectIds.
2. The serialized `roles` collection omitted `code` and `active`, leaving the
   frontend to treat `id` as both database identity and workspace code.
3. Driver, Fleet Owner, and Personal Vehicle portals had no workspace selector.
   A user whose persisted `selected_workspace` was `driver` could not reach any
   other assigned workspace.
4. Workspace switching changed the database and browser user object but retained
   the original JWT role claim. Legacy route handlers that still consume the JWT
   role therefore continued to behave as Driver. Several configured dashboard
   names (`system-dashboard`, `operations-dashboard`, and similar) also had no
   corresponding frontend page and could render a blank workspace.

## Resolution

- `role`, `user_type`, `role_ids`, role objects, role codes, and stored role
  ObjectIds now normalize into one ordered set of canonical codes.
- Login and `/auth/me` return canonical role objects with `id`, `code`, `name`,
  `active`, and `dashboard`.
- Effective permissions remain the union of all active assigned roles, followed
  by explicit user grants and denials. Authorization middleware continues to read
  current database assignments rather than trusting cached browser permissions.
- Switching workspace persists `selected_workspace`, writes an audit event,
  returns a refreshed canonical user, and rotates the JWT with the selected role
  plus the full role-code list.
- One shared workspace selector is used by the admin, Driver, Fleet Owner, and
  Personal Vehicle shells.
- Symbolic role dashboard names resolve to the existing role-aware dashboard page;
  dispatcher and customer-service workspaces continue to open Dispatch Requests.

The legacy `role` value remains intact as the backward-compatible primary role.
`selected_workspace` controls the current shell; it does not overwrite `role`.
