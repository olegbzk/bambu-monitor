import time
import os
import datetime
import asyncio
import bambulabs_api as bl
import textwrap
from telegram import Bot
import telegramify_markdown
import telegramify_markdown.customize as customize
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import json


IP = os.getenv('BAMBU_IP', '')
SERIAL = os.getenv('BAMBU_SERIAL', '')
ACCESS_CODE = os.getenv('BAMBU_ACCESS_CODE', '')
HEALTH_PORT = int(os.getenv('HEALTH_PORT', '8080'))

if IP == '' or SERIAL == '' or ACCESS_CODE == '':
    print('Please set the BAMBU_IP, BAMBU_SERIAL, and BAMBU_ACCESS_CODE environment variables.')
    exit(1)

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
    print(f'Health check server started on port {port}')
    print(f'Health endpoint: http://localhost:{port}/health')
    
    def serve():
        server.serve_forever()
    
    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return server


async def send_telegram_message(message=None, photo_path=None):
    TELEGRAM_BOT_TOKEN = os.getenv('TG_BOT_TOKEN', '')
    CHAT_ID = os.getenv('TG_CHAT_ID', '')
    if TELEGRAM_BOT_TOKEN == '' or CHAT_ID == '':
        print('Please set the TG_BOT_TOKEN and TG_CHAT_ID environment variables.')
        exit(1)
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    async def send_photo(text, chat_id, photo_file):
        async with bot:
            await  bot.send_photo(chat_id=chat_id, photo=photo_file, caption=text, parse_mode='MarkdownV2')
    try:
        with open(photo_path, 'rb') as photo_file:
            await send_photo(message, CHAT_ID, photo_file)
    except Exception as e:
        print(f"Failed to send photo: {e}")


if __name__ == '__main__':
    print('Connecting to BambuLab 3D printer')
    print(f'IP: {IP}')
    print(f'Serial: {SERIAL}')

    # Start health check server
    health_server = start_health_server(HEALTH_PORT)

    # Create a new instance of the API
    printer = bl.Printer(IP, ACCESS_CODE, SERIAL)

    # Connect to the BambuLab 3D printer
    try:
        printer.connect()
        time.sleep(5)  # Wait for connection to stabilize
        update_health_status(healthy=True, connected=True)
        print('Successfully connected to printer')
    except Exception as e:
        print(f'Failed to connect to printer: {e}')
        update_health_status(healthy=False, connected=False, error=str(e))
        exit(1)
    
    loop_num = 0
    previous_printer_status = None
    
    try:
        while True:
            try:
                time.sleep(5)
                loop_num = loop_num + 1
                status = printer.get_state()
                percentage = printer.get_percentage()
                layer_num = printer.current_layer_num()
                total_layer_num = printer.total_layer_num()
                bed_temperature = format(printer.get_bed_temperature(), '.0f')
                nozzle_temperature = format(printer.get_nozzle_temperature(), '.0f')
                remaining_time = printer.get_time()
                
                # Update health status on successful data fetch
                update_health_status(healthy=True, connected=True)
                
                if remaining_time is not None:
                    finish_time = datetime.datetime.now() + datetime.timedelta(
                        minutes=int(remaining_time))
                    finish_time_format = finish_time.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    finish_time_format = "NA"

                print(
                    f'''
{status}
----
Layers: {layer_num}/{total_layer_num}
Percentage: {percentage}%
Bed temp: {bed_temperature}ºC
Nozzle temp: {nozzle_temperature}ºC
Remaining time: {remaining_time}m
Finish time: {finish_time_format}
----
                    '''
                )
                if previous_printer_status != status and loop_num  != 1 or loop_num == 1:
                    customize.strict_markdown = False
                    markdown_text = textwrap.dedent(
                        f"""
                        # {status}
                        >Percentage: {percentage}%
                        >Bed temp: {bed_temperature}ºC
                        >Nozzle temp: {nozzle_temperature}ºC
                        >Remaining time: {remaining_time}m
                        >Finish time: {finish_time_format}
                        """
                    )
                    message = telegramify_markdown.markdownify(markdown_text)
                    image = printer.get_camera_image()
                    image.save("bambu_status.png")
                    previous_printer_status = status
                    asyncio.run(send_telegram_message(message, "bambu_status.png"))
            
            except Exception as e:
                print(f"Error during monitoring loop: {e}")
                update_health_status(healthy=False, connected=False, error=str(e))

                
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        printer.disconnect()
        update_health_status(healthy=False, connected=False, error="Service stopped")          