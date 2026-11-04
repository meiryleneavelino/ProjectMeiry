// Package httpgw exposes a small authenticated HTTP API for the Horus Python
// API. It holds the researcher's Fabric identity (sandbox simplification) and
// talks only to the researcher organization's own peer.
package httpgw

import (
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"log"
	"net/http"
	"os"
	"regexp"
	"strings"

	"github.com/hyperledger/fabric-protos-go-apiv2/common"
	"github.com/hyperledger/fabric-protos-go-apiv2/peer"
	"google.golang.org/protobuf/proto"

	"horus-ledger/internal/fabclient"
)

// Ledger is what the HTTP layer needs from Fabric (mocked in tests).
type Ledger interface {
	Evaluate(function string, args ...string) ([]byte, error)
	Submit(function string, args ...string) ([]byte, fabclient.Receipt, error)
	System(function string, args ...string) ([]byte, error)
}

// FabricLedger adds system chaincode (qscc) queries to the Fabric client.
type FabricLedger struct {
	*fabclient.Client
	Channel string
}

func (f *FabricLedger) System(function string, args ...string) ([]byte, error) {
	result, err := f.Network.GetContract("qscc").EvaluateTransaction(function, append([]string{f.Channel}, args...)...)
	return result, fabclient.Clean(err)
}

type Server struct {
	Ledger Ledger
	Token  string
	MSPID  string
	Peer   string
}

var (
	hashPattern = regexp.MustCompile(`^[0-9a-f]{64}$`)
	txPattern   = regexp.MustCompile(`^[0-9a-f]{64}$`)
)

func write(response http.ResponseWriter, status int, value any) {
	response.Header().Set("Content-Type", "application/json")
	response.Header().Set("Cache-Control", "no-store")
	response.WriteHeader(status)
	_ = json.NewEncoder(response).Encode(value)
}

func writeRaw(response http.ResponseWriter, raw []byte) {
	response.Header().Set("Content-Type", "application/json")
	response.Header().Set("Cache-Control", "no-store")
	_, _ = response.Write(raw)
}

func writeError(response http.ResponseWriter, err error) {
	statuses := map[string]int{"invalid": 422, "forbidden": 403, "conflict": 409, "notfound": 404, "unavailable": 503}
	kind := fabclient.KindOf(err)
	message := err.Error()
	var typed *fabclient.Error
	if errors.As(err, &typed) {
		message = typed.Message
	}
	write(response, statuses[kind], map[string]string{"kind": kind, "detail": message})
}

func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", func(response http.ResponseWriter, _ *http.Request) {
		write(response, 200, map[string]string{"status": "ok"})
	})
	mux.HandleFunc("GET /status", s.status)
	mux.HandleFunc("GET /config", s.query("GetConfig"))
	mux.HandleFunc("GET /submissions", s.query("ListSubmissions"))
	mux.HandleFunc("GET /events", s.query("ListEvents"))
	mux.HandleFunc("GET /submissions/{hash}", s.submission)
	mux.HandleFunc("POST /submissions", s.submit)
	mux.HandleFunc("POST /training-starts", s.training)
	mux.HandleFunc("GET /transactions/{tx}", s.transaction)
	return http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		if request.URL.Path != "/health" {
			expected := "Bearer " + s.Token
			if subtle.ConstantTimeCompare([]byte(request.Header.Get("Authorization")), []byte(expected)) != 1 {
				write(response, 401, map[string]string{"detail": "authentication required"})
				return
			}
		}
		request.Body = http.MaxBytesReader(response, request.Body, 2<<20)
		mux.ServeHTTP(response, request)
	})
}

func (s *Server) query(function string) http.HandlerFunc {
	return func(response http.ResponseWriter, _ *http.Request) {
		raw, err := s.Ledger.Evaluate(function)
		if err != nil {
			writeError(response, err)
			return
		}
		writeRaw(response, raw)
	}
}

func (s *Server) submission(response http.ResponseWriter, request *http.Request) {
	hash := request.PathValue("hash")
	if !hashPattern.MatchString(hash) {
		write(response, 422, map[string]string{"detail": "a SHA-256 code hash is required"})
		return
	}
	raw, err := s.Ledger.Evaluate("GetSubmission", hash)
	if err != nil {
		writeError(response, err)
		return
	}
	writeRaw(response, raw)
}

type receiptResult struct {
	Receipt fabclient.Receipt `json:"receipt"`
	Result  json.RawMessage   `json:"result"`
}

func (s *Server) submit(response http.ResponseWriter, request *http.Request) {
	var input struct {
		Code          string   `json:"code"`
		Organizations []string `json:"organizations"`
	}
	decoder := json.NewDecoder(request.Body)
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&input); err != nil {
		write(response, 422, map[string]string{"detail": "code and organizations are required"})
		return
	}
	selected, _ := json.Marshal(input.Organizations)
	raw, receipt, err := s.Ledger.Submit("SubmitCode", input.Code, string(selected))
	if err != nil {
		writeError(response, err)
		return
	}
	write(response, 201, receiptResult{Receipt: receipt, Result: raw})
}

func (s *Server) training(response http.ResponseWriter, request *http.Request) {
	var input struct {
		RunID         string   `json:"run_id"`
		AlgorithmID   string   `json:"algorithm_id"`
		Organizations []string `json:"organizations"`
	}
	decoder := json.NewDecoder(request.Body)
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&input); err != nil {
		write(response, 422, map[string]string{"detail": "run_id, algorithm_id and organizations are required"})
		return
	}
	organizations, _ := json.Marshal(input.Organizations)
	raw, receipt, err := s.Ledger.Submit("RecordTrainingStart", input.RunID, input.AlgorithmID, string(organizations))
	if err != nil {
		writeError(response, err)
		return
	}
	write(response, 201, receiptResult{Receipt: receipt, Result: raw})
}

// status reports what this peer sees: channel height and current block hash.
// Comparing these values across organizations' peers is the cross-check that
// nobody rewrote history (tools.py ledger verify does that comparison).
func (s *Server) status(response http.ResponseWriter, _ *http.Request) {
	raw, err := s.Ledger.System("GetChainInfo")
	if err != nil {
		writeError(response, err)
		return
	}
	var info common.BlockchainInfo
	if err := proto.Unmarshal(raw, &info); err != nil {
		write(response, 503, map[string]string{"detail": "invalid chain information"})
		return
	}
	result := map[string]any{"backend": "hyperledger-fabric", "peer": s.Peer, "msp_id": s.MSPID,
		"height": info.Height, "current_block_hash": hex.EncodeToString(info.CurrentBlockHash),
		"previous_block_hash": hex.EncodeToString(info.PreviousBlockHash)}
	if config, err := s.Ledger.Evaluate("GetConfig"); err == nil {
		result["config"] = json.RawMessage(config)
	} else {
		result["config_error"] = err.Error()
	}
	write(response, 200, result)
}

// transaction asks the peer whether a transaction is in a block and whether
// the peers validated it (endorsement policy and MVCC checks passed).
func (s *Server) transaction(response http.ResponseWriter, request *http.Request) {
	tx := request.PathValue("tx")
	if !txPattern.MatchString(tx) {
		write(response, 422, map[string]string{"detail": "a transaction ID is required"})
		return
	}
	raw, err := s.Ledger.System("GetTransactionByID", tx)
	if err != nil {
		writeError(response, err)
		return
	}
	var processed peer.ProcessedTransaction
	if err := proto.Unmarshal(raw, &processed); err != nil {
		write(response, 503, map[string]string{"detail": "invalid transaction record"})
		return
	}
	result := map[string]any{"tx_id": tx, "validation_code": peer.TxValidationCode(processed.ValidationCode).String(),
		"valid": processed.ValidationCode == int32(peer.TxValidationCode_VALID)}
	if blockRaw, err := s.Ledger.System("GetBlockByTxID", tx); err == nil {
		var block common.Block
		if proto.Unmarshal(blockRaw, &block) == nil && block.Header != nil {
			result["block_number"] = block.Header.Number
			result["block_data_hash"] = hex.EncodeToString(block.Header.DataHash)
		}
	}
	write(response, 200, result)
}

// ReadToken loads the shared bearer token mounted from a Kubernetes Secret.
func ReadToken(path string) (string, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	token := strings.TrimSpace(string(raw))
	if len(token) < 24 {
		return "", errors.New("gateway token is too short")
	}
	return token, nil
}

func Listen(address string, server *Server) error {
	log.Printf("horus ledger gateway listening on %s for %s", address, server.MSPID)
	return http.ListenAndServe(address, server.Handler())
}
