# Reaction Rush v2 — server image.
#
# Runs the headless TCP server. The Tkinter GUI client is NOT included, since
# GUI apps are not well-suited to containers; run the client on your desktop.
#
# Build:  docker build -t reaction-rush-server .
# Run:    docker run -p 5000:5000 reaction-rush-server
#
# Override options by appending flags, e.g.:
#   docker run -p 5000:5000 reaction-rush-server \
#       --access-code MYCODE --mode elimination --rounds 7

FROM python:3.11-slim

# No third-party runtime dependencies — the game uses only the stdlib.
WORKDIR /app
COPY . /app

# Persist the SQLite database outside the container if desired:
#   docker run -p 5000:5000 -v $(pwd)/data:/app/data reaction-rush-server \
#       --db /app/data/reaction_rush.db
EXPOSE 5000

# Bind to 0.0.0.0 so the server is reachable from outside the container.
ENTRYPOINT ["python", "server.py", "--host", "0.0.0.0", "--port", "5000"]
CMD ["--access-code", "RED123", "--min-players", "2"]
