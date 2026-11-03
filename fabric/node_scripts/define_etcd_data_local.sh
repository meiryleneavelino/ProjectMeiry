#!/bin/bash

{

echo "Create etcd-data folder"
sudo mkdir -p /mnt/etcd-data

echo "Copy config files into the folder"
sudo cp ./etcd_launch_files/*.json /mnt/etcd-data

echo "changing mode"
sudo chmod -R 777 /mnt/etcd-data

echo "Done!"
}
