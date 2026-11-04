# fhir-abac chaincode-as-a-service image. The static binary is built on the
# host by "tools.py deploy-cc" (Go module cache, offline): nothing is downloaded.
FROM scratch
COPY build/fhir-abac /fhir-abac
USER 65532:65532
EXPOSE 9999
ENTRYPOINT ["/fhir-abac"]
