#!/bin/sh
# Double-click in Finder to start the service and open its application window.
labcat_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
if ! "$labcat_dir/labcat.sh" start; then
    echo 'Press Return to close this window.'
    read -r labcat_reply
    exit 1
fi
