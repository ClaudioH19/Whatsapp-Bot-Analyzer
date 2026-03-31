import base64
import cv2
import requests
from urllib.parse import urlencode


class NotificadorWAHA:
    def __init__(self, api_url, api_key, chat_id, session_name="default"):
        """Cliente simple para enviar texto y fotos por WAHA."""
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.chat_id = chat_id
        self.session_name = session_name or "default"

    def _endpoint(self, path, include_session_query=False):
        if include_session_query:
            query = urlencode({"session": self.session_name})
            return f"{self.api_url}{path}?{query}"
        return f"{self.api_url}{path}"

    def _post_waha(self, path, json_payload, timeout=5):
        headers = {
            "X-Api-Key": self.api_key,
            "Content-Type": "application/json",
        }

        # Intenta formato normal y reintenta con session en query si WAHA lo solicita.
        respuesta = requests.post(
            self._endpoint(path),
            headers=headers,
            json=json_payload,
            timeout=timeout
        )
        respuesta_texto = (respuesta.text or "").lower()
        if respuesta.status_code == 400 and "session name is required" in respuesta_texto:
            respuesta = requests.post(
                self._endpoint(path, include_session_query=True),
                headers=headers,
                json=json_payload,
                timeout=timeout
            )
        return respuesta

    def enviar_mensaje(self, mensaje):
        data = {
            "session": self.session_name,
            "chatId": self.chat_id,
            "text": mensaje,
        }

        try:
            respuesta = self._post_waha("/api/sendText", data)
            if respuesta.status_code in (200, 201):
                return True
            print(f"[WAHA] Error enviando mensaje: {respuesta.text}")
            return False
        except requests.exceptions.RequestException as e:
            print(f"[WAHA] No se pudo conectar al contenedor WAHA: {e}")
            return False

    def enviar_foto(self, frame, caption=""):
        exito, buffer = cv2.imencode(".jpg", frame)
        if not exito:
            print("[WAHA] No se pudo convertir el frame a JPEG")
            return False

        imagen_base64 = base64.b64encode(buffer.tobytes()).decode("ascii")
        data = {
            "session": self.session_name,
            "chatId": self.chat_id,
            "caption": caption,
            "file": {
                "mimetype": "image/jpeg",
                "filename": "captura.jpg",
                "data": imagen_base64,
            },
        }

        try:
            respuesta = self._post_waha("/api/sendImage", data)
            if respuesta.status_code in (200, 201):
                print("[WAHA] Foto enviada correctamente")
                return True

            # Fallback: algunas versiones de WAHA aceptan imagen base64 como data URL.
            data_fallback = {
                "session": self.session_name,
                "chatId": self.chat_id,
                "caption": caption,
                "file": {
                    "url": f"data:image/jpeg;base64,{imagen_base64}",
                },
            }
            respuesta_fb = self._post_waha("/api/sendImage", data_fallback)
            if respuesta_fb.status_code in (200, 201):
                print("[WAHA] Foto enviada correctamente (fallback data URL)")
                return True

            print(f"[WAHA] Error enviando foto: {respuesta.text}")
            print(f"[WAHA] Error enviando foto (fallback): {respuesta_fb.text}")
            return False
        except requests.exceptions.RequestException as e:
            print(f"[WAHA] No se pudo conectar al contenedor WAHA: {e}")
            return False