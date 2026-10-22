#!/bin/bash

set -eu

# collectstatic Should be done during build
# Check STATIC_ROOT does not ends with a slash
if [[ "${STATIC_ROOT}" == */ ]]; then
    echo "Error: STATIC_ROOT should not ends with a slash"
    exit 1
fi

rm -rf "${STATIC_ROOT}/"*
cp -a noethysweb/static/. "${STATIC_ROOT}/"

uv run noethysweb/manage.py migrate --noinput
uv run noethysweb/manage.py update_permissions

exec uv run gunicorn
