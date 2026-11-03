#!/bin/bash

set -e

# Change this to the path of the DYNAMOS repository on your disk
echo "Setting up paths..."
DYNAMOS_ROOT="${HOME}/DYNAMOS"

# Charts
charts_path="${DYNAMOS_ROOT}/charts"
core_chart="${charts_path}/core"
namespace_chart="${charts_path}/namespaces"
orchestrator_chart="${charts_path}/orchestrator"
agents_chart="${charts_path}/agents"
ttp_chart="${charts_path}/thirdparty"
api_gw_chart="${charts_path}/api-gateway"

# Config
config_path="${DYNAMOS_ROOT}/configuration"
k8s_service_files="${config_path}/k8s_service_files"
# etcd_launch_files="${config_path}/etcd_launch_files"  # I think this is unused now 

rabbit_definitions_file="${k8s_service_files}/definitions.json"
example_definitions_file="${k8s_service_files}/definitions_example.json"

cp "$example_definitions_file" "$rabbit_definitions_file"
echo "definitions_example.json copied over definitions.json to ensure a clean file"

echo "Generating RabbitMQ password..."
# Create a password for a rabbit user
rabbit_pw=$(openssl rand -hex 16)

function encode_password()
{
    SALT=$(od -A n -t x -N 4 /dev/urandom)
    PASS=$SALT$(echo -n $1 | xxd -ps | tr -d '\n' | tr -d ' ')
    PASS=$(echo -n $PASS | xxd -r -p | sha256sum | head -c 128)
    PASS=$(echo -n $SALT$PASS | xxd -r -p | base64 | tr -d '\n')
    echo $PASS
}

actual_hash=$(encode_password $rabbit_pw)

echo "Replacing tokens..."
cp ${k8s_service_files}/definitions_example.json ${rabbit_definitions_file}


# The Rabbit Hashed password needs to be in definitions.json file, that is the configuration for RabbitMQ
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS sed
    sed -i '' "s|%PASSWORD%|${actual_hash}|g" ${rabbit_definitions_file}
else
    # GNU sed
    sed -i "s|%PASSWORD%|${actual_hash}|g" ${rabbit_definitions_file}
fi

echo "Installing namespaces..."

# Install namespaces
helm upgrade -i -f ${namespace_chart}/values.yaml namespaces ${namespace_chart} --set secret.password=${rabbit_pw}

echo "Preparing PVC"

# TODO: Check if this is required at all
{
    cd ${DYNAMOS_ROOT}/configuration
    ./fill-rabbit-pvc.sh
}

#Install prometheus
echo "Installing Prometheus..."

helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm upgrade -i prometheus prometheus-community/kube-prometheus-stack \
  --version 68.1.0 \
  -f "${core_chart}/prometheus-values.yaml"

echo "Installing NGINX..."
helm upgrade -i -f "${core_chart}/ingress-values.yaml" nginx oci://ghcr.io/nginxinc/charts/nginx-ingress -n ingress --version 0.18.0

echo "Installing DYNAMOS core..."
helm upgrade -i -f ${core_chart}/values.yaml core ${core_chart} --set hostPath=${HOME}

sleep 3
# Install orchestrator layer
helm upgrade -i -f "${orchestrator_chart}/values.yaml" orchestrator ${orchestrator_chart}

sleep 1

echo "Installing agents layer"
helm upgrade -i -f "${agents_chart}/values.yaml" agents ${agents_chart}

sleep 1

echo "Installing thirdparty layer..."
helm upgrade -i -f "${ttp_chart}/values.yaml" thirdparties ${ttp_chart}

sleep 1

echo "Installing api gateway"
helm upgrade -i -f "${api_gw_chart}/values.yaml" api-gateway ${api_gw_chart}

echo "Finished setting up DYNAMOS"

exit 0
