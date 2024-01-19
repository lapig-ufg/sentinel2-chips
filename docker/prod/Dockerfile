
# Use an official osgeo/gdal image as a parent image
FROM registry.lapig.iesa.ufg.br/lapig-images-prod/download-minio:base as python-base

# Clone app and npm install on server
ENV URL_TO_APPLICATION_GITHUB="https://github.com/lapig-ufg/sentinel2-chips.git"
ENV BRANCH="main"

# Set the working directory in the container to /app
WORKDIR /app

# Copy the current directory contents into the container at /app


# Install any needed packages specified in requirements.txt


RUN apt-get update && \
    apt-get install -y git make libpq-dev libpq5 && \
    mkdir -p /APP && cd /APP && \
    git clone -b ${BRANCH} ${URL_TO_APPLICATION_GITHUB} && \
    rm -rf /var/lib/apt/lists/* && chmod +x /APP/download-minio/start.sh

RUN pip install --no-cache-dir -r requirements.txt
RUN pip install GDAL
# Run app.py when the container launches
CMD ["python", "s2_cog.py"]

