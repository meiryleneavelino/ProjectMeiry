package main

import (
	"encoding/json"
	"fmt"
	"github.com/Jorrit05/DYNAMOS/pkg/etcd"
	"github.com/Jorrit05/DYNAMOS/pkg/lib"
	"log"
	"os"
	"strings"
	"time"
)

func registerAgent() {
	// Prepare agent configuration data
	// var service lib.MicroServiceData = lib.UnmarshalStackFile("/var/log/stack-files/agents.yaml")
	now := time.Now()
	agentConfig = lib.AgentDetails{
		Name:          serviceName,
		ActiveSince:   &now,
		ConfigUpdated: &now,
		RoutingKey:    serviceName + "-in",
		Dns:           fmt.Sprintf("%s.%s.svc.cluster.local", strings.ToLower(serviceName), strings.ToLower(serviceName)),
	}

	if os.Getenv("TRAINING_ENABLED") == "true" {
		agentConfig.Dns = fmt.Sprintf("http://training-agent.%s.svc.cluster.local:8080", strings.ToLower(serviceName))
	}
	// Serialize agent configuration data as JSON
	configData, err := json.Marshal(agentConfig)
	if err != nil {
		log.Fatal(err)
	}

	go etcd.PutEtcdWithLease(etcdClient, fmt.Sprintf("/agents/online/%s", agentConfig.Name), string(configData))
}

func updateAgent() {
	// Update the ActiveSince field
	now := time.Now()
	agentConfig.ConfigUpdated = &now

	// Serialize agent configuration data as JSON
	configData, err := json.Marshal(agentConfig)
	if err != nil {
		log.Fatal(err)
	}

	go etcd.PutEtcdWithLease(etcdClient, fmt.Sprintf("/agents/online/%s", agentConfig.Name), string(configData))

}
