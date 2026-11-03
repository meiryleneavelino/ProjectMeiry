package training

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"slices"
	"strings"
	"time"
)

const RequestType = "mlTrainingRequest"
const Algorithm = "logistic-regression-v1"
const Dataset = "synthetic-local-v1"

type Request struct {
	Algorithm     string   `json:"algorithm"`
	Organizations []string `json:"organizations"`
	DatasetID     string   `json:"dataset_id"`
	Rounds        int      `json:"rounds"`
	LocalEpochs   int      `json:"local_epochs"`
}

type Grant struct {
	RunID     string  `json:"run_id"`
	User      string  `json:"user"`
	Request   Request `json:"request"`
	ExpiresAt int64   `json:"expires_at"`
}

func (request Request) Validate() error {
	if request.Algorithm != Algorithm || request.DatasetID != Dataset {
		return errors.New("algorithm or dataset is not in the approved catalog")
	}
	if request.Rounds < 1 || request.Rounds > 10 || request.LocalEpochs < 1 || request.LocalEpochs > 5 {
		return errors.New("training parameters are outside the approved limits")
	}
	if len(request.Organizations) < 2 || len(request.Organizations) > 3 {
		return errors.New("select two or three organizations")
	}
	seen := make(map[string]bool)
	for _, organization := range request.Organizations {
		if !slices.Contains([]string{"UVA", "VU", "TUDELFT"}, organization) || seen[organization] {
			return errors.New("unknown or duplicate organization")
		}
		seen[organization] = true
	}
	return nil
}

func (request Request) AllowedBy(requestTypes, datasets, algorithms, archetypes []string) bool {
	return request.Validate() == nil && slices.Contains(requestTypes, RequestType) &&
		slices.Contains(datasets, request.DatasetID) && slices.Contains(algorithms, request.Algorithm) &&
		slices.Contains(archetypes, "computeToData")
}

func Sign(grant Grant, key string) (string, error) {
	if len(key) < 32 || grant.User == "" || grant.RunID == "" || grant.Request.Validate() != nil {
		return "", errors.New("invalid training grant")
	}
	payload, err := json.Marshal(grant)
	if err != nil {
		return "", err
	}
	encoded := base64.RawURLEncoding.EncodeToString(payload)
	mac := hmac.New(sha256.New, []byte(key))
	mac.Write([]byte(encoded))
	return encoded + "." + base64.RawURLEncoding.EncodeToString(mac.Sum(nil)), nil
}

func Verify(token, key string) (Grant, error) {
	var grant Grant
	parts := strings.Split(token, ".")
	if len(parts) != 2 || len(key) < 32 {
		return grant, errors.New("invalid training capability")
	}
	signature, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		return grant, err
	}
	mac := hmac.New(sha256.New, []byte(key))
	mac.Write([]byte(parts[0]))
	if !hmac.Equal(signature, mac.Sum(nil)) {
		return grant, errors.New("invalid training signature")
	}
	payload, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil {
		return grant, err
	}
	if err = json.Unmarshal(payload, &grant); err != nil {
		return grant, err
	}
	if grant.ExpiresAt <= time.Now().Unix() || grant.User == "" || grant.RunID == "" {
		return grant, errors.New("expired or incomplete training capability")
	}
	if err := grant.Request.Validate(); err != nil {
		return grant, fmt.Errorf("invalid training request: %w", err)
	}
	return grant, nil
}
