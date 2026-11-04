#!/bin/bash
# Runs inside ONE organization's namespace. It registers and enrolls that
# organization's identities with that organization's own CA and writes the
# results to that organization's crypto volume. Private keys never leave it.
# Only /crypto/public (CA certificate, NodeOU config, orderer TLS certificate)
# is meant to be shared with the other organizations.
set -euo pipefail
umask 077

CA_HOST="ca.${NAMESPACE}.svc.cluster.local"
URL="https://${CA_HOST}:7054"
TLS="/ca-home/ca-cert.pem"
export FABRIC_CA_CLIENT_HOME=/tmp/ca-client

if [ -f /crypto/.complete ]; then
  echo "Identities of ${ORGANIZATION} are already enrolled."
  exit 0
fi

until [ -f "$TLS" ] && fabric-ca-client getcainfo -u "$URL" --tls.certfiles "$TLS" -M /tmp/cainfo >/dev/null 2>&1; do
  echo "Waiting for the ${ORGANIZATION} CA..."
  sleep 3
done

ADMIN_MSP=/tmp/ca-client/registrar
fabric-ca-client enroll -u "https://admin:${CA_ADMIN_PASSWORD}@${CA_HOST}:7054" --tls.certfiles "$TLS" -M "$ADMIN_MSP" >/dev/null

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

# One CA issues both identity and TLS certificates, so the same root is used
# for cacerts and tlscacerts.
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

hosts() { echo "$1,$1.${NAMESPACE},$1.${NAMESPACE}.svc,$1.${NAMESPACE}.svc.cluster.local,localhost"; }

STAGE=/crypto/.staging
rm -rf "$STAGE"
mkdir -p "$STAGE"

secret=$(register peer0 peer)
enroll peer0 "$secret" "$STAGE/peer/msp" && normalize "$STAGE/peer/msp"
tls peer0 "$secret" "$STAGE/peer/tls" "$(hosts peer0)"

secret=$(register orderer0 orderer)
enroll orderer0 "$secret" "$STAGE/orderer/msp" && normalize "$STAGE/orderer/msp"
tls orderer0 "$secret" "$STAGE/orderer/tls" "$(hosts orderer0)"

secret=$(register orgadmin admin)
enroll orgadmin "$secret" "$STAGE/admin/msp" && normalize "$STAGE/admin/msp"
tls orgadmin "$secret" "$STAGE/admin/tls" "orgadmin"

secret=$(register sast-agent client "horus.role=reviewer-agent:ecert")
enroll sast-agent "$secret" "$STAGE/agent/msp" && normalize "$STAGE/agent/msp"

if [ "${RESEARCHER}" = "true" ]; then
  secret=$(register researcher client "horus.role=researcher:ecert")
  enroll researcher "$secret" "$STAGE/researcher/msp" && normalize "$STAGE/researcher/msp"
fi

mkdir -p "$STAGE/public/msp/cacerts" "$STAGE/public/msp/tlscacerts"
cp "$STAGE/peer/msp/cacerts/ca.pem" "$STAGE/public/msp/cacerts/ca.pem"
cp "$STAGE/peer/msp/cacerts/ca.pem" "$STAGE/public/msp/tlscacerts/ca.pem"
node_ous "$STAGE/public/msp"
cp "$STAGE/orderer/tls/server.crt" "$STAGE/public/orderer-tls.crt"
chmod -R go-rwx "$STAGE"
chmod -R g+rX "$STAGE"

for directory in "$STAGE"/*; do
  rm -rf "/crypto/$(basename "$directory")"
  mv "$directory" /crypto/
done
rmdir "$STAGE"
touch /crypto/.complete
echo "Enrolled peer0, orderer0, orgadmin, sast-agent$([ "${RESEARCHER}" = "true" ] && echo ", researcher") for ${ORGANIZATION}."
