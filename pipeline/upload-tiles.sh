#!/usr/bin/env bash
# Push the built tilesets to R2. Run after build-pmtiles-all.sh, once `wrangler login` has been
# done (or CLOUDFLARE_API_TOKEN is set).
#
#   pipeline/upload-tiles.sh              # upload anything missing or changed
#   pipeline/upload-tiles.sh --dry-run    # print what would be uploaded
#
# --remote is not optional: without it wrangler writes to the local simulation and reports
# success, leaving the real bucket empty.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/pipeline/data/pmtiles"
BUCKET="${BUCKET:-unburnt-tiles}"
DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

put() {
  local src="$1" key="$2"
  local size; size=$(du -h "$src" | cut -f1)
  if [ "$DRY" = 1 ]; then
    printf '  would upload %-28s %6s\n' "$key" "$size"
    return 0
  fi
  printf '  %-28s %6s  ' "$key" "$size"
  # PMTiles is served by byte range; the content type is what makes browsers and CDNs treat it
  # as an opaque binary rather than trying to sniff or transform it.
  if npx wrangler r2 object put "$BUCKET/$key" --file "$src" --remote \
       --content-type application/octet-stream >/dev/null 2>&1; then
    echo ok
  else
    echo FAILED
    return 1
  fi
}

[ -f "$OUT/perimeters.pmtiles" ] || { echo "no perimeters.pmtiles — run build-pmtiles-all.sh first" >&2; exit 1; }

echo "bucket: $BUCKET"
fail=0
put "$OUT/perimeters.pmtiles" "perimeters.pmtiles" || fail=1
for f in "$OUT"/severity/*.pmtiles; do
  [ -e "$f" ] || continue
  put "$f" "severity/$(basename "$f")" || fail=1
done

if [ "$fail" != 0 ]; then
  echo "some uploads failed — re-run, it overwrites rather than duplicating" >&2
  exit 1
fi
[ "$DRY" = 1 ] || echo "done"
