# Sprint 7-9 end-to-end checklist

## Driver private finance

- As admin, enable private finance only for an active target-enabled target/hybrid driver.
- As that driver, create a record and verify revenue, commission, expenses, and net calculations.
- Edit and delete the record; verify history retains before/after values.
- Attempt a duplicate driver/date/platform record and confirm it is rejected.
- Export CSV and confirm only the signed-in driver's private records appear.
- Sign in as owner, admin, and fleet owner; confirm every private-finance endpoint is denied.

## Maintenance override

- Create a non-critical fault or maintenance record and approve a restricted-availability override with restriction, justification, deadline, and limit.
- Confirm vehicle state is `available_with_restriction` and the linked issue remains unresolved.
- Confirm assigned driver and linked fleet owner see the restriction; driver acknowledges it.
- In dispatch, confirm restriction warning appears and reservation is rejected until explicitly acknowledged.
- Add another unsafe/critical blocker and confirm the vehicle remains blocked.
- Resolve/revoke/expire the override and confirm normal blocking immediately resumes if the issue remains open.
- Complete the linked issue and confirm the override closes idempotently.

## Reporting

- Compare approved collections minus fuel, maintenance, and other recorded operating costs for a known vehicle/date range.
- Verify estimated maintenance cost produces an incomplete-data warning.
- Filter by date, vehicle, driver, fleet owner, operation type, and status; verify pagination and CSV match the same scope.
- Move a vehicle between drivers mid-period and confirm activity follows the historical assignment interval.
- As fleet owner, attempt another owner's vehicle ID and confirm a 404 without leaked data.
- As driver, confirm only own operations/company collections appear, fleet costs are hidden, and private earnings never appear.

## Deployment

- Run `python scripts/backfill_sprint_7_9.py` and review the dry-run count.
- Run `python scripts/backfill_sprint_7_9.py --apply`; rerun it and confirm `modified=0`.
- Start the app and confirm index bootstrap succeeds for private finance and maintenance overrides.
