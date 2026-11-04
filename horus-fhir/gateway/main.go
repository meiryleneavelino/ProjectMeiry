// fhir-gateway is the internal Fabric Gateway service of horus-fhir. Only the
// fhir-api container calls it (inside horus-fhir-net, bearer token); it signs
// with the persona chosen by the API and reports tx ID, block and timings.
package main

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
	"time"

	"github.com/hyperledger/fabric-protos-go-apiv2/common"
	"github.com/hyperledger/fabric-protos-go-apiv2/peer"
	"google.golang.org/protobuf/proto"
)

// Ledger is what the HTTP layer needs (Pool in production, a fake in tests).
type Ledger interface {
	Evaluate(as, function string, args []string) (*Receipt, error)
	Submit(as, function string, args []string) (*Receipt, error)
	System(as, function string, args ...string) ([]byte, error)
}

type Server struct {
	Ledger Ledger
	Token  string
	// SystemIdentity reads chain information (qscc).
	SystemIdentity string
}

var (
	functionPattern = regexp.MustCompile(`^(PAP|PIP|PDP):[A-Za-z]{1,40}$|^(ListEvents|WhoAmI)$`)
	txPattern       = regexp.MustCompile(`^[0-9a-f]{64}$`)
)

type call struct {
	As       string   `json:"as"`
	Function string   `json:"function"`
	Args     []string `json:"args"`
}

func write(w http.ResponseWriter, code int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(value)
}

func writeError(w http.ResponseWriter, err error) {
	codes := map[string]int{"invalid": 422, "forbidden": 403, "conflict": 409, "notfound": 404}
	var typed *Error
	if !errors.As(err, &typed) {
		typed = &Error{"unavailable", err.Error()}
	}
	code, ok := codes[typed.Kind]
	if !ok {
		code = 503
	}
	write(w, code, map[string]string{"kind": typed.Kind, "detail": typed.Message})
}

func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, _ *http.Request) { write(w, 200, map[string]string{"status": "ok"}) })
	mux.HandleFunc("POST /evaluate", s.invoke(false))
	mux.HandleFunc("POST /submit", s.invoke(true))
	mux.HandleFunc("GET /chain", s.chain)
	mux.HandleFunc("GET /transactions/{tx}", s.transaction)
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/health" {
			expected := "Bearer " + s.Token
			if subtle.ConstantTimeCompare([]byte(r.Header.Get("Authorization")), []byte(expected)) != 1 {
				write(w, 401, map[string]string{"detail": "invalid gateway token"})
				return
			}
		}
		mux.ServeHTTP(w, r)
	})
}

func (s *Server) invoke(submit bool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var input call
		decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, 256*1024))
		decoder.DisallowUnknownFields()
		if err := decoder.Decode(&input); err != nil || !functionPattern.MatchString(input.Function) {
			write(w, 422, map[string]string{"kind": "invalid", "detail": "as, function (PAP:/PIP:/PDP:) and args are required"})
			return
		}
		run := s.Ledger.Evaluate
		if submit {
			run = s.Ledger.Submit
		}
		receipt, err := run(input.As, input.Function, input.Args)
		if err != nil {
			writeError(w, err)
			return
		}
		write(w, 200, receipt)
	}
}

func (s *Server) chain(w http.ResponseWriter, _ *http.Request) {
	raw, err := s.Ledger.System(s.SystemIdentity, "GetChainInfo")
	if err != nil {
		writeError(w, err)
		return
	}
	var info common.BlockchainInfo
	if err := proto.Unmarshal(raw, &info); err != nil {
		write(w, 503, map[string]string{"detail": "invalid chain information"})
		return
	}
	write(w, 200, map[string]any{"height": info.Height, "currentBlockHash": hex.EncodeToString(info.CurrentBlockHash)})
}

func (s *Server) transaction(w http.ResponseWriter, r *http.Request) {
	tx := r.PathValue("tx")
	if !txPattern.MatchString(tx) {
		write(w, 422, map[string]string{"detail": "a transaction ID is required"})
		return
	}
	raw, err := s.Ledger.System(s.SystemIdentity, "GetTransactionByID", tx)
	if err != nil {
		writeError(w, err)
		return
	}
	var processed peer.ProcessedTransaction
	if err := proto.Unmarshal(raw, &processed); err != nil {
		write(w, 503, map[string]string{"detail": "invalid transaction record"})
		return
	}
	result := map[string]any{"txId": tx, "validationCode": peer.TxValidationCode(processed.ValidationCode).String(),
		"valid": processed.ValidationCode == int32(peer.TxValidationCode_VALID)}
	if blockRaw, err := s.Ledger.System(s.SystemIdentity, "GetBlockByTxID", tx); err == nil {
		var block common.Block
		if proto.Unmarshal(blockRaw, &block) == nil && block.Header != nil {
			result["blockNumber"] = block.Header.Number
		}
	}
	write(w, 200, result)
}

func main() {
	token, err := os.ReadFile(os.Getenv("GATEWAY_TOKEN_FILE"))
	if err != nil || len(strings.TrimSpace(string(token))) < 24 {
		log.Fatal("GATEWAY_TOKEN_FILE must contain a token of at least 24 characters")
	}
	pool := NewPool(os.Getenv("WALLET_DIR"), os.Getenv("CHANNEL"), os.Getenv("CHAINCODE"), map[string]Peer{
		"HospitalMSP": {"fhir-peer0.hospital:7051", "/tls/hospital/msp/tlscacerts/ca.pem"},
		"LabMSP":      {"fhir-peer0.lab:7051", "/tls/lab/msp/tlscacerts/ca.pem"},
	})
	server := &Server{Ledger: pool, Token: strings.TrimSpace(string(token)), SystemIdentity: "adm-001"}
	log.Printf("fhir-gateway listening on :8080 (channel %s, chaincode %s)", os.Getenv("CHANNEL"), os.Getenv("CHAINCODE"))
	log.Fatal((&http.Server{Addr: ":8080", Handler: server.Handler(), ReadHeaderTimeout: 10 * time.Second}).ListenAndServe())
}
