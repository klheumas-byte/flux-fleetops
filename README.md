
  # Flux Fleet Ops

  This repository contains the Flux Fleet frontend generated from Figma plus a new Flask backend foundation.

  The original design source is available at:
  https://www.figma.com/design/DH2xrYipbfeELsaZ7oF7bE/flux-fleeet-ops

  ## Frontend

  Run `npm i` to install the frontend dependencies.

  Run `npm run dev` to start the Vite development server.

  ## Backend

  The backend lives in [`backend/`](backend/README.md) and currently includes:

  - Flask app factory
  - MongoDB configuration
  - JWT authentication
  - Role-based access for `owner`, `admin`, and `driver`
  - Auth and user foundation
  - Standard API responses, validation, and error handling

  Quick start:

  1. Create a Python virtual environment.
  2. Install dependencies with `pip install -r backend/requirements.txt`.
  3. Copy `backend/.env.example` to `backend/.env`.
  4. Run `flask --app backend/app.py --debug run` from the `backend` folder.

  ## Production

  Frontend:

  1. Copy `.env.example` to `.env`.
  2. Set `VITE_API_BASE_URL` to your deployed backend URL, including `/api`.
  3. Build with `npm run build`.

  Backend:

  1. Copy `backend/.env.example` to `backend/.env` on the server or set the same keys in your host dashboard.
  2. Keep `FLASK_ENV=production`, `FLASK_DEBUG=0`, and `DEBUG=false`.
  3. Set real `SECRET_KEY`, `JWT_SECRET_KEY`, `MONGO_URI`, and production `CORS_ORIGINS`.
  4. Start the API with the root `Procfile` or `backend/Procfile`.
  
