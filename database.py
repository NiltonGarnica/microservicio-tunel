"""Conexión a la base de datos y modelo de la tabla `personas`."""

import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import DateTime, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

# Carga las variables de .env (si existe) antes de leer la configuración.
# main.py importa este módulo primero, así que también le sirve a él.
load_dotenv(Path(__file__).resolve().parent / ".env")

# SQLite por defecto: un archivo local, sin instalar ningún servidor.
DATABASE_URL = os.getenv("DATABASE_URL", "").strip() or "sqlite:///./personas.db"

# SQLite solo permite usar una conexión desde el hilo que la creó; FastAPI
# atiende las rutas `def` en un pool de hilos, así que se desactiva esa
# comprobación. Los demás motores no necesitan este argumento.
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

# pool_pre_ping comprueba la conexión antes de usarla (útil con servidores
# PostgreSQL/MySQL que cierran conexiones inactivas).
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Persona(Base):
    __tablename__ = "personas"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(120))
    # Texto, no número: así se conservan el "+" y los ceros iniciales.
    telefono: Mapped[str] = mapped_column(String(20))
    email: Mapped[str] = mapped_column(String(254))
    genero: Mapped[str] = mapped_column(String(30))
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


def crear_tablas() -> None:
    """Crea las tablas que falten. No modifica las que ya existen."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """Dependencia de FastAPI: abre una sesión por petición y la cierra al final."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
