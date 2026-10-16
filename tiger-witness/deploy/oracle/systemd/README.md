# systemd fallback (no Docker)

Use this only if Docker is unavailable. It runs the same processes directly on the VM.

```bash
sudo apt-get install -y python3.12-venv postgresql-16 postgresql-16-pgvector caddy
# TimescaleDB for arm64: https://docs.timescale.com/self-hosted/latest/install/installation-linux/
sudo useradd --system --home /opt/witness witness
sudo -u witness python3.12 -m venv /opt/witness/venv
sudo -u witness /opt/witness/venv/bin/pip install -r /opt/witness/tiger-witness/requirements.txt
# llama.cpp server (native arm64 build)
git clone --depth 1 https://github.com/ggml-org/llama.cpp /opt/llama.cpp
cmake -S /opt/llama.cpp -B /opt/llama.cpp/build -DGGML_NATIVE=ON -DLLAMA_CURL=OFF && cmake --build /opt/llama.cpp/build -j2 --target llama-server
sudo cp witness-api.service witness-worker.service witness-llm.service /etc/systemd/system/
sudo cp ../.env /etc/witness.env && sudo chmod 600 /etc/witness.env   # add TIGER_DB_URL and WITNESS_LOCAL_LLM_URL=http://127.0.0.1:8080/v1
sudo -u witness bash -c 'set -a; . /etc/witness.env; cd /opt/witness/tiger-witness && /opt/witness/venv/bin/python -m witness.setup_db'
sudo systemctl daemon-reload && sudo systemctl enable --now witness-llm witness-api witness-worker
sudo cp ../Caddyfile /etc/caddy/Caddyfile && sudo systemctl reload caddy   # set WITNESS_DOMAIN in /etc/default/caddy
```
