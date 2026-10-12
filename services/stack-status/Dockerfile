# =====================================================================
# stack-status -- the one container that mounts the Docker socket.
#
# It serves webui-backend a fixed, GET-only API (app/main.py) on an internal
# network, so that the internet-facing backend needs neither the socket nor
# the Docker SDK. Built from the repository root (docker-compose.yml), because
# its allow-list is a file of webui-backend's: stack_contract.py lives in that
# service's package, whose image can only read its own directory, and is
# copied into this one under the same name. Both services import that one
# file; the tree holds no second copy.
# =====================================================================
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

COPY services/stack-status/requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY services/stack-status/app/ ./app/
COPY services/webui-backend/app/stack_contract.py ./app/stack_contract.py

# Import the server at build time, so a missing contract, or one whose names
# the server does not find, fails the build instead of the first request.
RUN python -c "from app import main; print('stack-status serves', ', '.join(main.StackStatus.PATHS))"

# No EXPOSE. webui-backend reaches port 8081 (main.LISTEN_PORT) over
# status-net, which needs no EXPOSE, and an exposed port is one that
# `docker run -P` would publish on the host.
CMD ["python", "-m", "app.main"]
