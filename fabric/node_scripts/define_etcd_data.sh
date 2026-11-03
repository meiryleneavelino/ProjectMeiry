#!/bin/bash

{
git clone https://github.com/Javernus/DYNAMOS.git

sudo mkdir -p /mnt/etcd-data
sudo cp ~/DYNAMOS/configuration/etcd_launch_files/*.json /mnt/etcd-data
sudo chmod -R 777 /mnt/etcd-data
}
