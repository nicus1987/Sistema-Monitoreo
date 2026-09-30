const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType, Table, TableRow, TableCell,
  WidthType, ShadingType, BorderStyle, LevelFormat, PageBreak, TableOfContents, Footer, Header,
  PageNumber, TableLayoutType,
} = require("docx");
const { normas, checklist, glosario } = require("./contenido");

const rules = JSON.parse(fs.readFileSync(path.join(__dirname, "rules.json"), "utf8"));
const OUT = process.argv[2];

const NAVY = "1F3864", ACCENT = "2E5C9A", LIGHT = "E8EEF7", GREY = "595959";
const W = 9026; // ancho útil A4 con márgenes de 1"
const FONT = "Calibri";

const border = { style: BorderStyle.SINGLE, size: 4, color: "BFBFBF" };
const borders = { top: border, bottom: border, left: border, right: border };

const p = (text, opts = {}) => new Paragraph({
  spacing: { after: 120, line: 276 }, ...opts.para,
  children: Array.isArray(text) ? text : [new TextRun({ text, ...opts.run })],
});
const label = (text) => new Paragraph({
  spacing: { before: 160, after: 60 },
  children: [new TextRun({ text, bold: true, color: ACCENT, size: 22 })],
});
const bullet = (text, ref = "bullets") => new Paragraph({
  numbering: { reference: ref, level: 0 }, spacing: { after: 60, line: 264 },
  children: [new TextRun(text)],
});

function cell(content, width, { fill, bold, color, align, size } = {}) {
  const runs = Array.isArray(content) ? content : [new TextRun({ text: String(content), bold, color, size: size || 20 })];
  return new TableCell({
    width: { size: width, type: WidthType.DXA }, borders,
    shading: fill ? { fill, type: ShadingType.CLEAR, color: "auto" } : undefined,
    margins: { top: 70, bottom: 70, left: 110, right: 110 },
    children: [new Paragraph({ alignment: align, children: runs })],
  });
}
function table(widths, header, rows, rowFill) {
  return new Table({
    width: { size: W, type: WidthType.DXA }, columnWidths: widths, layout: TableLayoutType.FIXED,
    rows: [
      new TableRow({ tableHeader: true, children: header.map((h, i) => cell(h, widths[i], { fill: NAVY, bold: true, color: "FFFFFF" })) }),
      ...rows.map((r, ri) => new TableRow({
        cantSplit: true,
        children: r.map((c, i) => {
          const f = rowFill ? rowFill(r, i, ri) : (ri % 2 ? "F5F7FA" : undefined);
          return typeof c === "object" && c.text !== undefined
            ? cell(c.text, widths[i], { fill: c.fill || f, bold: c.bold, align: c.align })
            : cell(c, widths[i], { fill: f });
        }),
      })),
    ],
  });
}
function callout(lines, fill = "FFF4E5", edge = "E69138") {
  const side = { style: BorderStyle.SINGLE, size: 24, color: edge };
  const none = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
  return new Table({
    width: { size: W, type: WidthType.DXA }, columnWidths: [W],
    rows: [new TableRow({ children: [new TableCell({
      width: { size: W, type: WidthType.DXA },
      borders: { left: side, top: none, bottom: none, right: none },
      shading: { fill, type: ShadingType.CLEAR, color: "auto" },
      margins: { top: 120, bottom: 120, left: 200, right: 200 },
      children: lines.map((l) => new Paragraph({ spacing: { after: 80 },
        children: Array.isArray(l) ? l : [new TextRun({ text: l, size: 20 })] })),
    })] })],
  });
}

// ------------------------------------------------------------------ portada
const today = new Date();
const meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
const fecha = `${meses[today.getMonth()]} de ${today.getFullYear()}`;

const portada = [
  new Paragraph({ spacing: { before: 2400 }, children: [] }),
  new Paragraph({ children: [new TextRun({ text: "Resumen normativo", size: 56, bold: true, color: NAVY })] }),
  new Paragraph({ spacing: { after: 240 }, children: [new TextRun({ text: "Monitoreo transaccional, fraude y PLA/FT", size: 36, color: ACCENT })] }),
  new Paragraph({ border: { bottom: { style: BorderStyle.SINGLE, size: 12, color: ACCENT, space: 4 } }, spacing: { after: 360 }, children: [] }),
  p("Qué exige cada norma referenciada en el sistema de monitoreo, qué tiene que hacer la entidad para cumplirla, qué parte ya resuelve el sistema y qué queda pendiente.", { run: { size: 24, color: GREY } }),
  p("Alcance: adquirencia, cash-in y cash-out.", { run: { size: 24, color: GREY } }),
  p(`Versión: ${fecha}`, { run: { size: 22, color: GREY }, para: { spacing: { before: 240, after: 600 } } }),
  callout([
    [new TextRun({ text: "Importante — validar antes de usar", bold: true, size: 22, color: "B45F06" })],
    "Este documento es una guía de trabajo preparada a partir del diseño del sistema. No es asesoramiento legal.",
    "La normativa argentina cambia con frecuencia (textos ordenados del BCRA, resoluciones de la UIF, montos y plazos). Antes de tomar decisiones, el Oficial de Cumplimiento y Legales deben confirmar la vigencia de cada norma citada, su número actual y los plazos aplicables.",
    "Los plazos específicos (por ejemplo, para presentar un ROS) no se detallan a propósito: deben tomarse de la norma vigente.",
  ]),
  new Paragraph({ children: [new PageBreak()] }),
];

// ----------------------------------------------------------------- índice
const indice = [
  new Paragraph({ spacing: { after: 200 }, children: [new TextRun({ text: "Contenido", size: 32, bold: true, color: NAVY })] }),
  new TableOfContents("Contenido", { hyperlink: true, headingStyleRange: "1-2" }),
  p("Si el índice aparece vacío: clic derecho sobre él → \"Actualizar campo\".", { run: { size: 18, color: GREY, italics: true } }),
  new Paragraph({ children: [new PageBreak()] }),
];

// ------------------------------------------------------------ introducción
const intro = [
  new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("1. Cómo leer este documento")] }),
  p("El sistema de monitoreo asocia cada regla a uno o más códigos normativos (los que aparecen en la consola, en \"Referencias normativas\"). Para cada código este documento explica:"),
  bullet("Qué es: la norma en pocas palabras."),
  bullet("Qué exige: las obligaciones principales."),
  bullet("Qué tenés que hacer: las acciones concretas de la entidad, en forma de lista de verificación."),
  bullet("Cómo lo cubre el sistema: qué parte ya resuelve el motor de monitoreo y qué reglas la implementan."),
  bullet("Pendiente fuera del sistema: lo que el sistema no hace y requiere procesos, personas u otras herramientas."),
  p("Las secciones 3 a 6 detallan cada norma, agrupadas por origen. La sección 7 es un plan de acción consolidado con el estado de cobertura de cada obligación; al final hay un glosario."),
  p("Una idea clave: el sistema es una herramienta de monitoreo. La responsabilidad de cumplimiento es de la entidad y no se delega en el software. Las obligaciones de gobierno (manuales, designaciones, capacitación, reportes al directorio, presentación de ROS) requieren procesos y personas."),
];

// ------------------------------------------------------------ resumen tabla
const resumen = [
  new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: true, children: [new TextRun("2. Resumen de normas")] }),
  p("Cantidad de reglas del sistema vinculadas a cada norma (una regla puede citar más de una norma)."),
  table([1700, 4526, 2000, 800], ["Código", "Norma", "Responsable sugerido", "Reglas"],
    normas.map((n) => [{ text: n.code, bold: true }, n.titulo, n.responsable, { text: String((rules[n.code] || []).length), align: AlignmentType.CENTER }])),
];

// ---------------------------------------------------------------- detalle
const detalle = [];
let grupoActual = null, nGrupo = 2;
for (const n of normas) {
  if (n.grupo !== grupoActual) {
    grupoActual = n.grupo; nGrupo += 1;
    detalle.push(new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: true,
      children: [new TextRun(`${nGrupo}. ${n.grupo}`)] }));
  }
  detalle.push(new Paragraph({ heading: HeadingLevel.HEADING_2, keepNext: true,
    children: [new TextRun({ text: n.code + "  ", color: ACCENT }), new TextRun(n.titulo)] }));
  detalle.push(p([
    new TextRun({ text: "Organismo: ", bold: true, size: 19, color: GREY }), new TextRun({ text: n.organismo, size: 19, color: GREY }),
    new TextRun({ text: "     Responsable sugerido: ", bold: true, size: 19, color: GREY }), new TextRun({ text: n.responsable, size: 19, color: GREY }),
  ]));
  detalle.push(label("Qué es"), p(n.que_es));
  detalle.push(label("Qué exige"), ...n.exige.map((x) => bullet(x)));
  detalle.push(label("Qué tenés que hacer"), ...n.hacer.map((x) => bullet(x, "checks")));
  const rs = rules[n.code] || [];
  detalle.push(label("Cómo lo cubre el sistema"), p(n.sistema));
  if (rs.length) {
    detalle.push(p([new TextRun({ text: `Reglas vinculadas (${rs.length}): `, bold: true, size: 19 }),
      new TextRun({ text: rs.map((r) => r.id + (r.mode === "shadow" ? " (sombra)" : "")).join(", "), size: 19, color: GREY })]));
  }
  detalle.push(label("Pendiente fuera del sistema"), ...n.pendiente.map((x) => bullet(x, "pending")));
}

// ---------------------------------------------------------- plan de acción
const FILL = { "Sí": "D9EAD3", "Parcial": "FFF2CC", "No": "F4CCCC" };
const plan = [
  new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: true, children: [new TextRun(`${nGrupo + 1}. Plan de acción consolidado`)] }),
  p("Estado de cobertura por parte del sistema de monitoreo:"),
  bullet("Sí: el sistema ya lo resuelve (hay que operarlo y mantenerlo)."),
  bullet("Parcial: el sistema aporta la herramienta, pero falta configuración, datos o integración."),
  bullet("No: requiere un proceso o herramienta fuera del sistema."),
  new Paragraph({ spacing: { after: 120 }, children: [] }),
  table([3900, 2126, 1900, 1100], ["Acción", "Normas", "Responsable", "¿Cubierto?"],
    checklist.map(([accion, refs, resp, estado]) => [accion, refs, resp, { text: estado, bold: true, align: AlignmentType.CENTER, fill: FILL[estado] }])),
  new Paragraph({ spacing: { before: 240 }, children: [] }),
  label("Prioridades sugeridas"),
  bullet("1. Antes de operar con clientes reales: listas de sanciones sincronizadas, perfil de riesgo de clientes cargado, umbrales validados por Cumplimiento, login con permisos en la consola.", "plain"),
  bullet("2. En los primeros 90 días: procedimiento formal de cambios de reglas, circuito de ROS documentado, persistencia de alertas y auditoría, pruebas de continuidad.", "plain"),
  bullet("3. Recurrente: actualización de la lista GAFI (3 veces por año), revisión de reglas (semestral), capacitación y revisión independiente (anual).", "plain"),
];

// --------------------------------------------------------------- glosario
const glos = [
  new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: true, children: [new TextRun(`${nGrupo + 2}. Glosario`)] }),
  table([2400, 6626], ["Término", "Significado"], glosario.map(([t, d]) => [{ text: t, bold: true }, d])),
  new Paragraph({ heading: HeadingLevel.HEADING_1, spacing: { before: 480 }, children: [new TextRun(`${nGrupo + 3}. Dónde verificar la normativa vigente`)] }),
  bullet("Boletín Oficial de la República Argentina: leyes, decretos y resoluciones UIF."),
  bullet("Sitio de la UIF (argentina.gob.ar/uif): resoluciones por tipo de sujeto obligado y listas."),
  bullet("Sitio del BCRA: textos ordenados vigentes y comunicaciones \"A\"."),
  bullet("GAFI / FATF (fatf-gafi.org): recomendaciones y listas de jurisdicciones de alto riesgo."),
  bullet("PCI Security Standards Council (pcisecuritystandards.org): versión vigente de PCI DSS."),
];

// -------------------------------------------------------------- documento
const doc = new Document({
  creator: "Sistema de Monitoreo",
  title: "Resumen normativo — Monitoreo transaccional, fraude y PLA/FT",
  styles: {
    default: { document: { run: { font: FONT, size: 21 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 32, bold: true, font: FONT, color: NAVY }, paragraph: { spacing: { before: 240, after: 200 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 25, bold: true, font: FONT, color: NAVY },
        paragraph: { spacing: { before: 360, after: 80 }, outlineLevel: 1,
          border: { top: { style: BorderStyle.SINGLE, size: 6, color: "BFBFBF", space: 8 } } } },
    ],
  },
  numbering: { config: [
    { reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
      style: { paragraph: { indent: { left: 540, hanging: 270 } } } }] },
    { reference: "checks", levels: [{ level: 0, format: LevelFormat.BULLET, text: "☐", alignment: AlignmentType.LEFT,
      style: { paragraph: { indent: { left: 540, hanging: 300 } }, run: { font: "Segoe UI Symbol" } } }] },
    { reference: "pending", levels: [{ level: 0, format: LevelFormat.BULLET, text: "→", alignment: AlignmentType.LEFT,
      style: { paragraph: { indent: { left: 540, hanging: 300 } }, run: { color: "B45F06" } } }] },
    { reference: "plain", levels: [{ level: 0, format: LevelFormat.BULLET, text: " ", alignment: AlignmentType.LEFT,
      style: { paragraph: { indent: { left: 360, hanging: 0 } } } }] },
  ] },
  sections: [{
    properties: { page: { margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } },
    headers: { default: new Header({ children: [new Paragraph({ alignment: AlignmentType.RIGHT,
      children: [new TextRun({ text: "Resumen normativo · Monitoreo transaccional, fraude y PLA/FT", size: 16, color: GREY })] })] }) },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: "Página ", size: 16, color: GREY }), new TextRun({ children: [PageNumber.CURRENT], size: 16, color: GREY }),
                 new TextRun({ text: " de ", size: 16, color: GREY }), new TextRun({ children: [PageNumber.TOTAL_PAGES], size: 16, color: GREY })] })] }) },
    children: [...portada, ...indice, ...intro, ...resumen, ...detalle, ...plan, ...glos],
  }],
});

Packer.toBuffer(doc).then((buf) => { fs.writeFileSync(OUT, buf); console.log("OK", OUT, buf.length); });
