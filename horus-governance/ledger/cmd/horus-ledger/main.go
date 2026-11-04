// Command horus-ledger has three modes, one image:
//
//	chaincode  the governance chaincode service each organization runs
//	agent      the organization-local SAST agent (commit/reveal, analysis, audit)
//	gateway    the researcher-side HTTP bridge used by the Horus Python API
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"horus-ledger/governance"
	"horus-ledger/internal/agent"
	"horus-ledger/internal/chaincode"
	"horus-ledger/internal/fabclient"
	"horus-ledger/internal/httpgw"
)

func main() {
	log.SetFlags(log.LstdFlags | log.LUTC)
	if len(os.Args) != 2 {
		fmt.Fprintln(os.Stderr, "usage: horus-ledger chaincode|agent|gateway")
		os.Exit(2)
	}
	var err error
	switch os.Args[1] {
	case "chaincode":
		err = chaincode.Serve()
	case "agent":
		err = runAgent()
	case "gateway":
		err = runGateway()
	default:
		err = fmt.Errorf("unknown mode %q", os.Args[1])
	}
	if err != nil {
		log.Fatal(err)
	}
}

func localConfig() (*governance.Config, error) {
	raw, err := os.ReadFile(os.Getenv("HORUS_CONFIG"))
	if err != nil {
		return nil, fmt.Errorf("read HORUS_CONFIG: %w", err)
	}
	var config governance.Config
	decoder := json.NewDecoder(strings.NewReader(string(raw)))
	decoder.DisallowUnknownFields()
	return &config, decoder.Decode(&config)
}

// connect retries because peers, orderers and the chaincode may still be starting.
func connect(ctx context.Context) (*fabclient.Client, error) {
	for {
		client, err := fabclient.Connect(fabclient.FromEnvironment())
		if err == nil {
			return client, nil
		}
		log.Printf("waiting for peer: %v", err)
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-time.After(5 * time.Second):
		}
	}
}

func runAgent() error {
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGTERM, syscall.SIGINT)
	defer stop()
	organization, namespace := os.Getenv("ORGANIZATION"), os.Getenv("NAMESPACE")
	config, err := localConfig()
	if err != nil {
		return err
	}
	if _, known := config.Organizations[organization]; !known || namespace == "" {
		return fmt.Errorf("ORGANIZATION and NAMESPACE must name a configured member")
	}
	client, err := connect(ctx)
	if err != nil {
		return err
	}
	defer client.Close()
	for {
		err := agent.VerifyConfig(client, config)
		if err == nil {
			break
		}
		if fabclient.KindOf(err) != "unavailable" || !strings.Contains(err.Error(), "initialized") {
			log.Printf("refusing to operate: %v", err)
		}
		select {
		case <-ctx.Done():
			return nil
		case <-time.After(10 * time.Second):
		}
	}
	runner, err := agent.NewKubeRunner(namespace, os.Getenv("ANALYZER_IMAGE"))
	if err != nil {
		return err
	}
	worker := &agent.Agent{Organization: organization, StateDir: os.Getenv("STATE_DIR"),
		Audit: agent.EnvBool("AUDIT_ENABLED", true), Ledger: client, Runner: runner, Config: config, Now: time.Now}
	log.Printf("SAST agent for %s ready (namespace %s, image %s, audit %t)", organization, namespace,
		runner.Image, worker.Audit)
	worker.Loop(ctx, 3*time.Second)
	return nil
}

func runGateway() error {
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGTERM, syscall.SIGINT)
	defer stop()
	token, err := httpgw.ReadToken(os.Getenv("GATEWAY_TOKEN_FILE"))
	if err != nil {
		return err
	}
	client, err := connect(ctx)
	if err != nil {
		return err
	}
	defer client.Close()
	settings := fabclient.FromEnvironment()
	server := &httpgw.Server{Ledger: &httpgw.FabricLedger{Client: client, Channel: settings.Channel},
		Token: token, MSPID: settings.MSPID, Peer: settings.PeerEndpoint}
	return httpgw.Listen(":8080", server)
}
