import { Paper, Typography } from "@mui/material";

export const DEFAULT_EMPTY_MESSAGE = "No records available";

export default function EmptyState({ message = DEFAULT_EMPTY_MESSAGE }) {
  return (
    <Paper
      variant="outlined"
      sx={{
        py: 4,
        px: 3,
        textAlign: "center",
        borderStyle: "dashed",
        borderColor: "rgba(27, 43, 116, 0.24)",
        borderRadius: 2,
        backgroundColor: "#fafbff",
      }}
    >
      <Typography variant="body1" sx={{ color: "text.secondary", fontWeight: 500 }}>
        {message}
      </Typography>
    </Paper>
  );
}
