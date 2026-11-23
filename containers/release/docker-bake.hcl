group "default" {
  targets = ["backend", "frontend", "ingress", "postgres", "compute-worker", "plot-executor", "plot-python", "plot-gnuplot"]
}

target "_linux" {
  platforms = ["linux/amd64"]
}

target "_application" {
  inherits = ["_linux"]
  dockerfile = "containers/application/Dockerfile"
  args = {
    PYTHON_IMAGE = "python@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2"
    DOCKER_CLI_IMAGE = "docker@sha256:2357639ad1ea7d0194134bf3292622fd4e562483966ed674e5d7c945b5f3b28d"
  }
}

target "backend" {
  inherits = ["_application"]
  target = "backend"
  tags = ["astroagent-ci-backend:local"]
}

target "compute-worker" {
  inherits = ["_application"]
  target = "compute-worker"
  tags = ["astroagent-ci-compute-worker:local"]
}

target "plot-executor" {
  inherits = ["_application"]
  target = "executor"
  tags = ["astroagent-ci-plot-executor:local"]
}

target "frontend" {
  inherits = ["_linux"]
  dockerfile = "containers/frontend/Dockerfile"
  target = "runtime"
  tags = ["astroagent-ci-frontend:local"]
  args = {
    NODE_IMAGE = "node@sha256:4e6b70dd6cbfc88c8157ba19aa3d9f9cce6ba4703576d55459e45efcbc9c5f5d"
  }
}

target "_gcp" {
  inherits = ["_linux"]
  dockerfile = "containers/gcp/Dockerfile"
  args = {
    POSTGRES_IMAGE = "pgvector/pgvector@sha256:0dd3149a06e4579a0d70d8fef9945636cd514005e7237deb27f9b67886f8dc4f"
    CADDY_IMAGE = "caddy@sha256:003a97808e781aa9f7e75cc2f43d34d461099031faf5e20faefb9f61126836f0"
  }
}

target "ingress" {
  inherits = ["_gcp"]
  target = "ingress"
  tags = ["astroagent-ci-ingress:local"]
}

target "postgres" {
  inherits = ["_gcp"]
  target = "postgres"
  tags = ["astroagent-ci-postgres:local"]
}

target "plot-python" {
  inherits = ["_linux"]
  context = "containers/plotting"
  dockerfile = "python.Dockerfile"
  tags = ["astroagent-ci-plot-python:local"]
}

target "plot-gnuplot" {
  inherits = ["_linux"]
  context = "containers/plotting"
  dockerfile = "gnuplot.Dockerfile"
  tags = ["astroagent-ci-plot-gnuplot:local"]
}
