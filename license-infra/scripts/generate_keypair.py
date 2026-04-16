#!/usr/bin/env python3
"""Generate an Ed25519 keypair for ChangeSafe license signing.

The private key goes into AWS Secrets Manager (Lambda signer).
The public key goes into the backend's LICENSE_PUBLIC_KEY_V1 env var.

Usage:
    python generate_keypair.py [--output-dir /path/to/dir]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

BANNER = """\
\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
  ChangeSafe License Keypair Generator
\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550"""


def generate_keypair(output_dir: Path) -> tuple[Path, Path]:
    """Generate an Ed25519 keypair and write PEM files to *output_dir*.

    Returns the paths to (private.pem, public.pem).
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    private_pem = private_key.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.PKCS8,
        encryption_algorithm=NoEncryption(),
    )
    public_pem = public_key.public_bytes(
        encoding=Encoding.PEM,
        format=PublicFormat.SubjectPublicKeyInfo,
    )

    private_path = output_dir / "private.pem"
    public_path = output_dir / "public.pem"

    private_path.write_bytes(private_pem)
    os.chmod(private_path, 0o600)

    public_path.write_bytes(public_pem)

    return private_path, public_path


def print_output(private_path: Path, public_path: Path) -> None:
    """Print keys to stdout along with deployment instructions."""
    private_pem = private_path.read_text()
    public_pem = public_path.read_text()

    print(BANNER)
    print()
    print(f"Generated Ed25519 keypair:")
    print(f"  Private key: {private_path.resolve()}")
    print(f"  Public key:  {public_path.resolve()}")
    print()
    print("\u2500\u2500 Private Key \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500")
    print(private_pem)
    print("\u2500\u2500 Public Key \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500")
    print(public_pem)
    print("\u2500\u2500 Deployment Instructions \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500")
    print()
    print("1. Upload private key to AWS Secrets Manager:")
    print("   aws secretsmanager put-secret-value \\")
    print("     --secret-id changesafe/license-signing-key \\")
    print("     --secret-string file://private.pem")
    print()
    print("2. Set public key as environment variable for the backend:")
    print('   LICENSE_PUBLIC_KEY_V1="$(cat public.pem)"')
    print()
    print("   Or in Docker Compose:")
    print("   environment:")
    print("     - LICENSE_PUBLIC_KEY_V1=-----BEGIN PUBLIC KEY-----\\n...\\n-----END PUBLIC KEY-----")
    print()
    print("3. Keep private.pem secure -- do NOT commit it to version control.")
    print("   The public key (public.pem) can be committed safely.")
    print()
    print("\u2550" * 55)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate an Ed25519 keypair for ChangeSafe license signing.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path.cwd(),
        help="Directory to write private.pem and public.pem (default: current directory)",
    )
    args = parser.parse_args()

    private_path, public_path = generate_keypair(args.output_dir)
    print_output(private_path, public_path)


if __name__ == "__main__":
    main()
