# Personal Vehicles manual checklist

- Create and activate a `personal_vehicle_owner`; confirm login opens `/my-vehicles/dashboard`.
- Confirm the personal account cannot open Admin, Driver, Fleet Owner, dispatch, target, collection, or commercial-report APIs.
- Add every supported vehicle type and verify type-specific engine/tyre fields and mobile layouts.
- Log in as two personal owners and verify direct vehicle and record ID substitution returns 404.
- Update mileage; verify regressions require a correction reason and appear in the timeline.
- Create service, fault, accident, fuel/charging, expense, document, and reminder records.
- Complete services/repairs and confirm history remains; renew a document and confirm both versions remain.
- Verify serious faults, incomplete accident repairs, overdue reminders, and expired documents affect health warnings.
- Verify monthly totals omit expenses already linked to a source record.
- Verify reminder notifications are deduplicated.
- Check dashboard at phone, tablet, and desktop widths with no horizontal overflow.
- Recheck commercial vehicle lists, allocations, Driver Portal, Fleet Owner Portal, maintenance/faults, dispatch, planner, reports, and CORS.
