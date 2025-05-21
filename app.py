import os
import time
import psycopg2
from twilio.rest import Client
from dotenv import load_dotenv
from flask import Flask

# Cargar variables del archivo .env
load_dotenv()

app = Flask(__name__)

# Conexión a PostgreSQL
DB_CONFIG = {
    'host': os.getenv("DB_HOST"),
    'dbname': os.getenv("DB_NAME"),
    'user': os.getenv("DB_USER"),
    'password': os.getenv("DB_PASSWORD"),
    'port': os.getenv("DB_PORT", 5432)
}

# Twilio
TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP = f"whatsapp:{os.getenv('TWILIO_WHATSAPP_NUMBER')}"

client = Client(TWILIO_SID, TWILIO_AUTH)

def get_db_connection():
    return psycopg2.connect(**DB_CONFIG)

def enviar_mensajes_pendientes():
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Seleccionar los envíos pendientes
        cur.execute("""
            SELECT sesion_id, celular, comuna_id, servicio_id, pregunta_cliente
            FROM envios_whatsapp
            WHERE pregunta_cliente IS NOT NULL
              AND enviado_proveedores = FALSE
            LIMIT 5
        """)
        pendientes = cur.fetchall()

        for sesion_id, celular, comuna_id, servicio_id, pregunta_cliente in pendientes:
            # Obtener comuna
            cur.execute("SELECT nombre FROM comunas WHERE id = %s", (comuna_id,))
            comuna_result = cur.fetchone()
            if not comuna_result:
                print(f"⚠️ No se encontró comuna para ID {comuna_id}")
                continue
            comuna_nombre = comuna_result[0]

            # Buscar proveedores
            cur.execute("""
                SELECT nombre, telefono
                FROM proveedores
                WHERE comuna = %s AND servicio_id = %s
            """, (comuna_nombre, servicio_id))
            proveedores = cur.fetchall()

            if not proveedores:
                print(f"⚠️ No hay proveedores en {comuna_nombre} para el servicio {servicio_id}")
                continue

            for nombre_prov, telefono in proveedores:
                mensaje = (
                    f"👋 Hola {nombre_prov}, tienes una nueva solicitud en {comuna_nombre}:\n\n"
                    f"📝 {pregunta_cliente}\n📞 Contacto: {celular}"
                )

                try:
                    client.messages.create(
                        body=mensaje,
                        from_=TWILIO_WHATSAPP,
                        to=f"whatsapp:{telefono}"
                    )
                    print(f"✅ Mensaje enviado a {nombre_prov} ({telefono})")
                except Exception as e:
                    print(f"❌ Error al enviar mensaje a {telefono}: {e}")

            # Marcar como enviado
            cur.execute("""
                UPDATE envios_whatsapp
                SET enviado_proveedores = TRUE
                WHERE sesion_id = %s
            """, (sesion_id,))
            conn.commit()

        cur.close()
        conn.close()

    except Exception as e:
        print("❌ Error general:", e)

@app.route('/')
def index():
    return "Bot de envío activo."




if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
    while True:
        enviar_mensajes_pendientes()
        time.sleep(40)  # cada 15 segundos
