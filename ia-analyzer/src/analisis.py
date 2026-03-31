import cv2
import numpy as np
import os
from ultralytics import YOLO

class AnalizadorVideo:
    def __init__(self):
        print("[Analisis] Cargando modelo YOLOv8 nano...")
        # Usamos la versión 'nano' (yolov8n.pt) que es la más rápida para CPU/Docker
        self.modelo = YOLO('yolov8n.pt') 
        
        # Clases animales COCO más comunes en exteriores.
        # 14=bird, 15=cat, 16=dog, 17=horse, 18=sheep, 19=cow, 21=bear, 22=zebra, 23=giraffe
        self.clases_animales = [14, 15, 16, 17, 18, 19, 21, 22, 23]
        self.nombres_animales = {
            15: "Gato",
            16: "Perro",
        }
        self.conf_animales = float(os.getenv("ANIMAL_CONFIDENCE", "0.35"))
        self.iou_animales = float(os.getenv("ANIMAL_IOU", "0.45"))

        #Filtro personas y autos
        self.clases_personas = [0, 2] # 0 = persona, 2 = auto
        
        # Porton
        self.roi_porton = [55, 166, 446, 587]
        self.frame_base_cerrado = None

        # Umbrales ajustables por entorno para calibrar sin tocar codigo.
        # Desv >= 30 suele indicar porton abierto en este escenario.
        self.umbral_desviacion = float(os.getenv("PORTON_UMBRAL_DESVIACION", "30"))
        self.umbral_pixel_cambio = int(os.getenv("PORTON_UMBRAL_PIXEL", "25"))
        self.umbral_ratio_cambio = float(os.getenv("PORTON_UMBRAL_RATIO", "0.08"))

        self.contador_frames_abierto = 0
        self.contador_frames_cerrado = 0
        # Cuántos frames SEGUIDOS debe estar alterada la imagen para confirmar
        self.frames_para_confirmar = int(os.getenv("PORTON_FRAMES_CONFIRMAR", "3"))
        self.frames_para_cerrar = int(os.getenv("PORTON_FRAMES_CERRAR", "3"))
        self.estado_porton_confirmado = "CERRADO"


    def procesar(self, frame):
        """
        Recibe el frame limpio desde captura.py, ejecuta los análisis
        y devuelve los resultados.
        """
        # 1. Análisis de Animales (YOLO)
        animales_detectados = self._detectar_animales(frame)

        # 2. Análisis del Portón
        estado_porton = self._analizar_porton(frame)

        # 3. Análisis de personas
        personas_detectadas = self._detectar_personas(frame)

        frame_con_boxes = frame.copy()
        self._dibujar_detecciones(frame_con_boxes, animales_detectados + personas_detectadas)

        return animales_detectados, estado_porton, personas_detectadas, frame_con_boxes

    def _dibujar_detecciones(self, frame, detecciones):
        for d in detecciones:
            x1, y1, x2, y2 = d["bbox"]
            tipo = d["tipo"]
            confianza = d["confianza"]

            if tipo == "Persona":
                color = (50, 220, 50)
            elif tipo == "Auto":
                color = (255, 160, 0)
            else:
                color = (40, 110, 255)

            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            etiqueta = f"{tipo} {confianza:.2f}"
            cv2.putText(frame, etiqueta, (x1, max(20, y1 - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
    
    def _detectar_personas(self, frame):
        resultados = self.modelo(frame, classes=self.clases_personas, verbose=False)
        detectados = []

        for r in resultados:
            for box in r.boxes:
                clase_id=int(box.cls[0])
                confianza=float(box.conf[0])
                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())

                if confianza > 0.5:
                    nombre = "Persona" if clase_id == 0 else "Auto" if clase_id == 2 else "Motocicleta"
                    detectados.append({"tipo": nombre, "confianza": confianza, "bbox": (x1, y1, x2, y2)})
        return detectados


    def _detectar_animales(self, frame):
        # verbose=False evita que llene tu consola de logs por cada frame
        resultados = self.modelo(
            frame,
            classes=self.clases_animales,
            conf=self.conf_animales,
            iou=self.iou_animales,
            verbose=False,
        )
        
        detectados = []
        # Extraemos la información útil de la predicción
        for r in resultados:
            for box in r.boxes:
                clase_id = int(box.cls[0])
                confianza = float(box.conf[0])
                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                
                # Umbral configurable por entorno para evitar perder animales por baja confianza.
                if confianza >= self.conf_animales:
                    nombre = self.nombres_animales.get(clase_id, f"Animal-{clase_id}")
                    detectados.append({"tipo": nombre, "confianza": confianza, "bbox": (x1, y1, x2, y2)})
                    
        return detectados

    def _analizar_porton(self, frame):
        y1, y2, x1, x2 = self.roi_porton
        # Validación de seguridad
        y1, y2 = max(0, y1), min(frame.shape[0], y2)
        x1, x2 = max(0, x1), min(frame.shape[1], x2)
        
        recorte = frame[y1:y2, x1:x2]
        if recorte.size == 0:
            return "Error ROI"

        gris = cv2.cvtColor(recorte, cv2.COLOR_BGR2GRAY)
        gris = cv2.GaussianBlur(gris, (21, 21), 0)

        if self.frame_base_cerrado is None:
            self.frame_base_cerrado = gris
            return "Calibrando..."

        diferencia = cv2.absdiff(self.frame_base_cerrado, gris)
        desviacion = np.mean(diferencia)
        _, mascara_cambios = cv2.threshold(diferencia, self.umbral_pixel_cambio, 255, cv2.THRESH_BINARY)
        ratio_cambio = float(cv2.countNonZero(mascara_cambios)) / float(mascara_cambios.size)

        # Apertura por desviacion alta o por ratio alto con una desviacion minima de respaldo.
        # Esto conserva sensibilidad sin disparar por ruido puntual.
        apertura_por_desviacion = desviacion >= self.umbral_desviacion
        apertura_por_ratio = (ratio_cambio >= self.umbral_ratio_cambio) and (desviacion >= self.umbral_desviacion * 0.8)
        apertura_detectada = apertura_por_desviacion or apertura_por_ratio

        if apertura_detectada:
            self.contador_frames_abierto += 1
            self.contador_frames_cerrado = 0

            if self.contador_frames_abierto >= self.frames_para_confirmar:
                self.estado_porton_confirmado = "ABIERTO"
                return f"ABIERTO (Desv: {desviacion:.1f}, Cambio: {ratio_cambio:.3f})"

            return f"TRANSICION (Posible apertura, Desv: {desviacion:.1f}, Cambio: {ratio_cambio:.3f})"
        else:
            self.contador_frames_abierto = 0
            self.contador_frames_cerrado += 1

            # Reaprende lentamente el fondo solo cuando se ve estable para evitar derivas bruscas.
            if self.contador_frames_cerrado >= self.frames_para_cerrar:
                self.estado_porton_confirmado = "CERRADO"
                self.frame_base_cerrado = cv2.addWeighted(self.frame_base_cerrado, 0.95, gris, 0.05, 0)

            return f"CERRADO (Desv: {desviacion:.1f}, Cambio: {ratio_cambio:.3f})"