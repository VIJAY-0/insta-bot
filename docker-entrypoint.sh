#!/bin/sh
# The container starts as root only to make sure the mounted downloads folder is writable,
# then runs the bot as the unprivileged "app" user (uid 1000).
#
# On Linux a bind-mounted folder keeps its owner from the host. If that is root or another
# user, the bot gets "Permission denied" when it saves a video, so hand the folder to "app".
# Only the folder itself changes owner, and only when "app" can't already write to it.
set -e

if [ "$(id -u)" = 0 ]; then
    if ! setpriv --reuid=app --regid=app --init-groups test -w /app/downloads; then
        echo "Making the downloads folder writable for the bot (uid 1000)." >&2
        chown app:app /app/downloads \
            || echo "Could not change the owner of the downloads folder; downloads will fail." >&2
    fi
    exec setpriv --reuid=app --regid=app --init-groups "$@"
fi
exec "$@"
