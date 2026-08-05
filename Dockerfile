# Stage I0 - Docker Compose: small, working, end-to-end version.
# Base image pinned to python:3.12-slim, matching this project's own
# confirmed runtime (Python 3.12.3 was the environment Stage G3's own
# Linux-path uvloop verification ran against - see requirements.txt's
# own uvloop comment block).
FROM python:3.12-slim

WORKDIR /app

# Dependencies copied and installed BEFORE the rest of the source, so
# Docker's own layer cache is invalidated only when requirements.txt
# itself changes, not on every source edit (dependencies change far
# less often than application code).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# This project has no setup.py/pyproject.toml - it is run today, and
# inside this container, as `python -m server.main` from the repo
# root, so the container's own working directory and module layout
# mirror that exactly (a plain recursive copy of the repo into /app).
COPY . .

CMD ["python", "-m", "server.main"]
