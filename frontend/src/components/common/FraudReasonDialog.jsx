// src/components/common/FraudReasonDialog.jsx

import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Typography,
} from "@mui/material";
import WarningAmberIcon from '@mui/icons-material/WarningAmber';


const formatFraudReason = (text) => {
  if (!text) return "<div>No details available.</div>";

  // Normalize escaped characters
  text = text.replace(/\\n/g, "\n").replace(/\\u2022/g, "•");

  // ---------- CASE 1: CIT bullet style ----------
  if (text.includes("•")) {
    const parts = text
      .split("•")
      .map((s) => s.trim())
      .filter(Boolean);

    return `
      <ul style="padding-left:18px; color:#333;">
        ${parts.map((p) => `<li style="margin:6px 0;">${p}</li>`).join("")}
      </ul>
    `;
  }

  // ---------- CASE 2: Simple semicolon text (GST) ----------
  if (!/\d+\.\s*/.test(text)) {
    const parts = text
      .split(";")
      .map((s) => s.trim())
      .filter(Boolean);

    return `
      <ul style="padding-left:18px; color:#333;">
        ${parts.map((p) => `<li style="margin:6px 0;">${p}</li>`).join("")}
      </ul>
    `;
  }

  // ---------- CASE 3: Numbered flags (SWT / complex GST) ----------
  const blocks = text.split(/(?=\n?\d+\.\s*)/g);

  const html = blocks
    .map((blk) => {
      const titleMatch = blk.match(/\d+\.\s*(?:Flag\s*-\s*)?([^:]+):/i);
      if (!titleMatch) return "";

      const title = titleMatch[1].trim();
      const details = blk.slice(titleMatch[0].length).trim();

      const parts = details
        .split(/\(\s*(?:i|ii|iii|iv|v|vi|vii|viii|ix|x)\s*\)/gi)
        .map((s) => s.trim())
        .filter(Boolean);

      return `
        <div style="margin: 14px 0;">
          <div style="font-size:16px; font-weight:700; color:#D2122E;">
            • ${title}
          </div>
          ${
            parts.length
              ? `<ul style="margin-top:6px; padding-left:18px; color:#333;">
                  ${parts.map((p) => `<li style="margin:4px 0;">${p}</li>`).join("")}
                 </ul>`
              : ""
          }
        </div>
      `;
    })
    .filter(Boolean)
    .join("");

  return html || "<div>No details available.</div>";
};



export default function FraudReasonDialog({ open, handleClose, message }) {
  return (
    <Dialog open={open} onClose={handleClose} maxWidth="md" fullWidth>
      <DialogTitle style={{ fontWeight: "bold", color: "#D2122E" }}>
       <WarningAmberIcon /> Fraud Reason Details
      </DialogTitle>

      <DialogContent dividers>
        <Typography
          variant="body1"
          component="div"
          dangerouslySetInnerHTML={{ __html: formatFraudReason(message) }}
          style={{ fontSize: "15px", lineHeight: "1.6" }}
        />
      </DialogContent>

      <DialogActions>
        <Button variant="contained" onClick={handleClose}>
          Close
        </Button>
      </DialogActions>
    </Dialog>
  );
}