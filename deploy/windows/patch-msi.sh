#!/bin/sh
# Adds SERVER, PORT, EMBED and PROXY to SecureCustomProperties (wixl ignores Property/@Secure). Without it an elevated installation drops
# these command-line properties silently. Runs inside the msitools container; fails if the value is not there afterwards.
set -eu
msi="$1"
cur=$(msiinfo export "$msi" Property | tr -d '\r' | awk -F '\t' '$1 == "SecureCustomProperties" { print $2 }')
msibuild "$msi" -q "UPDATE Property SET Value = '${cur:+$cur;}SERVER;PORT;EMBED;PROXY' WHERE Property = 'SecureCustomProperties'"
msiinfo export "$msi" Property | tr -d '\r' | grep -q "^SecureCustomProperties	.*SERVER;PORT;EMBED;PROXY$"
