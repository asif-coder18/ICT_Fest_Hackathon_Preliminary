"""Application configuration.

Values are read from the environment so the same image can run in different
deployments. Sensible defaults are provided for local development only — the
JWT_SECRET default must NEVER be used in production.
"""
import os
import warnings

# FIX #27: warn loudly when the default (weak, public) secret is in use so it
# is never silently deployed to production.
JWT_SECRET = os.getenv("JWT_SECRET", "")
if not JWT_SECRET:
    warnings.warn(
        "JWT_SECRET environment variable is not set. "
        "Using an insecure default — set a strong secret before deploying.",
        stacklevel=2,
    )
    JWT_SECRET = "cowork-dev-secret-change-me"

JWT_ALGORITHM = "HS256"

ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 7

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./cowork.db")
