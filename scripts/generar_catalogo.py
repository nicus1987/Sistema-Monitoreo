"""Genera docs/catalogo_reglas.md a partir de config/rules/*.yaml.

Uso: python scripts/generar_catalogo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from monitoreo.models import Channel  # noqa: E402
from monitoreo.service import MonitoringService  # noqa: E402

TITLES = {
    Channel.ACQUIRING: "Adquirencia",
    Channel.CASH_IN: "Cash-in",
    Channel.CASH_OUT: "Cash-out",
}


def main() -> None:
    svc = MonitoringService(ROOT / "config")
    rs = svc.ruleset
    out = [
        "# Catálogo de reglas",
        "",
        f"Generado automáticamente desde `config/rules/` — versión del ruleset `{rs.version}`, "
        f"{len(rs.rules)} reglas. No editar a mano: ejecutar `python scripts/generar_catalogo.py`.",
        "",
        "Decisión final = acción más severa entre (a) la acción de cada regla activa disparada y "
        "(b) el score combinado (noisy-OR) contra los umbrales del canal:",
        "",
        "| Canal | Revisión desde | Rechazo desde |",
        "|---|---|---|",
    ]
    for ch, th in svc.params["decision_thresholds"].items():
        out.append(f"| {ch} | {th['review']} | {th['decline']} |")
    for ch in Channel:
        out += ["", f"## {TITLES[ch]}", "",
                "| ID | Regla | Categoría | Severidad | Acción | Score | Modo | Condición | Normativa |",
                "|---|---|---|---|---|---|---|---|---|"]
        for r in rs.for_channel(ch):
            cond = " ".join(r.condition.source.split()).replace("|", "\\|")
            out.append(f"| {r.id} | {r.name} | {r.category.value} | {r.severity.value} | {r.action.value} | "
                       f"{r.score} | {r.mode} | `{cond}` | {', '.join(r.regulatory_refs)} |")
    (ROOT / "docs" / "catalogo_reglas.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"docs/catalogo_reglas.md generado ({len(rs.rules)} reglas)")


if __name__ == "__main__":
    main()
