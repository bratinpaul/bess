"""Build the ERD PDF: "BESS DESIGN/Database/BESS_ERD.pdf".

Steps: export the schema metadata (export_model.py) -> lay out and draw with ELK (erd.mjs, needs `npm install`
in db_docs once) -> print with headless Chrome (one PDF, a page per schema sized to its diagram).

Usage: python db_docs/build_erd.py
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "BESS DESIGN" / "Database" / "BESS_ERD.pdf"
CHROME = [Path(os.getenv("CHROME", r"C:\Program Files\Google\Chrome\Application\chrome.exe")),
          Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")]


def main() -> int:
    if not (HERE / "node_modules" / "elkjs").exists():
        subprocess.run("npm install --silent", cwd=HERE, shell=True, check=True)
    browser = next((c for c in CHROME if c.exists()), None)
    if browser is None:
        print("Chrome / Edge not found - set CHROME to the browser executable")
        return 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        model, html = Path(tmp) / "model.json", Path(tmp) / "erd.html"
        subprocess.run([sys.executable, str(HERE / "export_model.py"), str(model)], check=True)
        subprocess.run(["node", str(HERE / "erd.mjs"), str(model), str(html)], cwd=HERE, check=True)
        subprocess.run([str(browser), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                        f"--print-to-pdf={OUT}", html.as_uri()], check=True, capture_output=True)
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
