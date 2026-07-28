# Sprint 10 end-to-end checklist

## Driver operating mode and safety

- Change an allocated driver from Target Only to Hybrid and confirm the vehicle remains assigned.
- Confirm Dispatch and Operational Tasks appear after the session refreshes and backend operations endpoints allow access.
- Change the driver to Operations Only; confirm target wallet/payment and scheduled-customer actions are denied.
- Confirm My Vehicle, Report Fault, Report Incident, restrictions, handover actions, Profile, and Notifications remain available in every mode.
- Re-submit identical settings and confirm no duplicate audit or notification is created.
- Review the settings history for reason, actor role, old/new values, and timestamp; confirm the allocation still shows its original mode snapshot.

## Fleet Owner participation

- Open a linked vehicle and report a fault and incident; confirm reporter role and timestamps are retained.
- Submit maintenance, withdrawal, and driver-reassignment requests; verify assignments and vehicle status do not change before Admin review.
- Add comments to a linked fault and maintenance case and create/update a compliance document.
- Read/acknowledge a maintenance or restriction notification.
- Attempt every action with another owner's vehicle ID and confirm a 404 without leaked data.
- Confirm direct assignment, driver-mode, target, collection, dispatch approval, fault resolution, and override approval remain denied.

## Maintenance conversion

- Approve an eligible fault and select Convert to Maintenance.
- Confirm the request is `POST /api/faults/{id}/convert-to-maintenance`, returns success, and creates one linked maintenance job.
- Repeat the action and confirm the same job is returned without duplication.
- Attempt conversion from Reported/Rejected status and confirm a clear validation error.

## Allocation history and navigation

- Open active and ended allocations; verify local date/time, readable mode/status labels, reasons, actual end, and actor names/roles.
- Verify deleted legacy actors display “Unknown user” and no Object IDs appear.
- Expand/collapse each Fleet Operations group, reload, and confirm the group state is remembered.
- Verify active highlighting, badges, permission filtering, all visible links, and mobile close-after-navigation behavior.

## Responsive KPI cards

- At widths below 480px confirm two KPI cards per row with no clipping or horizontal overflow.
- At normal phone widths confirm three cards per row; confirm tablet and desktop layouts remain readable.
- Verify forms, tables, charts, and detailed panels were not forced into the KPI grid.
