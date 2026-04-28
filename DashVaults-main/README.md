# DashVaults

DashVaults is a backend API for fairness auditing on tabular datasets.
It allows authenticated users to upload CSV files, run bias analysis across protected groups, and generate plain-text audit reports.

## Features

- User authentication with JWT cookies (`register`, `login`, `logout`, `me`)
- CSV upload with validation and dataset preview metadata
- Bias metrics calculation:
  - Demographic parity difference
  - Disparate impact ratio (four-fifths rule)
  - Statistical parity difference
  - Severity classification (`low`, `medium`, `high`)
- AI-generated explanation and mitigation recommendations (when LLM integration is available)
- Plain-text report export endpoint

## Tech Stack

- Python 3.13
- FastAPI + Uvicorn
- MongoDB (Motor + PyMongo)
- Pandas / NumPy
- JWT + bcrypt

## Project Structure

```text
DashVaults-main/
  backend/
    server.py
    requirements.txt
    tests/backend_test.py
    .env
  frontend/
    README.md
    .env
    (config files only in current repo snapshot)
```

## Prerequisites

- Python 3.10+ (3.13 tested)
- MongoDB running locally on `mongodb://localhost:27017` (or update `.env`)
- pip

## Backend Setup

From the `backend` directory:

```bash
python -m pip install fastapi==0.110.1 uvicorn==0.25.0 motor==3.3.1 pymongo==4.5.0 pyjwt bcrypt==4.1.3 email-validator requests pandas numpy python-multipart python-dotenv pytest
```

> Note: `requirements.txt` includes `emergentintegrations==0.1.0`, which may be unavailable from pip in some environments.
> The backend now falls back gracefully if that package is missing.

## Environment Variables

`backend/.env` uses this shape:

```env
MONGO_URL="mongodb://localhost:27017"
DB_NAME="test_database"
JWT_SECRET="your-secret"
ADMIN_EMAIL="admin@unbias.ai"
ADMIN_PASSWORD="admin123"
EMERGENT_LLM_KEY="optional"
GEMINI_API_KEY="optional"
FRONTEND_URL="http://localhost:3000"
```

## Run the Backend

From `backend/`:

```bash
python -m uvicorn server:app --host 0.0.0.0 --port 8000
```

API base URL:

- `http://127.0.0.1:8000/api`

Health check:

- `GET /api/` -> `{"service":"Unbiased AI Decision API","status":"ok"}`

## Important Runtime Behavior

- If MongoDB is unavailable:
  - The app still starts successfully.
  - DB-backed routes return `503 Database unavailable`.
- If LLM integration package is unavailable:
  - Bias analysis still computes metrics.
  - AI explanation returns a fallback message instead of failing the request.

## API Endpoints

### Auth

- `POST /api/auth/register`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/auth/me`

### Files

- `POST /api/files/upload` (CSV only, max 20 MB)
- `GET /api/files`
- `GET /api/files/{file_id}`

### Analyses

- `POST /api/analyses/analyze`
- `GET /api/analyses`
- `GET /api/analyses/{analysis_id}`
- `GET /api/analyses/{analysis_id}/report`

## Testing

There is an integration test suite at `backend/tests/backend_test.py`.

Current note:
- It targets a remote URL by default via `REACT_APP_BACKEND_URL`, so you should set it for local runs:

```bash
set REACT_APP_BACKEND_URL=http://127.0.0.1:8000
python -m pytest -q
```

## Frontend Note

The `frontend/` folder currently contains config and metadata files only in this snapshot.
If you plan to run a UI, restore/add the React source (including `package.json` and `src/`) first.

## Troubleshooting

- `ImportError` around `motor/pymongo`:
  - Ensure `pymongo==4.5.0` with `motor==3.3.1`.
- Startup hangs then fails:
  - Check MongoDB service is running and matches `MONGO_URL`.
- `503 Database unavailable` on auth/files/analysis routes:
  - MongoDB is not reachable from backend.
