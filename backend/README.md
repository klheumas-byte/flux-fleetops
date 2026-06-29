# Flux Fleet Backend

This backend is the Flask + MongoDB foundation for Flux Fleet. It currently includes only app setup, authentication, user data, shared utilities, and role-based access control.

## Stack

- Flask
- MongoDB with `pymongo`
- JWT authentication
- Password hashing with Werkzeug
- CORS
- `.env` configuration
- Standard API responses and centralized error handling

## Roles

- `owner`
- `admin`
- `driver`

Access intent:

- `owner`: full access to executive dashboard, profits, expenses, asset cost, reports, vehicles, drivers, maintenance, insurance, revenue, and system overview
- `admin`: operations access for vehicles, drivers, assignments, collections, fuel, rides, customers, maintenance, and notifications
- `driver`: self-service access for own vehicle, wallet, trips, customers, fuel logs, fault reports, and notifications

## Structure

- `app.py`: Flask app factory and CLI setup
- `config.py`: environment-based settings
- `extensions.py`: CORS, JWT, and MongoDB helpers
- `routes/`: API blueprints
- `services/`: business logic
- `models/`: safe response serializers
- `utils/`: decorators, validators, responses, and error helpers

## Current API

- `POST /api/auth/register`
- `POST /api/auth/login`
- `GET /api/auth/me`
- `POST /api/auth/logout`
- `GET /api/users`
- `GET /api/users/me`
- `GET /api/users/<user_id>`
- `POST /api/users`
- `PATCH /api/users/<user_id>/status`
- `PATCH /api/users/<user_id>/role`
- `PATCH /api/users/<user_id>/driver-profile`
- `GET /api/vehicles`
- `GET /api/vehicles/<vehicle_id>`
- `POST /api/vehicles`
- `PATCH /api/vehicles/<vehicle_id>`
- `PATCH /api/vehicles/<vehicle_id>/status`
- `DELETE /api/vehicles/<vehicle_id>`

## Data rule

Guarantor is not a standalone module. Driver-specific details live inside an optional `driver_profile` object on users with the `driver` role, and `guarantor` stays nested inside that `driver_profile`. There is no separate guarantor route or standalone guarantor collection in this foundation.

Phase 2 also adds a standalone `vehicles` collection. Vehicle assignment remains a simple reference link only for now through `assigned_driver_id` on vehicles and `assigned_vehicle_id` inside the embedded `driver_profile`. Assignments, maintenance, wallets, collections, fuel, and rides are still out of scope.

## Setup

1. Create a Python virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Copy `.env.example` to `.env`.
4. Start MongoDB locally or update `MONGO_URI`.
5. For local development, explicitly enable development mode:

```env
FLASK_ENV=development
FLASK_DEBUG=1
DEBUG=true
```

6. Run the API:

```bash
flask --app app.py run
```

## Production deployment

Set these environment variables in Render or Railway:

```env
FLASK_ENV=production
FLASK_DEBUG=0
DEBUG=false
```

Also set:

```env
SECRET_KEY=<long-random-secret>
JWT_SECRET_KEY=<long-random-jwt-secret>
MONGO_URI=<production-mongodb-uri>
CORS_ORIGINS=https://your-frontend-domain.com
SEED_DEMO_ON_STARTUP=false
```

Do not use `flask --debug run` or `app.run(debug=True)` in production.

For the frontend, set `VITE_API_BASE_URL=https://your-backend-domain.com/api` before running `npm run build`.

If Render is using the repo root as the service root, use the top-level `Procfile`.

If Render is using `backend/` as the service root, use `backend/Procfile`.

Both start the app with:

```bash
gunicorn app:flask_app --bind 0.0.0.0:$PORT
```

## Demo accounts

Seed demo users with:

```bash
flask --app app.py seed-demo
```

Seeded accounts:

- `owner@fluxfleet.com` / `Owner@12345`
- `admin@fluxfleet.com` / `Admin@12345`
- `driver@fluxfleet.com` / `Driver12345`
