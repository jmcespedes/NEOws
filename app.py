import os
import psycopg2
from twilio.rest import Client
from dotenv import load_dotenv
from flask import Flask, request
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
            print(f"🏘️ Comuna detectada: {comuna_nombre}")

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
                mensaje = (
                    f"👋 Hola {nombre_prov}, soy de *NEOServicios*.\n"
                    f"Tienes una nueva solicitud en *{comuna_nombre}*:\n\n"
                    f"📝 {pregunta_cliente}\n📞 Contacto: {celular}\n\n"
                    f"¿Deseas tomar esta solicitud? Responde *sí* o *no*."
                )
                try:
                    client.messages.create(
                        body=mensaje,
                        from_=f"whatsapp:{TWILIO_WHATSAPP}",
                        to=f"whatsapp:{telefono}"
                    )
                    print(f"✅ Mensaje enviado a {telefono}")
                except Exception as e:
                    print(f"❌ Error al enviar a {telefono}: {e}")

            cur.execute("""
                UPDATE envios_whatsapp
                SET enviado_proveedores = TRUE
                WHERE sesion_id = %s
            """, (sesion_id,))
            conn.commit()
            print("✅ Registro marcado como enviado.")

        cur.close()
        conn.close()
        print("🔒 Conexión cerrada.\n")

    except Exception as e:
        print("❌ Error general:", e)

@app.route('/')
def index():
    return "Bot de envío activo."

@app.route('/test-enviar')
def test_enviar():
    enviar_mensajes_pendientes()
    return "✅ Envío ejecutado manualmente"

@app.route("/webhook-respuesta", methods=["POST"])
def webhook_respuesta():
    from_number = request.form.get("From", "").replace("whatsapp:", "")
    body = request.form.get("Body", "").strip().lower()

    conn = get_db_connection()
    cur = conn.cursor()

    if body not in ["sí", "si", "no"]:
        client.messages.create(
            body="❌ Por favor responde solo con *sí* o *no*.",
            from_=f"whatsapp:{TWILIO_WHATSAPP}",
            to=f"whatsapp:{from_number}"
        )
        return "❌ Respuesta inválida", 200

    cur.execute("""
        SELECT ew.sesion_id, ew.celular, c.nombre
        FROM envios_whatsapp ew
        JOIN comunas c ON ew.comuna_id = c.id
        WHERE ew.enviado_proveedores = TRUE
          AND ew.proveedor_acepta IS NULL
        ORDER BY ew.created_at ASC
        LIMIT 1
    """)
    resultado = cur.fetchone()

    if not resultado:
        return "📭 No hay sesión pendiente.", 200

    sesion_id, celular_cliente, comuna_nombre = resultado

    if body in ["sí", "si"]:
        mensaje_confirmacion = (
            f"✅ Gracias por aceptar. Aquí están los datos del cliente:\n"
            f"📞 {celular_cliente}\n📍 Comuna: {comuna_nombre}"
        )
        client.messages.create(
            body=mensaje_confirmacion,
            from_=f"whatsapp:{TWILIO_WHATSAPP}",
            to=f"whatsapp:{from_number}"
        )

        cur.execute("""
            UPDATE envios_whatsapp
            SET proveedor_acepta = 'SI',
                celular_proveedor = %s
            WHERE sesion_id = %s
        """, (from_number, sesion_id))
        conn.commit()
        print(f"📝 Proveedor {from_number} aceptó la sesión {sesion_id}.")
    else:
        print(f"🚫 Proveedor {from_number} rechazó la solicitud.")

    cur.close()
    conn.close()
    return "✅ Procesado", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 Iniciando en el puerto {port}...")

    scheduler = BackgroundScheduler()
    scheduler.add_job(func=enviar_mensajes_pendientes, trigger="interval", seconds=40)
    scheduler.start()
    print("⏰ Scheduler activo (cada 40 segundos).")

    app.run(host="0.0.0.0", port=port)
