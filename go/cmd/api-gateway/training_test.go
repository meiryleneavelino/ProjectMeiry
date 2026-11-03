package main

import (
	"net/http/httptest"
	"testing"
)

func TestTrainingIdentityCannotBeChosenByClient(t *testing.T) {
	t.Setenv("API_TOKEN", "test-only-secret")
	t.Setenv("TRAINING_USER", "sandbox-researcher")
	request := httptest.NewRequest("GET", "/ml/catalog?user=other-user", nil)
	request.Header.Set("Authorization", "Bearer test-only-secret")
	identity, err := trainingIdentity(request)
	if err != nil || identity != "sandbox-researcher" {
		t.Fatal("training identity was not server-controlled")
	}
	request.Header.Set("Authorization", "Bearer 1234")
	if _, err := trainingIdentity(request); err == nil {
		t.Fatal("legacy demo token authorized training")
	}
}

func TestUnauthenticatedTrainingStopsBeforeApproval(t *testing.T) {
	t.Setenv("API_TOKEN", "test-only-secret")
	t.Setenv("TRAINING_USER", "sandbox-researcher")
	response := httptest.NewRecorder()
	trainingHandler(response, httptest.NewRequest("POST", "/ml/runs", nil))
	if response.Code != 401 {
		t.Fatalf("expected 401, got %d", response.Code)
	}
}
