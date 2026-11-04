#!/bin/bash
# Usage (through tools.py): enroll.sh hospital|lab
# Registers and enrolls one organization's identities with that organization's
# own CA. Node material goes to /local/crypto/<org>/, persona credentials to
# /local/wallet/<enrollment id>/. Enrollment IDs are pseudonyms because the
# signer's certificate is stored in every block (no real names on-chain).
# Adapted copy of horus-governance/deploy/ledger/chart/files/enroll.sh.
set -euo pipefail
umask 077

ORG=${1:?hospital or lab}
case "$ORG" in
  hospital) MSP=HospitalMSP ;;
  lab) MSP=LabMSP ;;
  *) echo "unknown organization $ORG" >&2; exit 2 ;;
esac
CA_HOST="fhir-ca.${ORG}"
URL="https://${CA_HOST}:7054"
TLS="/ca/${ORG}/ca-cert.pem"
CRYPTO="/local/crypto/${ORG}"
WALLET=/local/wallet
export FABRIC_CA_CLIENT_HOME=/tmp/ca-client

if [ -f "$CRYPTO/.complete" ]; then
  echo "Identities of ${MSP} are already enrolled."
  exit 0
fi

until [ -f "$TLS" ] && fabric-ca-client getcainfo -u "$URL" --tls.certfiles "$TLS" -M /tmp/cainfo >/dev/null 2>&1; do
  echo "Waiting for ${CA_HOST}..."
  sleep 2
done

ADMIN_MSP=/tmp/ca-client/registrar
fabric-ca-client enroll -u "https://admin:$(cat "/run/secrets/fhir_ca_${ORG}")@${CA_HOST}:7054" \
  --tls.certfiles "$TLS" -M "$ADMIN_MSP" >/dev/null

# register NAME TYPE [ATTRIBUTES] -> prints a fresh one-time enrollment secret
register() {
  local secret
  secret=$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')
  if ! fabric-ca-client register -u "$URL" --tls.certfiles "$TLS" -M "$ADMIN_MSP" \
      --id.name "$1" --id.secret "$secret" --id.type "$2" ${3:+--id.attrs "$3"} >/dev/null 2>&1; then
    # Re-run after a partial failure: reset the secret of the existing identity.
    fabric-ca-client identity modify "$1" --secret "$secret" -u "$URL" --tls.certfiles "$TLS" -M "$ADMIN_MSP" >/dev/null
  fi
  echo "$secret"
}

enroll() {
  local name=$1 secret=$2 directory=$3
  shift 3
  fabric-ca-client enroll -u "https://${name}:${secret}@${CA_HOST}:7054" --tls.certfiles "$TLS" -M "$directory" "$@" >/dev/null
}

node_ous() {
  cat > "$1/config.yaml" <<'EOF'
NodeOUs:
  Enable: true
  ClientOUIdentifier:
    Certificate: cacerts/ca.pem
    OrganizationalUnitIdentifier: client
  PeerOUIdentifier:
    Certificate: cacerts/ca.pem
    OrganizationalUnitIdentifier: peer
  AdminOUIdentifier:
    Certificate: cacerts/ca.pem
    OrganizationalUnitIdentifier: admin
  OrdererOUIdentifier:
    Certificate: cacerts/ca.pem
    OrganizationalUnitIdentifier: orderer
EOF
}

# One CA issues identity and TLS certificates, so one root serves both.
normalize() {
  local directory=$1 root
  root=$(ls "$directory"/cacerts/*.pem | head -1)
  mv "$root" "$directory/ca.tmp"
  rm -rf "$directory"/cacerts/* "$directory"/IssuerPublicKey "$directory"/IssuerRevocationPublicKey "$directory"/user
  mv "$directory/ca.tmp" "$directory/cacerts/ca.pem"
  mkdir -p "$directory/tlscacerts"
  cp "$directory/cacerts/ca.pem" "$directory/tlscacerts/ca.pem"
  node_ous "$directory"
}

tls() {
  local name=$1 secret=$2 output=$3 hosts=$4 temporary="/tmp/tls-$1"
  enroll "$name" "$secret" "$temporary" --enrollment.profile tls --csr.hosts "$hosts"
  mkdir -p "$output"
  cp "$temporary/signcerts/cert.pem" "$output/server.crt"
  cp "$temporary"/keystore/* "$output/server.key"
  cp "$(ls "$temporary"/tlscacerts/*.pem "$temporary"/cacerts/*.pem 2>/dev/null | head -1)" "$output/ca.crt"
}

# persona ID ROLE: client identity with role=<ROLE> in the certificate
persona() {
  local secret
  secret=$(register "$1" client "role=$2:ecert")
  rm -rf "$STAGE_WALLET/$1"
  enroll "$1" "$secret" "$STAGE_WALLET/$1/msp" && normalize "$STAGE_WALLET/$1/msp"
  printf '{"id":"%s","msp":"%s","role":"%s"}\n' "$1" "$MSP" "$2" > "$STAGE_WALLET/$1/identity.json"
}

STAGE="$CRYPTO.staging"
STAGE_WALLET="$WALLET/.staging-$ORG"
rm -rf "$STAGE" "$STAGE_WALLET"
mkdir -p "$STAGE" "$STAGE_WALLET"

secret=$(register "peer0-${ORG}" peer)
enroll "peer0-${ORG}" "$secret" "$STAGE/peer/msp" && normalize "$STAGE/peer/msp"
tls "peer0-${ORG}" "$secret" "$STAGE/peer/tls" "fhir-peer0.${ORG},localhost"

secret=$(register "admin-${ORG}" admin)
enroll "admin-${ORG}" "$secret" "$STAGE/admin/msp" && normalize "$STAGE/admin/msp"
tls "admin-${ORG}" "$secret" "$STAGE/admin/tls" "admin-${ORG}"

if [ "$ORG" = hospital ]; then
  secret=$(register orderer0-hospital orderer)
  enroll orderer0-hospital "$secret" "$STAGE/orderer/msp" && normalize "$STAGE/orderer/msp"
  tls orderer0-hospital "$secret" "$STAGE/orderer/tls" "fhir-orderer0.hospital,localhost"
  persona adm-001 admin
  persona pat-001 patient
  persona phy-001 physician
  persona phy-002 physician
else
  persona lab-001 lab
fi

# Public material other parties may see: CA root, NodeOUs, orderer TLS cert.
mkdir -p "$STAGE/public/msp/cacerts" "$STAGE/public/msp/tlscacerts"
cp "$STAGE/peer/msp/cacerts/ca.pem" "$STAGE/public/msp/cacerts/ca.pem"
cp "$STAGE/peer/msp/cacerts/ca.pem" "$STAGE/public/msp/tlscacerts/ca.pem"
node_ous "$STAGE/public/msp"
if [ "$ORG" = hospital ]; then cp "$STAGE/orderer/tls/server.crt" "$STAGE/public/orderer-tls.crt"; fi

rm -rf "$CRYPTO"
mv "$STAGE" "$CRYPTO"
for directory in "$STAGE_WALLET"/*; do
  rm -rf "$WALLET/$(basename "$directory")"
  mv "$directory" "$WALLET/"
done
rmdir "$STAGE_WALLET"
touch "$CRYPTO/.complete"
echo "Enrolled ${MSP}: peer0, admin$([ "$ORG" = hospital ] && echo ", orderer0, adm-001, pat-001, phy-001, phy-002" || echo ", lab-001")."
