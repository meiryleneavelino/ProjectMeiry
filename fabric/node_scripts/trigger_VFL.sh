#!/bin/bash

# Get the port of the nginx ingress controller service in the ingress namespace
DYNAMOS_PORT=$(kubectl get svc -n ingress | grep "nginx-nginx-ingress-controller" | sed "s/.*80:\([0-9]*\)\/TCP.*/\1/")

# Get the IP address of the node containing "dynamos"
DYNAMOS_IP=$(kubectl get nodes -o wide | grep dynamos | sed "s/.*\s\([0-9]\{1,3\}\.[0-9]\{1,3\}\.[0-9]\{1,3\}\.[0-9]\{1,3\}\).*/\1/")

# Send the vflTrainModelRequest using curl
curl -H "Host: api-gateway.api-gateway.svc.cluster.local" \
  -H "Content-Type: application/json" \
  --data-raw '{
    "type": "vflTrainModelRequest",
    "user": {
      "id": "1234",
      "userName": "jake.jongejans@student.uva.nl"
    },
    "dataProviders": ["server", "clientone", "clienttwo", "clientthree"],
    "data_request": {
      "type": "vflTrainModelRequest",
      "data": {
        "learning_rate": 0.1,
        "cycles": 180,
        "policy_removal": 60,
        "policy_reintroduction": 120,
        "training_backtrack": 1
      },
      "requestMetadata": {}
    }
  }' \
  "http://${DYNAMOS_IP}:${DYNAMOS_PORT}/api/v1/requestApproval"