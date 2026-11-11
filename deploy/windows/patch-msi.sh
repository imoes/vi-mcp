#!/bin/sh
# Adds SERVER, PORT, EMBED, WIKI and PROXY to SecureCustomProperties (wixl ignores Property/@Secure). Without it an elevated installation drops
# these command-line properties silently. Runs inside the msitools container; fails if the value is not there afterwards.
set -eu
msi="$1"
cur=$(msiinfo export "$msi" Property | tr -d '\r' | awk -F '\t' '$1 == "SecureCustomProperties" { print $2 }')
msibuild "$msi" -q "UPDATE Property SET Value = '${cur:+$cur;}SERVER;PORT;EMBED;WIKI;PROXY' WHERE Property = 'SecureCustomProperties'"
msiinfo export "$msi" Property | tr -d '\r' | grep -q "^SecureCustomProperties	.*SERVER;PORT;EMBED;WIKI;PROXY$"
# 0.34.0: remove the previous version INSIDE the installation transaction (after InstallInitialize), so a failed update rolls back to it.
# wixl puts RemoveExistingProducts at 1401, before InstallInitialize, and ignores MajorUpgrade/@Schedule: a failed update then left no
# installed product but a running scheduled task (Windows 11 test VM, 10.11.2026).
msibuild "$msi" -q "UPDATE InstallExecuteSequence SET Sequence = 1501 WHERE Action = 'RemoveExistingProducts'"
msiinfo export "$msi" InstallExecuteSequence | tr -d '\r' | grep -q "^RemoveExistingProducts		1501$" || { echo "RemoveExistingProducts not moved" >&2; exit 1; }
# 0.54.0: wixl puts RunUninstall (Before="RemoveFiles") at 1801 or — from one build to the next — at 1402, before InstallInitialize;
# Windows Installer then refuses the deferred action (error 2762) and the uninstall ends with 1603, the product stays (Windows 11 test VM,
# 11.11.2026). Fixed just before RemoveFiles:
msibuild "$msi" -q "UPDATE InstallExecuteSequence SET Sequence = 3499 WHERE Action = 'RunUninstall'"
msiinfo export "$msi" InstallExecuteSequence | tr -d '\r' | grep -q "^RunUninstall	.*	3499$" || { echo "RunUninstall not moved" >&2; exit 1; }
# 0.34.0: a user interface. wixl builds no dialogs ("unhandled child Product node UI"), so ui.sql adds the dialog tables: Install, or
# Update when an older vi-mcp is installed (WIX_UPGRADE_DETECTED), Repair/Remove when this version is installed, progress, finish, error.
# Silent installs (/qn) show none of it. Fails if a statement fails or the dialogs are not all there afterwards.
if [ -f ui.sql ]; then
    while IFS= read -r q; do
        [ -n "$q" ] || continue
        msibuild "$msi" -q "$q" || { echo "ui.sql failed: $(printf %s "$q" | cut -c1-120)" >&2; exit 1; }
    done < ui.sql
    [ "$(msiinfo export "$msi" Dialog | tail -n +4 | wc -l)" -eq 6 ] || { echo "ui.sql: expected 6 dialogs" >&2; exit 1; }
fi
