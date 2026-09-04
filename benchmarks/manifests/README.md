# Benchmark manifests

Versioned benchmark manifests and split definitions, validated against
`schemas/benchmark-manifest.schema.json`.

Each manifest records product IDs, source URLs, required credentials, licences
and access conditions, byte sizes, checksums, labels, kernel sets, calibration
files, and reference versions, plus split role (train/development, validation,
held-out test), stress bins, and control uncertainty.

The interim public-data manifest is explicitly labelled interim until the
official SIH product IDs and benchmark split are released (D-001).

`interim-public-product-route-matrix.v1.json` is the current versioned public
route inventory. It is schema-validated and intentionally contains no
unverified product identifier, checksum, licensing term, or numerical scene
measurement. A frozen benchmark manifest can be added only once these facts
are available from the governing source records.
