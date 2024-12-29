FROM rust:latest AS builder
WORKDIR /usr/src/papersmith

COPY src src
COPY Cargo.toml Cargo.toml
COPY Cargo.lock Cargo.lock

RUN cargo build --bin papersmith --release

FROM ubuntu:22.04
RUN apt-get update && apt-get install -y poppler-utils ca-certificates
COPY --from=builder /usr/src/papersmith/target/release/papersmith /usr/local/bin/papersmith

ENTRYPOINT ["/usr/local/bin/papersmith"]
