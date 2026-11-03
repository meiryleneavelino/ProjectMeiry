import base64
import hashlib
import hmac
import json
import time


def verify_capability(token, key, parameters):
    if not token or len(key) < 32:
        raise ValueError("DYNAMOS approval is required")
    encoded, signature = token.split(".")
    actual = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
    expected = hmac.new(key.encode(), encoded.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(actual, expected):
        raise ValueError("Invalid DYNAMOS approval signature")
    grant = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    if grant["expires_at"] <= time.time() or not grant["user"]:
        raise ValueError("DYNAMOS approval expired")
    submitted = {name: parameters[name] for name in
                 ("algorithm", "organizations", "dataset_id", "rounds", "local_epochs")}
    if grant["request"] != submitted:
        raise ValueError("Parameters differ from the approved DYNAMOS composition")
    return grant


def send_via_sidecar(update, request, organization):
    import grpc
    import rabbitMQ_pb2 as messages
    import rabbitMQ_pb2_grpc as services
    import microserviceCommunication_pb2 as communication
    import generic_pb2 as generic
    from google.protobuf.struct_pb2 import Struct

    with grpc.insecure_channel("localhost:50051") as channel:
        grpc.channel_ready_future(channel).result(timeout=30)
        sidecar = services.RabbitMQStub(channel)
        queue = request["name"] + "-sender"
        sidecar.InitRabbitMq(messages.InitRequest(service_name=queue, routing_key=queue, queue_auto_delete=True), timeout=20)
        data = Struct()
        data.update(update)
        sidecar.SendMicroserviceComm(communication.MicroserviceCommunication(
            type="microserviceCommunication", request_type="mlTrainingRequest", data=data,
            metadata={"round_name": request["name"], "result_token": request["callback_token"]},
            request_metadata=generic.RequestMetadata(destination_queue=organization + "-in",
                                                     correlation_id=request["name"], job_id=request["run_id"]),
        ), timeout=20)
        sidecar.DeleteQueue(messages.QueueInfo(queue_name=queue), timeout=10)
        sidecar.StopReceivingRabbit(messages.StopRequest(), timeout=10)