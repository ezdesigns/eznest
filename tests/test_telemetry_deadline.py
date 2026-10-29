"""Exercise the real worker deadline with a slow synthetic loopback receiver."""
import opt_out
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch
import telemetry_sender as sender


class DeadlineTests(unittest.TestCase):
    def test_drip_response_cannot_outlive_deadline_or_leave_worker_running(self):
        payload={'schema':sender.SCHEMA,'requestId':'synthetic-id'}
        finished=threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                body=json.dumps({'outcome':'created','result':payload}).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers()
                try:
                    for byte in body:
                        self.wfile.write(bytes([byte]));self.wfile.flush();time.sleep(.15)
                except (BrokenPipeError,ConnectionResetError):
                    pass
                finally:finished.set()
            def log_message(self,*_):pass
        service=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=service.serve_forever);thread.start()
        url=f'http://127.0.0.1:{service.server_port}/'
        root=str(Path(sender.__file__).parent)
        code=f'import sys;sys.path.insert(0,{root!r});import telemetry_sender as s;s.ENDPOINT={url!r};s.worker()'
        processes=[];real_popen=subprocess.Popen
        def launch(*args,**kwargs):
            process=real_popen(*args,**kwargs);processes.append(process);return process
        try:
            with patch.object(sender,'worker_command',return_value=[sys.executable,'-c',code]),patch.object(subprocess,'Popen',side_effect=launch):
                started=time.monotonic()
                self.assertFalse(sender.emit(payload,'osa_'+'A'*43))
                self.assertLess(time.monotonic()-started,13)
            self.assertEqual(len(processes),1)
            self.assertIsNotNone(processes[0].poll())
            self.assertTrue(finished.wait(3))
        finally:
            service.shutdown();service.server_close();thread.join(3)

    def test_worker_arguments_and_environment_never_contain_the_token(self):
        token='osa_'+'A'*43
        with patch.object(sender.subprocess,'run',return_value=subprocess.CompletedProcess([],0,b'true',b'')) as run:
            self.assertTrue(sender.emit({'schema':sender.SCHEMA},token))
            args,kwargs=run.call_args
            self.assertNotIn(token,repr(args))
            self.assertNotIn(token,repr(kwargs['env']))
            self.assertEqual(kwargs['timeout'],10)
            self.assertEqual(json.loads(kwargs['input'])['token'],token)


if __name__=='__main__':unittest.main()
