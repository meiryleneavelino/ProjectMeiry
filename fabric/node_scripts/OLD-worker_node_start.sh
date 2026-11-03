#!/bin/bash

ip=$1

{

echo ${ip}

yes | sudo kubeadm reset

sudo kubeadm join ${ip}:6443 --token hfz4is.0yfe4oeh14h9wz7g --discovery-token-ca-cert-hash   sha256:b7a5eb4bf2ce0198e63f1d45eb4c09616d730b2b1907aeb77d27ac9bf42ba284

}  2>&1 | tee -a start_worker_node.log
