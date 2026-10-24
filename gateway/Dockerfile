# build
FROM golang:1.22-alpine AS build
WORKDIR /src
COPY go.mod ./
RUN go mod download || true
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/gateway .

# run
FROM alpine:3.20
RUN apk add --no-cache wget ca-certificates
COPY --from=build /out/gateway /usr/local/bin/gateway
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=6s --retries=5 \
  CMD wget -qO- http://127.0.0.1:8080/api/v1/health >/dev/null 2>&1 || exit 1
ENTRYPOINT ["/usr/local/bin/gateway"]
