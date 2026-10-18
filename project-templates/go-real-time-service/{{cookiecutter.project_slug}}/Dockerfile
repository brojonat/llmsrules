FROM golang:1.25-alpine AS builder

RUN apk update && apk add --no-cache git ca-certificates curl
RUN update-ca-certificates

WORKDIR /app

COPY go.mod go.sum ./
RUN go mod download

COPY . .

# templ code and the stylesheet are generated, not committed, so codegen has to
# run before the compile. Same steps as `mise run generate css`.
RUN go tool templ generate && \
    scripts/vendor.sh && \
    go tool gotailwind -i web/resources/styles/styles.css -o web/resources/static/index.css

RUN CGO_ENABLED=0 GOOS=linux go build -tags=prod -ldflags="-w -s" -o /bin/app ./cmd/server

FROM alpine:latest

COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
COPY --from=builder /bin/app /app

EXPOSE 8080

ENTRYPOINT ["/app"]
CMD ["server"]
