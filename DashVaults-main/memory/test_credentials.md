# Test Credentials — Unbiased AI Decision

## Admin
- Email: `admin@unbias.ai`
- Password: `admin123`
- Role: `admin`

## Test User (create via /api/auth/register)
- Email: `tester@unbias.ai`
- Password: `test12345`
- Role: `user`

## Auth Endpoints
- POST `/api/auth/register` — body `{email, password, name?}`
- POST `/api/auth/login` — body `{email, password}`
- POST `/api/auth/logout`
- GET  `/api/auth/me`

## File / Analysis Endpoints
- POST `/api/files/upload` (multipart: file=CSV)
- GET  `/api/files`
- GET  `/api/files/{id}`
- POST `/api/analyses/analyze` — body `{file_id, protected_attribute, outcome_column, favorable_outcome}`
- GET  `/api/analyses`
- GET  `/api/analyses/{id}`
- GET  `/api/analyses/{id}/report` (plain text)

Auth is cookie-based (httponly). Tests should use `credentials: 'include'` / `-c -b` cookie jar.
