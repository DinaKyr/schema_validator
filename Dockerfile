FROM python:3.11-slim
# Install bash (required for solution.sh)
# RUN apt-get update & apt-get install -y -no-install-recommends \
# bash \
# & apt-get clean & rm -rf /var/lib/apt/lists *
RUN apt-get update && \
    apt-get install -y --no-install-recommends bash && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Create model user and workdir
RUN useradd -m -s /bin/bash model \
&& mkdir -p /workdir \
&& chown model:model /workdir
WORKDIR /workdir
# No additional Python dependencies needed - json is built-in
# ------------ DO NOT CHANGE BELOW --------------
COPY ./tests/ /tests/
COPY ./solution.sh /tests/
COPY ./grader.py /tests/
COPY ./data /workdir/data
RUN chown -R model:model /workdir/data \
    && chmod -R 700 /workdir/data