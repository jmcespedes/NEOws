import os
import psycopg2
from twilio.rest import Client
from dotenv import load_dotenv
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler

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

# Para depurar temporalmente:
print("📦 TWILIO_PHONE_NUMBER cargado:", TWILIO_WHATSAPP)
print("TWILIO_PHONE_NUMBER:", os.getenv("TWILIO_PHONE_NUMBER"))

client = Client(TWILIO_SID, TWILIO_AUTH)

def get_db_connection():
    conn = psycopg2.connect(**DB_CONFIG)
    print("✅ Conexión a la base de datos establecida.")
    return conn

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
                    print("FROM:", f"whatsapp:{TWILIO_WHATSAPP}")
                    print("TO:", f"whatsapp:{telefono}")
                    # Enviar usando plantilla con variables
                    message = client.messages.create(
                        from_=f"whatsapp:{TWILIO_WHATSAPP}",
                        to=f"whatsapp:{telefono}",
                        template={
                            'name': 'neo_proveedor',
                            'language_code': 'es',
                            'components': [
                                {
                                    'type': 'body',
                                    'parameters': [
                                        {'type': 'text', 'text': comuna_nombre},      # {{1}}
                                        {'type': 'text', 'text': servicio_nombre}     # {{2}}
                                    ]
                                }
                            ]
                        }
                    )
                    print(f"✅ Mensaje enviado exitosamente (SID: {message.sid})")
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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 Iniciando aplicación en el puerto {port}...")

    scheduler = BackgroundScheduler()
    scheduler.add_job(func=enviar_mensajes_pendientes, trigger="interval", seconds=40)
    scheduler.start()
    print("⏰ Scheduler iniciado. Ejecutando cada 40 segundos.")

    app.run(host="0.0.0.0", port=port)
