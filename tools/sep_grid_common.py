"""Constantes compartidas del kernel SEP_RESPONSE_GRID (T6).

Un solo sitio para el dominio del kernel y su version, para que el generador
(`generate_sep_grid.py`), el verificador (`tests/check_sep_grid.py`) y los tests
no puedan divergir. Q93 del diseno: el artefacto lleva `model_version` y sus ejes
y unidad literales; el interprete (index.html) valida dimensiones y rangos al
arrancar, y un desajuste de version deja el SEP desactivado (nunca fallback a
DOSE_GRID).
"""
import math

# Version del kernel. Cambia SOLO cuando cambian ejes, unidad o representacion;
# el bloque embebido en index.html la lleva literal y el interprete la compara.
MODEL_VERSION = "sep-1"

# Dominio del kernel (Q85/contexto): protones 50 MeV - 20 GeV.
E_MIN_GEV = 0.05
E_MAX_GEV = 20.0

# ~53 bins logaritmicos (Q85/contexto). Se usa exactamente 53.
N_E_BINS = 53

# Ejes de la rejilla (Q85/contexto y cari7_make_input.RC_TARGETS/ALT_VALUES).
RC_TARGETS = [round(0.25 * i, 2) for i in range(73)]     # 0..18 GV, 73 nodos
ALT_VALUES = [8.0 + 0.5 * i for i in range(11)]           # 8..13 km, 11 nodos

# Magnitudes del bloque: solo D2 (ICRP-103) en v1 (Q89). El eje de magnitud se
# deja con longitud 1 para admitir H*(10) despues.
QUANTITIES = ["D2"]

# Unidad interna fijada en T4 (Q88): uSv/h por pfu integrado en el bin.
# El flujo del espectro base se normaliza a 1 pfu integrado sobre su bin; la
# celda del kernel vale uSv/h por ese pfu.
RATE_UNIT = "uSv/h per pfu"
FLUX_UNIT = "nuclei/(m2-sr-s-GeV)"

# Un pfu (particle flux unit, GOES) = 1 proton/(cm2-sr-s). MY_MODEL.OUT usa
# m2 (HELP.TXT 3.D: nuclei/(m2-sr-s-GeV)), asi que 1 pfu = 1e4 unidades m2.
# El kernel se normaliza a uSv/h POR PFU (Q88): la base de cada bin integra a
# AMP pfu = AMP*PFU_TO_M2 unidades m2, y el ensamblado divide por AMP.
PFU_TO_M2 = 1e4


def bin_edges(n_bins=N_E_BINS, e_min=E_MIN_GEV, e_max=E_MAX_GEV):
    """Bordes de n_bins logaritmicos en [e_min, e_max]: lista de n_bins+1."""
    lmin, lmax = math.log(e_min), math.log(e_max)
    return [math.exp(lmin + (lmax - lmin) * i / n_bins)
            for i in range(n_bins + 1)]


def bin_centers(n_bins=N_E_BINS, e_min=E_MIN_GEV, e_max=E_MAX_GEV):
    """Centros geometricos de los bins (raiz del producto de los bordes)."""
    edges = bin_edges(n_bins, e_min, e_max)
    return [math.sqrt(edges[i] * edges[i + 1]) for i in range(n_bins)]
