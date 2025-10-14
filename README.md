# BambuLab Printer Monitor and Telegram Notifier

Proprietary `Bambu Handy` app notifications are unreliable and often delayed.

This project provides a better solution: a monitoring service for BambuLab 3D printers that delivers real-time status updates and Telegram notifications.

## Features

- **Real-time Monitoring**: Continuously monitors printer status, temperature, and progress
- **Telegram Notifications**: Sends status updates with camera images to Telegram
- **Health Checks**: Built-in HTTP health endpoint for container monitoring
- **Docker Ready**: Easy deployment with Docker Compose

## Quick Start

### Prerequisites

- BambuLab 3D printer with network access
- Telegram bot token and chat ID

### Environment Variables

Create a `.env` file or set these environment variables:

```bash
BAMBU_IP=192.168.1.100
BAMBU_SERIAL=your_printer_serial
BAMBU_ACCESS_CODE=your_access_code
TG_BOT_TOKEN=your_telegram_bot_token
TG_CHAT_ID=your_telegram_chat_id
```

### Docker Compose

```bash
docker compose up --build
```

## Monitoring

The service monitors:
- Print status (Running, Paused, Finished)
- Layer progress
- Temperature (bed and nozzle)
- Remaining time
- Camera images

## Notifications

Telegram notifications are sent when:
- Print status changes


## License

See LICENSE file for details.