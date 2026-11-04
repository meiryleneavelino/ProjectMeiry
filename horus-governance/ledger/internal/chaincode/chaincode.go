// Package chaincode runs the governance rules as a Fabric chaincode service
// (chaincode-as-a-service): every organization runs its own copy next to its
// peer, and endorsements from a majority of those copies must agree.
package chaincode

import (
	"encoding/json"
	"fmt"
	"log"
	"os"
	"strings"
	"time"

	"github.com/hyperledger/fabric-chaincode-go/v2/pkg/cid"
	"github.com/hyperledger/fabric-chaincode-go/v2/shim"
	"github.com/hyperledger/fabric-protos-go-apiv2/peer"

	"horus-ledger/governance"
)

type contract struct {
	configPath string
}

func (c *contract) Init(shim.ChaincodeStubInterface) *peer.Response { return shim.Success(nil) }

func (c *contract) Invoke(stub shim.ChaincodeStubInterface) *peer.Response {
	function, args := stub.GetFunctionAndParameters()
	result, err := governance.Invoke(&context{stub: stub, configPath: c.configPath}, function, args)
	if err != nil {
		return shim.Error(err.Error())
	}
	return shim.Success(result)
}

type context struct {
	stub       shim.ChaincodeStubInterface
	configPath string
}

func (c *context) GetState(key string) ([]byte, error)     { return c.stub.GetState(key) }
func (c *context) PutState(key string, value []byte) error { return c.stub.PutState(key, value) }
func (c *context) MSPID() (string, error)                  { return cid.GetMSPID(c.stub) }
func (c *context) ClientID() (string, error)               { return cid.GetID(c.stub) }
func (c *context) TxID() string                            { return c.stub.GetTxID() }
func (c *context) Attribute(name string) (string, bool, error) {
	return cid.GetAttributeValue(c.stub, name)
}

// IsAdmin checks the NodeOU "admin" in the caller's X.509 certificate.
func (c *context) IsAdmin() (bool, error) {
	certificate, err := cid.GetX509Certificate(c.stub)
	if err != nil {
		return false, err
	}
	for _, unit := range certificate.Subject.OrganizationalUnit {
		if unit == "admin" {
			return true, nil
		}
	}
	return false, nil
}

func (c *context) Timestamp() (time.Time, error) {
	stamp, err := c.stub.GetTxTimestamp()
	if err != nil {
		return time.Time{}, err
	}
	return stamp.AsTime(), nil
}

// Range scans simple keys between prefix and the next possible prefix.
func (c *context) Range(prefix string) ([][]byte, error) {
	end := prefix[:len(prefix)-1] + string(prefix[len(prefix)-1]+1)
	iterator, err := c.stub.GetStateByRange(prefix, end)
	if err != nil {
		return nil, err
	}
	defer iterator.Close()
	var values [][]byte
	for iterator.HasNext() {
		item, err := iterator.Next()
		if err != nil {
			return nil, err
		}
		if strings.HasPrefix(item.Key, prefix) {
			values = append(values, item.Value)
		}
	}
	return values, nil
}

func (c *context) LocalConfig() (*governance.Config, error) {
	raw, err := os.ReadFile(c.configPath)
	if err != nil {
		return nil, err
	}
	var config governance.Config
	decoder := json.NewDecoder(strings.NewReader(string(raw)))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&config); err != nil {
		return nil, err
	}
	return &config, nil
}

// Serve starts the chaincode gRPC server the peer dials (see connection.json).
func Serve() error {
	address, id := os.Getenv("CHAINCODE_SERVER_ADDRESS"), os.Getenv("CHAINCODE_ID")
	configPath := os.Getenv("HORUS_CONFIG")
	if address == "" || id == "" || configPath == "" {
		return fmt.Errorf("CHAINCODE_SERVER_ADDRESS, CHAINCODE_ID and HORUS_CONFIG are required")
	}
	if _, err := (&context{configPath: configPath}).LocalConfig(); err != nil {
		return fmt.Errorf("local governance configuration is invalid: %w", err)
	}
	server := &shim.ChaincodeServer{CCID: id, Address: address, CC: &contract{configPath: configPath},
		TLSProps: shim.TLSProperties{Disabled: true}}
	log.Printf("horus governance chaincode %s listening on %s", id, address)
	return server.Start()
}
