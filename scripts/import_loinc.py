"""Import LOINC artifact into the local data directory.

Usage: python scripts/import_loinc.py <path-to-loinc-zip>

Requirements:
- Registered LOINC download account
- Artifact stored outside the public repo
- Checksum recorded
- Version pinned in configuration
"""

import sys


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/import_loinc.py <path-to-loinc-zip>")
        sys.exit(1)
    raise NotImplementedError("LOINC import not yet implemented")


if __name__ == "__main__":
    main()
