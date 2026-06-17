# Dev container for the PyTestLab circuit simulation lane.
#
# Bundles the ngspice binary (the circuit lane's system dependency, which pip
# cannot install) alongside an editable install of pytestlab[circuit].
#
# Standalone build/use:
#   docker build -t pytestlab-circuit -f .devcontainer/Dockerfile .
#   docker run --rm -it pytestlab-circuit ptl sim doctor
FROM python:3.13-slim-bookworm

# ngspice + minimal build/runtime tooling.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ngspice git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
COPY . /workspace

RUN python -m pip install --upgrade pip \
    && python -m pip install -e ".[circuit]"

# Self-verify: fail the image build if the circuit lane is not ready.
RUN ptl sim doctor

CMD ["bash"]
