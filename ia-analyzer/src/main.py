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
corriendo = True

def hilo_ia(analizador, notificador):
    global frame_limpio_actual, corriendo
    while corriendo:
        if frame_limpio_actual is not None:
            # Procesamos
            animales, estado_porton, personas = analizador.procesar(frame_limpio_actual.copy())
            
            if animales:
                detalles = ", ".join([f"{a['tipo']} ({a['confianza']:.2f})" for a in animales])
                notificador.enviar_alerta("animales", f"🐾 Detectado: {detalles}")

            if personas:
                detalles = ", ".join([f"{p['tipo']} ({p['confianza']:.2f})" for p in personas])
                notificador.enviar_alerta("personas", f"👀 Detectado: {detalles}")

            if isinstance(estado_porton, str) and "ABIERTO" in estado_porton:
                notificador.enviar_alerta("porton", f"🚪 Portón: {estado_porton}")
                
        time.sleep(2)

def iniciar_sistema():
    global frame_limpio_actual, corriendo
    
    camara = CapturaVideo(os.getenv("RTSP_URL"))
    analizador = AnalizadorVideo()
    notificador = NotificadorWAHA(
        api_url=os.getenv("WAHA_URL"), 
        api_key=os.getenv("WAHA_API_KEY"),
        chat_id=os.getenv("WAHA_CHAT_ID"),
        session_name=os.getenv("WAHA_SESSION", "default"),
        viewer_url=os.getenv("VIDEO_VIEWER_URL", "")
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
            time.sleep(1.5) 

    except KeyboardInterrupt:
        corriendo = False
        camara.detener()

if __name__ == "__main__":
    iniciar_sistema()