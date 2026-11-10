"""Generate private local Docker credentials without printing them."""
import secrets
from pathlib import Path

root = Path(__file__).resolve().parent.parent
path = root / '.env.cloud'
if path.exists():
    raise SystemExit('.env.cloud already exists; no secrets were changed.')
values = {'POSTGRES_PASSWORD':secrets.token_hex(24),'S3_ACCESS_KEY':'snacky',
          'S3_SECRET_KEY':secrets.token_hex(24),'SNACKY_CLOUD_PASSWORD':secrets.token_urlsafe(24),
          'SNACKY_SESSION_SECRET':secrets.token_hex(32),'SNACKY_PUBLIC_ORIGIN':'http://localhost:8080',
          'SNACKY_S3_PUBLIC_ENDPOINT':'http://localhost:9000'}
path.write_text(''.join(f'{key}={value}\n' for key,value in values.items()),encoding='utf-8')
print('Created .env.cloud. Open it locally to read your workspace password.')
