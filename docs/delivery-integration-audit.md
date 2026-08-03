# Delivery Operations integration audit

Audited 2026-07-30.

## Connection

- Frontend API base: `VITE_API_BASE_URL=/api`.
- Vite development proxy target: `VITE_DEV_API_TARGET=http://127.0.0.1:5011`.
- Frontend listener: port 5173.
- Flask listener: `127.0.0.1:5011`.
- Backend environment: development, database connected.
- Git branch/version: `main` at `fe58112` plus the current uncommitted delivery implementation.
- Blueprint: `smart_living_deliveries_bp` is imported by `backend/routes/__init__.py` and registered once at `/api/smart-living-deliveries`.

The frontend uses relative `/api` requests; it does not read `VITE_API_URL`. The active equivalent in this repository is `VITE_API_BASE_URL`, with Vite forwarding it to `VITE_DEV_API_TARGET`.

## Endpoint trace

The caller for these requests is `src/app/components/shared/SmartLivingDeliveries.tsx`.

| UI operation | Frontend URL | Method | Registered Flask route | Verified result |
| --- | --- | --- | --- | --- |
| Certified Deliveries | `/smart-living-deliveries/scheduler/queue` | GET | `/api/smart-living-deliveries/scheduler/queue` | 200 authenticated |
| Create Certified Delivery | `/smart-living-deliveries/scheduler/orders` | POST | `/api/smart-living-deliveries/scheduler/orders` | registered; scheduler tests pass |
| Daily Runs | `/smart-living-deliveries/scheduler/runs` | GET | `/api/smart-living-deliveries/scheduler/runs` | 200 authenticated |
| Create Daily Run | `/smart-living-deliveries/scheduler/runs` | POST | `/api/smart-living-deliveries/scheduler/runs` | registered; migration run test passes |
| Save Daily Run | `/smart-living-deliveries/scheduler/runs/<id>` | PATCH | `/api/smart-living-deliveries/scheduler/runs/<run_id>` | registered; scheduler tests pass |
| Publish Daily Run | `/smart-living-deliveries/scheduler/runs/<id>/publish` | POST | `/api/smart-living-deliveries/scheduler/runs/<run_id>/publish` | registered; scheduler tests pass |
| Weekly View | same Daily Runs request | GET | same Daily Runs route | 200; grouped client-side |
| Loading Schedule | `/smart-living-deliveries/scheduler/loading` | GET | `/api/smart-living-deliveries/scheduler/loading` | 200 authenticated |
| Returns & Reconciliation | `/smart-living-deliveries/accountability/batches` | GET | `/api/smart-living-deliveries/accountability/batches` | 200 authenticated |
| Driver/vehicle/agent lookups | `/smart-living-deliveries/scheduler/metadata` | GET | `/api/smart-living-deliveries/scheduler/metadata` | 200 authenticated |

Unauthenticated calls to each protected route correctly return 401. A request with insufficient permission returns 403 through the route's permission decorator. The shared frontend API layer now reports 403, 404, and 405 with the method and request path instead of advising a backend restart.

Development exposes `GET /api/smart-living-deliveries/debug/routes` and logs the complete delivery route table at startup. The route-audit endpoint is unavailable outside development.

## Root causes and repairs

1. A stale Flask listener contained scheduler phases 2–4 but did not contain the Phase 5 accountability routes. This produced a real HTML 404 for Returns & Reconciliation. The exact listener was replaced after verifying its PID and command. The active process now reports 49 registered delivery routes.
2. Twelve of thirteen live users and every live vehicle lacked branch data. The metadata service required an exact branch match, so valid legacy resources were silently removed.
3. Agent lookup recognized only `field_agent` in some write paths even though the data and UI also use `sales_agent`, `responsible_agent`, and `agent`.
4. Vehicle lookup and run validation disagreed on the legacy `in_service` status.
5. The frontend expected lookup arrays, while the repaired API uses the normalized `{items: [...]}` contract.

The repair:

- normalizes drivers, agents, and vehicles to `{items: [{id, label, status, branch, disabled_reason}]}`;
- supports `role`, `user_type`, `role_ids`, role objects, and existing driver/agent profiles through the canonical role helper;
- includes authorized branchless legacy records as `Unassigned`;
- preserves branch enforcement as soon as branch fields exist;
- supports active legacy users whose `status` is absent but `active` is true;
- keeps unavailable or assigned vehicles visible with a disabling reason;
- logs `total -> active -> branch match -> available -> returned` in development;
- accepts both the old array contract and normalized contract in the frontend during rollout.

Authenticated live lookup result after repair:

```text
Drivers:  total 6 -> active 6 -> branch 6 -> available 6 -> returned 6
Vehicles: total 4 -> active 3 -> branch 3 -> available 2 -> returned 3
Agents:   total 1 -> active 1 -> branch 1 -> available 1 -> returned 1
```

## Mobile form

The Certified Delivery dialog now uses a narrower responsive viewport, two-column desktop product layout, stacked mobile actions, and no manual latitude/longitude fields. Existing coordinates remain usable by routing and map links; users enter a delivery address and landmark rather than raw coordinates.
