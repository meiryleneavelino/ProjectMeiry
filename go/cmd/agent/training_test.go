package main

import (
	"math"
	"testing"
)

func TestTrainingResultHasBoundedModelFields(t *testing.T) {
	update := localModelUpdate{Coefficients: []float64{1, 2, 3, 4}, Intercept: 0, Samples: 192, Accuracy: 0.9, ValidationLoss: 0.2}
	if err := validateLocalUpdate(update); err != nil {
		t.Fatal(err)
	}
	update.Coefficients[0] = math.NaN()
	if validateLocalUpdate(update) == nil {
		t.Fatal("non-finite model value accepted")
	}
	update.Coefficients[0] = 1
	update.Samples = 0
	if validateLocalUpdate(update) == nil {
		t.Fatal("empty sample count accepted")
	}
}

func TestRoundNameCannotEscapeLocalStateDirectory(t *testing.T) {
	if !validTrainingRoundName("training-0123456789abcdef-r3") {
		t.Fatal("valid local round rejected")
	}
	for _, name := range []string{"../../other-org", "training-0123456789abcdef-r99", "training-nothex-r1"} {
		if validTrainingRoundName(name) {
			t.Fatalf("invalid round name accepted: %s", name)
		}
	}
}
