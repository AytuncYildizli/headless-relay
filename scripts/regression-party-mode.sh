#!/bin/sh
# Documentation tripwire with negative mutations and test-only record fixtures.
# This is NOT a council executor and never invokes any provider.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
python3 "$ROOT/scripts/test-party-contract.py"
printf 'party-mode documentation tripwire: PASS\n'
