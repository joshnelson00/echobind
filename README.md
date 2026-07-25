# EchoBind

EchoBind is a personal lecture and meeting transcription assistant designed to help capture important information from audio recordings and generate organized notes.

The goal of this project is to create a system that can process recorded lectures, meetings, and discussions into searchable transcripts and AI-generated summaries. The generated notes are intended to supplement personal note-taking by identifying missed details, important context, and key discussion points.

## Features (Planned)

- Upload audio recordings for processing
- Convert audio recordings into text transcripts
- Generate structured notes and summaries using local AI models
- Maintain a history of processed recordings and generated outputs

## Technologies Used

### Backend
- Python
- FastAPI
- SQLAlchemy
- SQLite

### AI / Machine Learning
- Whisper for speech-to-text transcription
- Ollama for local large language model inference

### Infrastructure
- Docker
- Kubernetes
- Linux
- Raspberry Pi

### Development Tools
- Git
- uv (Python package management)

## Project Status

Currently under active development. Future development will focus on transcription processing, AI summarization, and deployment workflows.

## Running locally with Docker Compose

The repo now includes a Compose file that mounts your shared storage at `/mnt/echobind-storage` into both the API and worker containers.

```bash
docker compose up --build
```

Set `ECHOBIND_STORAGE_ROOT` if you want to point at a different shared path.

## Kubernetes

A sample Kubernetes manifest is available in `src/k8s/echobind.yaml`.

Current assumptions:

- The k3s control plane runs on the Raspberry Pi at `raspberry.local`.
- Shared storage is exported from `raspberry.local` and mounted at `/mnt/echobind-storage`.
- API pods stay pinned to the Pi node.
- The API is exposed on `raspberry.local:30080` via `NodePort`.
- Images are tagged as `release` in the GitHub push workflow.
- Worker pods request `nvidia.com/gpu: 1` and run on CUDA-capable nodes.
- `OLLAMA_HOST` is set to `http://raspberry.local:11434` for the cluster.

Replace `YOUR_DOCKERHUB_USERNAME` with your Docker Hub username before applying it.

## Worker resilience

The worker is designed to handle transient node or network failures. If a worker goes offline while it has claimed a job, the job is requeued after a configurable timeout so another worker can pick it up.

You can tune the behavior with:

- `WORKER_POLL_INTERVAL_SECONDS`
- `WORKER_HEARTBEAT_INTERVAL_SECONDS`
- `JOB_REQUEUE_TIMEOUT_MINUTES`