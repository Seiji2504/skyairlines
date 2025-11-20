import random
from datetime import datetime
from io import BytesIO

from fpdf import FPDF
from flask import Flask, render_template, request, flash, redirect, url_for, send_file
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)

# Necesario para usar flash() y sesiones
app.secret_key = "super_secret_key"

# Configuración de conexión a MySQL usando PyMySQL
# Ajusta password si tu root tiene otra clave
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:root@localhost/airline_sales'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)


def generar_codigo_pnr():
    """Genera el siguiente código PNR correlativo (PNR001, PNR002, etc.)"""
    ultima_reserva = Reserva.query.order_by(Reserva.id_reserva.desc()).first()

    if ultima_reserva and ultima_reserva.codigo_pnr.startswith('PNR'):
        numero = int(ultima_reserva.codigo_pnr[3:])
        nuevo_numero = numero + 1
    else:
        nuevo_numero = 1

    return f"PNR{nuevo_numero:03d}"


def generar_precio_reserva():
    """Precio aleatorio de ejemplo para la reserva"""
    return round(random.uniform(100, 999), 2)


# ==========================
# MODELOS
# ==========================
class Vuelo(db.Model):
    __tablename__ = 'vuelo'   # Debe coincidir con la tabla en MySQL

    id_vuelo = db.Column(db.Integer, primary_key=True)
    numero_vuelo = db.Column(db.String(10), unique=True, nullable=False)
    origen = db.Column(db.String(3), nullable=False)
    destino = db.Column(db.String(3), nullable=False)
    fecha_salida = db.Column(db.DateTime, nullable=False)
    fecha_llegada = db.Column(db.DateTime, nullable=False)
    aeronave = db.Column(db.String(50))
    asientos_totales = db.Column(db.Integer, nullable=False)
    asientos_disponibles = db.Column(db.Integer, nullable=False)
    estado = db.Column(db.String(20), default='PROGRAMADO')


class Pasajero(db.Model):
    __tablename__ = 'pasajero'

    id_pasajero = db.Column(db.Integer, primary_key=True)
    dni = db.Column(db.String(15), unique=True, nullable=False)
    nombres = db.Column(db.String(100), nullable=False)
    apellidos = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), nullable=False)
    telefono = db.Column(db.String(20))
    # Se podría usar db.func.current_date(), pero datetime.utcnow funciona
    fecha_registro = db.Column(db.Date, default=datetime.utcnow)


class Reserva(db.Model):
    __tablename__ = 'reserva'

    id_reserva = db.Column(db.Integer, primary_key=True)
    codigo_pnr = db.Column(db.String(10), unique=True, nullable=False)

    id_pasajero = db.Column(
        db.Integer,
        db.ForeignKey('pasajero.id_pasajero', ondelete='RESTRICT', onupdate='CASCADE'),
        nullable=False
    )
    id_vuelo = db.Column(
        db.Integer,
        db.ForeignKey('vuelo.id_vuelo', ondelete='RESTRICT', onupdate='CASCADE'),
        nullable=False
    )

    fecha_reserva = db.Column(db.DateTime, default=datetime.utcnow)
    estado = db.Column(db.String(20), nullable=False, default='PENDIENTE')
    total_reserva = db.Column(db.Numeric(10, 2), default=0)

    pasajero = db.relationship('Pasajero', backref='reservas', lazy=True)
    vuelo = db.relationship('Vuelo', backref='reservas', lazy=True)


# ==========================
# RUTAS PRINCIPALES
# ==========================
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/buscar_vuelos', methods=['GET', 'POST'])
def buscar_vuelos():
    if request.method == 'POST':
        origen = request.form['origen'].upper()
        destino = request.form['destino'].upper()

        # Filtramos solo por origen, destino, estado PROGRAMADO y asientos disponibles
        vuelos = (
            Vuelo.query
            .filter_by(origen=origen, destino=destino, estado='PROGRAMADO')
            .filter(Vuelo.asientos_disponibles > 0)
            .all()
        )

        return render_template('resultados.html', vuelos=vuelos, origen=origen, destino=destino)
    else:
        # Si entran a /buscar_vuelos por GET, los mandamos al inicio
        return redirect(url_for('index'))


@app.route('/reservas')
def reservas():
    vuelos = Vuelo.query.filter_by(estado='PROGRAMADO').all()
    return render_template('reserva.html', vuelos=vuelos)


@app.route('/registrores', methods=['POST'])
def crear_reserva():
    # -------- DATOS DE PASAJERO --------
    dni = request.form['dni']
    nombres = request.form['nombres']
    apellidos = request.form['apellidos']
    email = request.form['email']
    telefono = request.form['telefono']
    id_vuelo = request.form['id_vuelo']

    # 1) Ver si el pasajero ya existe por DNI
    pasajero = Pasajero.query.filter_by(dni=dni).first()

    if not pasajero:
        # Crear pasajero nuevo
        pasajero = Pasajero(
            dni=dni,
            nombres=nombres,
            apellidos=apellidos,
            email=email,
            telefono=telefono
        )
        db.session.add(pasajero)
        # flush para obtener id_pasajero sin aún hacer commit global
        db.session.flush()

    # 2) Buscar vuelo
    vuelo = Vuelo.query.get_or_404(id_vuelo)

    if vuelo.asientos_disponibles <= 0:
        flash('No hay asientos disponibles para este vuelo.')
        return redirect(url_for('reservas'))

    # 3) Crear reserva
    nueva_reserva = Reserva(
        codigo_pnr=generar_codigo_pnr(),
        id_pasajero=pasajero.id_pasajero,
        id_vuelo=vuelo.id_vuelo,
        estado='PENDIENTE',
        total_reserva=generar_precio_reserva()
    )

    vuelo.asientos_disponibles -= 1

    db.session.add(nueva_reserva)
    db.session.commit()

    # Pasamos pasajero_id para que el template pueda mostrar el popup
    return render_template(
        'allreservas.html',
        codigo_pnr=nueva_reserva.codigo_pnr,
        id_vuelo=nueva_reserva.id_vuelo,
        id_pasajero=nueva_reserva.id_pasajero,
        estado=nueva_reserva.estado,
        total_reserva=nueva_reserva.total_reserva,
        fecha_reserva=nueva_reserva.fecha_reserva,
        reserva=nueva_reserva,
        pasajero_id=nueva_reserva.id_pasajero
    )


@app.route('/voucher/<int:id_reserva>')
def generar_voucher(id_reserva):
    reserva = Reserva.query.get_or_404(id_reserva)
    vuelo = reserva.vuelo
    pasajero = reserva.pasajero

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", 'B', 16)
    pdf.cell(0, 10, "Voucher de Reserva", ln=True, align='C')

    pdf.set_font("Helvetica", '', 12)
    pdf.ln(5)
    pdf.cell(0, 8, f"PNR: {reserva.codigo_pnr}", ln=True)
    pdf.cell(0, 8, f"Pasajero: {pasajero.nombres} {pasajero.apellidos}", ln=True)
    pdf.cell(0, 8, f"Vuelo: {vuelo.numero_vuelo}", ln=True)
    pdf.cell(0, 8, f"Origen: {vuelo.origen}", ln=True)
    pdf.cell(0, 8, f"Destino: {vuelo.destino}", ln=True)
    pdf.cell(0, 8, f"Fecha de salida: {vuelo.fecha_salida}", ln=True)
    pdf.cell(0, 8, f"Estado: {reserva.estado}", ln=True)
    pdf.cell(0, 8, f"Total: S/ {reserva.total_reserva}", ln=True)

    # Generar PDF en memoria como bytes
    pdf_bytes = pdf.output(dest="S").encode("latin-1")
    pdf_buffer = BytesIO(pdf_bytes)

    return send_file(
        pdf_buffer,
        as_attachment=True,
        download_name=f"voucher_{reserva.codigo_pnr}.pdf",
        mimetype='application/pdf'
    )


# ==========================
# ESTADO DE VUELO / RESERVAS (solo por DNI)
# ==========================
@app.route('/estado_vuelo', methods=['GET', 'POST'])
def estado_vuelo():
    reservas = []
    criterio = None
    valor = None

    if request.method == 'POST':
        valor = request.form.get('valor', '').strip()

        if valor:
            criterio = f"DNI: {valor}"
            reservas = (
                Reserva.query
                .join(Pasajero)
                .filter(Pasajero.dni == valor)
                .all()
            )

    return render_template('estado.html',
                           reservas=reservas,
                           criterio=criterio,
                           valor=valor)


# ==========================
# ENDPOINT PARA AUTOCOMPLETAR PASAJERO
# ==========================
@app.route('/api/pasajero')
def api_pasajero():
    """
    Busca un pasajero por:
    - DNI (si escriben solo números)
    - ID de pasajero (si es numérico y no es DNI)
    - Nombre / apellidos (texto)
    Devuelve JSON con los datos si lo encuentra.
    """
    q = request.args.get('q', '').strip()

    if not q:
        return {'found': False}

    pasajero = None

    # Si son solo dígitos, primero intento por DNI
    if q.isdigit():
        pasajero = Pasajero.query.filter_by(dni=q).first()
        # Si no hubo por DNI, intento por id_pasajero
        if not pasajero:
            try:
                pasajero = Pasajero.query.get(int(q))
            except ValueError:
                pasajero = None
    else:
        # Búsqueda simple por nombre o apellidos
        pasajero = (
            Pasajero.query
            .filter(
                (Pasajero.nombres.ilike(f"%{q}%")) |
                (Pasajero.apellidos.ilike(f"%{q}%"))
            )
            .first()
        )

    if not pasajero:
        return {'found': False}

    return {
        'found': True,
        'pasajero': {
            'dni': pasajero.dni,
            'nombres': pasajero.nombres,
            'apellidos': pasajero.apellidos,
            'email': pasajero.email,
            'telefono': pasajero.telefono
        }
    }


# ==========================
# ENDPOINTS PARA LOS DROPDOWN (origen/destino)
# ==========================
@app.route('/api/origenes')
def api_origenes():
    # SELECT DISTINCT origen FROM vuelo;
    origenes = db.session.query(Vuelo.origen).distinct().all()
    return {'data': [o[0] for o in origenes]}


@app.route('/api/destinos/<origen>')
def api_destinos(origen):
    # SELECT DISTINCT destino FROM vuelo WHERE origen = :origen;
    destinos = (
        db.session.query(Vuelo.destino)
        .filter_by(origen=origen)
        .distinct()
        .all()
    )
    return {'data': [d[0] for d in destinos]}


if __name__ == '__main__':
    app.run(debug=True)
