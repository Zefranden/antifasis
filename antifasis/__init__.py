"""Antifasis: titulares de los principales medios españoles en PostgreSQL."""

import warnings

# En macOS con el Python del sistema, urllib3 avisa de que LibreSSL no es
# OpenSSL 1.1.1+. No afecta a la descarga de feeds y ensucia la salida.
warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL")

__version__ = "1.1.0"
__all__ = ["__version__"]
