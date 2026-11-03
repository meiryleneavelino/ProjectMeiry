FROM golang:1.23-bookworm AS builder
WORKDIR /src
COPY go/go.mod go/go.sum ./
COPY go/pkg ./pkg
COPY go/cmd/api-gateway ./cmd/api-gateway
COPY go/cmd/orchestrator ./cmd/orchestrator
COPY go/cmd/policy-enforcer ./cmd/policy-enforcer
COPY go/cmd/agent ./cmd/agent
COPY go/cmd/sidecar ./cmd/sidecar
RUN --mount=type=cache,target=/root/.cache/go-build --mount=type=cache,target=/go/pkg/mod \
    mkdir /app && for service in api-gateway orchestrator policy-enforcer agent sidecar; do \
    CGO_ENABLED=0 go build -o /app/$service ./cmd/$service; done
FROM alpine:3.21
RUN apk add --no-cache ca-certificates && adduser -D -u 10001 dynamos
COPY --from=builder /app /app
USER 10001
WORKDIR /app