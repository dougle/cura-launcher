#!/usr/bin/env bash

SCRIPT_DIR=$(dirname "$(realpath "$0")")

python3 $SCRIPT_DIR/main.py --github-token=[personal_access_token]
