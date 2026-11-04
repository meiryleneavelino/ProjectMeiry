# fhir-gateway image: static binary built on the host by tools.py (offline).
FROM scratch
COPY build/fhir-gateway /fhir-gateway
USER 65532:65532
EXPOSE 8080
ENTRYPOINT ["/fhir-gateway"]
