"""Automated restore verification script for Snacky Studio.
Verifies SHA-256 checksum, decrypts AES-256-GCM payload, decompresses gzip,
restores into an isolated temporary verification schema, checks data integrity,
and measures RTO (Recovery Time Objective) compliance.
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
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import create_engine, inspect, text

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("restore_verify")

# RTO Target: Recovery Time Objective <= 15 minutes (900 seconds)
RTO_TARGET_SECONDS = 900.0


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
    return hashlib.sha256(passphrase.encode("utf-8")).digest()


def verify_and_restore(
    backup_file: Path,
    encryption_key: str,
    database_url: str | None = None,
    verify_in_db: bool = True,
) -> dict[str, Any]:
    """Decrypt, decompress, and verify backup file integrity and database restorable state."""
    start_time = time.time()
    base_stem = backup_file.name.split(".sql")[0]
    meta_file = backup_file.parent / f"{base_stem}.meta.json"

    logger.info("Reading backup file: %s", backup_file.name)
    if not backup_file.exists():
        raise FileNotFoundError(f"Backup file not found: {backup_file}")

    raw_encrypted = backup_file.read_bytes()

    # 1. Verify Checksum against metadata if present
    file_sha256 = hashlib.sha256(raw_encrypted).hexdigest()
    if meta_file.exists():
        metadata = json.loads(meta_file.read_text(encoding="utf-8"))
        expected_sha = metadata.get("sha256")
        if expected_sha and expected_sha != file_sha256:
            raise ValueError(f"Checksum mismatch! Expected {expected_sha}, got {file_sha256}")
        logger.info("SHA-256 Checksum verified: %s", file_sha256)
    else:
        metadata = {}
        logger.warning("No metadata sidecar found; skipping checksum pre-validation")

    # 2. Decrypt with AES-256-GCM
    if len(raw_encrypted) < 28:  # 12 nonce + 16 tag minimum
        raise ValueError("Corrupt backup file: payload is too small for AES-GCM")

    nonce = raw_encrypted[:12]
    ciphertext = raw_encrypted[12:]
    key = derive_key(encryption_key)
    aesgcm = AESGCM(key)

    try:
        compressed_bytes = aesgcm.decrypt(nonce, ciphertext, None)
    except Exception as exc:
        raise ValueError(f"Decryption failed! Invalid encryption key or corrupt payload: {exc}") from exc

    logger.info("AES-256-GCM payload successfully authenticated and decrypted")

    # 3. Decompress Gzip
    try:
        raw_json = gzip.decompress(compressed_bytes).decode("utf-8")
        backup_content = json.loads(raw_json)
    except Exception as exc:
        raise ValueError(f"Decompression or JSON parse failed: {exc}") from exc

    tables_data = backup_content.get("tables", {})
    alembic_rev = backup_content.get("alembic_version", "unknown")
    logger.info("Backup parsed successfully. Alembic revision: %s, Tables: %d", alembic_rev, len(tables_data))

    restored_counts: dict[str, int] = {}
    db_verification_status = "skipped"

    # 4. Optional Live Database Schema Restoration Test
    if verify_in_db and database_url:
        logger.info("Initiating live database restore verification in isolated test schema...")
        engine = create_engine(database_url)
        temp_schema = f"restore_verify_{uuid.uuid4().hex[:8]}"

        with engine.begin() as conn:
            # Create isolated test schema
            conn.execute(text(f'CREATE SCHEMA "{temp_schema}"'))

            try:
                # Replicate table structures from public schema into temp schema
                insp = inspect(conn)
                public_tables = insp.get_table_names(schema="public")

                for table_name in tables_data.keys():
                    if table_name in public_tables:
                        conn.execute(
                            text(f'CREATE TABLE "{temp_schema}"."{table_name}" (LIKE "public"."{table_name}" INCLUDING ALL)')
                        )

                        rows = tables_data[table_name]
                        if rows:
                            # Insert rows into temp table
                            cols = list(rows[0].keys())
                            col_identifiers = ", ".join([f'"{c}"' for c in cols])
                            param_placeholders = ", ".join([f":{c}" for c in cols])
                            insert_sql = text(
                                f'INSERT INTO "{temp_schema}"."{table_name}" ({col_identifiers}) VALUES ({param_placeholders})'
                            )

                            # Format parameters for json and byte columns
                            sanitized_rows = []
                            for r in rows:
                                clean_r = dict(r)
                                for k, v in clean_r.items():
                                    if isinstance(v, dict):
                                        clean_r[k] = json.dumps(v)
                                sanitized_rows.append(clean_r)

                            conn.execute(insert_sql, sanitized_rows)

                        # Count rows in restored schema
                        count = conn.execute(text(f'SELECT COUNT(*) FROM "{temp_schema}"."{table_name}"')).scalar()
                        restored_counts[table_name] = count or 0

                db_verification_status = "passed"
                logger.info("Database schema restore verification passed: %s", restored_counts)
            finally:
                # Always drop the temporary verification schema
                conn.execute(text(f'DROP SCHEMA IF EXISTS "{temp_schema}" CASCADE'))
                logger.info("Cleaned up temporary verification schema %s", temp_schema)

        engine.dispose()
    else:
        for tbl, rows in tables_data.items():
            restored_counts[tbl] = len(rows)

    duration = time.time() - start_time
    rto_met = duration <= RTO_TARGET_SECONDS

    report = {
        "verified_file": backup_file.name,
        "sha256": file_sha256,
        "alembic_version": alembic_rev,
        "encryption_verified": True,
        "database_restored": db_verification_status,
        "duration_seconds": round(duration, 3),
        "rto_target_seconds": RTO_TARGET_SECONDS,
        "rto_sla_met": rto_met,
        "verified_at": datetime.now().isoformat(),
        "table_counts": restored_counts,
    }

    logger.info("Restore verification completed in %.2fs (RTO target <= %.0fs met: %s)", duration, RTO_TARGET_SECONDS, rto_met)
    return report


def main():
    load_env_file()
    parser = argparse.ArgumentParser(description="Snacky Studio Automated Restore Verification")
    parser.add_argument("backup_file", type=Path, help="Path to .sql.gz.enc backup file")
    parser.add_argument("--key", default=os.getenv("BACKUP_ENCRYPTION_KEY", "snacky_production_vault_key_2026"), help="Backup encryption key")
    parser.add_argument("--db-url", default=os.getenv("SNACKY_DATABASE_URL"), help="PostgreSQL connection string for test schema verification")
    parser.add_argument("--no-db", action="store_true", help="Perform offline decryption and integrity verification without connecting to DB")

    args = parser.parse_args()
    try:
        report = verify_and_restore(
            backup_file=args.backup_file,
            encryption_key=args.key,
            database_url=args.db_url if not args.no_db else None,
            verify_in_db=not args.no_db and bool(args.db_url),
        )
        print(json.dumps(report, indent=2))
        sys.exit(0)
    except Exception as exc:
        logger.error("Restore verification FAILED: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
