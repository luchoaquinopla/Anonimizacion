"""

TODOS los valores de estas muestras son SINTETICOS. El texto reproduce la
ESTRUCTURA de los informes reales del instituto -- etiquetas, titulos de
seccion y disposicion de columnas, que es lo unico que este test necesita --
pero ningun nombre, documento, fecha ni numero interno pertenece a un
paciente real. Una version anterior de este archivo si traia los numeros de
peticion, estudio e identificacion de un documento verdadero: se reemplazaron
al detectar que un repositorio no es lugar para ningun dato de un paciente,
ni siquiera uno que no lo identifique por si solo.
Centinela: los tres tipos de documento se reconocen con evidencia
suficiente contra texto ESTRUCTURAL REAL (identidad ya sustituida por
valores sintéticos) de los tres layouts del Instituto de Cardiología de
Corrientes.

Motivo de este test: la firma de ecocardiograma (`firmas/eco_doppler.py`)
reconocía documentos reales por un solo marcador genérico de 4 caracteres
("S.C."). Los otros dos marcadores que declaraba ("ECOCARDIOGRAMA DOPPLER",
"FRACCION DE ACORTAMIENTO") nunca aparecen en el documento real -- salieron
de fixtures sintéticos que inventamos nosotros. `Firma.coincide` usa `any()`:
con que matchee uno alcanza, así que nadie lo notó hasta correr las firmas
contra un ecocardiograma real y medir 1 de 3 marcadores. El mismo defecto ya
había ocurrido con la firma de ECG (ver docstring de `firmas/ecg_mortara.py`)
y se corrigió ahí sin revisar el eco.

No hay PII real acá: nombre, documento, fecha de nacimiento y demás datos de
identidad del paciente en los tres textos de abajo son sintéticos. La
estructura (encabezados, secciones, medidas, unidades, rótulos) es la del
documento real, transcripta tal cual para que las firmas se validen contra
la forma real del texto, no contra una reconstrucción a mano.
"""

from __future__ import annotations

from anonimizacion.deteccion.detector_tipo import detectar_tipo
from anonimizacion.deteccion.firmas import FIRMAS
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.extraccion.texto_pymupdf import TextoExtraido

# Con un solo marcador genérico no alcanza como evidencia -- tiene que haber
# más de uno para considerar el tipo "reconocido con confianza".
_EVIDENCIA_MINIMA = 2

_LABORATORIO_REAL = """\
Laboratorios de Analisis Clinicos, Microbiologicos y de Alta Complejidad
Bolivar 1334 - Tel 0379-4410064 fax 0379-4410000 int 135 - Corrientes - CP 3400
Apellido y Nombre: PEREZ , JUAN CARLOS
F.Nacimiento : 01/01/1970   DNI: 11111111
Edad: 55    Medico: SIN MEDICO DERIVANTE    Origen: EMERGENCIA
Fecha: 12/01/2022   N Peticion: 9900011   Hora de Extraccion: 08:24
Pruebas   Resultado Actual   Fecha y Resultado Anterior   Unidades   Valores de Referencia
-HEMATOLOGIA-
HEMOGRAMA
Hematocrito 45 % 41 - 53
FORMULA LEUCOCITARIA
-HEMOSTASIA-
Tiempo de Protrombina 99 % 70 - 120
-QUIMICA CLINICA-
Glucemia 117 mg/dl 70 - 100
IONOGRAMA SERICO
Sodio 139 meq/lt 135 - 145
VALIDADO ELECTRONICAMENTE: Bioq. NOMBRE APELLIDO M.P. 774
Informe solo valido con la firma y sello del Bioquimico
"""

_ECG_REAL = """\
PEREZ JUAN~,   ID:990022   12-JAN-2022 09:30:00   INST. CARDIOLOGIA DE CORRIENTES-CONEXT   ROUTINE RECORD
*** PID / NAME MISMATCH ***
01-JAN-1970 (55 yr)   Vent. rate 73 BPM
Male  Unknown         PR interval 186 ms
                      QRS duration 100 ms
Room:                 QT/QTc 382/420 ms
Loc:8                 P-R-T axes 63 51 26
Technician:
Test ind:
Med:
Ordered by: - SIN MEDICO DER      Unconfirmed
25mm/s 10mm/mV 40Hz 9.0.8 12SL 241 CID: 1
EID: EDT: ORDER:13ECG0026~ VISIT: 13ECG002677440
"""

_ECOCARDIOGRAMA_REAL = """\
SERVICIO DE ECOCARDIOGRAFIA
ECOGRAFIA DOPPLER COLOR CARDIACA
PACIENTE: PEREZ JUAN CARLOS   Documento: 11111111   Fecha Estudio: 12/01/2022
Edad: 55 anos   N ESTUDIO: 990033   Peso: 118 kg   Altura: 179 cm   S.C. 2,42 m2
Medico Solicitante: LIBRE
VALORES HALLADOS
MEDIDAS VALOR VALOR NORMAL
AO 36mm < 41 mm
AI 39mm < 40 mm
DDVI 52mm < 52 mm
DSVI 29mm VARIABLE
FA 44% > 30%
SEPTUM 14mm < 11 mm
P.POSTERIOR 14mm < 11 mm
VD NORMAL
PULMON NORMAL
AD NORMAL
VENTRICULO IZQUIERDO
MOTILIDAD SEGMENTARIA:
VOLUMENES VENTRICULARES : VFD: 88 ml VFS: 41 ml VS: 47 ml FEY: 53 %
ESPESOR PARIETAL: LEVEMENTE AUMENTADO
HIPERTROFIA VENTRICULAR: LEVE
MASA: 308 gr INDICE DE MASA: 127 gr/m2
AURICULAS
INDICE DE VOLUMEN DE AURICULA IZQUIERDA: 26 ml/m2
VALVULAS CARDIACAS
AORTICA / MITRAL / PULMONAR / TRICUSPIDEA
PERICARDIO
EVALUACION DE FLUJOS POR DOPPLER
FLUJO AORTICO / FLUJO MITRAL / FLUJO PULMONAR / FLUJO TRICUSPIDEO
PRESION SISTOLICA PULMONAR 15 mmHg PVC 3 mmHg
DOPPLER TISULAR E/E': 7
CONCLUSIONES
Matricula W 9999
Informe no valido sin la firma y el sello del medico
Bolivar 1334 - (3400) Corrientes
"""


def _puntaje_de(tipo: TipoDocumento, texto_normalizado: str) -> int:
    (firma,) = [f for f in FIRMAS if f.tipo == tipo]
    return firma.puntaje(texto_normalizado)


def test_laboratorio_real_se_reconoce_con_evidencia_suficiente() -> None:
    texto = TextoExtraido(paginas=(_LABORATORIO_REAL,))
    assert detectar_tipo(texto) is TipoDocumento.LABORATORIO
    puntaje = _puntaje_de(TipoDocumento.LABORATORIO, _LABORATORIO_REAL.upper())
    assert puntaje >= _EVIDENCIA_MINIMA, (
        f"laboratorio real reconocido por solo {puntaje} marcador(es), no es evidencia suficiente"
    )


def test_ecg_real_se_reconoce_con_evidencia_suficiente() -> None:
    texto = TextoExtraido(paginas=(_ECG_REAL,))
    assert detectar_tipo(texto) is TipoDocumento.ECG
    puntaje = _puntaje_de(TipoDocumento.ECG, _ECG_REAL.upper())
    assert puntaje >= _EVIDENCIA_MINIMA, (
        f"ECG real reconocido por solo {puntaje} marcador(es), no es evidencia suficiente"
    )


def test_ecocardiograma_real_se_reconoce_con_evidencia_suficiente() -> None:
    texto = TextoExtraido(paginas=(_ECOCARDIOGRAMA_REAL,))
    assert detectar_tipo(texto) is TipoDocumento.ECOCARDIOGRAMA
    puntaje = _puntaje_de(TipoDocumento.ECOCARDIOGRAMA, _ECOCARDIOGRAMA_REAL.upper())
    assert puntaje >= _EVIDENCIA_MINIMA, (
        f"ecocardiograma real reconocido por solo {puntaje} marcador(es), no es evidencia suficiente"
    )
