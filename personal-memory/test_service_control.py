import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
try:
    import service_control as control
except ImportError:
    control = None


class ServiceControlTest(unittest.TestCase):
    def test_unrelated_listener_is_not_accepted_as_our_service(self):
        self.assertIsNotNone(control, 'service controller not implemented')
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_GET(self):
                body = b'{"ready":true,"service_id":"some-other-service"}'
                self.send_response(200);self.end_headers();self.wfile.write(body)
        server = HTTPServer(('127.0.0.1',0),Handler)
        thread = threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with self.assertRaisesRegex(ValueError,'其他'):
                control.probe(f'http://127.0.0.1:{server.server_port}')
        finally:
            server.shutdown();server.server_close();thread.join()

    def test_launch_configuration_uses_real_paths_and_survives_terminal_exit(self):
        self.assertIsNotNone(control, 'service controller not implemented')
        config = control.launch_config()
        self.assertTrue(Path(config['ProgramArguments'][0]).is_absolute())
        self.assertIn('memory_search.py', config['ProgramArguments'][2])
        self.assertTrue(config['RunAtLoad'])
        self.assertTrue(config['KeepAlive'])
        self.assertNotIn('API_KEY',json.dumps(config))


if __name__=='__main__':unittest.main()
