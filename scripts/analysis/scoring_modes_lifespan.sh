#!/usr/bin/env bash
# scoring_modes_lifespan.sh — Average lifespan per insertion class across suites/modes.
export LC_ALL=C
BASE=~/ChampSim-dev
DATE=20260608_2350

for suite in dpc3 gap gms ligra ml qmm; do
  echo "=== $suite ==="
  label=${suite}_scoring_modes_${DATE}
  for mode in mode0_ref mode0_flat3 mode3_decoup mode4_cal; do
    dir=$BASE/results/$label/$mode
    [ ! -d "$dir" ] && echo "  $mode: missing" && continue

    # Accumulate sums and counts across all traces
    sum_doa=0; sum_dead=0; sum_alive=0; n=0
    for tdir in "$dir"/*/; do
      line=$(grep "Avg lifespan" "$tdir/champsim.out" 2>/dev/null | head -1)
      [ -z "$line" ] && continue
      doa=$(echo  "$line" | grep -oP 'DoA=\K[0-9]+')
      dead=$(echo "$line" | grep -oP 'Dead=\K[0-9]+')
      alive=$(echo "$line" | grep -oP 'Alive=\K[0-9]+')
      [ -z "$doa" ] && continue
      sum_doa=$(awk  -v a="$sum_doa"  -v b="$doa"   'BEGIN{print a+b}')
      sum_dead=$(awk -v a="$sum_dead" -v b="$dead"  'BEGIN{print a+b}')
      sum_alive=$(awk -v a="$sum_alive" -v b="$alive" 'BEGIN{print a+b}')
      n=$((n+1))
    done

    if [ "$n" -eq 0 ]; then
      printf "  %-14s  no lifespan data\n" "$mode"
    else
      awk -v mode="$mode" -v n="$n" \
          -v sd="$sum_doa" -v sm="$sum_dead" -v sa="$sum_alive" \
        'BEGIN{
          doa=sd/n; dead=sm/n; alive=sa/n
          ok = (doa < dead || dead==0) && (dead < alive || dead==0) && (doa < alive)
          flag = ok ? "OK" : "INVERTED"
          printf "  %-14s  DoA=%7.0fK  Dead=%7.0fK  Alive=%7.0fK  [%s]\n",
                 mode, doa/1000, dead/1000, alive/1000, flag
        }'
    fi
  done
  echo ""
done
