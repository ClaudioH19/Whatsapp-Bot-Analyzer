import time
import threading
import os
from dotenv import load_dotenv
from captura import CapturaVideo
from analisis import AnalizadorVideo
from notificacion import NotificadorWAHA

load_dotenv()

# --- Variables Globales ---
frame_limpio_actual = None
frame_con_boxes_actual = None
corriendo = True

def hilo_ia(analizador, notificador):
    global frame_limpio_actual, frame_con_boxes_actual, corriendo
    viewer_url = (os.getenv("VIDEO_VIEWER_URL") or "").strip()

    while corriendo:
        if frame_limpio_actual is not None:
            # Procesamos
            animales, estado_porton, personas, frame_con_boxes = analizador.procesar(frame_limpio_actual.copy())
            frame_con_boxes_actual = frame_con_boxes

            partes = []
            if animales:
                detalles = ", ".join([f"{a['tipo']} ({a['confianza']:.2f})" for a in animales])
                partes.append(f"🐾 {detalles}")

            if personas:
                detalles = ", ".join([f"{p['tipo']} ({p['confianza']:.2f})" for p in personas])
                partes.append(f"👀 {detalles}")

            if isinstance(estado_porton, str) and "ABIERTO" in estado_porton:
                partes.append(f"🚪 {estado_porton}")

            if partes:
                mensaje = " | ".join(partes)
                if viewer_url:
                    mensaje = f"{mensaje} | 🎥 {viewer_url}"
                notificador.enviar_mensaje(mensaje)
                
        time.sleep(2)

def iniciar_sistema():
    global frame_limpio_actual, frame_con_boxes_actual, corriendo
    
    camara = CapturaVideo(os.getenv("RTSP_URL"))
    analizador = AnalizadorVideo()
    notificador = NotificadorWAHA(
        api_url=os.getenv("WAHA_URL"), 
        api_key=os.getenv("WAHA_API_KEY"),
        chat_id=os.getenv("WAHA_CHAT_ID"),
        session_name=os.getenv("WAHA_SESSION", "default")
    )

    # 1. Hilo de IA
    t_ia = threading.Thread(target=hilo_ia, args=(analizador, notificador), daemon=True)
    t_ia.start()

    print("🚀 Sistema Online. IA + notificaciones activas.")

    try:
        while True:
            ret, frame = camara.obtener_frame()
            if ret:
                frame_limpio_actual = frame
                if frame_con_boxes_actual is None:
                    frame_con_boxes_actual = frame
            time.sleep(1.5) 

    except KeyboardInterrupt:
        corriendo = False
        camara.detener()

if __name__ == "__main__":
    iniciar_sistema()