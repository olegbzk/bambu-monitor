#!/usr/bin/env python3
"""
Bambu Lab 3D Printer Monitor
Monitors printer status and sends Telegram notifications with photos
"""

import asyncio
import datetime
import json
import logging
import os
import sys
import textwrap
import threading
import time
from dataclasses import dataclass
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional, Dict, Any

import bambulabs_api as bl
import telegramify_markdown
import telegramify_markdown.customize as customize
from telegram import Bot

# Constants
LOOP_INTERVAL = 10  # seconds
MAX_RETRIES = 5
RETRY_DELAY = 10  # seconds
CONNECTION_WAIT = 5  # seconds
IMAGE_FILENAME = "bambu_status.png"

STATUS_ICONS = {
    "PAUSED": "⏸️",
    "RUNNING": "🚀", 
    "FINISHED": "✅",
}


@dataclass
class Config:
    """Application configuration from environment variables"""
    ip: str
    serial: str
    access_code: str
    health_port: int
    telegram_token: Optional[str]
    chat_id: Optional[str]
    log_level: int
    
    @classmethod
    def from_env(cls) -> 'Config':
        """Create config from environment variables"""
        ip = os.getenv('BAMBU_IP', '')
        serial = os.getenv('BAMBU_SERIAL', '')
        access_code = os.getenv('BAMBU_ACCESS_CODE', '')
        
        if not all([ip, serial, access_code]):
            print('Please set the BAMBU_IP, BAMBU_SERIAL, and BAMBU_ACCESS_CODE environment variables.')
            sys.exit(1)
            
        return cls(
            ip=ip,
            serial=serial,
            access_code=access_code,
            health_port=int(os.getenv('HEALTH_PORT', '8080')),
            telegram_token=os.getenv('TG_BOT_TOKEN'),
            chat_id=os.getenv('TG_CHAT_ID'),
            log_level=logging.DEBUG if os.getenv('LOG_LEVEL', 'INFO').upper() == 'DEBUG' else logging.INFO
        )

# Custom JSON formatter for structured logging
class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "timestamp": datetime.datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S,%f")[:-3],
            "level": record.levelname,
            "logger": record.name
        }
        
        # If the record has extra data, merge it into the log entry
        if hasattr(record, 'printer_data'):
            log_entry.update(record.printer_data)
        else:
            log_entry["message"] = record.getMessage()
            
        return json.dumps(log_entry, separators=(',', ':'))

# Set root logger level based on debug setting
root_level = logging.DEBUG if log_level == logging.DEBUG else logging.WARNING
logging.basicConfig(
    level=root_level,
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

for handler in logging.root.handlers:
    handler.setFormatter(JSONFormatter())

app_logger = logging.getLogger('bambu_monitor')
app_logger.setLevel(log_level)

if log_level != logging.DEBUG:
    logging.getLogger('httpx').setLevel(logging.ERROR)
    logging.getLogger('urllib3').setLevel(logging.ERROR)
    logging.getLogger('telegram').setLevel(logging.ERROR)
    logging.getLogger('httpcore').setLevel(logging.ERROR)
    logging.getLogger('bambulabs_api').setLevel(logging.ERROR)
    logging.getLogger('root').setLevel(logging.ERROR)

# Global health status
health_status = {
    'healthy': False,
    'last_update': None,
    'printer_connected': False,
    'error': None
}
health_lock = threading.Lock()


class HealthHandler(BaseHTTPRequestHandler):
    """HTTP handler for health check endpoint."""
    
    def do_GET(self):
        if self.path == '/health':
            with health_lock:
                status = health_status.copy()
            
            if status['healthy']:
                self.send_response(200)
            else:
                self.send_response(503)
            
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            
            response = {
                'status': 'healthy' if status['healthy'] else 'unhealthy',
                'printer_connected': status['printer_connected'],
                'last_update': status['last_update'],
                'error': status['error']
            }
            self.wfile.write(json.dumps(response, indent=2).encode('utf-8'))
        
        elif self.path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            html = """<!DOCTYPE html>
<html>
<head>
    <title>Bambu Monitor Health</title>
</head>
<body>
    <h1>Bambu Monitor Health Check</h1>
    <p><a href="/health">Health Endpoint</a></p>
</body>
</html>"""
            self.wfile.write(html.encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        """Suppress HTTP log messages."""
        pass


def update_health_status(healthy, connected, error=None):
    """Update the global health status."""
    with health_lock:
        health_status['healthy'] = healthy
        health_status['printer_connected'] = connected
        health_status['last_update'] = datetime.datetime.now().isoformat()
        health_status['error'] = error


def start_health_server(port):
    """Start the health check HTTP server in a separate thread."""
    server = HTTPServer(('0.0.0.0', port), HealthHandler)

    
    def serve():
        server.serve_forever()
    
    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return server


async def send_telegram_message(bot_instance, chat_id, message=None, photo_path=None):
    """Send telegram message with photo, fallback to text message if photo is absent"""
    async def send_photo(text, chat_id, photo_file):
        async with bot_instance:
            await bot_instance.send_photo(chat_id=chat_id, photo=photo_file, caption=text, parse_mode='MarkdownV2')
    
    async def send_text(text, chat_id):
        async with bot_instance:
            await bot_instance.send_message(chat_id=chat_id, text=text, parse_mode='MarkdownV2')
    
    try:
        # Try to send with photo if photo_path is provided and file exists
        if photo_path and os.path.exists(photo_path):
            with open(photo_path, 'rb') as photo_file:
                await send_photo(message, chat_id, photo_file)
        else:
            # Fallback to text message only
            if photo_path:
                app_logger.warning(f"Photo file not found: {photo_path}, sending text message only")
            await send_text(message, chat_id)
    except Exception as e:
        app_logger.error(f"Failed to send telegram message: {e}")
        # Try fallback to text message if photo sending failed
        if photo_path:
            try:
                app_logger.info("Attempting fallback to text message")
                await send_text(message, chat_id)
            except Exception as fallback_error:
                app_logger.error(f"Fallback text message also failed: {fallback_error}")





@dataclass
class PrinterStatus:
    """Printer status data structure"""
    status: str
    extended_status: str
    percentage: int
    layer_num: int
    total_layer_num: int
    bed_temperature: str
    nozzle_temperature: str
    remaining_time: Optional[int]
    finish_time: str


class BambuMonitor:
    """Main monitor class for Bambu Lab printer"""
    
    def __init__(self, config: Config):
        self.config = config
        self.app_logger = logging.getLogger('bambu_monitor')
        self.printer = None
        self.bot = None
        self.health_server = None
        self.previous_status = None
        self.loop_num = 0
        
    def setup_logging(self):
        """Configure logging with JSON formatter"""
        root_level = logging.DEBUG if self.config.log_level == logging.DEBUG else logging.WARNING
        logging.basicConfig(
            level=root_level,
            handlers=[logging.StreamHandler(sys.stdout)]
        )
        
        for handler in logging.root.handlers:
            handler.setFormatter(JSONFormatter())
        
        self.app_logger.setLevel(self.config.log_level)
        
        if self.config.log_level != logging.DEBUG:
            for logger_name in ['httpx', 'urllib3', 'telegram', 'httpcore', 'bambulabs_api', 'root']:
                logging.getLogger(logger_name).setLevel(logging.ERROR)
    
    def setup_telegram(self):
        """Initialize Telegram bot if configured"""
        if self.config.telegram_token and self.config.chat_id:
            self.bot = Bot(token=self.config.telegram_token)
        else:
            self.app_logger.warning('Telegram bot not configured - notifications disabled')
    
    def connect_printer(self) -> bool:
        """Connect to printer with retry logic"""
        self.printer = bl.Printer(self.config.ip, self.config.access_code, self.config.serial)
        
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                self.printer.connect()
                time.sleep(CONNECTION_WAIT)
                update_health_status(healthy=True, connected=True)
                self.app_logger.info('Successfully connected to printer')
                return True
            except Exception as e:
                self.app_logger.error(f'Connection attempt {attempt} failed: {e}')
                if attempt >= MAX_RETRIES:
                    self.app_logger.error('Max retries reached, exiting')
                    return False
                time.sleep(RETRY_DELAY)
        return False
    
    def get_printer_status(self) -> PrinterStatus:
        """Collect current printer status"""
        status = str(self.printer.get_state()).strip()
        extended_status = str(self.printer.get_current_state()).strip()
        percentage = self.printer.get_percentage()
        layer_num = self.printer.current_layer_num()
        total_layer_num = self.printer.total_layer_num()
        bed_temperature = format(self.printer.get_bed_temperature() or 0, '.0f')
        nozzle_temperature = format(self.printer.get_nozzle_temperature() or 0, '.0f')
        remaining_time = self.printer.get_time()
        
        # Calculate finish time
        if remaining_time is not None and remaining_time > 0:
            try:
                finish_time = datetime.datetime.now() + datetime.timedelta(minutes=int(remaining_time))
                finish_time_format = finish_time.strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, OverflowError):
                finish_time_format = "NA"
        else:
            finish_time_format = "NA"
        
        return PrinterStatus(
            status=status,
            extended_status=extended_status,
            percentage=percentage,
            layer_num=layer_num,
            total_layer_num=total_layer_num,
            bed_temperature=bed_temperature,
            nozzle_temperature=nozzle_temperature,
            remaining_time=remaining_time,
            finish_time=finish_time_format
        )
    
    def log_status(self, status: PrinterStatus):
        """Log printer status as structured JSON"""
        self.app_logger.info("Printer status update", extra={
            'printer_data': {
                "status": status.status,
                "extended_status": status.extended_status,
                "layers": f"{status.layer_num}/{status.total_layer_num}",
                "percentage": status.percentage,
                "bed_temperature": status.bed_temperature,
                "nozzle_temperature": status.nozzle_temperature,
                "remaining_time_minutes": status.remaining_time,
                "finish_time": status.finish_time
            }
        })
    
    def should_send_notification(self, current_status: str) -> bool:
        """Determine if notification should be sent"""
        return (self.previous_status != current_status and self.loop_num != 1) or self.loop_num == 1
    
    def should_skip_preparing(self, status: PrinterStatus) -> bool:
        """Check if printer is preparing and should skip notification"""
        return status.status == "RUNNING" and status.extended_status != "PRINTING"
    
    def create_message(self, status: PrinterStatus) -> str:
        """Create formatted Telegram message"""
        status_icon = STATUS_ICONS.get(status.status, "ℹ️")
        customize.strict_markdown = False
        
        markdown_text = textwrap.dedent(f"""
            {status_icon} {status.status} - {status.extended_status}
            >Percentage: {status.percentage}%
            >Bed temp: {status.bed_temperature}ºC
            >Nozzle temp: {status.nozzle_temperature}ºC
            >Remaining time: {status.remaining_time}m
            >Finish time: {status.finish_time}
        """)
        
        return telegramify_markdown.markdownify(markdown_text)
    
    def capture_image(self) -> bool:
        """Capture printer camera image"""
        try:
            image = self.printer.get_camera_image()
            image.save(IMAGE_FILENAME)
            return True
        except Exception as e:
            self.app_logger.error(f"Failed to get camera image: {e}")
            return False
    
    async def send_notification(self, message: str, has_image: bool):
        """Send Telegram notification"""
        if not self.bot:
            self.app_logger.info("Telegram bot not configured, skipping notification.")
            return
        
        photo_path = IMAGE_FILENAME if has_image else None
        await send_telegram_message(self.bot, self.config.chat_id, message, photo_path)
    
    def cleanup_resources(self):
        """Clean up resources on shutdown"""
        if self.printer:
            try:
                self.printer.disconnect()
            except Exception as e:
                self.app_logger.error(f"Error disconnecting printer: {e}")
        
        if self.health_server:
            try:
                self.health_server.shutdown()
            except Exception as e:
                self.app_logger.error(f"Error shutting down health server: {e}")
        
        try:
            if os.path.exists(IMAGE_FILENAME):
                os.remove(IMAGE_FILENAME)
        except Exception as e:
            self.app_logger.error(f"Error cleaning up image file: {e}")
        
        update_health_status(healthy=False, connected=False, error="Service stopped")
    
    async def process_status_update(self, status: PrinterStatus):
        """Process a single status update"""
        self.log_status(status)
        update_health_status(healthy=True, connected=True)
        
        if not self.should_send_notification(status.status):
            return
        
        if self.should_skip_preparing(status):
            self.app_logger.info("Printer is preparing, skipping notification.")
            return
        
        message = self.create_message(status)
        has_image = self.capture_image()
        
        if not has_image:
            return  # Skip if can't capture image
        
        self.app_logger.info(f"Sending notification - Status: '{status.status}', Extended: '{status.extended_status}'")
        await self.send_notification(message, has_image)
        self.previous_status = status.status
    
    def run(self):
        """Main monitoring loop"""
        self.setup_logging()
        
        # Log startup info
        self.app_logger.info("Starting Bambu Monitor", extra={
            'printer_data': {'IP': self.config.ip, 'Serial': self.config.serial}
        })
        
        # Setup components
        self.health_server = start_health_server(self.config.health_port)
        self.setup_telegram()
        
        if not self.connect_printer():
            sys.exit(1)
        
        try:
            while True:
                try:
                    time.sleep(LOOP_INTERVAL)
                    self.loop_num += 1
                    
                    status = self.get_printer_status()
                    asyncio.run(self.process_status_update(status))
                    
                except Exception as e:
                    self.app_logger.error(f"Error during monitoring loop: {e}")
                    update_health_status(healthy=False, connected=False, error=str(e))
                    
        except KeyboardInterrupt:
            self.app_logger.info("Shutting down...")
        finally:
            self.cleanup_resources()


def main():
    """Application entry point"""
    config = Config.from_env()
    monitor = BambuMonitor(config)
    monitor.run()


if __name__ == '__main__':
    main()