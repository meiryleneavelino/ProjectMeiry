#!/bin/bash

{
cd $HOME/kubespray
source ./venv/bin/activate

ansible-playbook -i inventory/dynamos/inventory.ini cluster.yml -b -v -u ubuntu --private-key=~/.ssh/slice_key

mkdir -p $HOME/.kube
sudo cp -f /etc/kubernetes/admin.conf $HOME/.kube/config
sudo chown $(id -u):$(id -g) $HOME/.kube/config
}
