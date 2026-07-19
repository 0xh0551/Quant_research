#!/usr/bin/env bash
# Nightly Claude post-mortems for the noches bots.
#   per-trade classification: Haiku (cheap, one call per losing trade)
#   synthesis (the 2-3 systemic fixes): SONNET (balanced tier — near-Opus quality on
#     structured synthesis for a few cents; a big jump over the old Haiku synthesis).
# The client's HARD monthly cap ($5) pre-reserves each call's cost, so a run that would
# breach the ceiling skips at $0 rather than overshooting.
#
# To use Opus for synthesis instead (higher quality, ~$2.5/mo more — watch the $5 cap):
#   export POSTMORTEM_SYNTH_TIER=reasoning   (default here is "smart" = Sonnet)
set -u
cd /home/h0551user/Quant_research || exit 1
PY=.venv/bin/python
SYNTH_TIER="${POSTMORTEM_SYNTH_TIER:-smart}"
for b in Popeye Bender Wall_E Mickey; do
  $PY scripts/postmortem_run.py --bot "$b" --n 10 --per-trade-tier cheap --synth-tier "$SYNTH_TIER" >> logs/postmortem.log 2>&1 || \
    echo "[$(date -u +%FT%TZ)] postmortem failed for $b" >> logs/postmortem.log
done

# Consolidate the per-bot syntheses into one prioritized action list for the dashboard's
# "recommended actions" panel (grounded, human-decides — no automatic bot changes).
$PY scripts/build_risk_actions.py >> logs/postmortem.log 2>&1 || \
  echo "[$(date -u +%FT%TZ)] build_risk_actions failed" >> logs/postmortem.log
