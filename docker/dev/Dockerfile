FROM registry.lapig.iesa.ufg.br/lapig-images-prod/download-minio:base as python-base

ENV LAPIG_ENV='dev' \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100 \
    POETRY_VERSION=1.0.5 \
    POETRY_HOME="/opt/poetry" \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1 \
    PYSETUP_PATH="/opt/pysetup" \
    VENV_PATH="/opt/pysetup/.venv"\
    PYTHONBREAKPOINT="web_pdb.set_trace"

# prepend poetry and venv to path
ENV PATH="$POETRY_HOME/bin:$VENV_PATH/bin:$PATH"


# Clone app and npm install on server
ENV URL_TO_APPLICATION_GITHUB="https://github.com/lapig-ufg/sentinel2-chips.git"
ENV BRANCH="main"

# Set the working directory in the container to /app
WORKDIR /app

# Copy the current directory contents into the container at /app


# Install any needed packages specified in requirements.txt


RUN apt-get update && \
    apt-get install -y git make  libgl1-mesa-glx libpq-dev libpq5 && \
    mkdir -p /app && cd /app && \
    git clone -b ${BRANCH} ${URL_TO_APPLICATION_GITHUB} && \
    rm -rf /var/lib/apt/lists/*

ENV LD_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu/:$LD_LIBRARY_PATH

RUN pip3 install --no-cache-dir -r sentinel2-chips/requirements.txt

# Run app.py when the container launches
CMD ["python", "sentinel2-chips/s2_cog.py"]

