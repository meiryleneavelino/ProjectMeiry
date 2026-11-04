package main

import (
	"crypto/x509"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"time"

	"github.com/hyperledger/fabric-gateway/pkg/client"
	"github.com/hyperledger/fabric-gateway/pkg/hash"
	"github.com/hyperledger/fabric-gateway/pkg/identity"
	gatewaypb "github.com/hyperledger/fabric-protos-go-apiv2/gateway"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/status"
)

// Persona is one wallet identity (.local/wallet/<id>/identity.json).
type Persona struct {
	ID   string `json:"id"`
	MSP  string `json:"msp"`
	Role string `json:"role"`
}

// Peer of each MSP: every persona talks to its own organization's peer, which
// collects the other organization's endorsement through discovery.
type Peer struct{ Endpoint, TLSRoot string }

var personaPattern = regexp.MustCompile(`^[a-z]{3}-[0-9]{3}$`)

// Pool keeps one gRPC connection per peer and one Gateway per persona.
// SANDBOX SIMPLIFICATION: this process holds every persona's private key; the
// "as=" selector is not authentication (future: SMART on FHIR / Keycloak).
type Pool struct {
	wallet    string
	channel   string
	chaincode string
	peers     map[string]Peer
	mu        sync.Mutex
	conns     map[string]*grpc.ClientConn
	gateways  map[string]*client.Gateway
}

func NewPool(wallet, channel, chaincode string, peers map[string]Peer) *Pool {
	return &Pool{wallet: wallet, channel: channel, chaincode: chaincode, peers: peers,
		conns: map[string]*grpc.ClientConn{}, gateways: map[string]*client.Gateway{}}
}

func (p *Pool) persona(id string) (Persona, error) {
	var persona Persona
	if !personaPattern.MatchString(id) {
		return persona, &Error{"invalid", "unknown persona"}
	}
	raw, err := os.ReadFile(filepath.Join(p.wallet, id, "identity.json"))
	if err != nil {
		return persona, &Error{"invalid", "unknown persona " + id}
	}
	return persona, json.Unmarshal(raw, &persona)
}

func (p *Pool) connection(msp string) (*grpc.ClientConn, error) {
	if conn, ok := p.conns[msp]; ok {
		return conn, nil
	}
	peer, ok := p.peers[msp]
	if !ok {
		return nil, fmt.Errorf("no peer configured for %s", msp)
	}
	rootPEM, err := os.ReadFile(peer.TLSRoot)
	if err != nil {
		return nil, err
	}
	roots := x509.NewCertPool()
	if !roots.AppendCertsFromPEM(rootPEM) {
		return nil, errors.New("peer TLS root is not a PEM certificate")
	}
	host := strings.Split(peer.Endpoint, ":")[0]
	conn, err := grpc.NewClient(peer.Endpoint, grpc.WithTransportCredentials(credentials.NewClientTLSFromCert(roots, host)))
	if err != nil {
		return nil, err
	}
	p.conns[msp] = conn
	return conn, nil
}

func (p *Pool) gateway(id string) (*client.Gateway, error) {
	p.mu.Lock()
	defer p.mu.Unlock()
	if gw, ok := p.gateways[id]; ok {
		return gw, nil
	}
	persona, err := p.persona(id)
	if err != nil {
		return nil, err
	}
	directory := filepath.Join(p.wallet, id, "msp")
	certificatePEM, err := os.ReadFile(filepath.Join(directory, "signcerts", "cert.pem"))
	if err != nil {
		return nil, err
	}
	certificate, err := identity.CertificateFromPEM(certificatePEM)
	if err != nil {
		return nil, err
	}
	signer, err := identity.NewX509Identity(persona.MSP, certificate)
	if err != nil {
		return nil, err
	}
	keys, err := os.ReadDir(filepath.Join(directory, "keystore"))
	if err != nil || len(keys) == 0 {
		return nil, errors.New("persona private key not found")
	}
	keyPEM, err := os.ReadFile(filepath.Join(directory, "keystore", keys[0].Name()))
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
	conn, err := p.connection(persona.MSP)
	if err != nil {
		return nil, err
	}
	gw, err := client.Connect(signer, client.WithSign(sign), client.WithHash(hash.SHA256), client.WithClientConnection(conn),
		client.WithEvaluateTimeout(20*time.Second), client.WithEndorseTimeout(30*time.Second),
		client.WithSubmitTimeout(30*time.Second), client.WithCommitStatusTimeout(60*time.Second))
	if err != nil {
		return nil, err
	}
	p.gateways[id] = gw
	return gw, nil
}

// Timings split a submit into its Fabric phases (stage 6 measurements).
type Timings struct {
	EndorseMs float64 `json:"endorseMs"`
	OrderMs   float64 `json:"orderMs"`
	CommitMs  float64 `json:"commitMs"`
	TotalMs   float64 `json:"totalMs"`
}

// Receipt identifies a committed (or evaluated) call.
type Receipt struct {
	Result      json.RawMessage `json:"result"`
	TxID        string          `json:"txId,omitempty"`
	BlockNumber uint64          `json:"blockNumber,omitempty"`
	Timings     Timings         `json:"timings"`
}

func ms(since time.Time) float64 { return float64(time.Since(since).Microseconds()) / 1000 }

func (p *Pool) Evaluate(as, function string, args []string) (*Receipt, error) {
	gw, err := p.gateway(as)
	if err != nil {
		return nil, err
	}
	start := time.Now()
	result, err := gw.GetNetwork(p.channel).GetContract(p.chaincode).EvaluateTransaction(function, args...)
	if err != nil {
		return nil, Clean(err)
	}
	return &Receipt{Result: json.RawMessage(result), Timings: Timings{TotalMs: ms(start)}}, nil
}

// Submit endorses (both organizations), orders and waits for the commit.
func (p *Pool) Submit(as, function string, args []string) (*Receipt, error) {
	gw, err := p.gateway(as)
	if err != nil {
		return nil, err
	}
	start := time.Now()
	proposal, err := gw.GetNetwork(p.channel).GetContract(p.chaincode).NewProposal(function, client.WithArguments(args...))
	if err != nil {
		return nil, Clean(err)
	}
	transaction, err := proposal.Endorse()
	if err != nil {
		return nil, Clean(err)
	}
	timings := Timings{EndorseMs: ms(start)}
	ordered := time.Now()
	commit, err := transaction.Submit()
	if err != nil {
		return nil, Clean(err)
	}
	timings.OrderMs = ms(ordered)
	committed := time.Now()
	state, err := commit.Status()
	if err != nil {
		return nil, Clean(err)
	}
	timings.CommitMs, timings.TotalMs = ms(committed), ms(start)
	if !state.Successful {
		return nil, &Error{"conflict", fmt.Sprintf("transaction %s was not committed: %s", state.TransactionID, state.Code)}
	}
	return &Receipt{Result: json.RawMessage(transaction.Result()), TxID: state.TransactionID,
		BlockNumber: state.BlockNumber, Timings: timings}, nil
}

// System queries the qscc system chaincode (chain height, transactions).
func (p *Pool) System(as, function string, args ...string) ([]byte, error) {
	gw, err := p.gateway(as)
	if err != nil {
		return nil, err
	}
	result, err := gw.GetNetwork(p.channel).GetContract("qscc").EvaluateTransaction(function, append([]string{p.channel}, args...)...)
	return result, Clean(err)
}

// Error carries the chaincode's kind prefix (invalid, forbidden, conflict, notfound).
type Error struct{ Kind, Message string }

func (e *Error) Error() string { return e.Kind + ": " + e.Message }

var kinds = []string{"invalid", "forbidden", "conflict", "notfound"}

// Clean turns gateway/gRPC errors into "kind: message" from the chaincode.
func Clean(err error) error {
	if err == nil {
		return nil
	}
	var typed *Error
	if errors.As(err, &typed) {
		return typed
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
				return &Error{kind, strings.TrimSpace(message[index+len(kind)+2:])}
			}
		}
	}
	return &Error{"unavailable", "ledger request failed: " + messages[0]}
}
