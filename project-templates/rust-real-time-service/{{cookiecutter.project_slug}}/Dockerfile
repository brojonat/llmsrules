# A static musl binary on an empty base image. cargo-chef builds the
# dependencies in their own layer, so editing src/ doesn't recompile them.

FROM rust:1-alpine AS chef
RUN apk add --no-cache musl-dev && cargo install cargo-chef --locked
WORKDIR /app

FROM chef AS planner
COPY . .
RUN cargo chef prepare --recipe-path recipe.json

FROM chef AS builder
COPY --from=planner /app/recipe.json recipe.json
RUN cargo chef cook --release --locked --recipe-path recipe.json
COPY . .
RUN cargo build --release --locked && \
    cp target/release/{{cookiecutter.project_slug}} /server && \
    mkdir /data

FROM scratch
COPY --from=builder /server /server
# The SQLite file lives here; mount a volume over it to keep it.
COPY --from=builder --chown=65534:65534 /data /data
USER 65534:65534
ENV DATABASE_URL=sqlite:///data/app.db
EXPOSE {{cookiecutter.default_port}}
ENTRYPOINT ["/server"]
