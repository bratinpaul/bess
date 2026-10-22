/**
 * Export a rendered page section to an A4 PDF that looks like the page.
 *
 * The element is drawn to a canvas (html2canvas, so chart canvases come out as on screen) and split over A4 pages.
 * Page breaks fall at the top of the "break" elements (cards, table rows) where possible, so no card is cut in two;
 * a table that continues onto the next page gets its column headings repeated there.
 * html2canvas and jsPDF are loaded only when a report is downloaded.
 */
export interface PdfReportOptions {
  fileName: string;
  /** Elements inside the root whose top edge is a good place for a page break (default: cards and table rows). */
  breakSelector?: string;
  /** Footer text on every page (page numbers are added on the right). */
  footer?: string;
  orientation?: 'portrait' | 'landscape';
  /** Called as the report is drawn: parts done / parts in all (a long report is drawn in a few parts). */
  onProgress?: (done: number, total: number) => void;
}

const MARGIN_MM = 10;
const FOOTER_MM = 6;
// the tallest piece of the page captured at once (CSS px; x2 scale stays well inside browser canvas limits)
const CHUNK_PX = 8000;

export async function exportElementToPdf(root: HTMLElement, options: PdfReportOptions): Promise<void> {
  const [{ default: html2canvas }, { jsPDF }] = await Promise.all([import('html2canvas'), import('jspdf')]);
  const scale = 2;
  const background = getComputedStyle(document.body).backgroundColor || '#ffffff';

  const pdf = new jsPDF({ orientation: options.orientation ?? 'portrait', unit: 'mm', format: 'a4' });
  const pageW = pdf.internal.pageSize.getWidth();
  const pageH = pdf.internal.pageSize.getHeight();
  const contentW = pageW - 2 * MARGIN_MM;
  const contentH = pageH - 2 * MARGIN_MM - FOOTER_MM;

  // page layout in CSS pixels of the root element
  const rect = root.getBoundingClientRect();
  const width = rect.width;
  const height = root.scrollHeight;
  const mmPerPx = contentW / width;
  const pagePx = Math.floor(contentH / mmPerPx);

  // where a page may end: the top of each break element
  const breaks = Array.from(root.querySelectorAll<HTMLElement>(options.breakSelector ?? '.card, tbody tr'))
    .map((el) => Math.round(el.getBoundingClientRect().top - rect.top - 1))
    .filter((y) => y > 0)
    .sort((a, b) => a - b);

  // tables with a header row: on a page that starts inside the table body the header row is repeated
  const tables = Array.from(root.querySelectorAll<HTMLTableElement>('table'))
    .map((t, id) => ({ id, head: t.tHead?.getBoundingClientRect(), box: t.getBoundingClientRect() }))
    .filter((t) => t.head && t.head.height > 0)
    .map((t) => ({ id: t.id, headTop: t.head!.top - rect.top, headBottom: t.head!.bottom - rect.top, bottom: t.box.bottom - rect.top }));
  const continuing = (at: number) => tables.find((t) => at >= t.headBottom + 1 && at < t.bottom - 2);

  const slices: { from: number; to: number; head?: (typeof tables)[number] }[] = [];
  let y = 0;
  while (y < height) {
    const head = continuing(y);
    const room = pagePx - (head ? Math.ceil(head.headBottom - head.headTop) : 0);
    let end = Math.min(y + room, height);
    if (end < height) {
      const fit = breaks.filter((b) => b > y + room * 0.25 && b <= end);
      if (fit.length) {
        end = fit[fit.length - 1];
      }
    }
    slices.push({ from: y, to: end, head });
    y = end;
  }

  // capture runs of whole pages up to CHUNK_PX tall: one capture for a short report, a few for a long one
  // (each capture clones the page, so fewer is faster; browsers cap the size of a single canvas)
  const chunks: { from: number; to: number; pages: number[] }[] = [];
  slices.forEach(({ from, to }, i) => {
    const last = chunks[chunks.length - 1];
    if (last && to - last.from <= CHUNK_PX) {
      last.to = to;
      last.pages.push(i);
    } else {
      chunks.push({ from, to, pages: [i] });
    }
  });
  const pageCanvas: HTMLCanvasElement[] = [];
  const headStrips = new Map<number, HTMLCanvasElement>();
  const crop = (shot: HTMLCanvasElement, top: number, rows: number) => {
    const c = document.createElement('canvas');
    c.width = shot.width;
    c.height = rows;
    const ctx = c.getContext('2d')!;
    ctx.fillStyle = background;
    ctx.fillRect(0, 0, c.width, c.height);
    ctx.drawImage(shot, 0, top, shot.width, rows, 0, 0, c.width, rows);
    return c;
  };
  for (const [n, chunk] of chunks.entries()) {
    options.onProgress?.(n, chunks.length);
    const shot = await html2canvas(root, {
      scale, backgroundColor: background, useCORS: true, logging: false,
      // x / y are offsets from the element's own top-left corner
      x: 0, y: chunk.from, width, height: chunk.to - chunk.from
    });
    // header rows captured in this part, for the pages their table continues onto
    for (const t of tables) {
      if (!headStrips.has(t.id) && t.headTop >= chunk.from && t.headBottom <= chunk.to) {
        const top = Math.round((t.headTop - chunk.from) * scale);
        headStrips.set(t.id, crop(shot, top, Math.round((t.headBottom - t.headTop) * scale)));
      }
    }
    for (const i of chunk.pages) {
      const { from, to, head } = slices[i];
      const body = crop(shot, Math.round((from - chunk.from) * scale), Math.round((to - from) * scale));
      const strip = head ? headStrips.get(head.id) : undefined;
      if (!strip) {
        pageCanvas[i] = body;
        continue;
      }
      const page = document.createElement('canvas');
      page.width = body.width;
      page.height = strip.height + body.height;
      const ctx = page.getContext('2d')!;
      ctx.drawImage(strip, 0, 0);
      ctx.drawImage(body, 0, strip.height);
      pageCanvas[i] = page;
    }
  }

  for (let i = 0; i < slices.length; i++) {
    const part = pageCanvas[i];
    if (i > 0) {
      pdf.addPage();
    }
    pdf.setFillColor(background);
    pdf.rect(0, 0, pageW, pageH, 'F');
    pdf.addImage(part.toDataURL('image/jpeg', 0.92), 'JPEG', MARGIN_MM, MARGIN_MM, contentW, (part.height / scale) * mmPerPx);
    pdf.setDrawColor(203, 213, 225);
    pdf.line(MARGIN_MM, pageH - MARGIN_MM - 2.5, pageW - MARGIN_MM, pageH - MARGIN_MM - 2.5);
    pdf.setFontSize(8);
    pdf.setTextColor(100, 116, 139);
    if (options.footer) {
      pdf.text(options.footer, MARGIN_MM, pageH - MARGIN_MM + 2);
    }
    pdf.text(`Page ${i + 1} of ${slices.length}`, pageW - MARGIN_MM, pageH - MARGIN_MM + 2, { align: 'right' });
  }
  pdf.save(options.fileName);
}

/**
 * The state a page needs for its "Download PDF" button: exporting (the page shows its report header instead of
 * the filters while true), the error, and when the report was generated.
 */
export class ReportExporter {
  exporting = false;
  /** e.g. "1/3" while a long report is drawn in parts ('' for a one-part report). */
  progress = '';
  error: string | null = null;
  generatedAt = new Date();

  async download(root: HTMLElement, options: PdfReportOptions): Promise<void> {
    if (this.exporting) {
      return;
    }
    this.exporting = true;
    this.error = null;
    this.generatedAt = new Date();
    // let the page switch to report mode (report header, full tables) and redraw before it is captured
    await new Promise((resolve) => setTimeout(resolve, 350));
    try {
      await exportElementToPdf(root, {
        ...options,
        onProgress: (done, total) => (this.progress = total > 1 ? `${done + 1}/${total}` : '')
      });
    } catch (err) {
      this.error = `Could not create the PDF: ${err instanceof Error ? err.message : err}`;
    } finally {
      this.exporting = false;
      this.progress = '';
    }
  }
}

/** A file-name-safe version of a label ("Bhuj BESS Site" -> "Bhuj_BESS_Site"). */
export function fileSafe(label: string | null | undefined, fallback = ''): string {
  return (label || fallback).replace(/[^\w-]+/g, '_').replace(/^_+|_+$/g, '');
}

/** "2026-09-30" -> "30 Sep 2026" for report headers. */
export function reportDate(iso: string | null | undefined): string {
  if (!iso) {
    return '';
  }
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  return y && m && d ? `${d} ${months[m - 1]} ${y}` : iso;
}
