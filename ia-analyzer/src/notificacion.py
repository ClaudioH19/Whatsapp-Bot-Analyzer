import time
import requests
from urllib.parse import urlencode

class NotificadorWAHA:
    def __init__(self, api_url, api_key, chat_id, session_name="default", viewer_url="", cooldown_segundos=60, cooldown_error_segundos=20):
        """
        api_url: La URL donde corre tu contenedor WAHA (ej. http://localhost:3000)
        api_key: Tu clave de API de WAHA
        chat_id: Tu número de WhatsApp con código de país (ej. 56912345678)
        cooldown_segundos: Tiempo mínimo entre mensajes repetidos de la misma categoría
        """
        self.api_url = api_url.rstrip('/') # Quita el / final por si acaso
        self.api_key = api_key
        self.chat_id = chat_id
        self.session_name = session_name or "default"
        self.viewer_url = (viewer_url or "").strip()
        if self.viewer_url and not self.viewer_url.startswith(("http://", "https://")):
            self.viewer_url = f"http://{self.viewer_url}"
        self.cooldown = cooldown_segundos
        self.cooldown_error = max(1, min(cooldown_error_segundos, cooldown_segundos))
        
        # Diccionario para rastrear en qué momento (timestamp) se envió la última alerta
        self.ultimas_alertas = {
            "animales": 0,
            "porton": 0,
            "personas": 0
        }

    def _endpoint(self, path, include_session_query=False):
        if include_session_query:
            query = urlencode({"session": self.session_name})
            return f"{self.api_url}{path}?{query}"
        return f"{self.api_url}{path}"

    def _post_waha(self, path, headers, json_payload, timeout):
        """Intenta formato oficial; si WAHA exige session en query, reintenta automaticamente."""
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

    def _registrar_intento_fallido(self, categoria, detalle_error=None):
        self.ultimas_alertas[categoria] = time.time() - (self.cooldown - self.cooldown_error)
        if detalle_error and "getChat" in detalle_error:
            print("[WAHA] La sesion de WhatsApp no parece lista o el chatId no es valido.")
            print("[WAHA] Verifica que la sesion 'default' este CONNECTED y que WAHA_CHAT_ID exista.")

    def _mensaje_con_link(self, mensaje):
        return mensaje

    def _enviar_url_separada(self, headers):
        if not self.viewer_url:
            return

        data_link = {
            "session": self.session_name,
            "chatId": self.chat_id,
            "text": self.viewer_url
        }

        try:
            resp_link = self._post_waha(
                "/api/sendText",
                headers=headers,
                json_payload=data_link,
                timeout=5
            )
            if resp_link.status_code not in (200, 201):
                print(f"[WAHA] No se pudo enviar URL separada: {resp_link.text}")
        except requests.exceptions.RequestException as e:
            print(f"[WAHA] Error enviando URL separada: {e}")

    def enviar_alerta(self, categoria, mensaje, frame=None):
        tiempo_actual = time.time()
        
        # 1. Verificamos si ya pasó el tiempo de enfriamiento
        tiempo_transcurrido = tiempo_actual - self.ultimas_alertas.get(categoria, 0)
        
        if tiempo_transcurrido > self.cooldown:
            print(f"[WAHA] Enviando WhatsApp ({categoria})...")
            
            # Payload estándar para la API de WAHA
            headers = {
                "X-Api-Key": self.api_key,
                "Content-Type": "application/json",
            }
            data = {
                "session": self.session_name,
                "chatId": self.chat_id,
                "text": self._mensaje_con_link(mensaje)
            }
            
            try:
                # 2. Hacemos la petición HTTP al Docker de WAHA
                respuesta = self._post_waha(
                    "/api/sendText",
                    headers=headers,
                    json_payload=data,
                    timeout=5
                )
                
                if respuesta.status_code == 201 or respuesta.status_code == 200:
                    print(f"[WAHA] ¡Mensaje de '{categoria}' enviado con éxito!")
                    # 3. Solo si el mensaje se envió, reiniciamos el cronómetro
                    self.ultimas_alertas[categoria] = tiempo_actual
                    self._enviar_url_separada(headers)
                else:
                    print(f"[WAHA] Error de API: {respuesta.text}")
                    self._registrar_intento_fallido(categoria, respuesta.text)
                    
            except requests.exceptions.RequestException as e:
                print(f"[WAHA] No se pudo conectar al contenedor WAHA: {e}")
                self._registrar_intento_fallido(categoria, str(e))