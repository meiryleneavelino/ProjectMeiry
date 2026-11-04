// Package memledger runs the real governance rules on an in-memory state so
// agents and the HTTP gateway can be tested without a Fabric network.
package memledger

import (
	"encoding/json"
	"fmt"
	"sort"
	"strings"
	"sync"
	"time"

	"horus-ledger/governance"
	"horus-ledger/internal/fabclient"
)

type World struct {
	mutex sync.Mutex
	State map[string][]byte
	Clock time.Time
	tx    int
	Local *governance.Config
}

func New(config *governance.Config) (*World, error) {
	world := &World{State: map[string][]byte{}, Clock: time.Date(2026, 11, 3, 12, 0, 0, 0, time.UTC), Local: config}
	raw, _ := json.Marshal(config)
	admin := world.As(config.Organizations["TUDELFT"], "", true)
	if _, _, err := admin.Submit("InitConfig", string(raw)); err != nil {
		return nil, err
	}
	return world, nil
}

// Identity is one caller; it implements both governance.Context and the
// Evaluate/Submit interface used by the agent and gateway.
type Identity struct {
	world *World
	MSP   string
	Role  string
	Admin bool
	txID  string
	stamp time.Time
}

func (w *World) As(msp, role string, admin bool) *Identity {
	return &Identity{world: w, MSP: msp, Role: role, Admin: admin}
}

func (i *Identity) GetState(key string) ([]byte, error) { return i.world.State[key], nil }
func (i *Identity) PutState(key string, value []byte) error {
	i.world.State[key] = append([]byte(nil), value...)
	return nil
}
func (i *Identity) Range(prefix string) ([][]byte, error) {
	var keys []string
	for key := range i.world.State {
		if strings.HasPrefix(key, prefix) {
			keys = append(keys, key)
		}
	}
	sort.Strings(keys)
	values := make([][]byte, len(keys))
	for index, key := range keys {
		values[index] = i.world.State[key]
	}
	return values, nil
}
func (i *Identity) MSPID() (string, error)                   { return i.MSP, nil }
func (i *Identity) Attribute(string) (string, bool, error)   { return i.Role, i.Role != "", nil }
func (i *Identity) IsAdmin() (bool, error)                   { return i.Admin, nil }
func (i *Identity) ClientID() (string, error)                { return "x509::" + i.MSP + "::" + i.Role, nil }
func (i *Identity) TxID() string                             { return i.txID }
func (i *Identity) Timestamp() (time.Time, error)            { return i.stamp, nil }
func (i *Identity) LocalConfig() (*governance.Config, error) { return i.world.Local, nil }

// run executes like a peer would: on a copy of the state, committed only on
// success, so a failed transaction never leaves partial writes.
func (i *Identity) run(function string, args []string, commit bool) ([]byte, fabclient.Receipt, error) {
	i.world.mutex.Lock()
	defer i.world.mutex.Unlock()
	i.world.tx++
	i.world.Clock = i.world.Clock.Add(time.Second)
	snapshot := make(map[string][]byte, len(i.world.State))
	for key, value := range i.world.State {
		snapshot[key] = value
	}
	caller := *i
	caller.txID, caller.stamp = fmt.Sprintf("%064x", i.world.tx), i.world.Clock
	result, err := governance.Invoke(&caller, function, args)
	if err != nil || !commit {
		i.world.State = snapshot
		return result, fabclient.Receipt{}, fabclient.Clean(err)
	}
	return result, fabclient.Receipt{TxID: caller.txID, BlockNumber: uint64(i.world.tx)}, nil
}

func (i *Identity) Evaluate(function string, args ...string) ([]byte, error) {
	result, _, err := i.run(function, args, false)
	return result, err
}

func (i *Identity) Submit(function string, args ...string) ([]byte, fabclient.Receipt, error) {
	return i.run(function, args, true)
}
