package main

import (
	"bytes"
	"context"
	"crypto/hmac"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"strings"
	"time"

	pb "github.com/Jorrit05/DYNAMOS/pkg/proto"
	"github.com/Jorrit05/DYNAMOS/pkg/training"
	"github.com/google/uuid"
	"google.golang.org/protobuf/types/known/structpb"
)

func trainingIdentity(request *http.Request) (string, error) {
	token := os.Getenv("API_TOKEN")
	user := os.Getenv("TRAINING_USER")
	if token == "" || user == "" || !hmac.Equal([]byte(request.Header.Get("Authorization")), []byte("Bearer "+token)) {
		return "", errors.New("training authentication required")
	}
	return user, nil
}

func approveTraining(ctx context.Context, request training.Request, user string, revalidate bool) (*pb.RequestApprovalResponse, error) {
	encoded, _ := json.Marshal(request)
	var metadata map[string]interface{}
	json.Unmarshal(encoded, &metadata)
	structured, err := structpb.NewStruct(metadata)
	if err != nil {
		return nil, err
	}
	correlation := uuid.NewString()
	responseChan := make(chan validation, 1)
	requestApprovalMutex.Lock()
	requestApprovalMap[correlation] = responseChan
	requestApprovalMutex.Unlock()
	defer func() {
		requestApprovalMutex.Lock()
		delete(requestApprovalMap, correlation)
		requestApprovalMutex.Unlock()
	}()
	_, err = c.SendRequestApproval(ctx, &pb.RequestApproval{
		Type: training.RequestType, User: &pb.User{Id: correlation, UserName: user},
		DataProviders: request.Organizations, DestinationQueue: "policyEnforcer-in", Training: structured,
		Options: map[string]bool{"_ml_revalidate": revalidate},
	})
	if err != nil {
		return nil, err
	}
	select {
	case result := <-responseChan:
		if result.response.Error != "" || len(result.response.AuthorizedProviders) != len(request.Organizations) {
			return nil, errors.New("training denied by DYNAMOS policies or unavailable organizations")
		}
		for _, organization := range request.Organizations {
			if result.response.AuthorizedProviders[organization] == "" {
				return nil, errors.New("a selected organization was not authorized")
			}
		}
		return result.response, nil
	case <-ctx.Done():
		return nil, errors.New("DYNAMOS training authorization timed out")
	}
}

func coordinatorRequest(ctx context.Context, method, path string, body []byte) (*http.Response, error) {
	base := os.Getenv("TRAINING_COORDINATOR_URL")
	if base == "" {
		return nil, errors.New("training coordinator not configured")
	}
	request, err := http.NewRequestWithContext(ctx, method, base+path, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	request.Header.Set("Authorization", "Bearer "+os.Getenv("API_TOKEN"))
	request.Header.Set("Content-Type", "application/json")
	return (&http.Client{Timeout: 30 * time.Second}).Do(request)
}

func proxyTrainingResponse(writer http.ResponseWriter, response *http.Response) {
	defer response.Body.Close()
	writer.Header().Set("Content-Type", response.Header.Get("Content-Type"))
	if disposition := response.Header.Get("Content-Disposition"); disposition != "" {
		writer.Header().Set("Content-Disposition", disposition)
	}
	writer.WriteHeader(response.StatusCode)
	io.Copy(writer, io.LimitReader(response.Body, 2<<20))
}

func loadTrainingGrant(ctx context.Context, runID, user string) (training.Grant, error) {
	var grant training.Grant
	if _, err := uuid.Parse(runID); err != nil {
		return grant, errors.New("unknown training run")
	}
	response, err := etcdClient.Get(ctx, "/training/approvals/"+runID)
	if err != nil || len(response.Kvs) != 1 || json.Unmarshal(response.Kvs[0].Value, &grant) != nil || grant.User != user {
		return grant, errors.New("unknown training run")
	}
	return grant, nil
}

func trainingHandler(writer http.ResponseWriter, request *http.Request) {
	user, err := trainingIdentity(request)
	if err != nil {
		http.Error(writer, err.Error(), http.StatusUnauthorized)
		return
	}
	ctx, cancel := context.WithTimeout(request.Context(), 60*time.Second)
	defer cancel()
	path := strings.TrimPrefix(request.URL.Path, "/ml")
	if path == "/catalog" && request.Method == http.MethodGet {
		response, err := coordinatorRequest(ctx, http.MethodGet, "/catalog", nil)
		if err != nil {
			http.Error(writer, "training coordinator unavailable", http.StatusBadGateway)
			return
		}
		proxyTrainingResponse(writer, response)
		return
	}
	if path == "/runs" && request.Method == http.MethodPost {
		var parameters training.Request
		decoder := json.NewDecoder(http.MaxBytesReader(writer, request.Body, 65536))
		decoder.DisallowUnknownFields()
		if err := decoder.Decode(&parameters); err != nil || parameters.Validate() != nil {
			http.Error(writer, "invalid training request", http.StatusUnprocessableEntity)
			return
		}
		result, err := approveTraining(ctx, parameters, user, false)
		if err != nil {
			http.Error(writer, err.Error(), http.StatusForbidden)
			return
		}
		grant := training.Grant{RunID: result.JobId, User: user, Request: parameters,
			ExpiresAt: time.Now().Add(time.Hour).Unix()}
		capability, err := training.Sign(grant, os.Getenv("TRAINING_SIGNING_KEY"))
		if err != nil {
			http.Error(writer, "training authorization configuration invalid", http.StatusInternalServerError)
			return
		}
		encoded, _ := json.Marshal(grant)
		if _, err := etcdClient.Put(ctx, "/training/approvals/"+grant.RunID, string(encoded)); err != nil {
			http.Error(writer, "could not persist training authorization", http.StatusInternalServerError)
			return
		}
		body, _ := json.Marshal(map[string]interface{}{
			"algorithm": parameters.Algorithm, "organizations": parameters.Organizations,
			"dataset_id": parameters.DatasetID, "rounds": parameters.Rounds,
			"local_epochs": parameters.LocalEpochs, "authorization": capability,
		})
		response, err := coordinatorRequest(ctx, http.MethodPost, "/runs", body)
		if err != nil {
			http.Error(writer, "could not start authorized training", http.StatusBadGateway)
			return
		}
		proxyTrainingResponse(writer, response)
		return
	}
	if path == "/revalidate" && request.Method == http.MethodPost {
		grant, err := training.Verify(request.Header.Get("X-Training-Authorization"), os.Getenv("TRAINING_SIGNING_KEY"))
		if err != nil || grant.User != user {
			http.Error(writer, "invalid training capability", http.StatusForbidden)
			return
		}
		stored, err := loadTrainingGrant(ctx, grant.RunID, user)
		actual, _ := json.Marshal(grant.Request)
		expected, _ := json.Marshal(stored.Request)
		if err != nil || !bytes.Equal(actual, expected) {
			http.Error(writer, "training plan does not match approved composition", http.StatusForbidden)
			return
		}
		if _, err := approveTraining(ctx, stored.Request, user, true); err != nil {
			http.Error(writer, "training permission revoked", http.StatusForbidden)
			return
		}
		writer.Header().Set("Content-Type", "application/json")
		io.WriteString(writer, `{"status":"authorized"}`)
		return
	}
	if path == "/runs" && request.Method == http.MethodGet {
		response, err := coordinatorRequest(ctx, http.MethodGet, "/runs", nil)
		if err != nil {
			http.Error(writer, "training coordinator unavailable", http.StatusBadGateway)
			return
		}
		defer response.Body.Close()
		var records []map[string]interface{}
		if response.StatusCode != 200 || json.NewDecoder(io.LimitReader(response.Body, 2<<20)).Decode(&records) != nil {
			http.Error(writer, "could not read training history", http.StatusBadGateway)
			return
		}
		visible := []map[string]interface{}{}
		for _, record := range records {
			runID, _ := record["id"].(string)
			if _, err := loadTrainingGrant(ctx, runID, user); err == nil {
				visible = append(visible, record)
			}
		}
		writer.Header().Set("Content-Type", "application/json")
		json.NewEncoder(writer).Encode(visible)
		return
	}
	segments := strings.Split(strings.Trim(path, "/"), "/")
	if len(segments) < 2 || len(segments) > 3 || segments[0] != "runs" {
		http.NotFound(writer, request)
		return
	}
	grant, err := loadTrainingGrant(ctx, segments[1], user)
	if err != nil {
		http.NotFound(writer, request)
		return
	}
	if len(segments) == 3 {
		if segments[2] == "model" && request.Method == http.MethodGet {
			if _, err := approveTraining(ctx, grant.Request, user, true); err != nil {
				http.Error(writer, "model download denied by current policies", http.StatusForbidden)
				return
			}
		} else if segments[2] != "cancel" || request.Method != http.MethodPost {
			http.NotFound(writer, request)
			return
		}
	} else if request.Method != http.MethodGet {
		writer.WriteHeader(http.StatusMethodNotAllowed)
		return
	}
	response, err := coordinatorRequest(ctx, request.Method, path, nil)
	if err != nil {
		http.Error(writer, "training coordinator unavailable", http.StatusBadGateway)
		return
	}
	proxyTrainingResponse(writer, response)
}
