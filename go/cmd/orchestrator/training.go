package main

import (
	"encoding/json"
	"errors"
	"slices"

	pb "github.com/Jorrit05/DYNAMOS/pkg/proto"
	"github.com/Jorrit05/DYNAMOS/pkg/training"
)

func validateTrainingApproval(response *pb.ValidationResponse) error {
	if !response.RequestApproved || response.Training == nil || len(response.InvalidDataproviders) != 0 {
		return errors.New("training authorization denied")
	}
	var request training.Request
	encoded, err := json.Marshal(response.Training.AsMap())
	if err != nil || json.Unmarshal(encoded, &request) != nil || request.Validate() != nil {
		return errors.New("invalid training authorization")
	}
	if len(response.ValidDataproviders) != len(request.Organizations) {
		return errors.New("all selected organizations must authorize training")
	}
	for _, organization := range request.Organizations {
		provider := response.ValidDataproviders[organization]
		if provider == nil || !slices.Contains(provider.Archetypes, "computeToData") {
			return errors.New("local training is not authorized for every organization")
		}
	}
	return nil
}
