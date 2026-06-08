FROM python:3.14-trixie AS compiler

WORKDIR /build

RUN apt-get update && \ 
    apt-get install -y --no-install-recommends build-essential && \
    rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.14-trixie AS runner

RUN apt update && \
    apt install -y ffmpeg && \
    rm -rf /var/lib/apt/lists/*

ARG USER_UID=1000
ARG USER_GID=1000
ARG USERNAME=appuser

ENV USER_UID=${USER_UID}
ENV USER_GID=${USER_GID}

RUN groupadd --gid ${USER_GID} ${USERNAME} && \
    useradd --uid ${USER_UID} --gid ${USER_GID} -m ${USERNAME}
	
WORKDIR /app

COPY --from=compiler /opt/venv /opt/venv

COPY privacy_scraper.py .

RUN chown -R ${USER_UID}:${USER_GID} /app

ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

USER ${USERNAME}

CMD ["python", "privacy_scraper.py"]
