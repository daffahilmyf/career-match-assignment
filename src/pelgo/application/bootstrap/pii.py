from __future__ import annotations

from pelgo.adapters.pii.simple_redactor import SimplePIIRedactor
from pelgo.ports.pii import PIIRedactor


def build_pii_redactor() -> PIIRedactor:
    return SimplePIIRedactor()
