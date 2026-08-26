import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
} from "@mui/material";
import WarningAmberIcon from "@mui/icons-material/WarningAmber";
import FraudReasonContent from "./FraudReasonContent";

export default function FraudReasonDialog({ open, handleClose, message }) {
  return (
    <Dialog open={open} onClose={handleClose} maxWidth="md" fullWidth>
      <DialogTitle style={{ fontWeight: "bold", color: "#D2122E" }}>
        <WarningAmberIcon /> Fraud Reason Details
      </DialogTitle>

      <DialogContent dividers>
        <FraudReasonContent message={message} typographyVariant="body1" />
      </DialogContent>

      <DialogActions>
        <Button variant="contained" onClick={handleClose}>
          Close
        </Button>
      </DialogActions>
    </Dialog>
  );
}
