package main

import (
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

type fakeLedger struct{ calls []string }

func (f *fakeLedger) Evaluate(as, function string, args []string) (*Receipt, error) {
	f.calls = append(f.calls, "evaluate "+as+" "+function)
	return &Receipt{Result: json.RawMessage(`{"ok":true}`)}, nil
}

func (f *fakeLedger) Submit(as, function string, args []string) (*Receipt, error) {
	f.calls = append(f.calls, "submit "+as+" "+function)
	if as == "phy-001" && function == "PAP:CreatePolicy" {
		return nil, Clean(errors.New("rpc error: chaincode response 500, forbidden: requires role=admin issued by HospitalMSP"))
	}
	return &Receipt{Result: json.RawMessage(`{}`), TxID: strings.Repeat("a", 64), BlockNumber: 7}, nil
}

func (f *fakeLedger) System(as, function string, args ...string) ([]byte, error) { return nil, nil }

func request(t *testing.T, server *Server, method, path, token, body string) (int, map[string]any) {
	t.Helper()
	r := httptest.NewRequest(method, path, strings.NewReader(body))
	if token != "" {
		r.Header.Set("Authorization", "Bearer "+token)
	}
	w := httptest.NewRecorder()
	server.Handler().ServeHTTP(w, r)
	var result map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &result)
	return w.Code, result
}

func TestGateway(t *testing.T) {
	ledger := &fakeLedger{}
	server := &Server{Ledger: ledger, Token: strings.Repeat("t", 32)}
	token := server.Token
	if code, _ := request(t, server, "GET", "/health", "", ""); code != http.StatusOK {
		t.Fatal("health must not need the token")
	}
	if code, _ := request(t, server, "POST", "/submit", "wrong", `{"as":"adm-001","function":"PAP:ListPolicies","args":[]}`); code != 401 {
		t.Fatal("token is required")
	}
	if code, _ := request(t, server, "POST", "/submit", token, `{"as":"adm-001","function":"lscc:install","args":[]}`); code != 422 {
		t.Fatal("only PAP/PIP/PDP functions are allowed")
	}
	code, result := request(t, server, "POST", "/submit", token, `{"as":"adm-001","function":"PAP:BindResource","args":["resource:dr-1","P"]}`)
	if code != 200 || result["blockNumber"].(float64) != 7 {
		t.Fatalf("submit: %d %v", code, result)
	}
	code, result = request(t, server, "POST", "/submit", token, `{"as":"phy-001","function":"PAP:CreatePolicy","args":["P","{}"]}`)
	if code != 403 || result["kind"] != "forbidden" || !strings.Contains(result["detail"].(string), "role=admin") {
		t.Fatalf("chaincode error must map to 403 with its message: %d %v", code, result)
	}
}

func TestPersonaNamesAreChecked(t *testing.T) {
	pool := NewPool(t.TempDir(), "c", "cc", nil)
	for _, id := range []string{"../etc", "adm-001/../x", "ADM-001", ""} {
		if _, err := pool.persona(id); err == nil {
			t.Fatalf("persona %q must be refused", id)
		}
	}
}
