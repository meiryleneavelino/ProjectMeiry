// fhir-abac runs the PAP/PIP/PDP chaincode as a service (chaincode-as-a-service):
// each organization runs its own copy next to its peer, and every write needs
// matching endorsements from HospitalMSP AND LabMSP.
package main

import (
	"log"
	"os"
	"strings"
	"time"

	"github.com/hyperledger/fabric-chaincode-go/v2/pkg/cid"
	"github.com/hyperledger/fabric-chaincode-go/v2/shim"
	"github.com/hyperledger/fabric-protos-go-apiv2/peer"

	"fhir-abac/abac"
)

type chaincode struct{}

func (chaincode) Init(shim.ChaincodeStubInterface) *peer.Response { return shim.Success(nil) }

func (chaincode) Invoke(stub shim.ChaincodeStubInterface) *peer.Response {
	function, args := stub.GetFunctionAndParameters()
	result, err := abac.Invoke(&context{stub}, function, args)
	if err != nil {
		return shim.Error(err.Error())
	}
	return shim.Success(result)
}

// context adapts the Fabric stub to abac.Context.
type context struct{ stub shim.ChaincodeStubInterface }

func (c *context) GetState(key string) ([]byte, error)        { return c.stub.GetState(key) }
func (c *context) PutState(key string, value []byte) error    { return c.stub.PutState(key, value) }
func (c *context) SetEvent(name string, payload []byte) error { return c.stub.SetEvent(name, payload) }
func (c *context) MSPID() (string, error)                     { return cid.GetMSPID(c.stub) }
func (c *context) TxID() string                               { return c.stub.GetTxID() }
func (c *context) Attribute(name string) (string, bool, error) {
	return cid.GetAttributeValue(c.stub, name)
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

func main() {
	address, id := os.Getenv("CHAINCODE_SERVER_ADDRESS"), os.Getenv("CHAINCODE_ID")
	if address == "" || id == "" {
		log.Fatal("CHAINCODE_SERVER_ADDRESS and CHAINCODE_ID are required")
	}
	server := &shim.ChaincodeServer{CCID: id, Address: address, CC: chaincode{},
		TLSProps: shim.TLSProperties{Disabled: true}}
	log.Printf("fhir-abac chaincode %s listening on %s", id, address)
	if err := server.Start(); err != nil {
		log.Fatal(err)
	}
}
