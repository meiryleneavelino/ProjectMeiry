#!/bin/bash

{
git clone https://github.com/kubernetes-sigs/kubespray.git
cd kubespray
git checkout release-2.27
rm -rf .git

python3 -m venv venv
source ./venv/bin/activate

pip3 install -r requirements.txt

mv inventory/sample inventory/dynamos

# sed -i -e 's/kube_proxy_mode: ipvs/kube_proxy_mode: iptables/g' ./inventory/dynamos/group_vars/k8s_cluster/k8s-cluster.yml
sed -i -e "s/# flannel_interface_regexp:/flannel_interface_regexp: 'enp[5-9]s\\\\\\\\d' #/g" ./inventory/dynamos/group_vars/k8s_cluster/k8s-net-flannel.yml
sed -i -e 's/kube_network_plugin: calico/kube_network_plugin: flannel/g' ./inventory/dynamos/group_vars/k8s_cluster/k8s-cluster.yml

# ingress_nginx_service_nodeport_http: 30080
# ingress_nginx_service_nodeport_https: 30081
sed -i -e 's/# ingress_nginx_service_nodeport_http: 30080/ingress_nginx_service_nodeport_http: 30080/g' ./inventory/dynamos/group_vars/k8s_cluster/addons.yml
sed -i -e 's/# ingress_nginx_service_nodeport_https: 30081/ingress_nginx_service_nodeport_https: 30443/g' ./inventory/dynamos/group_vars/k8s_cluster/addons.yml

ansible --version
}
