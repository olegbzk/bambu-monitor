#!/usr/bin/env python3
"""Bambu Lab 3D Printer Monitor with Telegram notifications"""

import asyncio
import datetime
import json
import logging
import os
import sys
import textwrap
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

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

# Configuration from environment
IP = os.getenv('BAMBU_IP', '')
SERIAL = os.getenv('BAMBU_SERIAL', '')
ACCESS_CODE = os.getenv('BAMBU_ACCESS_CODE', '')
HEALTH_PORT = int(os.getenv('HEALTH_PORT', '8080'))
TELEGRAM_TOKEN = os.getenv('TG_BOT_TOKEN', '')
CHAT_ID = os.getenv('TG_CHAT_ID', '')
PRINTER_NAME = os.getenv('PRINTER_NAME', 'Bambu Printer')

if not all([IP, SERIAL, ACCESS_CODE]):
    print('Please set the BAMBU_IP, BAMBU_SERIAL, and BAMBU_ACCESS_CODE environment variables.')
    sys.exit(1)

log_level = logging.DEBUG if os.getenv('LOG_LEVEL', 'INFO').upper() == 'DEBUG' else logging.INFO

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

def setup_logging():
    """Configure logging with JSON formatter"""
    root_level = logging.DEBUG if log_level == logging.DEBUG else logging.WARNING
    logging.basicConfig(
        level=root_level,
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    
    for handler in logging.root.handlers:
        handler.setFormatter(JSONFormatter())
    
    app_logger = logging.getLogger('bambu_monitor')
    app_logger.setLevel(log_level)
    
    if log_level != logging.DEBUG:
        external_loggers = ['httpx', 'urllib3', 'telegram', 'httpcore', 'bambulabs_api', 'root']
        for logger_name in external_loggers:
            logging.getLogger(logger_name).setLevel(logging.ERROR)
    
    return app_logger


# Initialize logging
app_logger = setup_logging()

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


def get_printer_data(printer):
    """Collect and format printer data"""
    # print(printer.mqtt_client.dump())
    status = str(printer.get_state()).strip()
    extended_status = str(printer.get_current_state()).strip()
    percentage = printer.get_percentage()
    layer_num = printer.current_layer_num()
    total_layer_num = printer.total_layer_num()
    bed_temperature = format(printer.get_bed_temperature() or 0, '.0f')
    nozzle_temperature = format(printer.get_nozzle_temperature() or 0, '.0f')
    remaining_time = printer.get_time()
    
    # Calculate finish time with timezone awareness
    if remaining_time is not None and remaining_time > 0:
        try:
            now = datetime.datetime.now(datetime.timezone.utc)
            finish_time = now + datetime.timedelta(minutes=int(remaining_time))
            local_finish_time = finish_time.astimezone()
            finish_time_format = local_finish_time.strftime("%Y-%m-%d %H:%M:%S %Z")
            
        except (ValueError, OverflowError):
            finish_time_format = "NA"
    else:
        finish_time_format = "NA"
    
    return {
        'printer_name': PRINTER_NAME,
        'status': status,
        'extended_status': extended_status,
        'percentage': percentage,
        'layer_num': layer_num,
        'total_layer_num': total_layer_num,
        'bed_temperature': bed_temperature,
        'nozzle_temperature': nozzle_temperature,
        'remaining_time': remaining_time,
        'finish_time': finish_time_format,
    }


def create_telegram_message(data):
    """Create formatted Telegram message"""
    status_icon = STATUS_ICONS.get(data['status'], "ℹ️")
    customize.strict_markdown = False
    
    markdown_text = textwrap.dedent(f"""
        **{data['printer_name']}**
        {status_icon} {data['status']} - {data['extended_status']}
        >Percentage: {data['percentage']}%
        >Bed temp: {data['bed_temperature']}ºC
        >Nozzle temp: {data['nozzle_temperature']}ºC
        >Remaining time: {data['remaining_time']}m
        >Finish time: {data['finish_time']}
    """)
    
    return telegramify_markdown.markdownify(markdown_text)


def should_send_notification(current_status, previous_status, loop_num):
    """Determine if notification should be sent"""
    return (previous_status != current_status and loop_num != 1) or loop_num == 1


def should_skip_preparing(current_status):
    """Check if printer is preparing and should skip notification"""
    if (current_status['status'] == "RUNNING" and current_status['extended_status'] != "PRINTING") or current_status['status'] == "PREPARE":
        return True
    else:
        return False


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


if __name__ == '__main__':
    app_logger.info({'printer_data': {'Name': PRINTER_NAME, 'IP': IP, 'Serial': SERIAL}})
    retry_count = 0
    
    health_server = start_health_server(HEALTH_PORT)
    printer = bl.Printer(IP, ACCESS_CODE, SERIAL)

    while retry_count < MAX_RETRIES:
        try:
            printer.connect()
            time.sleep(CONNECTION_WAIT)
            update_health_status(healthy=True, connected=True)
            app_logger.info('Successfully connected to printer')
            break
        except Exception as e:
            retry_count += 1
            app_logger.error(f'Connection attempt {retry_count} failed: {e}')
            if retry_count >= MAX_RETRIES:
                app_logger.error('Max retries reached, exiting')
                exit(1)
            time.sleep(RETRY_DELAY)
        
    if not TELEGRAM_TOKEN or not CHAT_ID:
        app_logger.warning('Telegram bot not configured - notifications disabled')
        bot = None
    else:
        bot = Bot(token=TELEGRAM_TOKEN)
    
    loop_num = 0
    previous_printer_status = {}
    
    try:
        while True:
            try:
                time.sleep(LOOP_INTERVAL)
                loop_num = loop_num + 1
                printer_data = get_printer_data(printer)
                update_health_status(healthy=True, connected=True)
                # Log status update
                app_logger.info("Printer status update", extra={
                    'printer_data': {
                        "printer_name": PRINTER_NAME,
                        "status": printer_data['status'],
                        "extended_status": printer_data['extended_status'],
                        "layers": f"{printer_data['layer_num']}/{printer_data['total_layer_num']}",
                        "percentage": printer_data['percentage'],
                        "bed_temperature": printer_data['bed_temperature'],
                        "nozzle_temperature": printer_data['nozzle_temperature'],
                        "remaining_time_minutes": printer_data['remaining_time'],
                        "finish_time": printer_data['finish_time']
                    }
                })
                
                # Check if notification should be sent
                current_printer_status = {"status": printer_data['status'], "extended_status": printer_data['extended_status']}
                if should_send_notification(current_printer_status, previous_printer_status, loop_num):
                    message = create_telegram_message(printer_data)
                    try:
                        image = printer.get_camera_image()
                        image.save(IMAGE_FILENAME)
                    except Exception as e:
                        app_logger.error(f"Failed to get camera image: {e}")
                        continue
                    if bot is None:
                        app_logger.info("Telegram bot not configured, skipping notification.")
                    elif should_skip_preparing(current_printer_status):
                        app_logger.info("Printer is preparing, skipping notification.")
                    else:
                        app_logger.info(f"Sending notification - Status: '{printer_data['status']}', Extended: '{printer_data['extended_status']}'")
                        asyncio.run(send_telegram_message(bot, CHAT_ID, message, IMAGE_FILENAME))
                    previous_printer_status = current_printer_status
                    
                    
            except Exception as e:
                app_logger.error(f"Error during monitoring loop: {e}")
                update_health_status(healthy=False, connected=False, error=str(e))

                
    except KeyboardInterrupt:
        app_logger.info("Shutting down...")
    finally:
        try:
            printer.disconnect()
        except Exception as e:
            app_logger.error(f"Error disconnecting printer: {e}")
        
        try:
            health_server.shutdown()
        except Exception as e:
            app_logger.error(f"Error shutting down health server: {e}")
        
        try:
            if os.path.exists(IMAGE_FILENAME):
                os.remove(IMAGE_FILENAME)
        except Exception as e:
            app_logger.error(f"Error cleaning up image file: {e}")
        
        update_health_status(healthy=False, connected=False, error="Service stopped")