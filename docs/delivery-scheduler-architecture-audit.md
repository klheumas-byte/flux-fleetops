# Delivery Scheduler architecture audit

## Existing systems reused

- Authentication and authorization remain the existing JWT, user, multi-role, permission, and branch-scope systems.
- Certified orders use the existing `delivery_orders` collection. Manual orders use `external_source: FleetOps Manual`; future Smart Living ingestion can write the same document shape.
- Daily Delivery Runs use the existing `delivery_batches` collection. `run_number`/`batch_number`, `assigned_agent_ids`/`field_agent_id`, and `stops`/`route_sequence` compatibility aliases keep the existing custody and delivery services readable.
- The existing notification service publishes schedule events to driver and field-agent workspaces. The existing audit collection stores order, run, publish, lock, override, and cancellation events.
- The existing Operations navigation, Driver Portal, field-agent role workspace, issuing role workspace, vehicle records, and branch access helpers are extended rather than duplicated.

## Domain decisions

- New scheduler records use the requested uppercase order and run statuses. Legacy lowercase Smart Living records continue through their existing execution lifecycle.
- Product instructions are embedded in the canonical order, including certified conversion references. FleetOps records approved instructions and performs no conversion calculation.
- Stops are embedded versioned run records with stable `stop_id` values. This keeps sequencing and schedule version history atomic without introducing a parallel stop database.
- Draft creation reserves selected orders through their existing `batch_id` link but does not send notifications. Publishing changes the orders to `SCHEDULED` and exposes the run to assigned users and loading staff.
- Conflict validation conservatively treats any active run on the same delivery date as overlapping because the requested run schema has no planned end time. A later optimization phase can add time-window overlap without changing identifiers.
- Published edits increment `version` and notify affected users. Locked edits require `delivery_runs.override_lock` and a reason. Started runs reject driver or vehicle changes.

## Visibility and scope

- Operations queue, run, metadata, and detail queries apply the shared branch/data-scope helpers.
- Driver and field-agent schedule queries require assignment by stored user ID and expose only published operational statuses.
- Field-agent UI filters run details to that agent's stops. Driver details retain the complete ordered route.
- Loading schedule access is independently controlled by `loading_schedule.view`.

## Explicit phase boundary

This foundation does not add route optimization, product issue/custody, delivery confirmation, receipts, returns, or reconciliation. Existing legacy execution endpoints remain intact for existing records.
