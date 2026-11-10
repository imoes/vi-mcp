#!/bin/sh
# Verifies a downloaded release: signature of SHA256SUMS with the public release key, then the checksums.
#   deploy/pruefe-release.sh <directory with SHA256SUMS, SHA256SUMS.sig and the packages> [public-key.pem]
# Pin the public key once through a trusted channel (compare the fingerprint in the README)
# and then use your own copy, not the one in the download: whoever forges the release could swap the key as well.
set -eu
verz="${1:?Verzeichnis fehlt}"
pub="${2:-$(dirname "$0")/release-schluessel.pem}"
openssl pkeyutl -verify -pubin -inkey "$pub" -rawin -in "$verz/SHA256SUMS" -sigfile "$verz/SHA256SUMS.sig" >/dev/null 2>&1 \
    || { echo "SIGNATURE INVALID: SHA256SUMS was not signed with the release key" >&2; exit 1; }
(cd "$verz" && sha256sum --ignore-missing -c SHA256SUMS) || { echo "CHECKSUM MISMATCH" >&2; exit 1; }
echo "Signature and checksums OK (key $(openssl pkey -pubin -in "$pub" -outform DER | sha256sum | cut -c1-16)…)"
