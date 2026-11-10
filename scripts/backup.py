"""Automated, encrypted database backup script for Snacky Studio.
Performs table dump, gzip compression, AES-256-GCM encryption, checksum validation,
and optional S3 bucket synchronization.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import create_engine, inspect, select, text

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backup")

TABLE_ORDER = [
    "alembic_version",
    "tenants",
    "users",
    "media_jobs",
    "audit_logs",
    "api_keys",
    "webhooks",
    "webhook_deliveries",
    "tenant_usage",
    "abuse_controls",
    "active_sessions",
]


def load_env_file():
    for fname in [".env.cloud", ".env"]:
        p = Path(fname)
        if p.is_file():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def derive_key(passphrase: str) -> bytes:
    """Derive 256-bit AES key from passphrase using SHA-256."""
    return hashlib.sha256(passphrase.encode("utf-8")).digest()


def dump_database_data(database_url: str) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int], str]:
    """Extract table rows, row counts, and alembic version from database."""
    engine = create_engine(database_url)
    data: dict[str, list[dict[str, Any]]] = {}
    row_counts: dict[str, int] = {}
    alembic_rev = "unknown"

    with engine.connect() as conn:
        insp = inspect(conn)
        existing_tables = set(insp.get_table_names())

        if "alembic_version" in existing_tables:
            try:
                rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
                if rev:
                    alembic_rev = str(rev)
            except Exception:
                pass

        for tbl in TABLE_ORDER:
            if tbl in existing_tables:
                rows = conn.execute(text(f'SELECT * FROM "{tbl}"')).mappings().all()
                serialized_rows = []
                for r in rows:
                    d = dict(r)
                    for k, v in d.items():
                        if isinstance(v, (datetime,)):
                            d[k] = v.isoformat()
                        elif isinstance(v, bytes):
                            d[k] = base64.b64encode(v).decode("ascii")
                    serialized_rows.append(d)
                data[tbl] = serialized_rows
                row_counts[tbl] = len(serialized_rows)
            else:
                row_counts[tbl] = 0

    engine.dispose()
    return data, row_counts, alembic_rev


def create_encrypted_backup(
    database_url: str,
    output_dir: Path,
    encryption_key: str,
    upload_s3: bool = False,
    s3_bucket: str | None = None,
) -> Path:
    """Create a compressed, AES-256-GCM encrypted backup file with metadata sidecar."""
    output_dir.mkdir(parents=True, exist_ok=True)
    start_time = time.time()
    now_utc = datetime.now(timezone.utc)
    timestamp_str = now_utc.strftime("%Y%m%d_%H%M%SZ")
    backup_basename = f"snacky_backup_{timestamp_str}"
    encrypted_file = output_dir / f"{backup_basename}.sql.gz.enc"
    meta_file = output_dir / f"{backup_basename}.meta.json"

    logger.info("Extracting database records from %s...", database_url.split("@")[-1] if "@" in database_url else database_url)
    dump_data, row_counts, alembic_rev = dump_database_data(database_url)

    # 1. Serialize to JSON and compress with Gzip
    raw_json = json.dumps({"version": 1, "alembic_version": alembic_rev, "tables": dump_data}, ensure_ascii=False)
    compressed_bytes = gzip.compress(raw_json.encode("utf-8"), compresslevel=9)

    # 2. Encrypt with AES-256-GCM
    key = derive_key(encryption_key)
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)  # 96-bit nonce for AES-GCM
    ciphertext = aesgcm.encrypt(nonce, compressed_bytes, None)

    # Write: [12 bytes nonce] + [ciphertext with authentication tag]
    encrypted_payload = nonce + ciphertext
    encrypted_file.write_bytes(encrypted_payload)

    # 3. Calculate SHA-256 checksum
    sha256_hash = hashlib.sha256(encrypted_payload).hexdigest()

    # 4. Write metadata sidecar
    duration = time.time() - start_time
    metadata = {
        "backup_name": backup_basename,
        "timestamp": now_utc.isoformat(),
        "alembic_version": alembic_rev,
        "encryption": "AES-256-GCM",
        "compression": "gzip-9",
        "sha256": sha256_hash,
        "size_bytes": len(encrypted_payload),
        "duration_seconds": round(duration, 3),
        "row_counts": row_counts,
        "total_records": sum(row_counts.values()),
    }
    meta_file.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    logger.info(
        "Backup created: %s (%d bytes, %d records, duration: %.2fs)",
        encrypted_file.name,
        len(encrypted_payload),
        metadata["total_records"],
        duration,
    )

    # 5. Optional S3 upload
    if upload_s3 and s3_bucket:
        try:
            import boto3
            s3 = boto3.client("s3")
            s3_key_enc = f"backups/postgres/{encrypted_file.name}"
            s3_key_meta = f"backups/postgres/{meta_file.name}"
            logger.info("Uploading backup to s3://%s/%s...", s3_bucket, s3_key_enc)
            s3.upload_file(str(encrypted_file), s3_bucket, s3_key_enc)
            s3.upload_file(str(meta_file), s3_bucket, s3_key_meta)
            logger.info("Successfully uploaded backup to S3.")
        except Exception as exc:
            logger.error("Failed to upload backup to S3: %s", exc)

    return encrypted_file


def main():
    load_env_file()
    parser = argparse.ArgumentParser(description="Snacky Studio Automated Encrypted Database Backup")
    parser.add_argument("--db-url", default=os.getenv("SNACKY_DATABASE_URL"), help="PostgreSQL connection string")
    parser.add_argument("--output-dir", default="./backups", help="Directory where backups are stored")
    parser.add_argument("--key", default=os.getenv("BACKUP_ENCRYPTION_KEY", "snacky_production_vault_key_2026"), help="Backup encryption key")
    parser.add_argument("--upload-s3", action="store_true", help="Upload backup to S3 bucket")
    parser.add_argument("--s3-bucket", default=os.getenv("SNACKY_BACKUP_S3_BUCKET"), help="Target S3 backup bucket")

    args = parser.parse_args()
    if not args.db_url:
        logger.error("No database URL provided. Set SNACKY_DATABASE_URL or pass --db-url.")
        sys.exit(1)

    create_encrypted_backup(
        database_url=args.db_url,
        output_dir=Path(args.output_dir),
        encryption_key=args.key,
        upload_s3=args.upload_s3,
        s3_bucket=args.s3_bucket,
    )


if __name__ == "__main__":
    main()
