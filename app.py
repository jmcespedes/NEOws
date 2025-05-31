import os
import psycopg2
from twilio.rest import Client
from dotenv import load_dotenv
from flask import Flask, request
from apscheduler.schedulers.background import BackgroundScheduler
import requests
from requests.auth import HTTPBasicAuth

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
TWILIO_CONTENT_SID = os.getenv("TWILIO_CONTENT_SID")  # Agrega esta variable en tu env

client = Client(TWILIO_SID, TWILIO_AUTH)

def enviar_mensaje_plantilla(to_whatsapp_number):
    url = f'https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/Messages.json'
    payload = {
        'To': to_whatsapp_number,
        'From': f'whatsapp:{TWILIO_WHATSAPP}',
        'ContentSid': TWILIO_CONTENT_SID
    }
    response = requests.post(url, data=payload, auth=HTTPBasicAuth(TWILIO_SID, TWILIO_AUTH))
    if response.status_code == 201 or response.status_code == 200:
        print(f"✅ Mensaje plantilla enviado a {to_whatsapp_number}")
        return True
    else:
        print(f"❌ Error enviando mensaje plantilla a {to_whatsapp_number}: {response.text}")
        return False

def enviar_mensajes_pendientes():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
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

            for nombre_prov, telefono, nombre_servicio in proveedores:
                # Enviar mensaje plantilla en vez de texto libre
                to_whatsapp = f"whatsapp:{telefono}"
                exito = enviar_mensaje_plantilla(to_whatsapp)
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

# El resto de tu código (rutas Flask, whatsapp_incoming, etc.) queda igual

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 Iniciando aplicación en el puerto {port}...")

    scheduler = BackgroundScheduler()
    scheduler.add_job(func=enviar_mensajes_pendientes, trigger="interval", seconds=40)
    scheduler.start()
    print("⏰ Scheduler iniciado. Ejecutando cada 40 segundos.")

    app.run(host="0.0.0.0", port=port)