#!/usr/bin/env bash
# ============================================================
# NEXUS Intelligence Platform — HashiCorp Vault Key Management
# Configures PKI, transit encryption, and Kubernetes auth.
# ============================================================

# Enable PKI secrets engine for TLS certificates
vault secrets enable -path=nexus-pki pki
vault secrets tune -max-lease-ttl=8760h nexus-pki

# Configure certificate authority (offline root, online intermediate)
vault write nexus-pki/root/generate/internal \
    common_name="NEXUS Root CA" \
    ttl=87600h key_bits=4096 key_type=rsa

# Create role for API service certificates (90-day TTL)
vault write nexus-pki/roles/nexus-api \
    allowed_domains="nexus.mil.local" \
    allow_subdomains=true \
    max_ttl=2160h key_bits=4096

# Enable transit secrets engine for database key management
vault secrets enable transit
vault write transit/keys/nexus-db-key type=aes256-gcm96

# Application role with least-privilege policy
vault policy write nexus-app - <<EOF
path "transit/encrypt/nexus-db-key" { capabilities = ["update"] }
path "transit/decrypt/nexus-db-key" { capabilities = ["update"] }
path "nexus-pki/issue/nexus-api"    { capabilities = ["update"] }
path "secret/data/nexus/*"          { capabilities = ["read"] }
EOF

# Kubernetes auth method for pod identity
vault auth enable kubernetes
vault write auth/kubernetes/config \
    kubernetes_host="https://k8s.nexus.mil.local:6443" \
    kubernetes_ca_cert=@/var/run/secrets/kubernetes.io/serviceaccount/ca.crt

vault write auth/kubernetes/role/nexus-api \
    bound_service_account_names=nexus-api \
    bound_service_account_namespaces=nexus-prod \
    policies=nexus-app \
    ttl=1h
