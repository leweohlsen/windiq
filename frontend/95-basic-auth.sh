#!/bin/sh
set -e

if [ -z "${BASIC_AUTH_USER:-}" ] || [ -z "${BASIC_AUTH_PASSWORD:-}" ]; then
    echo "95-basic-auth: BASIC_AUTH_USER and BASIC_AUTH_PASSWORD are required" >&2
    exit 1
fi

# htpasswd reads the password from stdin (-i) so it is not in the process list
# or the docker inspect of this container. bcrypt (-B) rotates safely with nginx.
# The newline is required: without one htpasswd -i produces an invalid hash.
printf '%s\n' "$BASIC_AUTH_PASSWORD" | htpasswd -i -n -B "$BASIC_AUTH_USER" > /etc/nginx/.htpasswd
