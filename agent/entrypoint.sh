#!/bin/sh
set -e
python -c "from flowboard.db.session import init_db; init_db()"
exec uvicorn flowboard.main:app --host 0.0.0.0 --port 8101
