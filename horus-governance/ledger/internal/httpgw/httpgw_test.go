package httpgw

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"horus-ledger/governance"
	"horus-ledger/internal/memledger"
)

type memory struct{ *memledger.Identity }

func (memory) System(string, ...string) ([]byte, error) { return nil, nil }

func server(t *testing.T) http.Handler {
	hash := func(value string) string { sum := sha256.Sum256([]byte(value)); return hex.EncodeToString(sum[:]) }
	config := &governance.Config{Version: 1, Channel: "horus-governance",
		Organizations: map[string]string{"UVA": "UvaMSP", "VU": "VuMSP", "TUDELFT": "TudelftMSP"},
		RulesHash:     hash("rules"), PolicyHash: hash("policy"), SemgrepVersion: "1.145.0",
		AnalyzerImages:       map[string]string{"UVA": "sha256:" + hash("u"), "VU": "sha256:" + hash("v"), "TUDELFT": "sha256:" + hash("t")},
		Rules:                map[string]governance.Rule{"r": {Severity: "high", Message: "m"}},
		Policy:               governance.Policy{Deductions: map[string]int{"high": 25, "medium": 10, "low": 2}, MinimumScore: 70},
		RevealTimeoutSeconds: 600}
	world, err := memledger.New(config)
	if err != nil {
		t.Fatal(err)
	}
	researcher := world.As("TudelftMSP", governance.RoleResearcher, false)
	return (&Server{Ledger: memory{researcher}, Token: strings.Repeat("t", 32), MSPID: "TudelftMSP"}).Handler()
}

func call(handler http.Handler, method, path, body, token string) *httptest.ResponseRecorder {
	request := httptest.NewRequest(method, path, strings.NewReader(body))
	if token != "" {
		request.Header.Set("Authorization", "Bearer "+token)
	}
	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, request)
	return recorder
}

func TestGatewayAuthenticatesAndMapsChaincodeErrors(t *testing.T) {
	handler, token := server(t), strings.Repeat("t", 32)
	if call(handler, "GET", "/submissions", "", "wrong").Code != 401 {
		t.Fatal("wrong token must be rejected")
	}
	if call(handler, "GET", "/health", "", "").Code != 200 {
		t.Fatal("health needs no token")
	}
	created := call(handler, "POST", "/submissions", `{"code":"value = 1\n","organizations":["UVA","TUDELFT"]}`, token)
	if created.Code != 201 {
		t.Fatalf("submit failed: %d %s", created.Code, created.Body)
	}
	var result struct {
		Receipt struct {
			TxID string `json:"tx_id"`
		} `json:"receipt"`
		Result governance.Submission `json:"result"`
	}
	_ = json.Unmarshal(created.Body.Bytes(), &result)
	if result.Result.Reviewer != "UVA" || len(result.Receipt.TxID) != 64 {
		t.Fatalf("unexpected submit result: %s", created.Body)
	}
	duplicate := call(handler, "POST", "/submissions", `{"code":"value = 1\n","organizations":["UVA"]}`, token)
	if duplicate.Code != 409 || !strings.Contains(duplicate.Body.String(), "already submitted") {
		t.Fatalf("duplicate must map to 409: %d %s", duplicate.Code, duplicate.Body)
	}
	if call(handler, "GET", "/submissions/"+strings.Repeat("0", 64), "", token).Code != 404 {
		t.Fatal("unknown submission must map to 404")
	}
	if call(handler, "POST", "/submissions", `{"code":"x","organizations":["TUDELFT"]}`, token).Code != 422 {
		t.Fatal("no eligible reviewer must map to 422")
	}
	if call(handler, "POST", "/submissions", `{"code":"x","organizations":["UVA"],"researcher_org":"UVA"}`, token).Code != 422 {
		t.Fatal("unknown fields such as a claimed organization must be rejected")
	}
}
