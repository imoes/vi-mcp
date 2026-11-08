#!/bin/sh
# Prüft ein heruntergeladenes Release: Signatur von SHA256SUMS mit dem öffentlichen Release-Schlüssel, dann die Prüfsummen.
#   deploy/pruefe-release.sh <verzeichnis mit SHA256SUMS, SHA256SUMS.sig und den Paketen> [öffentlicher-schlüssel.pem]
# Den öffentlichen Schlüssel einmal über einen vertrauenswürdigen Weg festhalten (Fingerabdruck im README vergleichen)
# und ihn dann aus der eigenen Kopie nehmen, nicht aus dem Download: Wer das Release fälscht, könnte auch den Schlüssel tauschen.
set -eu
verz="${1:?Verzeichnis fehlt}"
pub="${2:-$(dirname "$0")/release-schluessel.pem}"
openssl pkeyutl -verify -pubin -inkey "$pub" -rawin -in "$verz/SHA256SUMS" -sigfile "$verz/SHA256SUMS.sig" >/dev/null 2>&1 \
    || { echo "SIGNATUR UNGÜLTIG: SHA256SUMS stammt nicht vom Release-Schlüssel" >&2; exit 1; }
(cd "$verz" && sha256sum --ignore-missing -c SHA256SUMS) || { echo "PRÜFSUMME FALSCH" >&2; exit 1; }
echo "Signatur und Prüfsummen in Ordnung (Schlüssel $(openssl pkey -pubin -in "$pub" -outform DER | sha256sum | cut -c1-16)…)"
