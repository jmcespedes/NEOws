import os
import psycopg2
from twilio.rest import Client
from dotenv import load_dotenv
from flask import Flask, request
from apscheduler.schedulers.background import BackgroundScheduler
import requests
from requests.auth import HTTPBasicAuth
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
TWILIO_WHATSAPP = f"{os.getenv('TWILIO_PHONE_NUMBER')}"
TWILIO_CONTENT_SID = os.getenv("TWILIO_CONTENT_SID")  # Agrega esta variable en tu entorno

client = Client(TWILIO_SID, TWILIO_AUTH)

def get_db_connection():
    conn = psycopg2.connect(**DB_CONFIG)
    print("✅ Conexión a la base de datos establecida.")
    return conn

def enviar_mensaje_plantilla(to_whatsapp_number, comuna, servicio, pregunta_cliente):
    url = f'https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/Messages.json'
    content_variables = {
        "1": servicio,
        "2": comuna,
        "3": pregunta_cliente,
        "4": "NEOServicios"
    payload = {
        'To': to_whatsapp_number,
        'From': f'whatsapp:{TWILIO_WHATSAPP}',
        'ContentSid': TWILIO_CONTENT_SID,
        'ContentVariables': json.dumps(content_variables)
    }
    try:
        response = requests.post(url, data=payload, auth=HTTPBasicAuth(TWILIO_SID, TWILIO_AUTH))
        if response.status_code in [200, 201]:
            print(f"✅ Mensaje plantilla enviado a {to_whatsapp_number}")
            return True
        else:
            print(f"❌ Error enviando mensaje plantilla a {to_whatsapp_number}: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Error al enviar mensaje plantilla: {e}")
        return False

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
              AND proveedor_acepta IS NULL
            LIMIT 5
        """)
        pendientes = cur.fetchall()

        if not pendientes:
            print("📭 No hay mensajes pendientes por enviar.")
        else:
            print(f"📦 Se encontraron {len(pendientes)} mensajes pendientes.")

        for sesion_id, celular, comuna_id, servicio_id, pregunta_cliente in pendientes:
            print(f"\n➡️ Procesando sesión: {sesion_id}, celular: {celular}")

            cur.execute("SELECT nombre FROM comunas WHERE id = %s", (comuna_id,))
            comuna_result = cur.fetchone()
            if not comuna_result:
                print(f"⚠️ No se encontró comuna para ID {comuna_id}")
                continue
            comuna_nombre = comuna_result[0]

            cur.execute("""
                SELECT p.nombre, p.telefono, s.nombre as nombre_servicio
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

            for nombre, telefono, nombre_servicio in proveedores:
                to_whatsapp = f"whatsapp:{telefono}"
                exito = enviar_mensaje_plantilla(to_whatsapp, comuna_nombre, nombre_servicio, pregunta_cliente)
                if not exito:
                    print(f"❌ No se pudo enviar plantilla a {telefono}")

            cur.execute("""
                UPDATE envios_whatsapp
                SET enviado_proveedores = TRUE
                WHERE sesion_id = %s
            """, (sesion_id,))
            conn.commit()

        cur.close()
        conn.close()
        print("🔒 Conexión cerrada.\n")

    except Exception as e:
        print("❌ Error general en enviar_mensajes_pendientes:", e)

@app.route('/')
def index():
    return "Bot de envío activo."

@app.route('/test-enviar')
def test_enviar():
    print("Ejecutando envío manual...")
    enviar_mensajes_pendientes()
    return "✅ Envío ejecutado manualmente"

@app.route('/whatsapp-incoming', methods=['POST'])
def whatsapp_incoming():
    from_number = request.values.get('From', '').replace('whatsapp:', '')
    incoming_msg = request.values.get('Body', '').strip().lower()

    button_id = None
    if request.is_json:
        data = request.get_json()
        interactive = data.get('Interactive')
        if interactive and interactive.get('Type') == 'button_reply':
            button_id = interactive['ButtonReply']['Id']
            print(f"📨 Botón presionado: {button_id} desde {from_number}")
    else:
        print(f"📨 Mensaje recibido: {incoming_msg} desde {from_number}")

    if button_id == 'respuesta_si':
        respuesta = 'SI, ACEPTO'
    elif button_id == 'respuesta_no':
        respuesta = 'no'
    else:
        if incoming_msg not in ['SI, ACEPTO', 'sí', 'no']:
            return "⚠️ Por favor, responde solo con SÍ o NO.", 200
        respuesta = incoming_msg

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT sesion_id, celular, comuna_id
        FROM envios_whatsapp
        WHERE enviado_proveedores = TRUE
          AND proveedor_acepta IS NULL
        ORDER BY created_at DESC
        LIMIT 1
    """)
    row = cur.fetchone()

    if not row:
        cur.close()
        conn.close()
        return "⚠️ No hay solicitudes pendientes para este número.", 200

    sesion_id, celular_cliente, comuna_id = row

    if respuesta == 'SI, ACEPTO':
        cur.execute("SELECT nombre FROM comunas WHERE id = %s", (comuna_id,))
        comuna_nombre = cur.fetchone()[0]

        mensaje_contacto = (
            f"✅ Gracias por aceptar. Aquí están los datos del cliente, por favor contactalo lo antes posible:\n"
            f"📍 Comuna: {comuna_nombre}\n📞 Contacto: {celular_cliente}"
        )
        try:
            client.messages.create(
                body=mensaje_contacto,
                from_=f"whatsapp:{TWILIO_WHATSAPP}",
                to=f"whatsapp:{from_number}"
            )
            print(f"📤 Mensaje de contacto enviado a {from_number}")
        except Exception as e:
            print(f"❌ Error al enviar datos de cliente: {e}")

        cur.execute("""
            UPDATE envios_whatsapp
            SET proveedor_acepta = 'SI',
                celular_proveedor = %s
            WHERE sesion_id = %s
        """, (from_number, sesion_id))
        conn.commit()

    elif respuesta == 'no':
        print("🚫 Proveedor no aceptó la solicitud.")

    cur.close()
    conn.close()
    return "✅ Respuesta procesada correctamente.", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 Iniciando aplicación en el puerto {port}...")

    scheduler = BackgroundScheduler()
    scheduler.add_job(func=enviar_mensajes_pendientes, trigger="interval", seconds=40)
    scheduler.start()
    print("⏰ Scheduler iniciado. Ejecutando cada 40 segundos.")

    app.run(host="0.0.0.0", port=port)