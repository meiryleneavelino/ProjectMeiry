// Package fabclient connects one organization identity to its own peer through
// the Fabric Gateway API. Every submitted transaction is signed with the
// private key of that identity, which never leaves the organization's namespace.
package fabclient

import (
	"crypto/x509"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/hyperledger/fabric-gateway/pkg/client"
	"github.com/hyperledger/fabric-gateway/pkg/hash"
	"github.com/hyperledger/fabric-gateway/pkg/identity"
	gatewaypb "github.com/hyperledger/fabric-protos-go-apiv2/gateway"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/status"
)

// Settings come from environment variables set by the Helm chart.
type Settings struct {
	PeerEndpoint string // peer0.<namespace>.svc.cluster.local:7051
	TLSRootCert  string // CA certificate that issued the peer TLS certificate
	MSPID        string
	IdentityDir  string // MSP folder produced by fabric-ca-client enroll
	Channel      string
	Chaincode    string
}

func FromEnvironment() Settings {
	value := func(name, fallback string) string {
		if found := os.Getenv(name); found != "" {
			return found
		}
		return fallback
	}
	return Settings{
		PeerEndpoint: os.Getenv("PEER_ENDPOINT"), TLSRootCert: os.Getenv("PEER_TLS_ROOT"),
		MSPID: os.Getenv("MSP_ID"), IdentityDir: value("IDENTITY_DIR", "/identity/msp"),
		Channel: value("CHANNEL", "horus-governance"), Chaincode: value("CHAINCODE", "horus-governance"),
	}
}

// Client wraps one gateway connection.
type Client struct {
	connection *grpc.ClientConn
	gateway    *client.Gateway
	Network    *client.Network
	Contract   *client.Contract
	settings   Settings
}

func Connect(settings Settings) (*Client, error) {
	if settings.PeerEndpoint == "" || settings.TLSRootCert == "" || settings.MSPID == "" {
		return nil, errors.New("PEER_ENDPOINT, PEER_TLS_ROOT and MSP_ID are required")
	}
	rootPEM, err := os.ReadFile(settings.TLSRootCert)
	if err != nil {
		return nil, fmt.Errorf("read peer TLS root: %w", err)
	}
	roots := x509.NewCertPool()
	if !roots.AppendCertsFromPEM(rootPEM) {
		return nil, errors.New("peer TLS root is not a PEM certificate")
	}
	host := strings.Split(settings.PeerEndpoint, ":")[0]
	connection, err := grpc.NewClient(settings.PeerEndpoint,
		grpc.WithTransportCredentials(credentials.NewClientTLSFromCert(roots, host)))
	if err != nil {
		return nil, err
	}
	certificatePEM, err := os.ReadFile(filepath.Join(settings.IdentityDir, "signcerts", "cert.pem"))
	if err != nil {
		return nil, fmt.Errorf("read identity certificate: %w", err)
	}
	certificate, err := identity.CertificateFromPEM(certificatePEM)
	if err != nil {
		return nil, err
	}
	id, err := identity.NewX509Identity(settings.MSPID, certificate)
	if err != nil {
		return nil, err
	}
	keys, err := os.ReadDir(filepath.Join(settings.IdentityDir, "keystore"))
	if err != nil || len(keys) == 0 {
		return nil, errors.New("identity private key not found")
	}
	keyPEM, err := os.ReadFile(filepath.Join(settings.IdentityDir, "keystore", keys[0].Name()))
	if err != nil {
		return nil, err
	}
	privateKey, err := identity.PrivateKeyFromPEM(keyPEM)
	if err != nil {
		return nil, err
	}
	sign, err := identity.NewPrivateKeySign(privateKey)
	if err != nil {
		return nil, err
	}
	gateway, err := client.Connect(id, client.WithSign(sign), client.WithHash(hash.SHA256),
		client.WithClientConnection(connection),
		client.WithEvaluateTimeout(20*time.Second), client.WithEndorseTimeout(30*time.Second),
		client.WithSubmitTimeout(30*time.Second), client.WithCommitStatusTimeout(90*time.Second))
	if err != nil {
		connection.Close()
		return nil, err
	}
	network := gateway.GetNetwork(settings.Channel)
	return &Client{connection: connection, gateway: gateway, Network: network,
		Contract: network.GetContract(settings.Chaincode), settings: settings}, nil
}

func (c *Client) Close() {
	c.gateway.Close()
	c.connection.Close()
}

// Evaluate runs a read-only query on the organization's own peer.
func (c *Client) Evaluate(function string, args ...string) ([]byte, error) {
	result, err := c.Contract.EvaluateTransaction(function, args...)
	return result, Clean(err)
}

// Receipt identifies a committed transaction.
type Receipt struct {
	TxID        string `json:"tx_id"`
	BlockNumber uint64 `json:"block_number"`
}

// Submit endorses on a majority of organizations, orders and waits for commit.
func (c *Client) Submit(function string, args ...string) ([]byte, Receipt, error) {
	proposal, err := c.Contract.NewProposal(function, client.WithArguments(args...))
	if err != nil {
		return nil, Receipt{}, Clean(err)
	}
	transaction, err := proposal.Endorse()
	if err != nil {
		return nil, Receipt{}, Clean(err)
	}
	commit, err := transaction.Submit()
	if err != nil {
		return nil, Receipt{}, Clean(err)
	}
	state, err := commit.Status()
	if err != nil {
		return nil, Receipt{}, Clean(err)
	}
	receipt := Receipt{TxID: state.TransactionID, BlockNumber: state.BlockNumber}
	if !state.Successful {
		return nil, receipt, &Error{Kind: "conflict", Message: fmt.Sprintf(
			"transaction %s was not committed: %s", state.TransactionID, state.Code)}
	}
	return transaction.Result(), receipt, nil
}

// Error is a chaincode or network error with the chaincode's kind prefix.
type Error struct {
	Kind    string
	Message string
}

func (e *Error) Error() string { return e.Kind + ": " + e.Message }

var kinds = []string{"invalid", "forbidden", "conflict", "notfound", "unavailable"}

// Clean extracts the chaincode message ("kind: text") from gateway errors so
// callers see "conflict: this code hash was already submitted" instead of a
// gRPC dump.
func Clean(err error) error {
	if err == nil {
		return nil
	}
	messages := []string{err.Error()}
	if grpcStatus, ok := status.FromError(err); ok {
		messages = append([]string{grpcStatus.Message()}, messages...)
		for _, detail := range grpcStatus.Details() {
			if item, ok := detail.(*gatewaypb.ErrorDetail); ok {
				messages = append([]string{item.Message}, messages...)
			}
		}
	}
	for _, message := range messages {
		for _, kind := range kinds {
			if index := strings.Index(message, kind+": "); index >= 0 {
				return &Error{Kind: kind, Message: strings.TrimSpace(message[index+len(kind)+2:])}
			}
		}
	}
	return &Error{Kind: "unavailable", Message: "ledger request failed: " + messages[0]}
}

// KindOf returns the error kind, or "unavailable" for unknown errors.
func KindOf(err error) string {
	var typed *Error
	if errors.As(err, &typed) {
		return typed.Kind
	}
	return "unavailable"
}
