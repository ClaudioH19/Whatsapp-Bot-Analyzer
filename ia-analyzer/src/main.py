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
ultimas_alertas = {
    "animales": 0.0,
    "personas": 0.0,
    "porton": 0.0,
}
ultimo_envio_general = 0.0


def _puede_alertar(tipo_evento, ahora, cooldowns):
    return (ahora - ultimas_alertas[tipo_evento]) >= cooldowns[tipo_evento]

def hilo_ia(analizador, notificador):
    global frame_limpio_actual, frame_con_boxes_actual, corriendo, ultimas_alertas, ultimo_envio_general
    viewer_url = (os.getenv("VIDEO_VIEWER_URL") or "").strip()
    if viewer_url and not viewer_url.startswith(("http://", "https://")):
        viewer_url = f"http://{viewer_url}"

    cooldowns = {
        "animales": float(os.getenv("ALERTA_COOLDOWN_ANIMALES", "60")),
        "personas": float(os.getenv("ALERTA_COOLDOWN_PERSONAS", "60")),
        "porton": float(os.getenv("ALERTA_COOLDOWN_PORTON", "60")),
    }
    cooldown_global = float(os.getenv("ALERTA_COOLDOWN_GLOBAL", "5"))

    while corriendo:
        if frame_limpio_actual is not None:
            ahora = time.time()
            # Procesamos
            animales, estado_porton, personas, frame_con_boxes = analizador.procesar(frame_limpio_actual.copy())
            frame_con_boxes_actual = frame_con_boxes

            partes = []
            if animales and _puede_alertar("animales", ahora, cooldowns):
                detalles = ", ".join([f"{a['tipo']} ({a['confianza']:.2f})" for a in animales])
                partes.append(f"🐾 {detalles}")
                ultimas_alertas["animales"] = ahora

            if personas and _puede_alertar("personas", ahora, cooldowns):
                detalles = ", ".join([f"{p['tipo']} ({p['confianza']:.2f})" for p in personas])
                partes.append(f"👀 {detalles}")
                ultimas_alertas["personas"] = ahora

            if isinstance(estado_porton, str) and "ABIERTO" in estado_porton and _puede_alertar("porton", ahora, cooldowns):
                partes.append(f"🚪 {estado_porton}")
                ultimas_alertas["porton"] = ahora

            if partes and (ahora - ultimo_envio_general) >= cooldown_global:
                mensaje = " | ".join(partes)
                if viewer_url:
                    mensaje = f"{mensaje} | 🎥 {viewer_url}"
                if not notificador.enviar_foto(frame_con_boxes, caption=mensaje):
                    notificador.enviar_mensaje(mensaje)
                ultimo_envio_general = ahora
                
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