import { Box, Skeleton } from "@mui/material";

export default function TableSkeleton({
  columnCount = 4,
  rowCount = 5,
}) {
  return (
    <Box>
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: `repeat(${columnCount}, minmax(100px, 1fr))`,
          gap: 1,
          mb: 1.5,
        }}
      >
        {Array.from({ length: columnCount }).map((_, index) => (
          <Skeleton key={`head-${index}`} variant="rounded" height={32} />
        ))}
      </Box>

      <Box sx={{ display: "grid", gap: 1 }}>
        {Array.from({ length: rowCount }).map((_, rowIndex) => (
          <Box
            key={`row-${rowIndex}`}
            sx={{
              display: "grid",
              gridTemplateColumns: `repeat(${columnCount}, minmax(100px, 1fr))`,
              gap: 1,
            }}
          >
            {Array.from({ length: columnCount }).map((__, columnIndex) => (
              <Skeleton key={`cell-${rowIndex}-${columnIndex}`} variant="rounded" height={28} />
            ))}
          </Box>
        ))}
      </Box>
    </Box>
  );
}
