
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
  
