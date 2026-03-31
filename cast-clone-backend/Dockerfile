FROM python:3.12-slim

WORKDIR /app

# ── System packages ──────────────────────────────────────────────
# git: repo cloning during analysis
# curl/wget: downloading toolchains
# default-jdk: scip-java runtime
# maven: scip-java needs Maven for Maven-based projects
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl wget default-jdk maven \
    && rm -rf /var/lib/apt/lists/*

# ── Node.js 20 (scip-typescript + scip-python) ──────────────────
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# ── SCIP: TypeScript / JavaScript ────────────────────────────────
RUN npm install -g @sourcegraph/scip-typescript

# ── SCIP: Python (Pyright-based, npm package) ────────────────────
RUN npm install -g @sourcegraph/scip-python

# ── SCIP: Java (via Coursier) ────────────────────────────────────
RUN curl -fL "https://github.com/coursier/coursier/releases/latest/download/cs-x86_64-pc-linux.gz" \
    | gzip -d > /tmp/cs \
    && chmod +x /tmp/cs \
    && /tmp/cs fetch com.sourcegraph:scip-java_2.13:0.9.9 >/dev/null 2>&1 \
    && /tmp/cs bootstrap --standalone \
       -M com.sourcegraph.scip_java.ScipJava \
       -o /usr/local/bin/scip-java \
       com.sourcegraph:scip-java_2.13:0.9.9 \
    && chmod +x /usr/local/bin/scip-java \
    && rm /tmp/cs

# ── .NET SDK 9.0 + SCIP: C# / .NET ──────────────────────────────
# .NET 9 SDK builds .NET 6/7/8/9 projects (backward compatible)
RUN apt-get update && apt-get install -y --no-install-recommends libicu-dev && rm -rf /var/lib/apt/lists/*
ENV DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=false
RUN wget -q https://dot.net/v1/dotnet-install.sh -O /tmp/dotnet-install.sh \
    && chmod +x /tmp/dotnet-install.sh \
    && /tmp/dotnet-install.sh --channel 9.0 --install-dir /usr/share/dotnet \
    && ln -s /usr/share/dotnet/dotnet /usr/local/bin/dotnet \
    && rm /tmp/dotnet-install.sh \
    && dotnet tool install --global scip-dotnet
ENV PATH="$PATH:/root/.dotnet/tools"
ENV DOTNET_ROOT="/usr/share/dotnet"

# ── Python app dependencies (uv) ────────────────────────────────
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# ── Application code + migrations ────────────────────────────────
COPY alembic.ini ./
COPY migrations/ migrations/
COPY app/ app/

EXPOSE 8000

# Run migrations then start the server
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000"]
