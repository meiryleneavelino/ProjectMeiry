package main

import (
	"encoding/json"
	"testing"

	"github.com/Jorrit05/DYNAMOS/pkg/api"
	pb "github.com/Jorrit05/DYNAMOS/pkg/proto"
	"google.golang.org/protobuf/types/known/structpb"
)

func TestTrainingAgreementRetainsAlgorithmPermissions(t *testing.T) {
	encoded := []byte(`{"name":"UVA","relations":{"sandbox-researcher":{"allowedAlgorithms":["logistic-regression-v1"]}}}`)
	var agreement api.Agreement
	if err := json.Unmarshal(encoded, &agreement); err != nil {
		t.Fatal(err)
	}
	saved, err := json.Marshal(agreement)
	if err != nil {
		t.Fatal(err)
	}
	var restored api.Agreement
	if err := json.Unmarshal(saved, &restored); err != nil {
		t.Fatal(err)
	}
	algorithms := restored.Relations["sandbox-researcher"].AllowedAlgorithms
	if len(algorithms) != 1 || algorithms[0] != "logistic-regression-v1" {
		t.Fatal("agreement seeding dropped training algorithm permissions")
	}
}

func TestTrainingRequiresEveryOrganizationAndLocalArchetype(t *testing.T) {
	metadata, _ := structpb.NewStruct(map[string]interface{}{
		"algorithm": "logistic-regression-v1", "dataset_id": "synthetic-local-v1",
		"organizations": []interface{}{"UVA", "TUDELFT"}, "rounds": 3, "local_epochs": 2,
	})
	response := &pb.ValidationResponse{RequestApproved: true, Training: metadata,
		ValidDataproviders: map[string]*pb.DataProvider{
			"UVA": {Archetypes: []string{"computeToData"}}, "TUDELFT": {Archetypes: []string{"computeToData"}},
		}}
	if err := validateTrainingApproval(response); err != nil {
		t.Fatal(err)
	}
	delete(response.ValidDataproviders, "TUDELFT")
	if validateTrainingApproval(response) == nil {
		t.Fatal("partially authorized training accepted")
	}
	response.ValidDataproviders["TUDELFT"] = &pb.DataProvider{Archetypes: []string{"dataThroughTtp"}}
	if validateTrainingApproval(response) == nil {
		t.Fatal("data transfer archetype accepted for local training")
	}
}
