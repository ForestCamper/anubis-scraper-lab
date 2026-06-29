FROM ghcr.io/techarohq/anubis:latest

# NOTE: this base image is distroless and runs as non-root (uid 1000). It has no
# shell, so RUN steps are impossible, and uid 1000 cannot create/own /data. We
# therefore use the in-memory store (see policies.yaml) and only copy the policy in.

# Copy policy configuration
COPY policies.yaml /etc/anubis/policies.yaml

# Expose Anubis ports
EXPOSE 8923
EXPOSE 9090

# Entrypoint (/ko-app/anubis) is already set by the base image.
