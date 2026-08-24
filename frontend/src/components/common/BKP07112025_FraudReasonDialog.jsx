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

// ✅ Cleanly format Fraud_Reason text → bullets with colors
const formatFraudReason = (text) => {
  if (!text) return "";

  // Split each "N. Flag - ..." section; keep only real flag blocks
  const blocks = text.split(/(?=\d+\.\s*Flag\s*-)/g);

  const html = blocks
    .map((blk) => {
      // Require a proper flag title like: "8. Flag - Excessive Input Tax:"
      const titleMatch = blk.match(/\d+\.\s*(Flag\s*-\s*[^:]+):/i);
      if (!titleMatch) return ""; // 🚫 skip anything that isn't a valid "Flag - ...:" section

      const title = titleMatch[1].trim();

      // Remaining details after the title
      const details = blk.slice(titleMatch[0].length).trim();

      // Split on roman numeral markers (i), (ii), (iii), ... only
      // This avoids breaking "(1,046.00)" etc.
      const parts = details
        .split(/\(\s*(?:i|ii|iii|iv|v|vi|vii|viii|ix|x)\s*\)\s*/gi)
        .map((s) => s.trim())
        .filter(Boolean) // drop empty
        // also drop stray pure-digit leftovers like "1", "2" just in case
        .filter((s) => !/^\d+$/.test(s));

      // Build the section HTML with only text color changes
      return `
        <div style="margin: 14px 0;">
          <div style="font-size:16px; font-weight:700; color:#dc3545;">
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