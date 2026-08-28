FROM python:3.11-slim

WORKDIR /app

# [Infra fix, docs/IMPLEMENTATION_PLAN.md verification gate] Originally this
# ran `apt-get install libpq-dev gcc` for a "rare wheel-build fallback."
# That step was never actually necessary: requirements.txt pins
# psycopg2-binary, whose manylinux wheel statically bundles libpq and needs
# no system libpq or a C compiler to install. Removed rather than patched
# around after it started failing here on the base image's current Debian
# apt mirror (HTTP 403 - an external repo/mirror issue, not a TRACE-X
# config problem) - the fix is deleting an unneeded step, not working
# around a flaky mirror for a dependency the build doesn't need.

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x docker-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["./docker-entrypoint.sh"]
