#!/usr/bin/env bash
# Downloads OFL-licensed Google Fonts TTFs used by the pin factory.
# Usage: bash tools/fetch_fonts.sh
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FONTS="$ROOT/fonts"
LIC="$FONTS/licenses"
mkdir -p "$FONTS" "$LIC"

BASE="https://raw.githubusercontent.com/google/fonts/main/ofl"

# family_key|repo_subpath|local_filename
FILES="
playfairdisplay|playfairdisplay/PlayfairDisplay%5Bwght%5D.ttf|PlayfairDisplay-VF.ttf
playfairdisplay|playfairdisplay/PlayfairDisplay-Italic%5Bwght%5D.ttf|PlayfairDisplay-Italic-VF.ttf
poppins|poppins/Poppins-Regular.ttf|Poppins-Regular.ttf
poppins|poppins/Poppins-Medium.ttf|Poppins-Medium.ttf
poppins|poppins/Poppins-SemiBold.ttf|Poppins-SemiBold.ttf
poppins|poppins/Poppins-Bold.ttf|Poppins-Bold.ttf
poppins|poppins/Poppins-ExtraBold.ttf|Poppins-ExtraBold.ttf
poppins|poppins/Poppins-Light.ttf|Poppins-Light.ttf
poppins|poppins/Poppins-Italic.ttf|Poppins-Italic.ttf
poppins|poppins/Poppins-BoldItalic.ttf|Poppins-BoldItalic.ttf
caveat|caveat/Caveat%5Bwght%5D.ttf|Caveat-VF.ttf
inter|inter/Inter%5Bopsz,wght%5D.ttf|Inter-VF.ttf
inter|inter/Inter-Italic%5Bopsz,wght%5D.ttf|Inter-Italic-VF.ttf
dmserifdisplay|dmserifdisplay/DMSerifDisplay-Regular.ttf|DMSerifDisplay-Regular.ttf
dmserifdisplay|dmserifdisplay/DMSerifDisplay-Italic.ttf|DMSerifDisplay-Italic.ttf
"

ok=0; fail=0
for row in $FILES; do
  fam="${row%%|*}"; rest="${row#*|}"; sub="${rest%%|*}"; out="${rest##*|}"
  url="$BASE/$sub"
  code=$(curl -sSL --max-time 45 -o "$FONTS/$out.part" -w "%{http_code}" "$url")
  if [ "$code" = "200" ] && [ -s "$FONTS/$out.part" ]; then
    mv "$FONTS/$out.part" "$FONTS/$out"
    echo "OK   $out  ($(stat -c%s "$FONTS/$out") bytes)"
    ok=$((ok+1))
  else
    rm -f "$FONTS/$out.part"
    echo "FAIL $out  http=$code  $url"
    fail=$((fail+1))
  fi
done

# OFL license texts (required to accompany the font files)
for fam in playfairdisplay poppins caveat inter dmserifdisplay; do
  curl -sSL --max-time 30 -o "$LIC/$fam-OFL.txt" "$BASE/$fam/OFL.txt" || true
done

echo "----"
echo "downloaded=$ok failed=$fail"
ls -1 "$FONTS"/*.ttf 2>/dev/null | wc -l | xargs echo "ttf files:"
[ "$fail" -eq 0 ] || exit 1
