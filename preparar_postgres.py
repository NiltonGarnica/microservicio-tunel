"""Prepara PostgreSQL para el microservicio.

1. Lee DATABASE_URL de .env (debe empezar con postgresql+psycopg://).
2. Crea la base de datos si no existe (por ejemplo `practica`).
3. Crea la tabla `personas`.
4. Copia las personas que ya estén en personas.db (SQLite), sin duplicarlas.

Uso (con el entorno virtual activado):
    python preparar_postgres.py
"""

import sqlite3
import sys
from pathlib import Path

import psycopg
from psycopg import sql
from sqlalchemy import make_url, select

import database
from database import Persona, SessionLocal, crear_tablas

RUTA_SQLITE = Path(__file__).resolve().parent / "personas.db"


def crear_base_si_falta() -> None:
    url = make_url(database.DATABASE_URL)
    if not url.drivername.startswith("postgresql"):
        sys.exit(
            "DATABASE_URL no apunta a PostgreSQL. En .env usa:\n"
            "  DATABASE_URL=postgresql+psycopg://postgres:TU_CLAVE@localhost:5432/practica"
        )

    nombre_base = url.database
    # Para crear una base hay que conectarse a otra que ya exista: `postgres`.
    try:
        conexion = psycopg.connect(
            host=url.host or "localhost",
            port=url.port or 5432,
            user=url.username,
            password=url.password,
            dbname="postgres",
            autocommit=True,  # CREATE DATABASE no puede ir dentro de una transacción
        )
    except psycopg.OperationalError as error:
        sys.exit(f"No pude conectarme a PostgreSQL. Revisa usuario y clave en .env.\nDetalle: {error}")

    with conexion:
        existe = conexion.execute("SELECT 1 FROM pg_database WHERE datname = %s", (nombre_base,)).fetchone()
        if existe:
            print(f"La base '{nombre_base}' ya existe.")
        else:
            conexion.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(nombre_base)))
            print(f"Base '{nombre_base}' creada.")


def copiar_desde_sqlite() -> None:
    if not RUTA_SQLITE.exists():
        print("No hay personas.db: nada que copiar.")
        return

    origen = sqlite3.connect(RUTA_SQLITE)
    filas = origen.execute("SELECT nombre, telefono, email, genero FROM personas").fetchall()
    origen.close()

    copiadas = 0
    with SessionLocal() as db:
        for nombre, telefono, email, genero in filas:
            ya_esta = db.scalar(
                select(Persona.id).where(Persona.email == email, Persona.nombre == nombre, Persona.telefono == telefono)
            )
            if ya_esta is None:
                db.add(Persona(nombre=nombre, telefono=telefono, email=email, genero=genero))
                copiadas += 1
        db.commit()
    print(f"Personas en SQLite: {len(filas)}. Copiadas a PostgreSQL: {copiadas}.")


if __name__ == "__main__":
    crear_base_si_falta()
    crear_tablas()
    print("Tabla 'personas' lista.")
    copiar_desde_sqlite()
    print("Listo. Arranca Uvicorn y prueba POST /process.")
