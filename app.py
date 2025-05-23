import os
import psycopg2
import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
import json

load_dotenv()

app = Flask(__name__)

DB_CONFIG = {
    'host': os.getenv("DB_HOST"),
    'dbname': os.getenv("DB_NAME"),
    'user': os.getenv("DB_USER"),
    'password': os.getenv("DB_PASSWORD"),
    'port': os.getenv("DB_PORT", 5432)
}

TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP = os.getenv('TWILIO_PHONE_NUMBER')

print("📦 TWILIO_PHONE_NUMBER cargado:", TWILIO_WHATSAPP)
print("TWILIO_PHONE_NUMBER:", os.getenv("TWILIO_PHONE_NUMBER"))

def get_db_connection():
    conn = psycopg2.connect(**DB_CONFIG)
    print("✅ Conexión a la base de datos establecida.")
    return conn

def enviar_template_whatsapp(to_number, comuna_nombre, servicio_nombre, sesion_id):
    url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/Messages.json"
    headers = {'Content-Type': 'application/json'}

    print(f"DEBUG - to_number: '{to_number}'")
    print(f"DEBUG - TWILIO_WHATSAPP: '{TWILIO_WHATSAPP}'")
    print(f"DEBUG - comuna_nombre: '{comuna_nombre}'")
    print(f"DEBUG - servicio_nombre: '{servicio_nombre}'")
    print(f"DEBUG - sesion_id: '{sesion_id}'")

    data = {
        "To": f"whatsapp:{to_number}",
        "From": f"whatsapp:{TWILIO_WHATSAPP}",
        "Template": {
            "Name": "neo_proveedor",
            "Language": "es",
            "Components": [
                {
                    "Type": "body",
                    "Parameters": [
                        {"Type": "text", "Text": comuna_nombre},   # {{1}}
                        {"Type": "text", "Text": servicio_nombre}  # {{2}}
                    ]
                },
                {
                    "Type": "button",
                    "SubType": "quick_reply",
                    "Index": "0",
                    "Parameters": [
                        {"Type": "payload", "Payload": f"respuesta_si_{sesion_id}"}
                    ]
                },
                {
                    "Type": "button",
                    "SubType": "quick_reply",
                    "Index": "1",
                    "Parameters": [
                        {"Type": "payload", "Payload": f"respuesta_no_{sesion_id}"}
                    ]
                }
            ]
        }
    }

    print("Payload enviado a Twilio:", json.dumps(data, indent=2))

    response = requests.post(
        url,
        data=json.dumps(data),
        headers=headers,
        auth=HTTPBasicAuth(TWILIO_SID, TWILIO_AUTH)
    )
    
    print(f"Twilio API response: {response.status_code} {response.text}")
    
    if response.status_code not in (200, 201):
        raise Exception(f"Error al enviar mensaje: {response.text}")

def enviar_mensaje_simple(to_number, mensaje):
    url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/Messages.json"
    data = {
        "To": f"whatsapp:{to_number}",
        "From": f"whatsapp:{TWILIO_WHATSAPP}",
        "Body": mensaje
    }
    response = requests.post(
        url,
        data=data,
        auth=HTTPBasicAuth(TWILIO_SID, TWILIO_AUTH)
    )
    print(f"Twilio API response: {response.status_code} {response.text}")
    if response.status_code not in (200, 201):
        raise Exception(f"Error al enviar mensaje: {response.text}")

def enviar_mensajes_pendientes():
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        print("🔍 Buscando mensajes pendientes...")
        cur.execute("""
            SELECT sesion_id, celular, comuna_id, servicio_id, pregunta_cliente
            FROM envios_whatsapp
            WHERE pregunta_cliente IS NOT NULL
              AND enviado_proveedores = FALSE
            LIMIT 5
        """)
        pendientes = cur.fetchall()

        if not pendientes:
            print("📭 No hay mensajes pendientes por enviar.")
        else:
            print(f"📦 Se encontraron {len(pendientes)} mensajes pendientes.")

        for sesion_id, celular, comuna_id, servicio_id, pregunta_cliente in pendientes:
            print(f"\n➡️ Procesando sesión: {sesion_id}, celular: {celular}")

            # Obtener nombre de la comuna
            cur.execute("SELECT nombre FROM comunas WHERE id = %s", (comuna_id,))
            comuna_result = cur.fetchone()
            if not comuna_result:
                print(f"⚠️ No se encontró comuna para ID {comuna_id}")
                continue
            comuna_nombre = comuna_result[0]
            print(f"🏘️ Comuna detectada: {comuna_nombre}")

            # Obtener nombre del servicio
            cur.execute("SELECT nombre FROM servicios WHERE id = %s", (servicio_id,))
            servicio_result = cur.fetchone()
            if not servicio_result:
                print(f"⚠️ No se encontró servicio para ID {servicio_id}")
                continue
            servicio_nombre = servicio_result[0]
            print(f"🛠️ Servicio detectado: {servicio_nombre}")

            # Buscar proveedores
            cur.execute("""
                SELECT p.nombre, p.telefono
                    FROM proveedores p
                    JOIN comunas c ON p.comuna = c.nombre
                    JOIN servicios s ON p.servicios = s.nombre
                    WHERE c.nombre = %s
                    AND s.id = %s
            """, (comuna_nombre, servicio_id))
            proveedores = cur.fetchall()

            if not proveedores:
                print(f"⚠️ No hay proveedores en {comuna_nombre} para el servicio {servicio_id}")
                continue

            print(f"📞 Se encontraron {len(proveedores)} proveedores para contactar.")

            for nombre_prov, telefono in proveedores:
                print(f"📤 Enviando mensaje a {nombre_prov} ({telefono})...")
                try:
                    print(f"Intentando enviar AAAAAAAAAAAAAAAAAAAAAAA: {nombre_prov} - {telefono}")
                    enviar_template_whatsapp(
                        to_number=telefono,
                        comuna_nombre=comuna_nombre,
                        servicio_nombre=servicio_nombre,
                        sesion_id=sesion_id
                    )
                    print(f"✅ Mensaje enviado exitosamente a {telefono}")
                except Exception as e:
                    print(f"❌ Error al enviar mensaje a {telefono}: {e}")

            print(f"🔄 Marcando mensaje como enviado para sesión {sesion_id}...")
            cur.execute("""
                UPDATE envios_whatsapp
                SET enviado_proveedores = TRUE
                WHERE sesion_id = %s
            """, (sesion_id,))
            conn.commit()
            print("✅ Registro actualizado.")

        cur.close()
        conn.close()
        print("🔒 Conexión cerrada.\n")

    except Exception as e:
        print("❌ Error general en la función enviar_mensajes_pendientes:", e)

@app.route('/')
def index():
    return "Bot de envío activo."

@app.route('/test-enviar')
def test_enviar():
    enviar_mensajes_pendientes()
    return "✅ Envío ejecutado manualmente"

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        # Obtener datos de la solicitud
        data = request.form
        print("📩 Webhook recibido:", data)

        # Obtener el número de teléfono del remitente (sin el prefijo whatsapp:)
        from_number = data.get('From', '').replace('whatsapp:', '')

        # Obtener el payload del botón (si existe)
        button_payload = data.get('ButtonPayload', '')

        # Si no hay payload, puede ser un mensaje de texto normal
        if not button_payload:
            return jsonify({"status": "success", "message": "No es una respuesta de botón"})

        print(f"🔘 Botón presionado: {button_payload} por {from_number}")

        # Verificar si es una respuesta "SI"
        if button_payload.startswith('respuesta_si_'):
            # Extraer el ID de sesión del payload
            sesion_id = button_payload.replace('respuesta_si_', '')

            # Actualizar la base de datos
            conn = get_db_connection()
            cur = conn.cursor()

            # Verificar si la sesión existe
            cur.execute("SELECT * FROM envios_whatsapp WHERE sesion_id = %s", (sesion_id,))
            sesion = cur.fetchone()

            if not sesion:
                print(f"⚠️ No se encontró la sesión {sesion_id}")
                cur.close()
                conn.close()
                return jsonify({"status": "error", "message": "Sesión no encontrada"})

            # Actualizar la columna proveedor_acepta
            cur.execute("""
                UPDATE envios_whatsapp
                SET proveedor_acepta = %s
                WHERE sesion_id = %s
            """, (from_number, sesion_id))

            conn.commit()
            cur.close()
            conn.close()

            print(f"✅ Base de datos actualizada: proveedor {from_number} aceptó la solicitud {sesion_id}")

            # Enviar mensaje de confirmación al proveedor
            try:
                enviar_mensaje_simple(
                    to_number=from_number,
                    mensaje="Gracias, pronto el cliente te contactará."
                )
                print(f"✅ Mensaje de confirmación enviado a {from_number}")
            except Exception as e:
                print(f"❌ Error al enviar mensaje de confirmación: {e}")

            return jsonify({"status": "success", "message": "Respuesta SI procesada correctamente"})

        elif button_payload.startswith('respuesta_no_'):
            # Aquí puedes agregar lógica para manejar respuestas "NO" si lo deseas
            print(f"ℹ️ El proveedor {from_number} rechazó la solicitud")
            return jsonify({"status": "success", "message": "Respuesta NO procesada correctamente"})

        return jsonify({"status": "success", "message": "Webhook procesado correctamente"})

    except Exception as e:
        print(f"❌ Error en webhook: {e}")
        return jsonify({"status": "error", "message": str(e)})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 Iniciando aplicación en el puerto {port}...")

    scheduler = BackgroundScheduler()
    scheduler.add_job(func=enviar_mensajes_pendientes, trigger="interval", seconds=40)
    scheduler.start()
    print("⏰ Scheduler iniciado. Ejecutando cada 40 segundos.")

    app.run(host="0.0.0.0", port=port)