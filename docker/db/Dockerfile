# PostGIS 16 + pgvector (same Postgres major version as before, so the existing data volume is reused).
# The base image is Debian bullseye, whose PostgreSQL apt repo moved to apt-archive.postgresql.org;
# we point apt there. If pgvector still cannot be installed the image still builds (plain PostGIS)
# and the RAG vector search runs in memory instead of pgvector - the app keeps working.
FROM postgis/postgis:16-3.4
RUN set -eux; \
    grep -rl "apt.postgresql.org" /etc/apt 2>/dev/null | xargs -r sed -i 's|apt.postgresql.org|apt-archive.postgresql.org|g'; \
    apt-get -o Acquire::Check-Valid-Until=false update || true; \
    (apt-get install -y --no-install-recommends postgresql-16-pgvector \
       || echo "WARNING: pgvector not installed - RAG will use in-memory vectors"); \
    rm -rf /var/lib/apt/lists/*
