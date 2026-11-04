FROM golang:1.23-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go test ./... && CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/horus-ledger ./cmd/horus-ledger

FROM alpine:3.20
RUN addgroup -g 1000 horus && adduser -D -u 1000 -G horus horus
COPY --from=build /out/horus-ledger /usr/local/bin/horus-ledger
USER 1000:1000
ENTRYPOINT ["/usr/local/bin/horus-ledger"]
