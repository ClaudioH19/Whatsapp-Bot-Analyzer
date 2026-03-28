import os
import threading
import time

# Fuerza RTSP sobre TCP para reducir cortes en redes inestables/WiFi.
os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS",
    "rtsp_transport;tcp|stimeout;15000000|max_delay;500000|fflags;nobuffer|flags;low_delay",
)

import cv2

class CapturaVideo:
    # Agregamos los parámetros de ancho y alto por defecto (ideales para YOLO)
    def __init__(self, url_rtsp, ancho=640, alto=480):
        self.url_rtsp = url_rtsp
        self.ancho = ancho
        self.alto = alto
        self.reintentos = 0
        self.max_espera_reconexion = 30
        
        self.cap = self._abrir_captura()
        self.ret = False
        self.frame = None
        self.corriendo = True
        
        if not self.cap.isOpened():
            print(f"[Captura] Advertencia: No se pudo conectar a {self.url_rtsp} al iniciar.")

        # Iniciamos el hilo
        self.hilo = threading.Thread(target=self._actualizar, daemon=True)
        self.hilo.start()

    def _abrir_captura(self):
        cap = cv2.VideoCapture(self.url_rtsp, cv2.CAP_FFMPEG)
        # Reducimos buffer para priorizar frames recientes.
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)
        # Timeouts para cortar lecturas colgadas y reconectar antes.
        cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 8000)
        cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 8000)
        return cap

    def _espera_reconexion(self):
        # Backoff simple: 1, 2, 3... hasta 30 segundos.
        self.reintentos += 1
        espera = min(self.reintentos, self.max_espera_reconexion)
        time.sleep(espera)

    def _actualizar(self):
        """Lee frames y los redimensiona inmediatamente."""
        while self.corriendo:
            if self.cap.isOpened():
                ret, frame_original = self.cap.read()
                
                if ret:
                    # ==========================================
                    # REDIMENSIÓN INMEDIATA ANTES DE GUARDARLO
                    # ==========================================
                    frame_listo = cv2.resize(frame_original, (self.ancho, self.alto))
                    
                    self.ret = ret
                    self.frame = frame_listo
                    self.reintentos = 0
                else:
                    print("[Captura] Señal perdida. Intentando reconectar...")
                    self.cap.release()
                    self.ret = False
                    self._espera_reconexion()
                    self.cap = self._abrir_captura()
            else:
                self.ret = False
                self._espera_reconexion()
                self.cap = self._abrir_captura()

    def obtener_frame(self):
        """Devuelve el frame ya redimensionado y listo para ML"""
        return self.ret, self.frame

    def detener(self):
        self.corriendo = False
        if self.hilo.is_alive():
            self.hilo.join()
        if self.cap.isOpened():
            self.cap.release()
        print("[Captura] Detenido correctamente.")