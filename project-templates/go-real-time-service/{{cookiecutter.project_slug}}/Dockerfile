FROM golang:1.24-alpine AS builder

RUN apk update && apk add --no-cache git ca-certificates make
RUN update-ca-certificates

WORKDIR /app

COPY go.mod go.sum ./
RUN go mod download

COPY . .

# templ code and the stylesheet are generated, not committed, so codegen has to
# run before the compile. Same two targets the local build uses.
RUN make generate css

RUN CGO_ENABLED=0 GOOS=linux go build -tags=prod -ldflags="-w -s" -o /bin/app ./cmd/server

FROM alpine:latest

COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
COPY --from=builder /bin/app /app

EXPOSE 8080

ENTRYPOINT ["/app"]
CMD ["server"]
