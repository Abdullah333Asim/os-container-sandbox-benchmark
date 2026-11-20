#!/bin/bash
VIRUS="$1"
GEN="${2:-1}"
/red_team/"$VIRUS" --gen "$GEN" &
sleep 360
