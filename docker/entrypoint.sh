#!/bin/sh
set -eu

alembic upgrade head
exec supervisord --configuration /etc/supervisor/supervisord.conf
