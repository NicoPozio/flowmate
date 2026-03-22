FROM mariadb:11.7.2-ubi9

COPY init/ /docker-entrypoint-initdb.d/

HEALTHCHECK --start-period=10s --interval=10s --timeout=10s --retries=5 \
  CMD healthcheck.sh --connect --innodb_initialized