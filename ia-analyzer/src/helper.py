import cv2
import os
from dotenv import load_dotenv

# --- CONFIGURACIÓN ---
# Tu URL de iCSee exacta con stream=1 (para calibrar en el tamaño real de ML)
load_dotenv()
URL_RTSP = os.getenv("RTSP_URL")
ANCHO_ML = 640
ALTO_ML = 480

# --- VARIABLES GLOBALES DEL MOUSE ---
drawing = False
ix, iy = -1, -1
tx, ty = -1, -1
roi_coordinates = None

def draw_rectangle(event, x, y, flags, param):
    global ix, iy, tx, ty, drawing, roi_coordinates

    if event == cv2.EVENT_LBUTTONDOWN:
        drawing = True
        ix, iy = x, y
        roi_coordinates = None # Reiniciar

    elif event == cv2.EVENT_MOUSEMOVE:
        if drawing:
            tx, ty = x, y

    elif event == cv2.EVENT_LBUTTONUP:
        drawing = False
        roi_coordinates = (iy, ty, ix, tx) # Formato: y_inicio, y_fin, x_inicio, x_fin
        print("\n=== ¡COORDENADAS ENCONTRADAS! ===")
        print(f"Pégalas en analisis.py en self.roi_porton:")
        print(f"[{iy}, {ty}, {ix}, {tx}]")
        print("===============================\n")

# --- INICIALIZACIÓN ---
cap = cv2.VideoCapture(URL_RTSP)
if not cap.isOpened():
    print("Error: No se pudo conectar a la cámara.")
    exit()

cv2.namedWindow('Asistente de Mapeo de ROI')
cv2.setMouseCallback('Asistente de Mapeo de ROI', draw_rectangle)

print("\n--- INSTRUCCIONES ---")
print("1. Espera a que se cargue la imagen.")
print("2. Mantén presionado el botón IZQUIERDO del mouse sobre una esquina de tu portón.")
print("3. Arrastra hasta la esquina opuesta para formar un rectángulo.")
print("4. Suelta el botón. Las coordenadas aparecerán aquí en la consola.")
print("5. Presiona 'q' para salir.")

while True:
    ret, frame_full = cap.read()
    if not ret:
        print("Se perdió la conexión.")
        break

    # IMPORTANTE: Mapeamos en el tamaño que usará ML
    frame = cv2.resize(frame_full, (ANCHO_ML, ALTO_ML))

    # Dibujar rectángulo en tiempo real si estamos arrastrando
    if drawing and ix != -1:
        cv2.rectangle(frame, (ix, iy), (tx, ty), (0, 255, 0), 2)
    
    # Dibujar el rectángulo final guardado
    if roi_coordinates:
        y1, y2, x1, x2 = roi_coordinates
        # Convertimos coordenadas Y/X para el rectángulo de OpenCV (X/Y)
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)

    cv2.imshow('Asistente de Mapeo de ROI', frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()