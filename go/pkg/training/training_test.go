package training

import (
	"strings"
	"testing"
	"time"
)

func TestRequestPermissions(t *testing.T) {
	request := Request{Algorithm: Algorithm, DatasetID: Dataset, Organizations: []string{"UVA", "TUDELFT"}, Rounds: 3, LocalEpochs: 2}
	if !request.AllowedBy([]string{RequestType}, []string{Dataset}, []string{Algorithm}, []string{"computeToData"}) {
		t.Fatal("valid training permission rejected")
	}
	if request.AllowedBy([]string{"sqlDataRequest"}, []string{Dataset}, []string{Algorithm}, []string{"computeToData"}) {
		t.Fatal("SQL permission authorized training")
	}
	if request.AllowedBy([]string{RequestType}, []string{"other-data"}, []string{Algorithm}, []string{"computeToData"}) {
		t.Fatal("unauthorized dataset accepted")
	}
	request.Organizations = []string{"UVA", "UVA"}
	if request.Validate() == nil {
		t.Fatal("duplicate organization accepted")
	}
}

func TestTrainingCapability(t *testing.T) {
	key := strings.Repeat("test", 16)
	grant := Grant{RunID: "example-run", User: "sandbox-researcher", ExpiresAt: time.Now().Add(time.Hour).Unix(),
		Request: Request{Algorithm: Algorithm, DatasetID: Dataset, Organizations: []string{"UVA", "VU"}, Rounds: 3, LocalEpochs: 2}}
	token, err := Sign(grant, key)
	if err != nil {
		t.Fatal(err)
	}
	verified, err := Verify(token, key)
	if err != nil || verified.User != grant.User || verified.RunID != grant.RunID {
		t.Fatal("valid capability rejected")
	}
	if _, err := Verify(token+"x", key); err == nil {
		t.Fatal("modified capability accepted")
	}
	grant.ExpiresAt = time.Now().Add(-time.Minute).Unix()
	expired, _ := Sign(grant, key)
	if _, err := Verify(expired, key); err == nil {
		t.Fatal("expired capability accepted")
	}
}
