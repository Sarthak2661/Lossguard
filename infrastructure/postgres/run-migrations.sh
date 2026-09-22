#!/bin/sh
set -eu

psql_base="psql -h postgres -U ${POSTGRES_USER:-lossguard} -d ${POSTGRES_DB:-lossguard} -v ON_ERROR_STOP=1"

$psql_base -c "CREATE TABLE IF NOT EXISTS schema_migrations (
  version TEXT PRIMARY KEY,
  checksum TEXT NOT NULL,
  applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)"

for migration in /migrations/*.sql; do
  version=$(basename "$migration")
  checksum=$(sha256sum "$migration" | awk '{print $1}')
  case "$version" in
    *[!A-Za-z0-9_.-]*) echo "Unsafe migration filename: $version" >&2; exit 1 ;;
  esac
  stored=$($psql_base -At -c "SELECT checksum FROM schema_migrations WHERE version = '$version'")
  if [ -n "$stored" ]; then
    if [ "$stored" != "$checksum" ]; then
      echo "Applied migration $version has changed; refusing to continue" >&2
      exit 1
    fi
    continue
  fi
  echo "Applying $version"
  $psql_base -1 -v grafana_reader_password="$GRAFANA_READER_PASSWORD" -f "$migration"
  $psql_base -c "INSERT INTO schema_migrations(version, checksum) VALUES ('$version', '$checksum')"
done
