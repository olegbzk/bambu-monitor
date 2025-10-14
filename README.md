# VW Geko Prometheus Exporter

This Docker container runs a Prometheus exporter that monitors the VW Geko system status from https://status.vw-geko.com/

## Features

- Scrapes VW Geko status every 60 seconds by default
- Exposes Prometheus metrics on port 9090
- Monitors all car brands: Volkswagen, Audi, Skoda, Seat, Bentley, Lamborghini, MAN
- Tracks status for: SVM/Coding, Immobilizer/Component Protection, DSS/SFD services

## Quick Start

### Using Docker Compose (Recommended)

```bash
docker-compose up -d
```

### Using Docker directly

```bash
# Build the image
docker build -t vw-geko-exporter .

# Run the container
docker run -d \
  --name vw-geko-exporter \
  -p 9090:9090 \
  --restart unless-stopped \
  vw-geko-exporter
```

## Environment Variables

You can customize the behavior using environment variables:

- `INTERVAL`: Scraping interval in seconds (default: 60)
- `PORT`: HTTP server port (default: 9090)
- `VERBOSE`: Enable verbose logging (default: true)

Example with custom settings:

```bash
docker run -d \
  --name vw-geko-exporter \
  -p 8080:8080 \
  -e PORT=8080 \
  -e INTERVAL=30 \
  -e VERBOSE=false \
  vw-geko-exporter
```

## Metrics Endpoint

Once running, metrics are available at:
- http://localhost:9090/metrics

## Prometheus Configuration

Add this to your prometheus.yml:

```yaml
scrape_configs:
  - job_name: 'vw-geko-exporter'
    static_configs:
      - targets: ['localhost:9090']
    scrape_interval: 60s
```

## Health Check

The container includes a health check that verifies the metrics endpoint:

```bash
docker ps  # Check health status
curl http://localhost:9090/metrics  # Manual health check
```

## Sample Metrics

```
# HELP vw_geko_service_status Status of VW Geko services (0=Offline, 1=Online, 2=Restricted, 3=Contact)
# TYPE vw_geko_service_status gauge
vw_geko_service_status{brand="Volkswagen",service="SVM_Coding",status="Online"} 1
vw_geko_service_status{brand="Volkswagen",service="Immobilizer_Component_Protection",status="Offline"} 0
vw_geko_service_status{brand="Audi",service="SVM_Coding",status="Online"} 1
...

# HELP vw_geko_total_services Total number of services monitored
# TYPE vw_geko_total_services gauge
vw_geko_total_services 21

# HELP vw_geko_services_by_status Number of services by status
# TYPE vw_geko_services_by_status gauge
vw_geko_services_by_status{status="Online"} 14
vw_geko_services_by_status{status="Offline"} 7
```

## Stopping

```bash
# Using docker-compose
docker-compose down

# Using docker directly
docker stop vw-geko-exporter
docker rm vw-geko-exporter
```