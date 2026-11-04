#!/bin/bash
# Creates fhir-channel (idempotent): genesis block, orderer join through the
# channel participation API, then each peer joins with its own org admin.
set -euo pipefail
CHANNEL=fhir-channel
CRYPTO=/local/crypto
WORK=/local/channel
ORDERER=fhir-orderer0.hospital
mkdir -p "$WORK"

if [ ! -f "$WORK/genesis.block" ]; then
  configtxgen -configPath /network -profile FhirChannel -channelID "$CHANNEL" -outputBlock "$WORK/genesis.block"
fi

ADMIN_TLS="$CRYPTO/hospital/admin/tls"
if ! osnadmin channel list -o "$ORDERER:7053" --ca-file "$ADMIN_TLS/ca.crt" \
     --client-cert "$ADMIN_TLS/server.crt" --client-key "$ADMIN_TLS/server.key" | grep -q "\"$CHANNEL\""; then
  osnadmin channel join --channelID "$CHANNEL" --config-block "$WORK/genesis.block" -o "$ORDERER:7053" \
    --ca-file "$ADMIN_TLS/ca.crt" --client-cert "$ADMIN_TLS/server.crt" --client-key "$ADMIN_TLS/server.key" >/dev/null
  echo "Orderer joined $CHANNEL."
fi

for org in hospital lab; do
  msp=$([ "$org" = hospital ] && echo HospitalMSP || echo LabMSP)
  export CORE_PEER_LOCALMSPID=$msp CORE_PEER_MSPCONFIGPATH="$CRYPTO/$org/admin/msp" \
    CORE_PEER_ADDRESS="fhir-peer0.$org:7051" CORE_PEER_TLS_ENABLED=true \
    CORE_PEER_TLS_ROOTCERT_FILE="$CRYPTO/$org/public/msp/tlscacerts/ca.pem"
  for attempt in $(seq 1 20); do
    if peer channel list 2>/dev/null | grep -qx "$CHANNEL"; then echo "fhir-peer0.$org is in $CHANNEL."; break; fi
    if peer channel join -b "$WORK/genesis.block" >/dev/null 2>&1; then echo "fhir-peer0.$org joined $CHANNEL."; break; fi
    [ "$attempt" = 20 ] && { echo "fhir-peer0.$org could not join $CHANNEL" >&2; exit 1; }
    sleep 2
  done
done
