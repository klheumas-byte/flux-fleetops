# Sprint 7-9 API permissions

| API | Owner/Admin | Fleet owner | Driver |
| --- | --- | --- | --- |
| `GET/POST/PATCH/DELETE /api/driver/private-finance...` | Denied | Denied | Own records only; feature eligibility required |
| `GET /api/maintenance-overrides` | All scoped records | Linked vehicles, read-only | Active assignment, read/acknowledge only |
| `POST /api/maintenance-overrides` | Allowed | Denied | Denied |
| `PATCH .../revoke` or `.../resolve` | Allowed | Denied | Denied |
| `PATCH .../acknowledge` | Denied | Denied | Assigned vehicle only |
| `GET /api/reports/commercial` and CSV | Fleet-wide, filterable | Linked vehicles only | Own historical operations/collections only |

Private-finance data is stored in dedicated collections and is never read by fleet-owner, admin-report, maintenance, dispatch, or commercial-profitability services. Commercial reports resolve allowed vehicle/driver IDs before reading fact collections. Driver attribution uses the assignment interval that overlaps the event date; ambiguous legacy records are excluded instead of being assigned to the current driver.

Maintenance overrides cannot suppress critical or `vehicle_unsafe` blockers. Dispatch requires an explicit acknowledgement flag for `available_with_restriction` vehicles, while other unresolved blockers continue to block the vehicle.
