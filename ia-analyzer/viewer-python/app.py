import os
import time
import threading
import base64
from typing import Optional

import cv2
from flask import Flask, Response, render_template, request
from flask_sock import Sock


def parse_env_file(path: str) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path or not os.path.exists(path):
        return values

    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            values[key] = value
    return values


def resolve_rtsp_url() -> Optional[str]:
    direct = os.getenv("RTSP_URL", "").strip().strip('"').strip("'")
    if direct:
        return direct

    source_env = os.getenv("SOURCE_ENV_FILE", "/run/source.env")
    file_values = parse_env_file(source_env)
    from_file = file_values.get("RTSP_URL", "").strip().strip('"').strip("'")   
    if from_file:
        return from_file

    return None


class CameraStream:
    def __init__(self, url: str):
        self.url = url
        self.lock = threading.Lock()
        self.frame = None
        self.last_frame_ts = 0.0
        self.running = True
        self.cap = None
        self.thread = threading.Thread(target=self._worker, daemon=True)        
        self.thread.start()

    def _open_capture(self):
        if self.cap is not None:
            self.cap.release()

        # Try several capture modes to maximize compatibility with cheap/legacy cameras.
        strategies = [
            "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay",
            "rtsp_transport;udp|fflags;nobuffer|flags;low_delay",
            "rtsp_transport;tcp",
            "",
        ]

        self.cap = None
        for opts in strategies:
            if opts:
                os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = opts
            elif "OPENCV_FFMPEG_CAPTURE_OPTIONS" in os.environ:
                del os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"]

            cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if cap.isOpened():
                # Validate that this strategy yields actual frames.
                ok, _ = cap.read()
                if ok:
                    self.cap = cap
                    return
            cap.release()

    def _worker(self):
        while self.running:
            if self.cap is None or not self.cap.isOpened():
                self._open_capture()
                if self.cap is None or not self.cap.isOpened():
                    time.sleep(2)
                    continue

            # Use read() for broad codec compatibility. Keep only the latest frame in memory.
            ok, frame = self.cap.read()
            if not ok or frame is None:
                self.cap.release()
                self.cap = None
                time.sleep(1)
                continue

            with self.lock:
                self.frame = frame
                self.last_frame_ts = time.time()

    def get_frame_base64(self) -> Optional[str]:
        with self.lock:
            if self.frame is None:
                return None
            # Bajamos la calidad al 65% para que pase por el WebSocket instantáneamente
            ok, encoded = cv2.imencode(".jpg", self.frame, [int(cv2.IMWRITE_JPEG_QUALITY), 65])
            if not ok:
                return None
            return base64.b64encode(encoded.tobytes()).decode("utf-8")

    def get_frame_jpeg(self) -> Optional[bytes]:
        return self.get_frame_jpeg_tuned(quality=70, max_width=0)

    def get_frame_jpeg_tuned(self, quality: int = 70, max_width: int = 0) -> Optional[bytes]:
        with self.lock:
            if self.frame is None:
                return None
            frame = self.frame

        # Resize outside lock to keep capture thread unblocked.
        if max_width and frame.shape[1] > max_width:
            h, w = frame.shape[:2]
            new_h = int(h * (max_width / float(w)))
            frame = cv2.resize(frame, (max_width, new_h), interpolation=cv2.INTER_AREA)

        quality = max(35, min(90, int(quality)))
        ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if not ok:
            return None
        return encoded.tobytes()

    def stop(self):
        self.running = False
        if self.thread.is_alive():
            self.thread.join(timeout=2)
        if self.cap is not None:
            self.cap.release()


app = Flask(__name__)
sock = Sock(app)
RTSP_URL = resolve_rtsp_url()
CAMERA = CameraStream(RTSP_URL) if RTSP_URL else None


@app.after_request
def add_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route("/")
def index():
    return render_template("index.html", has_stream=CAMERA is not None)


@app.route("/video_feed")
def video_feed():
    if CAMERA is None:
        return Response("RTSP_URL no configurada", status=500)

    quality = int(request.args.get("q", "70"))
    max_width = int(request.args.get("w", "0"))
    frame_delay = float(request.args.get("d", "0.05"))
    frame_delay = max(0.01, min(0.25, frame_delay))

    def generate():
        while True:
            frame = CAMERA.get_frame_jpeg_tuned(quality=quality, max_width=max_width)
            if frame is None:
                time.sleep(0.05)
                continue
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
            time.sleep(frame_delay)

    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/video_feed_mobile")
def video_feed_mobile():
    # Mobile profile tuned for low bandwidth and lower buffering on phones.
    if CAMERA is None:
        return Response("RTSP_URL no configurada", status=500)

    def generate():
        while True:
            frame = CAMERA.get_frame_jpeg_tuned(quality=50, max_width=640)
            if frame is None:
                time.sleep(0.06)
                continue
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
            time.sleep(1)

    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")


@sock.route("/ws_video")
def ws_video(ws):
    """
    Ruta WebSocket para empujar frames al cliente.
    """
    if CAMERA is None:
        ws.send("closed")
        return
        
    while True:
        try:
            b64_frame = CAMERA.get_frame_base64()
            if b64_frame:
                ws.send(b64_frame)
            time.sleep(0.05) # Control de limitación (approx 20 FPS max) para que la red no muera.
        except Exception as e:
            # Cliente desconectado
            break


@app.route("/health")
def health():
    if CAMERA is None:
        return {
            "ok": False,
            "stream_configured": False,
            "reason": "RTSP_URL missing",
        }

    age_sec = time.time() - CAMERA.last_frame_ts if CAMERA.last_frame_ts else None
    return {
        "ok": age_sec is not None and age_sec < 5,
        "stream_configured": True,
        "capture_opened": CAMERA.cap is not None and CAMERA.cap.isOpened(),
        "frame_age_sec": age_sec,
    }


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, threaded=True)
