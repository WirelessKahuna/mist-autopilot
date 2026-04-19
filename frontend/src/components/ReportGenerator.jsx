/**
 * ReportGenerator.jsx
 * Mist Autopilot — Client-side PDF report export
 *
 * Dependencies:
 *   npm install jspdf   ← already done
 *
 * Usage:
 *   import ReportGenerator from './components/ReportGenerator';
 *
 *   <ReportGenerator
 *     orgName={orgName}
 *     orgId={orgId}
 *     moduleResults={moduleResults}
 *     siteNames={siteNames}
 *   />
 *
 * moduleResults shape (one entry per module):
 *   {
 *     moduleId:    string,           // e.g. "secure-scope"
 *     moduleName:  string,           // e.g. "SecureScope"
 *     moduleIcon:  string,           // emoji, e.g. "🔒"
 *     status:      "pass"|"warning"|"critical"|"error"|"pending",
 *     findings:    [
 *       {
 *         severity:  "critical"|"warning"|"info",
 *         site_id:   string|null,    // null = org-level finding
 *         message:   string,
 *       }
 *     ]
 *   }
 */

import React, { useState } from 'react';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function countBySeverity(findings = []) {
  return findings.reduce(
    (acc, f) => {
      const key = f.severity || 'info';
      acc[key] = (acc[key] || 0) + 1;
      return acc;
    },
    { critical: 0, warning: 0, info: 0 }
  );
}

function moduleStatusLabel(status) {
  switch (status) {
    case 'pass':     return 'PASS';
    case 'warning':  return 'WARNING';
    case 'critical': return 'CRITICAL';
    case 'error':    return 'ERROR';
    case 'pending':  return 'PENDING';
    default:         return status?.toUpperCase() || 'UNKNOWN';
  }
}

function overallHealth(moduleResults = []) {
  if (moduleResults.some(m => m.status === 'critical')) return 'critical';
  if (moduleResults.some(m => m.status === 'warning'))  return 'warning';
  if (moduleResults.every(m => m.status === 'pass'))    return 'pass';
  return 'unknown';
}

// ---------------------------------------------------------------------------
// PDF builder  (pure function, no React)
// ---------------------------------------------------------------------------

async function generatePDF({ orgName, orgId, moduleResults, siteNames }) {
  const { jsPDF } = await import('jspdf');

  const doc = new jsPDF({ orientation: 'portrait', unit: 'mm', format: 'a4' });

  const PAGE_W    = 210;
  const PAGE_H    = 297;
  const MARGIN    = 18;
  const CONTENT_W = PAGE_W - MARGIN * 2;

  const C = {
    black:     [15,  15,  20],
    darkGray:  [45,  45,  55],
    midGray:   [110, 110, 120],
    lightGray: [200, 200, 205],
    rule:      [230, 230, 235],
    critical:  [220,  50,  50],
    warning:   [230, 150,  20],
    pass:      [40,  170,  90],
    info:      [60,  130, 220],
    accent:    [25,  130, 220],
    bgHeader:  [18,  30,  48],
    white:     [255, 255, 255],
  };

  let y = 0;

  function setColor(rgb, type = 'text') {
    if (type === 'text') doc.setTextColor(...rgb);
    else if (type === 'fill') doc.setFillColor(...rgb);
    else if (type === 'draw') doc.setDrawColor(...rgb);
  }

  function rule(yPos, color = C.rule, thickness = 0.2) {
    doc.setLineWidth(thickness);
    setColor(color, 'draw');
    doc.line(MARGIN, yPos, PAGE_W - MARGIN, yPos);
  }

  function drawPageFooter() {
    const footerY = PAGE_H - 10;
    setColor(C.midGray, 'text');
    doc.setFontSize(7);
    doc.setFont('helvetica', 'normal');
    doc.text(
      'Mist Autopilot  |  tools.wirelesskahuna.com  |  Read-only analysis — Observer role sufficient',
      MARGIN, footerY
    );
    const pageNum = 'Page ' + doc.internal.getCurrentPageInfo().pageNumber;
    doc.text(pageNum, PAGE_W - MARGIN, footerY, { align: 'right' });
  }

  function checkPageBreak(needed = 10) {
    if (y + needed > PAGE_H - 15) {
      doc.addPage();
      y = MARGIN;
      drawPageFooter();
    }
  }

  function severityColor(sev) {
    switch (sev) {
      case 'critical': return C.critical;
      case 'warning':  return C.warning;
      case 'pass':     return C.pass;
      case 'info':     return C.info;
      default:         return C.midGray;
    }
  }

  // ── Cover / header block ─────────────────────────────────────────────
  setColor(C.bgHeader, 'fill');
  doc.rect(0, 0, PAGE_W, 52, 'F');

  doc.setFont('helvetica', 'bold');
  doc.setFontSize(22);
  setColor(C.white, 'text');
  doc.text('Mist Autopilot', MARGIN, 22);

  doc.setFont('helvetica', 'normal');
  doc.setFontSize(11);
  setColor([160, 190, 220], 'text');
  doc.text('Org Health Report', MARGIN, 31);

  doc.setFontSize(8);
  setColor([180, 205, 230], 'text');
  const ts = new Date().toLocaleString('en-US', {
    month: 'short', day: 'numeric', year: 'numeric',
    hour: '2-digit', minute: '2-digit', timeZoneName: 'short'
  });
  doc.text('Generated: ' + ts, PAGE_W - MARGIN, 18, { align: 'right' });
  doc.text('Org: ' + orgName, PAGE_W - MARGIN, 25, { align: 'right' });
  const sitesAnalyzed = Object.keys(siteNames || {}).length;
  doc.text('Sites analyzed: ' + sitesAnalyzed, PAGE_W - MARGIN, 31, { align: 'right' });

  y = 60;

  // ── Executive Summary ────────────────────────────────────────────────
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(13);
  setColor(C.black, 'text');
  doc.text('Executive Summary', MARGIN, y);
  y += 2;
  rule(y, C.accent, 0.5);
  y += 7;

  const health = overallHealth(moduleResults);
  setColor(severityColor(health), 'fill');
  doc.roundedRect(MARGIN, y - 4, 38, 8, 2, 2, 'F');
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(9);
  setColor(C.white, 'text');
  doc.text('* ' + health.toUpperCase(), MARGIN + 19, y + 1.2, { align: 'center' });

  const allFindings = moduleResults.flatMap(m => m.findings || []);
  const totals = countBySeverity(allFindings);
  const modulesPassed = moduleResults.filter(m => m.status === 'pass').length;

  const summaryItems = [
    { label: 'Modules run', value: moduleResults.length, color: C.black },
    { label: 'Passed',      value: modulesPassed,        color: C.pass },
    { label: 'Critical',    value: totals.critical,      color: C.critical },
    { label: 'Warnings',    value: totals.warning,       color: C.warning },
  ];

  let sx = MARGIN + 46;
  summaryItems.forEach(item => {
    setColor(item.color, 'text');
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(14);
    doc.text(String(item.value), sx, y + 1);
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(7.5);
    setColor(C.midGray, 'text');
    doc.text(item.label, sx, y + 6);
    sx += 30;
  });

  y += 18;
  rule(y, C.rule);
  y += 8;

  // ── Module Results Table ─────────────────────────────────────────────
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(13);
  setColor(C.black, 'text');
  doc.text('Module Results', MARGIN, y);
  y += 2;
  rule(y, C.accent, 0.5);
  y += 7;

  const COL = { name: MARGIN, status: MARGIN + 95, counts: MARGIN + 125 };

  doc.setFont('helvetica', 'bold');
  doc.setFontSize(7.5);
  setColor(C.midGray, 'text');
  doc.text('MODULE',   COL.name,   y);
  doc.text('STATUS',   COL.status, y);
  doc.text('FINDINGS', COL.counts, y);
  y += 2;
  rule(y, C.lightGray, 0.15);
  y += 5;

  const sorted = [...moduleResults].sort((a, b) => {
    const order = { critical: 0, warning: 1, error: 2, pass: 3, pending: 4 };
    return (order[a.status] ?? 9) - (order[b.status] ?? 9);
  });

  sorted.forEach((mod, idx) => {
    checkPageBreak(14);

    if (idx % 2 === 0) {
      setColor([248, 248, 250], 'fill');
      doc.rect(MARGIN - 2, y - 4, CONTENT_W + 4, 9, 'F');
    }

    const fc = countBySeverity(mod.findings || []);

    doc.setFont('helvetica', 'bold');
    doc.setFontSize(9);
    setColor(C.darkGray, 'text');
    doc.text(mod.moduleName, COL.name, y);

    setColor(severityColor(mod.status), 'text');
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(8);
    doc.text('* ' + moduleStatusLabel(mod.status), COL.status, y);

    doc.setFont('helvetica', 'normal');
    doc.setFontSize(7.5);
    const parts = [];
    if (fc.critical > 0) parts.push(fc.critical + ' critical');
    if (fc.warning  > 0) parts.push(fc.warning  + ' warning');
    if (fc.info     > 0) parts.push(fc.info      + ' info');
    if (parts.length === 0 && mod.status === 'pass') parts.push('No issues');
    setColor(C.midGray, 'text');
    doc.text(parts.join('  ·  '), COL.counts, y);

    y += 9;
  });

  y += 4;

  // ── Per-Module Finding Detail ────────────────────────────────────────
  const modulesWithFindings = sorted.filter(m => (m.findings || []).length > 0);

  if (modulesWithFindings.length > 0) {
    checkPageBreak(20);

    doc.setFont('helvetica', 'bold');
    doc.setFontSize(13);
    setColor(C.black, 'text');
    doc.text('Finding Detail', MARGIN, y);
    y += 2;
    rule(y, C.accent, 0.5);
    y += 8;

    modulesWithFindings.forEach(mod => {
      checkPageBreak(18);

      setColor(C.bgHeader, 'fill');
      doc.rect(MARGIN - 2, y - 5, CONTENT_W + 4, 8, 'F');
      doc.setFont('helvetica', 'bold');
      doc.setFontSize(9);
      setColor(C.white, 'text');
      doc.text(mod.moduleName, MARGIN + 1, y);
      y += 8;

      const grouped = ['critical', 'warning', 'info'].reduce((acc, sev) => {
        const items = (mod.findings || []).filter(f => (f.severity || 'info') === sev);
        if (items.length) acc.push({ sev, items });
        return acc;
      }, []);

      grouped.forEach(({ sev, items }) => {
        items.forEach(finding => {
          checkPageBreak(10);

          setColor(severityColor(sev), 'fill');
          doc.rect(MARGIN - 2, y - 4, 2, 7, 'F');

          let prefix = '';
          if (finding.site_id && finding.site_id !== '00000000-0000-0000-0000-000000000000') {
            const siteName = (siteNames || {})[finding.site_id] || 'Unknown Site';
            prefix = '[' + siteName + ']  ';
          } else {
            prefix = '[Org-level]  ';
          }

          doc.setFont('helvetica', 'bold');
          doc.setFontSize(7.5);
          setColor(severityColor(sev), 'text');
          doc.text(sev.toUpperCase(), MARGIN + 2, y);

          doc.setFont('helvetica', 'normal');
          setColor(C.midGray, 'text');
          doc.text(prefix, MARGIN + 18, y);

          doc.setFont('helvetica', 'normal');
          setColor(C.darkGray, 'text');
          const msgX = MARGIN + 18 + doc.getTextWidth(prefix);
          const maxW = PAGE_W - MARGIN - msgX;
          const lines = doc.splitTextToSize(finding.message, maxW);
          doc.text(lines, msgX, y);

          y += Math.max(lines.length * 4.5, 6);
        });
      });

      y += 4;
    });
  }

  // ── Site Breakdown ───────────────────────────────────────────────────
  if (Object.keys(siteNames || {}).length > 0) {
    checkPageBreak(20);

    doc.setFont('helvetica', 'bold');
    doc.setFontSize(13);
    setColor(C.black, 'text');
    doc.text('Site Breakdown', MARGIN, y);
    y += 2;
    rule(y, C.accent, 0.5);
    y += 8;

    Object.entries(siteNames).forEach(([siteId, siteName]) => {
      checkPageBreak(10);

      const siteFindings = moduleResults.flatMap(m =>
        (m.findings || []).filter(f => f.site_id === siteId)
      );
      const sc = countBySeverity(siteFindings);

      doc.setFont('helvetica', 'bold');
      doc.setFontSize(9);
      setColor(C.darkGray, 'text');
      doc.text(siteName, MARGIN, y);

      doc.setFont('helvetica', 'normal');
      doc.setFontSize(8);

      if (siteFindings.length === 0) {
        setColor(C.pass, 'text');
        doc.text('All clear', MARGIN + 75, y);
      } else {
        let fx = MARGIN + 75;
        if (sc.critical > 0) { setColor(C.critical, 'text'); doc.text(sc.critical + ' critical', fx, y); fx += 28; }
        if (sc.warning  > 0) { setColor(C.warning,  'text'); doc.text(sc.warning  + ' warning',  fx, y); fx += 28; }
        if (sc.info     > 0) { setColor(C.info,     'text'); doc.text(sc.info     + ' info',     fx, y); }
      }

      rule(y + 3, C.rule, 0.1);
      y += 8;
    });
  }

  // ── Footer on last page ───────────────────────────────────────────────
  drawPageFooter();

  // ── Save ─────────────────────────────────────────────────────────────
  const dateStr = new Date().toISOString().slice(0, 10);
  const safeName = (orgName || 'org').replace(/[^a-z0-9]/gi, '-').toLowerCase();
  doc.save('mist-autopilot-' + safeName + '-' + dateStr + '.pdf');
}

// ---------------------------------------------------------------------------
// React component
// ---------------------------------------------------------------------------

export default function ReportGenerator({ orgName, orgId, moduleResults = [], siteNames = {} }) {
  const [state, setState] = useState('idle'); // idle | generating | done | error
  const [errMsg, setErrMsg] = useState('');

  const health = overallHealth(moduleResults);
  const allFindings = moduleResults.flatMap(m => m.findings || []);
  const totals = countBySeverity(allFindings);

  const healthColors = {
    critical: { bg: '#dc3232', text: '#fff' },
    warning:  { bg: '#e69614', text: '#fff' },
    pass:     { bg: '#28a745', text: '#fff' },
    unknown:  { bg: '#6c757d', text: '#fff' },
  };
  const hc = healthColors[health] || healthColors.unknown;

  async function handleDownload() {
    if (moduleResults.length === 0) return;
    setState('generating');
    try {
      await generatePDF({ orgName, orgId, moduleResults, siteNames });
      setState('done');
      setTimeout(() => setState('idle'), 3000);
    } catch (err) {
      console.error('ReportGenerator error:', err);
      setErrMsg(err.message || 'PDF generation failed');
      setState('error');
      setTimeout(() => setState('idle'), 5000);
    }
  }

  const disabled = state === 'generating' || moduleResults.length === 0;

  const label = {
    idle:       '⬇ Download Report',
    generating: '⏳ Generating…',
    done:       '✓ Downloaded',
    error:      '✗ Failed',
  }[state];

  const btnStyle = {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '6px',
    padding: '7px 16px',
    borderRadius: '6px',
    border: 'none',
    cursor: disabled ? 'not-allowed' : 'pointer',
    fontFamily: 'inherit',
    fontSize: '13px',
    fontWeight: 600,
    letterSpacing: '0.01em',
    transition: 'all 0.15s ease',
    background: state === 'done'  ? '#28a745'
              : state === 'error' ? '#dc3232'
              : '#1a7fd4',
    color: '#fff',
    opacity: disabled ? 0.6 : 1,
    boxShadow: disabled ? 'none' : '0 1px 4px rgba(26,127,212,0.3)',
  };

  const pills = [
    { label: 'Critical', count: totals.critical, color: '#dc3232' },
    { label: 'Warning',  count: totals.warning,  color: '#e69614' },
  ].filter(p => p.count > 0);

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
      <button
        onClick={handleDownload}
        disabled={disabled}
        style={btnStyle}
        title={moduleResults.length === 0 ? 'Run analysis first' : 'Download PDF report'}
      >
        {label}
      </button>

      {state === 'error' && errMsg && (
        <span style={{ fontSize: '11px', color: '#dc3232' }}>{errMsg}</span>
      )}
    </div>
  );
}
