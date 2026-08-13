# Anonimización clínica local

Este proyecto prepara una base segura, **local primero**, para ingerir datos derivados de PDFs clínicos, aplicar anonimización y validar privacidad antes de emitir un acuse técnico seguro. Su propósito es separar desde el inicio las reglas de protección de datos de las interfaces, los lectores de documentos y cualquier infraestructura futura.

> **Estado:** el repositorio contiene el núcleo del PR 1, en memoria y con datos sintéticos. No procesa PDFs reales, no ofrece interfaz de navegador y no está listo para uso clínico ni productivo.

## Propósito y alcance

El objetivo es construir un flujo local que, cuando esté aprobado e implementado por etapas, reciba documentos clínicos desde el equipo de la persona usuaria, trate su contenido de forma transitoria, lo anonimice y compruebe que no queden datos identificables antes de reconocer el resultado.

El proyecto no busca diagnosticar, interpretar clínicamente ni reemplazar procedimientos sanitarios. Tampoco supone que un documento derivado de un PDF sea apto para análisis posterior: la calidad y la privacidad deben verificarse con evidencia aprobada antes de habilitar cualquier uso.

## Principios de privacidad y límites explícitos

| Principio | Aplicación prevista |
| --- | --- |
| Local primero | La carga y el tratamiento se diseñan para ocurrir en el equipo local, sin enviar documentos a servicios externos. |
| Minimización | Sólo se procesará la información necesaria para el propósito aprobado y durante el tiempo mínimo necesario. |
| Transitoriedad | Los bytes de entrada y resultados intermedios se descartan tras completar o rechazar el procesamiento. |
| Defensa en profundidad | La anonimización se complementa con una validación residual independiente de privacidad. |
| Salida segura | El acuse expone únicamente decisión técnica, códigos y conteos; no texto, valores clínicos, identificadores ni diagnósticos. |
| Aprobación por capacidad | Persistencia, corpus, umbrales de calidad y ML requieren decisiones y evidencia propias. |

Límites actuales y permanentes salvo aprobación explícita:

- no se persisten PDFs, texto extraído, datos identificables, resultados transitorios ni registros con contenido;
- no hay red externa, API pública, integración hospitalaria, colas ni base de datos;
- no se usan datos de pacientes ni corpus clínicos en el repositorio;
- no se afirma seguridad clínica, cobertura sobre documentos reales ni preparación para producción.

## Arquitectura objetivo: núcleo hexagonal

La arquitectura objetivo es hexagonal: el **dominio** concentra las reglas de privacidad, estados y decisiones; la **aplicación** organiza los casos de uso mediante puertos; y los **adaptadores** conectan esos puertos con mecanismos concretos, como una carga local en navegador o un lector de PDF aprobado.

```text
adaptador de carga local ─┐
                          ▼
                    puerto de entrada
                          ▼
              aplicación / caso de uso
                          ▼
             dominio: anonimización,
              privacidad y decisiones
                          ▼
                    puerto de salida
                          ▼
 adaptador de extracción o clasificación
```

## Por qué se eligió esta arquitectura

La decisión responde principalmente al riesgo de privacidad y a la incertidumbre técnica del proyecto. Las reglas que deciden si un documento puede continuar o debe rechazarse —anonimización, detección residual de información identificable, completitud y códigos seguros— son las partes más sensibles. Deben conservar el mismo comportamiento aunque cambie la interfaz, la biblioteca de lectura de PDFs o una futura decisión de persistencia.

La arquitectura hexagonal las protege mediante una regla simple: **el dominio y la aplicación definen lo que necesitan; las tecnologías concretas se conectan desde afuera como adaptadores**. Por eso `PuertoEntradaIngesta` conoce el contrato `PuertoSalidaClasificacionFamilia`, pero no conoce ni importa un lector de PDF, una UI ni una base de datos. El cableado concreto se concentra en `composicion.py`.

| Alternativa | Problema para este proyecto | Decisión |
| --- | --- | --- |
| Monolito centrado en la UI | Mezclaría la carga de archivos, la presentación y la decisión de privacidad; las reglas críticas serían más difíciles de probar sin navegador. | Se descarta para proteger y probar el núcleo de manera aislada. |
| Caso de uso dependiente de PyMuPDF u otra biblioteca PDF | Una decisión o cambio de biblioteca obligaría a modificar la lógica de negocio y de privacidad. | La biblioteca futura queda detrás de un adaptador de salida. |
| Persistencia o colas desde el inicio | Introduciría retención, credenciales, fallas operativas y superficie de exposición antes de que exista una necesidad aprobada. | Se mantiene el flujo en memoria; cualquier persistencia requiere un cambio SDD separado. |
| Arquitectura en capas sin puertos explícitos | Puede separar carpetas, pero no garantiza que la aplicación deje de depender de tecnologías concretas. | Se usan puertos explícitos para aplicar inversión de dependencias verificable. |

Con esta elección se obtienen cuatro beneficios concretos: (1) pruebas rápidas con entradas sintéticas, sin PDF ni datos sensibles; (2) sustitución de adaptadores sin reescribir la política de privacidad; (3) revisión más clara de las fronteras donde podría aparecer información sensible; y (4) evolución gradual hacia UI local, lectura real de PDF o persistencia autorizada sin adelantar decisiones de infraestructura.

La arquitectura no elimina la necesidad de validar seguridad o calidad clínica. Sólo mantiene esas decisiones acotadas y comprobables: incorporar un nuevo adaptador o una capacidad de retención no cambia automáticamente las reglas del núcleo ni queda autorizado por existir la estructura.

## Flujo de datos previsto

El flujo siguiente describe el objetivo futuro; no está implementado completo todavía:

```text
carga de PDF en navegador local
  → bytes transitorios por archivo
  → clasificación y extracción local aprobada
  → anonimización en memoria
  → validación residual de privacidad y controles de calidad disponibles
  → descarte de datos transitorios
  → acuse técnico seguro para la persona usuaria
```

El acuse sólo informará una aprobación o rechazo técnico, códigos seguros y conteos. No devolverá contenido extraído ni información clínica. Cualquier persistencia, auditoría, uso de corpus o preparación de datos para aprendizaje automático queda fuera de este flujo hasta contar con una propuesta separada y aprobada.

## Hoja de ruta por etapas

| Etapa | Resultado previsto | Puerta y límite |
| --- | --- | --- |
| PR 1 — núcleo actual | Contratos de ingesta efímera, política de privacidad y adaptador de laboratorio en memoria con marcadores sintéticos. | Sin UI, PDFs reales, persistencia ni evaluación de calidad habilitable. |
| PR 2 — UI local | Carga desde navegador local y acuse seguro para el lote. | Sin exposición externa ni almacenamiento. |
| PR 3 — calidad | Evaluación de calidad para laboratorio. | Sólo después de aprobar corpus, inventario versionado y umbrales. |
| PR 4 — persistencia | Retención de datos, sólo si hiciera falta. | Requiere propuesta y aprobación específicas sobre propósito, acceso, esquema, retención y privacidad. |
| PR 5+ — capacidades diferidas | Ecocardiografía, ECG y preparación de datos para ML. | Cada capacidad requiere aprobación, alcance y evidencia propios. |

La ecocardiografía, el ECG —incluida cualquier decisión sobre la señal de trazado— y el aprendizaje automático no forman parte del alcance actual. No se iniciarán como extensiones implícitas de la ingesta de laboratorio.

## Estructura del repositorio

### Código actual

```text
src/ingesta_clinica/
├── dominio/                    # Estados de extracción, política y privacidad
├── aplicacion/puertos/          # Contratos de entrada y salida
├── adaptadores/salida/          # Adaptador sintético de laboratorio en memoria
└── composicion.py               # Ensamblado del núcleo

tests/                           # Pruebas con datos sintéticos y no identificantes
pyproject.toml                   # Configuración de pytest
```

El código actual demuestra los límites del PR 1: reconoce marcadores sintéticos de laboratorio, aplica una validación residual sintética y devuelve una salida técnica segura. No es un lector de PDFs ni una implementación completa de anonimización para documentos clínicos.

### Planificación y trazabilidad

```text
openspec/
└── changes/ingesta-pdf-clinicos/
    ├── proposal.md              # Propósito, límites y entregas
    ├── design.md                # Decisiones de diseño
    ├── tasks.md                 # Tareas y puertas de aprobación
    └── specs/                   # Especificaciones por capacidad
```

Los artefactos de OpenSpec documentan lo planificado y las condiciones para avanzar; no implican que una capacidad futura ya exista en el código.

### Capacidades futuras

La UI local, la extracción real de PDFs, la evaluación con corpus aprobado, la persistencia, ecocardiografía, ECG y ML son capacidades futuras. Cada una se incorporará únicamente dentro de su etapa aprobada.

## Desarrollo y pruebas

Desde la raíz del repositorio, con el entorno virtual local disponible:

```powershell
.venv/Scripts/python.exe -m pytest
```

### Estado y limitaciones verificables hoy

- Las pruebas ejercitan reglas y marcadores sintéticos; no contienen ni validan documentos clínicos reales.
- Los bytes se decodifican como UTF-8 para inspeccionar marcadores sintéticos; no hay procesamiento real de formato PDF.
- No existe UI, carga por navegador, procesamiento por lote ni integración con red.
- No existe persistencia, base de datos, archivos temporales ni registro de contenido.
- La aprobación técnica del núcleo no es una validación clínica, una garantía de anonimización para datos reales ni una declaración de preparación productiva.
