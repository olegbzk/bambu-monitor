# Bambu Monitor Health Check

## Overview

The bambu-monitor application now includes a built-in HTTP health check endpoint that can be used by Docker, Kubernetes, or any orchestration system to monitor the application's health.

## Health Check Endpoint

### `/health` Endpoint

**URL:** `http://localhost:8080/health`

**Response Format:** JSON

**Response Codes:**
- `200 OK` - Service is healthy and printer is connected
- `503 Service Unavailable` - Service is unhealthy or printer is disconnected

### Response Structure

```json
{
  "status": "healthy",
  "printer_connected": true,
  "last_update": "2025-10-14T10:30:45.123456",
  "error": null
}
```

**Fields:**
- `status`: Either "healthy" or "unhealthy"
- `printer_connected`: Boolean indicating if the printer connection is active
- `last_update`: ISO 8601 timestamp of the last successful status update
- `error`: Error message if the service is unhealthy, otherwise null

### Example Unhealthy Response

```json
{
  "status": "unhealthy",
  "printer_connected": false,
  "last_update": "2025-10-14T10:28:12.456789",
  "error": "Failed to connect to printer: Connection timeout"
}
```

## Configuration

### Environment Variables

- `HEALTH_PORT` - Port for the health check server (default: `8080`)
- `BAMBU_IP` - Printer IP address (required)
- `BAMBU_SERIAL` - Printer serial number (required)
- `BAMBU_ACCESS_CODE` - Printer access code (required)
- `TG_BOT_TOKEN` - Telegram bot token (required for notifications)
- `TG_CHAT_ID` - Telegram chat ID (required for notifications)

## Docker Health Check

The Dockerfile includes a built-in health check:

```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1
```

**Parameters:**
- `interval=30s` - Check every 30 seconds
- `timeout=10s` - Health check timeout
- `start-period=10s` - Grace period for startup
- `retries=3` - Mark unhealthy after 3 consecutive failures

## Usage Examples

### Check Health with curl

```bash
curl http://localhost:8080/health
```

### Check Health Status Code Only

```bash
curl -f http://localhost:8080/health && echo "Healthy" || echo "Unhealthy"
```

### Docker Container Health

```bash
docker ps --filter "health=healthy"
docker ps --filter "health=unhealthy"
docker inspect --format='{{.State.Health.Status}}' container_name
```

### Kubernetes Liveness Probe

```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8080
  initialDelaySeconds: 10
  periodSeconds: 30
  timeoutSeconds: 10
  failureThreshold: 3
```

### Kubernetes Readiness Probe

```yaml
readinessProbe:
  httpGet:
    path: /health
    port: 8080
  initialDelaySeconds: 5
  periodSeconds: 10
  timeoutSeconds: 5
  failureThreshold: 2
```

## Health Status Updates

The application automatically updates its health status:

1. **On Startup**: 
   - Sets healthy=true when successfully connected to printer
   - Sets healthy=false if initial connection fails

2. **During Operation**:
   - Updates to healthy=true on each successful printer status fetch
   - Updates to healthy=false if printer communication fails

3. **On Shutdown**:
   - Sets healthy=false when service stops

## Monitoring

### What the Health Check Monitors

- ✅ Printer connection status
- ✅ Last successful data fetch timestamp
- ✅ Error conditions and messages
- ✅ HTTP server availability

### What It Does NOT Monitor

- Telegram notification delivery (errors are logged but don't affect health)
- Disk space for image storage
- Network connectivity to Telegram API

## Troubleshooting

### Container Always Unhealthy

1. Check logs: `docker logs container_name`
2. Verify printer connection settings (IP, serial, access code)
3. Ensure printer is powered on and accessible
4. Check health endpoint manually: `docker exec container_name curl http://localhost:8080/health`

### Health Check Timeout

1. Increase timeout in HEALTHCHECK: `--timeout=15s`
2. Check if the container is resource-constrained
3. Verify network connectivity to the printer

### False Positives

If the health check passes but the service isn't working:
- Check Telegram configuration (bot token, chat ID)
- Verify the monitoring loop is running
- Check for Python exceptions in logs

## Implementation Details

The health check is implemented using:
- `http.server.HTTPServer` - Lightweight HTTP server
- `threading` - Runs health server in background thread
- Thread-safe global state with `threading.Lock`
- Automatic health status updates throughout the application lifecycle

The health server starts before connecting to the printer and runs independently, ensuring the health endpoint is always available even if the printer connection fails.
