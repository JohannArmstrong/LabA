# En cuanto a la comunicación con la DB, este script es funcina de forma
# muy parecida al que toma los datos desde el CSV desde google.
# La diferencia es que este los toma de un json cuando se lo envía google
# cuando el formulario es enviado.



from flask import Flask, request, jsonify, render_template, make_response, url_for
import pdfkit
from weasyprint import HTML, CSS
from bs4 import BeautifulSoup
import psycopg as psy
from datetime import datetime
import logging
import os
import atexit # para cerrar ngrok al cerrar el server
from decimal import Decimal, InvalidOperation
import math
import threading
import pandas as panda
import atexit

# Intervalo para ejecutar el escaneo de los archivos CSV adjuntos
INTERVALO_CARGA = 1200  # tiempo en SEGUNDOS     3600 = 1 hora

# CSV público de google sheets
# Se pueden agregar más archivos separados con coma
'''
links = [ 
    "https://docs.google.com/spreadsheets/d/e/2PACX-1vTilwi5g-OdfObKJmRWFIV-8N0RBaGLX2QiF0bmSpl915RlkIed5Ye-O80Ey5crsg5D7o8bCNtz26sv/pub?gid=1350431005&single=true&output=csv",
    "https://docs.google.com/spreadsheets/d/e/2PACX-1vTilwi5g-OdfObKJmRWFIV-8N0RBaGLX2QiF0bmSpl915RlkIed5Ye-O80Ey5crsg5D7o8bCNtz26sv/pub?gid=728128631&single=true&output=csv"
    
]'''
links = []

# Se inicia un temporizador que ejecuta el escaneo de las hojas de google
t = None
def scheduler():
    cargar_csv_a_db() #ejecuta la carga
    # tomo la t declarada global ahí arriba
    global t
    # vuelve a programar la siguiente ejecución
    t = threading.Timer(INTERVALO_CARGA, scheduler)
    t.daemon = True  # importante: hace que el hilo no bloquee la salida
    t.start()


app = Flask(__name__)

# cambia los NaN, etc. para mostrar "-" en las tablas
# Los @app usan jinja2 a través de flask
# se usa directamente desde el HTML con <td>{{ cell|default_dash }}</td>
@app.template_filter("default_dash")
def default_dash(value):
    if value is None or str(value).lower() in ("nan", "none"):
        return "-"
    return value

@app.template_filter("sin_especificar")
def sin_especificar(value):
    if value is None or str(value).lower() in ("nan", "none"):
        return "Sin especificar"
    return value


# almacena logs en un archivo local. Para eso el módulo "os"
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    filename="logs/server.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# config para conección con la DB
DB_CONFIG = {
    "host": "localhost",
    "dbname": "labA",
    "user": "postgres",
    "password": "Passw0rd",
    "port": 5432
}

# uso de la config de la DB para crear la cadena de conecci'on
conn_str = (
    f"host={DB_CONFIG['host']} dbname={DB_CONFIG['dbname']} "
    f"user={DB_CONFIG['user']} password={DB_CONFIG['password']} port={DB_CONFIG['port']}"
)

############################################################################################################
# Las siguientes funciones contienen toda la lógica necesaria para cargar                                  #
# los datos desde el archivo exportado en formato csv hacia la DB.                                         #
# ##########################################################################################################

# cambia valores numéricos de fecha a formato TIMESTAMP
def parse_timestamp(value):
    if not value or not isinstance(value, str):
        return None
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except Exception:
            pass
    return None

# transforma float a int
def parse_int(value):
    try:
        return int(float(value))
    except Exception:
        return None


def parse_decimal(value):
    if value is None:
        return None
    try:
        v = str(value).replace(",", ".").strip()
        if v == "":
            return None
        d = Decimal(v)
        # descartar NaN o infinitos
        if d.is_nan() or d.is_infinite():
            return None
        return d
    except (InvalidOperation, ValueError):
        return None
        

# funci'on para obtener o insertar ID en tablas normalizadas
def get_or_create_id(cur, table, name_value):
    """ Devuelve el id de la tabla normalizada. Inserta si no existe """
    if not name_value or str(name_value).strip() == "":
        return None

    name_value = str(name_value).strip()

    cur.execute(f"SELECT id_{table} FROM {table} WHERE nombre = %s;", (name_value,))
    row = cur.fetchone()

    if row:
        return row[0]

    cur.execute(
        f"INSERT INTO {table} (nombre) VALUES (%s) RETURNING id_{table};",
        (name_value,)
    )
    return cur.fetchone()[0]

def cargar_csv_a_db():
    print("▶ Ejecutando carga automática desde CSV ▶")
    
    total = 0 # para mostrar total de inserciones

    for link in links:
        # lee hoja 
        hoja = panda.read_csv(link)
        hoja.columns = [name.strip().replace("\n", " ").replace("\r", "").replace("  ", " ") for name in hoja.columns]

        print("Columnas detectadas:")
        print(hoja.columns.tolist())
        print(f"Total de filas leídas (sin encabezado): {len(hoja)}")
        print(hoja.head(3))


        with psy.connect(conn_str) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM proyecto;")
                total_antes = cur.fetchone()[0]

                tiene_copiado = "Ya copiado" in hoja.columns
                tiene_estado = "Estado" in hoja.columns

                for i, row in hoja.iterrows():
                    email = row.get("Dirección de correo electrónico")
                    nombre = row.get("Nombre completo:")

                    print(f"Fila {i+1} → email={repr(email)}, nombre={repr(nombre)}")

                    if not email or not nombre:
                        print(f"⚠ Fila {i+1} sin email o nombre → omitida")
                        continue

                    # usuario
                    cur.execute("SELECT id_usuario FROM usuario WHERE email = %s;", (email,))
                    user_row = cur.fetchone()
                    if user_row:
                        id_usuario = user_row[0]
                    else:
                        cur.execute(
                            "INSERT INTO usuario (nombre, email) VALUES (%s, %s) RETURNING id_usuario;",
                            (nombre, email)
                        )
                        id_usuario = cur.fetchone()[0]
                        print(f"🆕 Usuario creado: {nombre} ({email}) id={id_usuario}")

                    fecha_registro = parse_timestamp(str(row.get("Marca temporal")))
                    fecha_necesidad = parse_timestamp(str(row.get("Fecha de necesidad: (considerar fecha de necesidad teniendo en cuenta una semana de antelación)")))

                    tiempo_estimado = parse_decimal(row.get("Tiempo estimado de utilización de la herramienta / material / servicio (hs):"))


                    # por si hay texto en vez de números, aunque de todas formas inserta null
                    cantidad_prototipos = row.get("Cantidad de prototipos a fabricar:")
                    try:
                        cantidad_prototipos = parse_int(cantidad_prototipos)
                    except Exception:
                        pass

                    # estas 2 columnas puede que no vayan en la DB final
                    # por ahora están de forma opcional para poder probarlas al completar yo el formulario
                    copiado = row.get("Ya copiado") if tiene_copiado else None
                    estado_val = row.get("Estado") if tiene_estado else None

                    # NUEVO SISTEMA → obtiene IDs de tablas normalizadas (alternativo a lo que se hace con usuario)
                    id_cargo = get_or_create_id(cur, "cargo", row.get("Describa su cargo dentro de la Institución y/o Proyecto."))
                    id_sede = get_or_create_id(cur, "sede", row.get("En qué sede queda el laboratorio al cual quiere acceder:"))
                    id_tipo = get_or_create_id(cur, "tipo", row.get("Seleccione el tipo de solicitud"))
                    id_herramienta = get_or_create_id(cur, "herramienta", row.get("Seleccione la herramienta, material o servicio que desea utilizar:"))
                    id_origen_material = get_or_create_id(cur, "origen_material", row.get("Origen del material"))
                    id_estado = get_or_create_id(cur, "estado", estado_val)
                    # 'carrera' por si quieren hacerla con opciones precargadas en un futuro
                    id_carrera = get_or_create_id(cur, "carrera", row.get("Describa a qué carrera y/o institución corresponde el proyecto:"))


                    # valores ordenados según la nueva tabla
                    valores = (
                        fecha_registro,
                        id_usuario,
                        id_carrera,
                        id_cargo,
                        id_sede,
                        row.get("Nombre del proyecto/actividad:"),
                        row.get("Breve descripción del proyecto"),
                        id_tipo,
                        id_herramienta,
                        row.get("Material a utilizar"),
                        cantidad_prototipos,
                        row.get("Vinculación del proyecto con las acciones relacionadas a las herramientas de fabricación digital / materiales / servicios: (justificación de uso)"),
                        fecha_necesidad,
                        tiempo_estimado,
                        #row.get("Tiempo estimado de utilización de la herramienta / material / servicio (hs):"),
                        row.get("Otros comentarios"),
                        id_origen_material,
                        copiado,
                        id_estado
                    )

                    print(f"\n➡ Insertando proyecto de: {nombre}")

                    try:
                        cur.execute("""
                            INSERT INTO proyecto (
                                fecha_registro,
                                id_usuario,
                                id_carrera,
                                id_cargo,
                                id_sede,
                                nombre_proyecto,
                                descripcion,
                                id_tipo,
                                id_herramienta,
                                material,
                                cantidad_prototipos,
                                justificacion,
                                fecha_necesidad,
                                tiempo_estimado,
                                otros_comentarios,
                                id_origen_material,
                                copiado,
                                id_estado
                            ) VALUES (
                                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                            )

                            ON CONFLICT (id_usuario, fecha_registro)
                            DO UPDATE SET
                                id_carrera = EXCLUDED.id_carrera,
                                id_cargo = EXCLUDED.id_cargo,
                                id_sede = EXCLUDED.id_sede,
                                nombre_proyecto = EXCLUDED.nombre_proyecto,
                                descripcion = EXCLUDED.descripcion,
                                id_tipo = EXCLUDED.id_tipo,
                                id_herramienta = EXCLUDED.id_herramienta,
                                material = EXCLUDED.material,
                                cantidad_prototipos = EXCLUDED.cantidad_prototipos,
                                justificacion = EXCLUDED.justificacion,
                                fecha_necesidad = EXCLUDED.fecha_necesidad,
                                tiempo_estimado = EXCLUDED.tiempo_estimado,
                                otros_comentarios = EXCLUDED.otros_comentarios,
                                id_origen_material = EXCLUDED.id_origen_material,
                                copiado = EXCLUDED.copiado,
                                id_estado = EXCLUDED.id_estado;
                        """, valores)

                        if cur.rowcount == 0:
                            print("⚠ No se insertó (conflicto o duplicado)")
                        else:
                            print("✅ Proyecto insertado")

                    except Exception as e:
                        print(f"❌ Error en fila {i+1}: {e}")
                        conn.rollback()
                        continue

                conn.commit()

                cur.execute("SELECT COUNT(*) FROM proyecto;")
                total_despues = cur.fetchone()[0]
                insertados = total_despues - total_antes
                total += insertados
                print(f"\n✔ Registros insertados/editados ahora: {insertados}")
                print(f"\n✔ Total de registros insertados/editados: {total}")

            #print("Script ejecutado sin problemas.")    luego poner el nombre del archivo cargado




    print("✔ Carga finalizada")










# funciones auxiliares -------------------------------------------------------------------------------------
'''
def parse_date(value):
    if not value:
        return None

    value = str(value).strip()

    # A veces Google Forms manda "2025-01-31T12:33:10.123Z"
    if "T" in value and "Z" in value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except:
            pass

    formatos = [
        "%Y-%m-%d",              # JSON Google Forms (solo fecha)
        "%Y-%m-%d %H:%M:%S",     # JSON Google Forms (fecha y hora)
        "%d/%m/%Y",              # CSV Google Sheets
        "%d/%m/%Y %H:%M:%S",     # CSV Google Sheets (si agrega hora)
        "%Y/%m/%d",              # Algunas configuraciones
        "%Y/%m/%d %H:%M:%S"
    ]

    for fmt in formatos:
        try:
            return datetime.strptime(value, fmt).date()
        except:
            pass

    print("⚠ No se pudo parsear la fecha:", value)
    return None



def parse_int(value):
    try:
        return int(float(value))
    except Exception:
        return None


def parse_decimal(value):
    if value is None:
        return None
    try:
        v = str(value).replace(",", ".").strip()
        if v == "":
            return None
        d = Decimal(v)
        # descarta NaN o infinitos
        if d.is_nan() or d.is_infinite():
            return None
        return d
    except (InvalidOperation, ValueError):
        return None


def clean_keys(data):
    clean = {}
    for key, value in data.items():
        new_key = key.strip().replace("\n", " ").replace("\r", "").replace("  ", " ")
        clean[new_key] = value
    return clean
'''

'''
# NUEVA FUNCIÓN ⇨ consulta/crea valores en tablas normalizadas

def get_or_create(cur, table, field, value):
    """
    Busca un valor en una tabla normalizada.
    Si no existe, lo crea.
    Retorna el id.
    """
    if value is None or str(value).strip() == "":
        return None

    cur.execute(f"SELECT id_{table} FROM {table} WHERE {field} = %s;", (value,))    
    row = cur.fetchone()

    if row:
        return row[0]

    cur.execute(
        f"INSERT INTO {table} ({field}) VALUES (%s) RETURNING id_{table};",
        (value,)
    )
    return cur.fetchone()[0]
'''

'''
# establece la ruta, es decir, el "túnel" que proporciona ngrok
# para la entrada de datos hacia la DB
@app.route("/api/nuevo_proyecto", methods=["POST"])
def nuevo_proyecto():
    data = clean_keys(request.get_json())
    logging.info(f"📩 Datos recibidos: {data}")

    # si por alguna razón no se puede parsear la fecha, se coloca la actual
    fecha_registro = parse_date(str(data.get("Marca temporal"))) or datetime.now().date()
    
    # para evitar errores que había
    #fecha_necesidad_raw = data.get("Fecha de necesidad: (considerar fecha de necesidad teniendo en cuenta una semana de antelación)")
    #fecha_necesidad = parse_date(fecha_necesidad_raw)

    # fecha_registro = parse_date(str(data.get("Marca temporal"))) or datetime.now().date()
    # esa anda pero se ve que toma el date.now
    fecha_necesidad = parse_date(str(data.get("Fecha de necesidad: (considerar fecha de necesidad teniendo en cuenta una semana de antelación)")))
    # Manejo flexible de la clave de fecha de necesidad

    #key_fecha_necesidad = next(
    #    (k for k in data.keys() if "Fecha de necesidad" in k),
    #    None
    #)
    #print(">>> Fecha llegada del JSON:", data.get(key_fecha_necesidad))


    #fecha_necesidad = parse_date(str(data.get(key_fecha_necesidad))) if key_fecha_necesidad else None



    cantidad_prototipos = parse_int(data.get("Cantidad de prototipos a fabricar:"))

    copiado = data.get("Ya copiado") if "Ya copiado" in data else None
    estado_raw = data.get("Estado") if "Estado" in data else None

    try:
        with psy.connect(conn_str) as conn:
            with conn.cursor() as cur:

                # verifica si el usuario ya existe
                email = data.get("Dirección de correo electrónico")
                nombre = data.get("Nombre completo:")

                cur.execute("SELECT id_usuario FROM usuario WHERE email = %s;", (email,))
                user_row = cur.fetchone()

                if user_row:
                    id_usuario = user_row[0]
                else:
                    cur.execute(
                        "INSERT INTO usuario (nombre, email) VALUES (%s, %s) RETURNING id_usuario;",
                        (nombre, email)
                    )
                    id_usuario = cur.fetchone()[0]

                
                # nuevo método para consultar/insertar en las nuevas tablas
                id_cargo = get_or_create(
                    cur, "cargo", "nombre",
                    data.get("Describa su cargo dentro de la Institución y/o Proyecto.")
                )

                id_sede = get_or_create(
                    cur, "sede", "nombre",
                    data.get("En qué sede queda el laboratorio al cual quiere acceder:")
                )

                id_tipo = get_or_create(
                    cur, "tipo", "nombre",
                    data.get("Seleccione el tipo de solicitud")
                )

                id_herramienta = get_or_create(
                    cur, "herramienta", "nombre",
                    data.get("Seleccione la herramienta, material o servicio que desea utilizar:")
                )

                id_origen_material = get_or_create(
                    cur, "origen_material", "nombre",
                    data.get("Origen del material")
                )

                id_estado = get_or_create(
                    cur, "estado", "nombre",
                    estado_raw
                )

                id_carrera = get_or_create(
                    cur, "carrera", "nombre",
                    data.get("Describa a qué carrera y/o institución corresponde el proyecto:")
                )

                tiempo_estimado = parse_decimal(data.get("Tiempo estimado de utilización de la herramienta / material / servicio (hs):"))


                # insertar proyecto en DB
                cur.execute("""
                    INSERT INTO proyecto (
                        fecha_registro,
                        id_usuario,
                        id_carrera,
                        id_cargo,
                        id_sede,
                        nombre_proyecto,
                        descripcion,
                        id_tipo,
                        id_herramienta,
                        material,
                        cantidad_prototipos,
                        justificacion,
                        fecha_necesidad,
                        tiempo_estimado,
                        otros_comentarios,
                        id_origen_material,
                        copiado,
                        id_estado
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT ON CONSTRAINT proyecto_unico DO NOTHING;
                """, (
                    fecha_registro,
                    id_usuario,
                    id_carrera,
                    id_cargo,
                    id_sede,
                    data.get("Nombre del proyecto/actividad:"),
                    data.get("Breve descripción del proyecto"),
                    id_tipo,
                    id_herramienta,
                    data.get("Material a utilizar"),
                    cantidad_prototipos,
                    data.get("Vinculación del proyecto con las acciones relacionadas a las herramientas de fabricación digital / materiales / servicios: (justificación de uso)"),
                    fecha_necesidad,
                    tiempo_estimado,
                    #data.get("Tiempo estimado de utilización de la herramienta / material / servicio (hs):"),
                    data.get("Otros comentarios"),
                    id_origen_material,
                    copiado,
                    id_estado
                ))

                conn.commit()

        msg = "✅ Proyecto insertado correctamente (o ignorado si ya existía)."
        logging.info(msg)
        print(msg)
        return jsonify({"status": "ok", "mensaje": msg})

    except Exception as e:
        msg = f"❌ Error al insertar en la base de datos: {e}"
        logging.error(msg)
        print(msg)
        return jsonify({"status": "error", "mensaje": str(e)}), 500
'''
#####################################################################################

# para concatenar con la consulta
COLUMNAS_DISPONIBLES = {
    "id_proyecto": "p.id_proyecto",
    "fecha_registro": "p.fecha_registro",
    "email": "u.email",
    "usuario_nombre": "u.nombre",
    "carrera": "carrera.nombre",
    "cargo": "cargo.nombre",
    "sede": "sede.nombre",
    "nombre_proyecto": "p.nombre_proyecto",
    "descripcion": "p.descripcion",
    "tipo": "tipo.nombre",
    "herramienta": "herr.nombre",
    "material": "p.material",
    "cantidad_prototipos": "p.cantidad_prototipos",
    "justificacion": "p.justificacion",
    "fecha_necesidad": "p.fecha_necesidad",
    "tiempo_estimado": "p.tiempo_estimado",
    "otros_comentarios": "p.otros_comentarios",
    "origen": "origen.nombre",
    "estado": "estado.nombre"
}

# ruta para la p'agina web localhost:5000
@app.route("/", methods=["GET", "POST"])
def proyectos():
    try:

        if request.method == "POST":
            seleccionadas = request.form.getlist("columnas")
            # si hay una alg'un par'ametro de b'usqueda, vac'io
            filtros = {col: request.form.get(f"filtro_{col}", "") for col in seleccionadas}
        else:
            # GET inicial con todas las columnas seleccionadas por defecto
            seleccionadas = list(COLUMNAS_DISPONIBLES.keys())
            filtros = {col: "" for col in seleccionadas}

        # se juntan las columnas seleccionadas, separadas por coma
        cols_sql = ", ".join([COLUMNAS_DISPONIBLES[c] for c in seleccionadas])

        # se obtienen par'ametros de filtrado, si los hay (los campos de b'usqueda de coincidencias)
        where_clauses = []
        params = []
        for col, val in filtros.items():
            if val.strip():  # si el input no está vacío. Strip vita espacios innecesarios
                where_clauses.append(f"{COLUMNAS_DISPONIBLES[col]}::text ILIKE %s")
                params.append(f"%{val}%")


        filtro_fecha_desde = request.form.get("filtro_fecha_registro_desde", "")
        filtro_fecha_hasta = request.form.get("filtro_fecha_registro_hasta", "")

        if filtro_fecha_desde:
            where_clauses.append("p.fecha_registro >= %s")
            params.append(filtro_fecha_desde)

        if filtro_fecha_hasta:
            where_clauses.append("p.fecha_registro <= %s")
            params.append(filtro_fecha_hasta)

        # Guardar en filtros para que se muestre en el template
        filtros["fecha_registro_desde"] = filtro_fecha_desde
        filtros["fecha_registro_hasta"] = filtro_fecha_hasta
        
        # se juntan los filtros para la consulta
        where_sql = " AND ".join(where_clauses)

        if where_sql:
            query = f"""
                SELECT {cols_sql}
                FROM proyecto p
                JOIN usuario u ON p.id_usuario = u.id_usuario
                LEFT JOIN tipo ON p.id_tipo = tipo.id_tipo
                LEFT JOIN sede ON p.id_sede = sede.id_sede
                LEFT JOIN origen_material origen ON p.id_origen_material = origen.id_origen_material
                LEFT JOIN herramienta herr ON p.id_herramienta = herr.id_herramienta
                LEFT JOIN estado ON p.id_estado = estado.id_estado
                LEFT JOIN carrera ON p.id_carrera = carrera.id_carrera
                LEFT JOIN cargo ON p.id_cargo = cargo.id_cargo
                WHERE {where_sql}
                ORDER BY p.id_proyecto DESC;
            """
        else:
            # consulta cuando no hay búsqueda
            # se unen ambas partes para formar la consulta
            query = f"""
                SELECT {cols_sql}
                FROM proyecto p
                JOIN usuario u ON p.id_usuario = u.id_usuario
                LEFT JOIN tipo ON p.id_tipo = tipo.id_tipo
                LEFT JOIN sede ON p.id_sede = sede.id_sede
                LEFT JOIN origen_material origen ON p.id_origen_material = origen.id_origen_material
                LEFT JOIN herramienta herr ON p.id_herramienta = herr.id_herramienta
                LEFT JOIN estado ON p.id_estado = estado.id_estado
                LEFT JOIN carrera ON p.id_carrera = carrera.id_carrera
                LEFT JOIN cargo ON p.id_cargo = cargo.id_cargo
                ORDER BY p.id_proyecto DESC;
            """


        with psy.connect(conn_str) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                proyectos = cur.fetchall()
                print(len(proyectos))
                cur.execute("SELECT COUNT(*) FROM proyecto;")
                print("Total proyectos en DB:", cur.fetchone()[0])

                # traer opciones para los selects (listas desplegables)
                # ordenadas alfab'eticamente
                cur.execute("SELECT nombre FROM sede ORDER BY nombre;")
                sedes = [row[0] for row in cur.fetchall()]

                cur.execute("SELECT nombre FROM cargo ORDER BY nombre;")
                cargos = [row[0] for row in cur.fetchall()]

                cur.execute("SELECT nombre FROM tipo ORDER BY nombre;")
                tipos = [row[0] for row in cur.fetchall()]

                cur.execute("SELECT nombre FROM herramienta ORDER BY nombre;")
                herramientas = [row[0] for row in cur.fetchall()]

                cur.execute("SELECT nombre FROM carrera ORDER BY nombre;")
                carreras = [row[0] for row in cur.fetchall()]

                cur.execute("SELECT nombre FROM estado ORDER BY nombre;")
                estados = [row[0] for row in cur.fetchall()]


        # sumatorias de columnas numéricas
        # con problemas por ser algunas texto en vez de n'umeros
        sum_row = []
        for i, col in enumerate(seleccionadas):
            valores = []
            for p in proyectos:
                v = p[i]
                # aceptar int, float, Decimal
                if isinstance(v, (int, float, Decimal)):
                    # descartar NaN
                    if isinstance(v, float) and math.isnan(v):
                        continue
                    valores.append(v)
            sum_row.append(sum(valores) if valores else "-")

        return render_template("proyectos.html",
                                active_page="proyectos",
                                columnas_disponibles=COLUMNAS_DISPONIBLES.keys(),
                                columnas=seleccionadas,
                                rows=proyectos,
                                sum_row=sum_row,
                                filtros=filtros,
                                sedes=sedes,
                                cargos=cargos,
                                tipos=tipos,
                                herramientas=herramientas,
                                carreras=carreras,
                                estados=estados)

    except Exception as e:
        logging.error(f"Error en consulta: {e}")
        return f"❌ Error al cargar proyectos: {e}", 500


########### estad'isticas ############################################################################

@app.route("/estadisticas", methods=["GET", "POST"])
def estadisticas():
    try:
        # ejecuta consulta para conseguir los nombres de las sedes
        with psy.connect(conn_str) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT nombre FROM sede ORDER BY nombre;")
                sedes = [row[0] for row in cur.fetchall()]

        # se reciben los filtros desde la p'agina
        seleccionadas = request.form.getlist("sedes")
        mostrar_herramientas = "herramientas" in request.form
        mostrar_graficas = "graficas" in request.form
        filtro_fecha_desde = request.form.get("filtro_fecha_desde", "")
        filtro_fecha_hasta = request.form.get("filtro_fecha_hasta", "")

        uso_equipamiento, asistencia_tecnica, asistencia_desarrollo = obtener_datos_estadisticas(
            seleccionadas,
            fecha_desde=filtro_fecha_desde,
            fecha_hasta=filtro_fecha_hasta
        )

        # los siguientes 3 son para las sumatorias antes de las tablas
        # uso de equipamiento
        total_proyectos_uso = len(uso_equipamiento)
        total_prototipos_uso = 0
        total_tiempo_uso = 0
        for fila in uso_equipamiento:
            # fila[4] = cantidad de prototipos
            # fila[6] = tiempo estimado
            total_prototipos_uso += fila[4] or 0
            total_tiempo_uso += fila[6] or 0
        resumen_uso = (total_proyectos_uso, total_prototipos_uso, total_tiempo_uso)

        # asistencia técnica
        total_proyectos_tecnica = len(asistencia_tecnica)
        total_prototipos_tecnica = 0  # esta tabla no tiene prototipos
        total_tiempo_tecnica = 0
        for fila in asistencia_tecnica:
            # fila[1] = tiempo estimado
            total_tiempo_tecnica += fila[1] or 0
        resumen_tecnica = (total_proyectos_tecnica, total_prototipos_tecnica, total_tiempo_tecnica)

        # asistencia en desarrollo
        total_proyectos_desarrollo = len(asistencia_desarrollo)
        total_prototipos_desarrollo = 0
        total_tiempo_desarrollo = 0
        for fila in asistencia_desarrollo:
            # fila[1] = cantidad de prototipos
            # fila[3] = tiempo estimado
            total_prototipos_desarrollo += fila[1] or 0
            total_tiempo_desarrollo += fila[3] or 0
        resumen_desarrollo = (total_proyectos_desarrollo, total_prototipos_desarrollo, total_tiempo_desarrollo)



        # si est'a seleccionada la opci'on "Mostrar tabla de herramientas"
        herramientas_summary = []
        if mostrar_herramientas:
            with psy.connect(conn_str) as conn:
                with conn.cursor() as cur:
                    placeholders = ", ".join(["%s"] * len(seleccionadas)) if seleccionadas else "%s"
                    where_clause = f"sede.nombre IN ({placeholders})" if seleccionadas else "TRUE"

                    # Filtro de fechas
                    fecha_clause = []
                    params = seleccionadas if seleccionadas else []
                    if filtro_fecha_desde:
                        fecha_clause.append("p.fecha_registro >= %s")
                        params.append(filtro_fecha_desde)
                    if filtro_fecha_hasta:
                        fecha_clause.append("p.fecha_registro <= %s")
                        params.append(filtro_fecha_hasta)
                    fecha_sql = " AND ".join(fecha_clause)

                    query = f"""
                        SELECT herr.nombre,
                            SUM(COALESCE(p.tiempo_estimado,0)) AS total_tiempo,
                            SUM(COALESCE(p.cantidad_prototipos,0)) AS total_prototipos,
                            COUNT(p.id_proyecto) AS total_proyectos
                        FROM proyecto p
                        JOIN herramienta herr ON p.id_herramienta = herr.id_herramienta
                        JOIN sede ON p.id_sede = sede.id_sede
                        WHERE {where_clause}
                        {f"AND {fecha_sql}" if fecha_sql else ""}
                        GROUP BY herr.nombre
                        ORDER BY herr.nombre;
                    """
                    cur.execute(query, params)
                    herramientas_summary = cur.fetchall()

        # si est'a seleccionada la opci'on "Mostrar gr'aficas"
        graficas_data = []
        if mostrar_graficas:
            with psy.connect(conn_str) as conn:
                with conn.cursor() as cur:
                    fecha_clause = []
                    params = []
                    if filtro_fecha_desde:
                        fecha_clause.append("p.fecha_registro >= %s")
                        params.append(filtro_fecha_desde)
                    if filtro_fecha_hasta:
                        fecha_clause.append("p.fecha_registro <= %s")
                        params.append(filtro_fecha_hasta)
                    fecha_sql = " AND ".join(fecha_clause)

                    query = f"""
                        SELECT s.nombre,
                            COUNT(p.id_proyecto) AS total_proyectos,
                            SUM(COALESCE(p.cantidad_prototipos,0)) AS total_prototipos,
                            SUM(COALESCE(p.tiempo_estimado,0)) AS total_tiempo,

                            SUM(CASE WHEN t.nombre = 'Uso de equipamiento del LabA' THEN 1 ELSE 0 END) AS proyectos_equipamiento,
                            SUM(CASE WHEN t.nombre = 'Asistencia técnica (de equipamiento u otro)' THEN 1 ELSE 0 END) AS proyectos_tecnica,
                            SUM(CASE WHEN t.nombre = 'Asistencia en desarrollo de un producto' THEN 1 ELSE 0 END) AS proyectos_desarrollo,

                            SUM(CASE WHEN t.nombre = 'Uso de equipamiento del LabA' THEN COALESCE(p.tiempo_estimado,0) ELSE 0 END) AS tiempo_equipamiento,
                            SUM(CASE WHEN t.nombre = 'Asistencia técnica (de equipamiento u otro)' THEN COALESCE(p.tiempo_estimado,0) ELSE 0 END) AS tiempo_tecnica,
                            SUM(CASE WHEN t.nombre = 'Asistencia en desarrollo de un producto' THEN COALESCE(p.tiempo_estimado,0) ELSE 0 END) AS tiempo_desarrollo
                        FROM proyecto p
                        JOIN sede s ON p.id_sede = s.id_sede
                        JOIN tipo t ON p.id_tipo = t.id_tipo
                        {f"WHERE {fecha_sql}" if fecha_sql else ""}
                        GROUP BY s.nombre
                        ORDER BY s.nombre;
                    """
                    cur.execute(query, params)
                    graficas_data = cur.fetchall()

        return render_template("estadisticas.html",
                            active_page="estadisticas",
                            sedes=sedes,
                            sedes_seleccionadas=seleccionadas,
                            uso_equipamiento=uso_equipamiento,
                            asistencia_tecnica=asistencia_tecnica,
                            asistencia_desarrollo=asistencia_desarrollo,
                            mostrar_herramientas=mostrar_herramientas,
                            mostrar_graficas=mostrar_graficas,
                            herramientas_summary=herramientas_summary,
                            graficas_data=graficas_data,
                            resumen_uso=resumen_uso,
                            resumen_tecnica=resumen_tecnica,
                            resumen_desarrollo=resumen_desarrollo,
                            filtro_fecha_desde=filtro_fecha_desde,
                            filtro_fecha_hasta=filtro_fecha_hasta)

    except Exception as e:
        logging.error(f"Error en consulta: {e}")
        return f"❌ Error al cargar proyectos: {e}", 500


# funci'on para reutilizar en imprimir pdf estad'isticas
def obtener_datos_estadisticas(seleccionadas, fecha_desde=None, fecha_hasta=None):
    where_clauses = []
    params_uso_equipamiento = []
    params_asistencia_tecnica = []
    params_asistencia_desarrollo = []

    # filtro por sedes seleccionadas
    if seleccionadas:
        placeholders = ", ".join(["%s"] * len(seleccionadas))
        where_clauses.append(f"sede.nombre IN ({placeholders})")

        params_uso_equipamiento.extend(seleccionadas)
        params_asistencia_tecnica = list(params_uso_equipamiento)
        params_asistencia_desarrollo = list(params_uso_equipamiento)

    # filtro fijo por tipo
    where_clauses.append("tipo.nombre = %s")

    params_uso_equipamiento.append("Uso de equipamiento del LabA")
    params_asistencia_tecnica.append("Asistencia técnica (de equipamiento u otro)")
    params_asistencia_desarrollo.append("Asistencia en desarrollo de un producto")

    # filtros de fechas
    if fecha_desde:
        where_clauses.append("p.fecha_registro >= %s")
        params_uso_equipamiento.append(fecha_desde)
        params_asistencia_tecnica.append(fecha_desde)
        params_asistencia_desarrollo.append(fecha_desde)

    if fecha_hasta:
        where_clauses.append("p.fecha_registro <= %s")
        params_uso_equipamiento.append(fecha_hasta)
        params_asistencia_tecnica.append(fecha_hasta)
        params_asistencia_desarrollo.append(fecha_hasta)

    where_sql = " AND ".join(where_clauses)

    # columnas
    cols_uso_equipamiento = """
            cargo.nombre,
            p.nombre_proyecto,
            herr.nombre,
            p.material,
            p.cantidad_prototipos,
            p.fecha_necesidad,
            p.tiempo_estimado,
            origen.nombre
        """

    cols_asistencia_tecnica = """
            p.nombre_proyecto,
            p.tiempo_estimado,
            p.descripcion,
            cargo.nombre,
            p.fecha_necesidad
        """

    cols_asistencia_desarrollo = """
            p.nombre_proyecto,
            p.cantidad_prototipos,
            herr.nombre,
            p.tiempo_estimado,
            p.material,
            origen.nombre,
            cargo.nombre,
            p.fecha_necesidad
        """

    # queries
    query_uso_equipamiento = f"""
        SELECT {cols_uso_equipamiento}
        FROM proyecto p
        JOIN usuario u ON p.id_usuario = u.id_usuario
        LEFT JOIN tipo ON p.id_tipo = tipo.id_tipo
        LEFT JOIN sede ON p.id_sede = sede.id_sede
        LEFT JOIN origen_material origen ON p.id_origen_material = origen.id_origen_material
        LEFT JOIN herramienta herr ON p.id_herramienta = herr.id_herramienta
        LEFT JOIN estado ON p.id_estado = estado.id_estado
        LEFT JOIN carrera ON p.id_carrera = carrera.id_carrera
        LEFT JOIN cargo ON p.id_cargo = cargo.id_cargo
        WHERE {where_sql}
        ORDER BY p.id_proyecto DESC;
    """

    query_asistencia_tecnica = f"""
        SELECT {cols_asistencia_tecnica}
        FROM proyecto p
        JOIN usuario u ON p.id_usuario = u.id_usuario
        LEFT JOIN tipo ON p.id_tipo = tipo.id_tipo
        LEFT JOIN sede ON p.id_sede = sede.id_sede
        LEFT JOIN origen_material origen ON p.id_origen_material = origen.id_origen_material
        LEFT JOIN herramienta herr ON p.id_herramienta = herr.id_herramienta
        LEFT JOIN estado ON p.id_estado = estado.id_estado
        LEFT JOIN carrera ON p.id_carrera = carrera.id_carrera
        LEFT JOIN cargo ON p.id_cargo = cargo.id_cargo
        WHERE {where_sql}
        ORDER BY p.id_proyecto DESC;
    """

    query_asistencia_desarrollo = f"""
        SELECT {cols_asistencia_desarrollo}
        FROM proyecto p
        JOIN usuario u ON p.id_usuario = u.id_usuario
        LEFT JOIN tipo ON p.id_tipo = tipo.id_tipo
        LEFT JOIN sede ON p.id_sede = sede.id_sede
        LEFT JOIN origen_material origen ON p.id_origen_material = origen.id_origen_material
        LEFT JOIN herramienta herr ON p.id_herramienta = herr.id_herramienta
        LEFT JOIN estado ON p.id_estado = estado.id_estado
        LEFT JOIN carrera ON p.id_carrera = carrera.id_carrera
        LEFT JOIN cargo ON p.id_cargo = cargo.id_cargo
        WHERE {where_sql}
        ORDER BY p.id_proyecto DESC;
    """

    # ejecutar consultas
    with psy.connect(conn_str) as conn:
        with conn.cursor() as cur:
            cur.execute(query_uso_equipamiento, params_uso_equipamiento)
            uso_equipamiento = cur.fetchall()

            cur.execute(query_asistencia_tecnica, params_asistencia_tecnica)
            asistencia_tecnica = cur.fetchall()

            cur.execute(query_asistencia_desarrollo, params_asistencia_desarrollo)
            asistencia_desarrollo = cur.fetchall()

    return uso_equipamiento, asistencia_tecnica, asistencia_desarrollo



#############################################################################################

@app.route("/estadisticas/pdf", methods=["GET", "POST"])
def estadisticas_pdf():
    try:
        # Reutilizamos la misma lógica de /estadisticas
        seleccionadas = request.form.getlist("sedes")
        filtro_fecha_desde = request.form.get("filtro_fecha_desde", "")
        filtro_fecha_hasta = request.form.get("filtro_fecha_hasta", "")
        grafica_img = request.form.get("grafica_img", None)

        uso_equipamiento, asistencia_tecnica, asistencia_desarrollo = obtener_datos_estadisticas(
            seleccionadas,
            fecha_desde=filtro_fecha_desde,
            fecha_hasta=filtro_fecha_hasta
        )

        resumen_uso = (
            len(uso_equipamiento),
            sum(fila[4] or 0 for fila in uso_equipamiento),
            sum(fila[6] or 0 for fila in uso_equipamiento)
        )
        resumen_tecnica = (
            len(asistencia_tecnica),
            0,
            sum(fila[1] or 0 for fila in asistencia_tecnica)
        )
        resumen_desarrollo = (
            len(asistencia_desarrollo),
            sum(fila[1] or 0 for fila in asistencia_desarrollo),
            sum(fila[3] or 0 for fila in asistencia_desarrollo)
        )

        # para las 2 tablas a elecci'on
        mostrar_herramientas = "herramientas" in request.form
        mostrar_graficas = "graficas" in request.form

        herramientas_summary = []
        if mostrar_herramientas:
            with psy.connect(conn_str) as conn:
                with conn.cursor() as cur:
                    # misma query que en /estadisticas
                    cur.execute("""SELECT herr.nombre,
                                        SUM(COALESCE(p.tiempo_estimado,0)),
                                        SUM(COALESCE(p.cantidad_prototipos,0)),
                                        COUNT(p.id_proyecto)
                                FROM proyecto p
                                JOIN herramienta herr ON p.id_herramienta = herr.id_herramienta
                                JOIN sede ON p.id_sede = sede.id_sede
                                GROUP BY herr.nombre
                                ORDER BY herr.nombre;""")
                    herramientas_summary = cur.fetchall()

        graficas_data = []
        if mostrar_graficas:
            with psy.connect(conn_str) as conn:
                with conn.cursor() as cur:
                    # misma query que en /estadisticas
                    cur.execute("""SELECT s.nombre,
                                        COUNT(p.id_proyecto),
                                        SUM(COALESCE(p.cantidad_prototipos,0)),
                                        SUM(COALESCE(p.tiempo_estimado,0))
                                FROM proyecto p
                                JOIN sede s ON p.id_sede = s.id_sede
                                GROUP BY s.nombre
                                ORDER BY s.nombre;""")
                    graficas_data = cur.fetchall()


        # Renderizamos el template con solo_pdf=True
        html = render_template(
            "estadisticas.html",
            uso_equipamiento=uso_equipamiento,
            asistencia_tecnica=asistencia_tecnica,
            asistencia_desarrollo=asistencia_desarrollo,
            resumen_uso=resumen_uso,
            resumen_tecnica=resumen_tecnica,
            resumen_desarrollo=resumen_desarrollo,
            filtro_fecha_desde=filtro_fecha_desde,
            filtro_fecha_hasta=filtro_fecha_hasta,
            mostrar_herramientas=mostrar_herramientas,
            herramientas_summary=herramientas_summary,
            mostrar_graficas=mostrar_graficas,
            graficas_data=graficas_data,
            grafica_img=grafica_img, 
            solo_pdf=True
        )


        # Rutas absolutas a los CSS
        css_files = [
            url_for('static', filename='css/bootstrap.min.css', _external=True),
            url_for('static', filename='css/styles.css', _external=True),
            url_for('static', filename='css/pdf.css', _external=True) 
        ]
        stylesheets = [CSS(file) for file in css_files]

        # Generamos el PDF
        pdf = HTML(string=html).write_pdf(stylesheets=stylesheets)

        response = make_response(pdf)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = 'inline; filename=estadisticas.pdf'
        return response

    except Exception as e:
        logging.error(f"Error al generar PDF: {e}")
        return f"❌ Error al generar PDF: {e}", 500

#######################################################################################
# función auxiliar para obtener datos y sumatorias
def obtener_proyectos(seleccionadas):
    cols_sql = ", ".join([COLUMNAS_DISPONIBLES[c] for c in seleccionadas])
    query = f"""
        SELECT {cols_sql}
        FROM proyecto p
        JOIN usuario u ON p.id_usuario = u.id_usuario
        LEFT JOIN tipo ON p.id_tipo = tipo.id_tipo
        LEFT JOIN sede ON p.id_sede = sede.id_sede
        LEFT JOIN origen_material origen ON p.id_origen_material = origen.id_origen_material
        LEFT JOIN herramienta herr ON p.id_herramienta = herr.id_herramienta
        LEFT JOIN estado ON p.id_estado = estado.id_estado
        LEFT JOIN carrera ON p.id_carrera = carrera.id_carrera
        LEFT JOIN cargo ON p.id_cargo = cargo.id_cargo
        ORDER BY p.id_proyecto DESC;
    """


    with psy.connect(conn_str) as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            proyectos = cur.fetchall()

    # fila de sumatorias
    sum_row = []
    for i, col in enumerate(seleccionadas):
        valores = []
        for p in proyectos:
            v = p[i]
            # aceptar int, float, Decimal
            if isinstance(v, (int, float, Decimal)):
                # descartar NaN
                if isinstance(v, float) and math.isnan(v):
                    continue
                valores.append(v)
        sum_row.append(sum(valores) if valores else "-")

    return proyectos, sum_row

@app.route("/exportar_pdf", methods=["GET", "POST"])
def exportar_pdf():
    seleccionadas = request.form.getlist("columnas")
    if not seleccionadas:
        seleccionadas = list(COLUMNAS_DISPONIBLES.keys())

    proyectos, sum_row = obtener_proyectos(seleccionadas)

    # renderizar el mismo template que usás en pantalla
    html_string = render_template("proyectos.html",
                                  columnas_disponibles=COLUMNAS_DISPONIBLES.keys(),
                                  columnas=seleccionadas,
                                  rows=proyectos,
                                  sum_row=sum_row)

    # generar PDF con WeasyPrint
    pdf = HTML(string=html_string).write_pdf(
        stylesheets=[CSS("static/css/bootstrap.min.css"),
                     CSS("static/css/styles-pdf.css")]
    )

    response = make_response(pdf)
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = "inline; filename=proyectos.pdf"
    return response





# corre en el puerto 5000
if __name__ == "__main__":
    scheduler()
    atexit.register(t.cancel) # detiene el hilo del timer, sino interfiere en el SO
    app.run(debug=True, port=5000, use_reloader=False)
