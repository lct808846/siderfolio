#!/bin/sh
# Install as a root-owned forced command for the deploy-only SSH key.
set -eu
[ "${SSH_ORIGINAL_COMMAND:-}" = apply ] || exit 64
exec sudo -n /usr/bin/python3 -I /usr/local/lib/astroagent/release_apply.py apply
