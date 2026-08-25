import { useState, useEffect } from "react";
import {
  Box,
  Typography,
  Button,
  Divider,
  Checkbox,
  FormControlLabel,
} from "@mui/material";

const monthNames = [
  "", "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December"
];

export default function DataChangeDetailView({
  record,
  onBack,
  onApprove,
  onReject,
}) {
  const [selectedFields, setSelectedFields] = useState({});
  const [selectAll, setSelectAll] = useState(false);

  useEffect(() => {
    if (record?.change_json) {
      const initialState = {};
      Object.keys(record.change_json).forEach((key) => {
        initialState[key] = false;
      });
      setSelectedFields(initialState);
      setSelectAll(false);
    }
  }, [record]);

  const handleFieldChange = (field) => {
    setSelectedFields((prev) => ({
      ...prev,
      [field]: !prev[field],
    }));
  };

  const handleSelectAll = () => {
    const newValue = !selectAll;
    const updated = {};
    Object.keys(selectedFields).forEach((key) => {
      updated[key] = newValue;
    });
    setSelectedFields(updated);
    setSelectAll(newValue);
  };

  const selectedKeys = Object.keys(selectedFields).filter(
    (key) => selectedFields[key]
  );

  
  return (
    <Box>
      <Typography variant="h6" gutterBottom>
        Change Details
      </Typography>

      <Divider className="mb-3" />

      <Typography><b>TIN:</b> {record.tin}</Typography>
      <Typography><b>Assessment:</b> {record.assessment_number}</Typography>
      <Typography>
        <b>Period:</b> {monthNames[record.tax_period_month]} {record.tax_period_year}
      </Typography>
      <Typography><b>Status:</b> {record.status || "Pending"}</Typography>

      <Divider className="my-3" />

      <Box className="mb-2">
        <FormControlLabel
          control={
            <Checkbox
              checked={selectAll}
              onChange={handleSelectAll}
            />
          }
          label="Select All"
        />
      </Box>

      {record.change_json &&
        Object.entries(record.change_json).map(([field, values]) => (
            <Box
            key={field}
            className="mb-2 p-2"
            sx={{
                border: "1px solid #ddd",
                borderRadius: "6px",
                backgroundColor: "#fafafa",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                flexWrap: "wrap",
            }}
            >
            {/* Left Side: Checkbox + Field Name */}
            <FormControlLabel
                control={
                <Checkbox
                    checked={selectedFields[field] || false}
                    onChange={() => handleFieldChange(field)}
                />
                }
                label={<b>{field}</b>}
            />

            {/* Right Side: Old | New | Difference in one line */}
            <Typography
                variant="body2"
                sx={{
                fontWeight: 500,
                }}
            >
                Old: {values.old} &nbsp; | &nbsp;
                New: {values.new} &nbsp; | &nbsp;
                <span
                style={{
                    fontWeight: "bold",
                    color: values.difference > 0 ? "green" : "red",
                }}
                >
                Difference: {values.difference}
                </span>
            </Typography>
            </Box>
        ))}

      <Box className="d-flex gap-2 mt-3">
        <Button
          variant="contained"
          color="success"
          onClick={onApprove}
          disabled={record.status === "Approved"}
        >
          Approve
        </Button>

        <Button
          variant="contained"
          color="error"
          onClick={onReject}
          disabled={record.status === "Disapproved"}
        >
          Reject
        </Button>

        <Button variant="outlined" onClick={onBack}>
          Back
        </Button>
      </Box>
    </Box>
  );
}