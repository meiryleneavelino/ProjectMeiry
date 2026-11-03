package main

import (
	"context"
	"sync"
	"testing"

	pb "github.com/Jorrit05/DYNAMOS/pkg/proto"
)

func TestTrainingSidecarStopsWithoutConsumer(t *testing.T) {
	t.Setenv("TEMPORARY_JOB", "true")
	stop = make(chan struct{})
	trainingStopOnce = &sync.Once{}
	sidecar := &serverInstance{}
	for attempt := 0; attempt < 2; attempt++ {
		if _, err := sidecar.StopReceivingRabbit(context.Background(), &pb.StopRequest{}); err != nil {
			t.Fatal(err)
		}
	}
	select {
	case <-stop:
	default:
		t.Fatal("temporary sidecar did not receive stop signal")
	}
}
