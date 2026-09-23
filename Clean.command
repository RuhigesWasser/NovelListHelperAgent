#!/bin/bash
bash "$(dirname "$0")/Clean.sh" "$@"
status=$?
read -r -p 'Press Return to close. ' _answer
exit "$status"
