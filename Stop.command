#!/bin/bash
bash "$(dirname "$0")/Stop.sh" "$@"
status=$?
if [[ $status != 0 ]]; then read -r -p 'Press Return to close. ' _answer; fi
exit "$status"
