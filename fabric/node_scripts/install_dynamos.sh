#!/bin/bash
set -e 

{

# Remove old helm repo if present
if [ -f /etc/apt/sources.list.d/helm-stable-debian.list ]; then
  sudo rm /etc/apt/sources.list.d/helm-stable-debian.list
fi

# Ensure apt supports HTTPS and curl
sudo apt-get update
sudo apt-get install -y curl gpg apt-transport-https

# Add Helm signing key
curl -fsSL https://packages.buildkite.com/helm-linux/helm-debian/gpgkey | gpg --dearmor | sudo tee /usr/share/keyrings/helm.gpg > /dev/null

# Add Helm apt repo
echo "deb [signed-by=/usr/share/keyrings/helm.gpg] https://packages.buildkite.com/helm-linux/helm-debian/any/ any main" | \
  sudo tee /etc/apt/sources.list.d/helm-stable-debian.list

# Update and try installing via apt
sudo apt-get update

if sudo apt-get install -y helm; then
  echo "Helm installed via apt"
else
  echo "APT install failed — falling back to manual install"
  VERSION="v3.19.0"
  curl -fsSL "https://get.helm.sh/helm-${VERSION}-linux-amd64.tar.gz" -o helm-${VERSION}-linux-amd64.tar.gz
  tar -zxvf helm-${VERSION}-linux-amd64.tar.gz
  sudo mv linux-amd64/helm /usr/local/bin/helm
  rm -rf linux-amd64 helm-${VERSION}-linux-amd64.tar.gz
  echo "Helm manually installed, version:"
  helm version
fi

# # Install Helm
# curl https://baltocdn.com/helm/signing.asc | gpg --dearmor | sudo tee /usr/share/keyrings/helm.gpg > /dev/null
# sudo apt-get install apt-transport-https --yes
# echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/helm.gpg] https://baltocdn.com/helm/stable/debian/ all main" | sudo tee /etc/apt/sources.list.d/helm-stable-debian.list
# sudo apt-get update
# sudo apt-get install helm

function addPathExport () {
  echo -e "export PATH=$1" >> $HOME/.bashrc
  echo "[inserted] export PATH=$1"
}

# Install CLI
curl --proto '=https' --tlsv1.2 -sSfL https://run.linkerd.io/install-edge | LINKERD2_VERSION=edge-25.8.1 sh
# curl --proto '=https' --tlsv1.2 -sSfL https://run.linkerd.io/install-edge | sh

# Add Linkerd to PATH
addPathExport "\$PATH:/home/ubuntu/.linkerd2/bin"
export PATH=$PATH:/home/ubuntu/.linkerd2/bin

kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.2.1/standard-install.yaml

linkerd check --pre                         # validate that Linkerd can be installed
linkerd install --set nodeSelector."kubernetes\\.io/hostname"=dynamos --crds | kubectl apply -f - # install the Linkerd CRDs
linkerd install --set nodeSelector."kubernetes\\.io/hostname"=dynamos | kubectl apply -f - # install the control plane into the 'linkerd' namespace
linkerd check                               # validate everything worked!

# Install Jaeger onto the cluster for observability
linkerd jaeger install \
  --set collector.nodeSelector."kubernetes\\.io/hostname"=dynamos \
  --set nodeSelector."kubernetes\\.io/hostname"=dynamos \
  --set jaeger.nodeSelector."kubernetes\\.io/hostname"=dynamos \
  --set webhook.nodeSelector."kubernetes\\.io/hostname"=dynamos \
  | kubectl apply -f -

mkdir homebrew
curl -L https://github.com/Homebrew/brew/tarball/master | tar xz --strip 1 -C homebrew

addPathExport "\$PATH:$HOME/homebrew/bin"
export PATH="$PATH:$HOME/homebrew/bin"

brew update
brew install etcd

echo -e "127.0.0.1 api-gateway.api-gateway.svc.cluster.local" | sudo tee -a /etc/hosts

# git clone https://github.com/Javernus/DYNAMOS.git
git clone https://github.com/DYNAMOS-UVA/Scattered-Directive

# rename to DYNAMOS 
mv Scattered-Directive/ DYNAMOS 

# curl -H "Host: api-gateway.api-gateway.svc.cluster.local" http://10.145.6.3:31813/api/v1/requestApproval \
# --header 'Content-Type: application/json' \
# --data-raw '{
#     "type": "sqlDataRequest",
#     "user": {
#         "id": "12324",
#         "userName": "jorrit.stutterheim@cloudnation.nl"
#     },
#     "dataProviders": ["VU"],
#     "data_request": {
#         "type": "sqlDataRequest",
#         "query" : "SELECT * FROM Personen p JOIN Aanstellingen s LIMIT 1000",
#         "algorithm" : "average",
#         "options" : {
#             "graph" : false,
#             "aggregate": false
#         },
#         "requestMetadata": {}
#     }
# }'

# curl -H "Host: api-gateway.api-gateway.svc.cluster.local" http://10.145.6.3:31813/api/v1/requestApproval \
# --header 'Content-Type: application/json' \
# --data-raw '{
#     "type": "vflTrainRequest",
#     "user": {
#         "id": "1234",
#         "userName": "jake.jongejans@student.uva.nl"
#     },
#     "dataProviders": ["alpha"],
#     "data_request": {
#         "type": "vflTrainRequest",
#         "data": {
#           "learning_rate": 0.05
#         },
#         "requestMetadata": {}
#     }
# }'

# DYNAMOS_PORT=$(kubectl get svc -n ingress | grep "nginx-nginx-ingress-controller" | sed "s/.*80:\([0-9]*\)\/TCP.*/\1/")
# DYNAMOS_IP=$(kubectl get nodes -o wide | grep dynamos | sed "s/.*\s\([0-9]\{1,3\}\.[0-9]\{1,3\}\.[0-9]\{1,3\}\.[0-9]\{1,3\}\).*/\1/")

# curl -H "Host: api-gateway.api-gateway.svc.cluster.local" http://$DYNAMOS_IP:$DYNAMOS_PORT/api/v1/requestApproval \
# --header 'Content-Type: application/json' \
# --data-raw '{
#     "type": "vflTrainModelRequest",
#     "user": {
#         "id": "1234",
#         "userName": "jake.jongejans@student.uva.nl"
#     },
#     "dataProviders": ["alpha", "enigma", "omnia", "zenith"],
#     "data_request": {
#         "type": "vflTrainModelRequest",
#         "data": {
#           "learning_rate": 0.05,
#           "cycles": 50
#         },
# "requestMetadata": {}
#     }
# }'

}