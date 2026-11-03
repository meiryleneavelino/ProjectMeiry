#!/bin/bash

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 <request_id>" >&2
  exit 1
fi

REQUEST_ID="$1"

# Get the port of the nginx ingress controller service in the ingress namespace
DYNAMOS_PORT=$(kubectl get svc -n ingress | grep "nginx-nginx-ingress-controller" | sed "s/.*80:\([0-9]*\)\/TCP.*/\1/")

# Get the IP address of the node containing "dynamos"
DYNAMOS_IP=$(kubectl get nodes -o wide | grep dynamos | sed "s/.*\s\([0-9]\{1,3\}\.[0-9]\{1,3\}\.[0-9]\{1,3\}\.[0-9]\{1,3\}\).*/\1/")

curl -s -H "Host: api-gateway.api-gateway.svc.cluster.local" \
  -H "Content-Type: application/json" \
  "http://${DYNAMOS_IP}:${DYNAMOS_PORT}/api/v1/getTrainingStatus?id=${REQUEST_ID}" 