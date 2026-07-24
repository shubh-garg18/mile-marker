#!/usr/bin/env bash
# Render build command. No `migrate` step: the API is stateless and has no models.
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input

# Fails the build on a misconfiguration that would otherwise surface only as
# silently absent CORS headers. A malformed origin is caught by `check` and by
# neither `collectstatic` nor `gunicorn`.
python manage.py check --deploy --fail-level ERROR
