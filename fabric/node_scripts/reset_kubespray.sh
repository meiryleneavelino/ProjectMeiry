#!/bin/bash

{
cd $HOME/kubespray
source ./venv/bin/activate

ansible-playbook -i inventory/dynamos/inventory.ini reset.yml -b -v --private-key=~/.ssh/slice_key -u ubuntu -e reset_confirmation=yes
}
