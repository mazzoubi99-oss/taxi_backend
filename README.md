# Taxi backend

This FastAPI service provides the API for the rider and driver app and the admin
console. It requires an initialized PostgreSQL database with PostGIS and the
project's application tables and functions. Configure the database and JWT
settings in the deployment environment, then install the Python dependencies
from `requirements.txt` and start `uvicorn app.main:app`.

Set `OSRM_URL` to the base URL of an OSRM driving service that covers the
operating region. `POST /api/trips/estimate` returns the road distance, duration,
and geometry when OSRM returns a route. Trip creation uses the same pricing
logic. The `route` property contains latitude/longitude pairs and is null when
only an approximate estimate is available.

`PUT /api/auth/me` updates the authenticated user's name. It accepts
`{"full_name": "Updated name"}` and returns the updated user profile.
