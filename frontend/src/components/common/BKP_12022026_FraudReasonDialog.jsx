// ✅ src/components/common/FraudReasonDialog.jsx

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
  if (!text) return "";

  // ✅ Pattern will now match both:
  // "3. Flag - Something:"
  // "3. Something:"
  const blocks = text.split(/(?=\n?\d+\.\s*)/g);

  const html = blocks
    .map((blk) => {
      // ✅ Match title: GST OR SWT (with or without "Flag -")
      const titleMatch = blk.match(/\d+\.\s*(?:Flag\s*-\s*)?([^:]+):/i);
      if (!titleMatch) return "";

      const title = titleMatch[1].trim();

      // Remaining details after title
      const details = blk.slice(titleMatch[0].length).trim();

      // ✅ Split on roman numeral markers (i)(ii)(iii)
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